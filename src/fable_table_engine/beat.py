"""Beat runner — coordinates one pass of the beat loop (CORE §5; phase 5).

`BeatRunner.run` implements beat-loop steps 2–9 for a single actor. Steps
deferred to later phases are noted inline:

  Step 1  (route / spotlight)       → phase 7 (orchestrator)
  Step 3  (propose from queue)      → phase 7 (action queue / orchestrator)
  Step 7  (audit)                   → phase 8 (auditor)

The beat runner is deliberately thin: it sequences the existing deterministic
services (context assembly, rules engine, commit pipeline) with the GM agents
(adjudicator, narrator) and logs the result. It owns no authoritative state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from .access import CommitPipeline
from .auditor import AuditFlag, AuditTier, Auditor
from .character_agent import CharacterAgent, Proposal
from .character_sheet import CharacterSheet
from .context import BeliefStore, ContextAssembler
from .effects import (
    ApplyScar,
    ApplyStress,
    CreateTruth,
    EffectExecutor,
    EffectResult,
    SpendEdge,
    STRESS_CAP,
    TypedEffect,
    describe_effect,
    effect_from_dict,
)
from .events import Commitment
from .gm import AdjudicatorGM, NarratorGM, ResolutionPlan, StakesDecision, WorldSimulator
from .orchestrator import ActionQueue, Orchestrator, SceneCadence
from .plot_graph import InterestSignalAccumulator
from .plot_manager import PlotManager
from .budgeter import ContextBudgeter
from .provider import ModelCallError, ToolOutputError
from .rules import Band, CheckResult, RulesEngine
from .world_state import WorldState

# Effect quality tiers in ascending order (Phase 13 / D-025).
EFFECT_TIERS: list[str] = ["Minimal", "Standard", "Superior", "Extreme"]

# Legacy fallback window — used when no ContextBudgeter is configured.
# Phase 22 (D-042): ContextBudgeter replaces this per role; this constant
# is kept only for backward compatibility with tests and callers that omit
# the budgeter.
CONTEXT_EVENT_WINDOW: int = 12


class ActionLifecycleState(str, Enum):
    """Backend-owned lifecycle state for one beat (D-027).

    Inherits ``str`` so values pass directly as event content strings.
    The client reads these states only; it never writes or infers them.

    State machine (Phase 21):
        submitted → validating → adjudicating
            → pending_player_choice (when stakes exist; trade selection)
            → rolling
            → pending_edge_decision (when lean_after/push declared)
            → applying_effects → narrating → auditing → committed
        Exits: cancelled · aborted · failed
    """

    SUBMITTED = "submitted"
    VALIDATING = "validating"
    ADJUDICATING = "adjudicating"
    PENDING_PLAYER_CHOICE = "pending_player_choice"
    ROLLING = "rolling"
    PENDING_EDGE_DECISION = "pending_edge_decision"
    APPLYING_EFFECTS = "applying_effects"
    NARRATING = "narrating"
    AUDITING = "auditing"
    COMMITTED = "committed"
    CANCELLED = "cancelled"
    ABORTED = "aborted"
    FAILED = "failed"


def _apply_trade(
    base_exposure: int,
    base_effect: str,
    trade: str,
) -> tuple[int, str]:
    """Apply a trade selection to exposure and effect tier.

    Trade NEVER modifies TN — only Exposure (danger) and Effect (quality of success).
    Clamps: exposure to [1, 4]; effect index to [0, len(EFFECT_TIERS)-1].
    """
    idx = EFFECT_TIERS.index(base_effect) if base_effect in EFFECT_TIERS else 1
    if trade == "Aggressive":
        return min(4, base_exposure + 1), EFFECT_TIERS[min(len(EFFECT_TIERS) - 1, idx + 1)]
    if trade == "Guarded":
        return max(1, base_exposure - 1), EFFECT_TIERS[max(0, idx - 1)]
    # "Balanced" or unrecognised → no change
    return base_exposure, EFFECT_TIERS[idx]


_BAND_ORDER = [Band.SETBACK, Band.COST, Band.SUCCESS, Band.TRIUMPH]


def _step_band_up(band: Band) -> Band:
    """Step a band up one level. Clamps at Triumph (v6 §13: no Top Exit via Edge)."""
    idx = _BAND_ORDER.index(band)
    return _BAND_ORDER[min(idx + 1, len(_BAND_ORDER) - 1)]


# --------------------------------------------------------------------------- #
# Internal: atomic beat transaction                                             #
# --------------------------------------------------------------------------- #

class _BeatAborted(Exception):
    """Raised inside log.transaction() to trigger rollback when the post-narration
    audit blocks the beat. Carries the BeatResult so the caller can return it
    after the rollback completes. Using an exception ensures the context manager
    sees a failure exit and calls conn.rollback(), undoing the step-6 fact
    commits and step-9 narration writes atomically."""

    def __init__(self, result: BeatResult) -> None:
        self.result = result


# --------------------------------------------------------------------------- #
# Delivery scope — resolved once at beat entry, never reconstructed            #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class DeliveryScope:
    """Immutable delivery contract for one beat.

    Computed from the proposal's channel and target at beat entry. Threaded
    through adjudication, narration, event logging, and audit so no downstream
    component can widen or independently reconstruct the audience.

    channel: "public" | "whisper" | "ooc"
    audience: entity IDs that receive the narration event
    target: whisper recipient, set only when channel == "whisper"
    """

    channel: str
    audience: tuple[str, ...]
    target: str | None = None


def _resolve_delivery(
    channel: str,
    actor: str,
    target: str | None,
    world: WorldState,
    gm: str,
) -> DeliveryScope:
    """Compute and validate the delivery scope for a proposal.

    Raises ValueError for unknown channels or invalid/absent whisper targets.
    """
    all_present = tuple(dict.fromkeys(list(world.entities.keys()) + [gm]))
    if channel == "public":
        return DeliveryScope(channel="public", audience=all_present)
    if channel == "ooc":
        return DeliveryScope(channel="ooc", audience=all_present)
    if channel == "whisper":
        if not target:
            raise ValueError("whisper channel requires a non-empty target")
        if target not in world.entities:
            raise ValueError(
                f"whisper target {target!r} is not a known entity; "
                f"known: {sorted(world.entities)}"
            )
        if target == actor:
            raise ValueError(f"cannot whisper to yourself ({actor!r})")
        return DeliveryScope(
            channel="whisper",
            audience=tuple(dict.fromkeys([actor, target, gm])),
            target=target,
        )
    raise ValueError(
        f"unknown proposal channel {channel!r}; expected public/whisper/ooc"
    )


# --------------------------------------------------------------------------- #
# Context helpers                                                               #
# --------------------------------------------------------------------------- #

def _world_summary(
    world: WorldState,
    pipeline: CommitPipeline,
    plot_manager: PlotManager | None = None,
) -> str:
    lines: list[str] = []
    if world.zones:
        lines.append(f"Zones: {', '.join(sorted(world.zones))}")
    for e in world.entities.values():
        zone = (e.position or {}).get("zone", "—")
        cond = f" [{', '.join(e.conditions)}]" if e.conditions else ""
        lines.append(f"  {e.name} ({e.kind}) in {zone}{cond}")
    if world.clocks:
        for name, clock in world.clocks.items():
            cur = clock.get("current", 0)
            mx = clock.get("max", 6)
            fired = " [FIRED]" if clock.get("fired") else ""
            lines.append(f"  Clock '{name}': {cur}/{mx}{fired}")
    canon = pipeline.canon_ledger()
    if canon:
        lines.append("Established facts:")
        for fact in canon.values():
            lines.append(f"  {fact.subject}.{fact.predicate} = {fact.value!r}")
    if plot_manager is not None:
        plot_ctx = plot_manager.gm_context_summary()
        if plot_ctx and plot_ctx != "(no active hooks or fronts)":
            lines.append(f"\n{plot_ctx}")
    return "\n".join(lines) if lines else "(empty world)"


def _events_summary(store: BeliefStore, limit: int = CONTEXT_EVENT_WINDOW) -> str:
    if not store.events:
        return "(no events yet)"
    lines: list[str] = []
    for e in store.events[-limit:]:
        if e.content:
            lines.append(f"[{e.type}] {e.author}: {e.content[:140]}")
    return "\n".join(lines) if lines else "(no visible events)"


def _narrator_context(store: BeliefStore, channel: str, limit: int = CONTEXT_EVENT_WINDOW) -> str:
    """Return narrator context filtered to the delivery scope.

    Public narration: only public-channel events. Actor-private events
    (whispers received, system events) must not flow into prose that all
    present participants will read (invariant 5).
    Whisper narration: full actor context is safe — output goes only to
    actor, target, and GM.
    """
    events = store.events
    if channel == "public":
        events = [e for e in events if e.channel == "public"]
    # D-029: warm GM never receives gm_only dice results (cold/warm split, D-007)
    events = [e for e in events if e.roll_visibility != "gm_only"]
    if not events:
        return "(no events yet)"
    lines: list[str] = []
    for e in events[-limit:]:
        if e.content:
            lines.append(f"[{e.type}] {e.author}: {e.content[:140]}")
    return "\n".join(lines) if lines else "(no visible events)"


# --------------------------------------------------------------------------- #
# BeatResult                                                                    #
# --------------------------------------------------------------------------- #

@dataclass
class BeatResult:
    """Everything that happened during one beat."""

    actor: str
    action: str
    channel: str
    had_stakes: bool
    stakes_reasoning: str
    resolution: CheckResult | None
    narration: str
    narration_event_id: str
    committed_fact_count: int
    clocks_fired: list[str] = field(default_factory=list)
    audit_flags: list[AuditFlag] = field(default_factory=list)
    beat_aborted: bool = False
    effect_results: list[EffectResult] = field(default_factory=list)
    # Phase 13: trade + consequence palette results
    applied_trade: str = "Balanced"
    effective_exposure: int = 2
    effective_effect: str = "Standard"
    # Phase 21: Edge mechanic
    edge_spend: str | None = None
    edge_spent: bool = False
    edge_step_applied: bool = False
    # Phase 21: D-027 action lifecycle
    lifecycle_state: ActionLifecycleState = ActionLifecycleState.COMMITTED


# --------------------------------------------------------------------------- #
# BeatRunner                                                                    #
# --------------------------------------------------------------------------- #

class BeatRunner:
    """Sequences one beat of the FABLE beat loop for a single actor.

    Construct once per session and call `run(actor, action)` each beat.
    Provide a `WorldSimulator` to tick clocks after each beat; omit it to
    skip clock advancement.

    The GM entity (default ``"gm"``) must be a known entity in the event log's
    audience set for the adjudicator's system-view events. It does not need to
    be in the WorldState entity table — the GM is not a positioned entity.
    """

    def __init__(
        self,
        log,
        world: WorldState,
        pipeline: CommitPipeline,
        rules: RulesEngine,
        assembler: ContextAssembler,
        adjudicator: AdjudicatorGM,
        narrator: NarratorGM,
        sheets: dict[str, CharacterSheet],
        gm_entity: str = "gm",
        simulator: WorldSimulator | None = None,
        auditor: Auditor | None = None,
        interest_accumulator: InterestSignalAccumulator | None = None,
        plot_manager: PlotManager | None = None,
        executor: EffectExecutor | None = None,
        budgeter: ContextBudgeter | None = None,
    ) -> None:
        self._log = log
        self._world = world
        self._pipeline = pipeline
        self._rules = rules
        self._assembler = assembler
        self._adjudicator = adjudicator
        self._narrator = narrator
        self._sheets = sheets
        self._gm = gm_entity
        self._simulator = simulator
        self._auditor = auditor
        self._interest_accumulator = interest_accumulator
        self._plot_manager = plot_manager
        self._executor = executor
        self._budgeter = budgeter

    def _emit_audit_events(self, flags: list[AuditFlag]) -> None:
        for flag in flags:
            if flag.tier == AuditTier.CRITICAL:
                etype = "audit_block"
            elif flag.tier == AuditTier.NON_CRITICAL:
                etype = "audit_warning"
            else:
                etype = "audit_advisory"
            self._log.append(
                author=self._gm,
                channel="system",
                type=etype,
                content=f"[{flag.category}] {flag.description[:120]}",
                audience=(self._gm,),
                visibility="content",
            )

    def _emit_lifecycle(
        self,
        state: ActionLifecycleState,
        audience: tuple[str, ...],
    ) -> None:
        """Emit one action_lifecycle event to the log (D-027).

        Internal processing states go to the GM only; interactive pause states
        include the actor; terminal states go to all present.
        """
        self._log.append(
            author=self._gm,
            channel="system",
            type="action_lifecycle",
            content=state.value,
            audience=audience,
            visibility="content",
        )

    def run(
        self,
        actor: str,
        action: str,
        channel: str = "public",
        target: str | None = None,
        trade: str | None = None,
        edge_spend: str | None = None,
        edge_justification: str = "",
        edge_shield_target: str | None = None,
        _shield_registry: dict[str, str] | None = None,
    ) -> BeatResult:
        """Run one beat: actor declares action, world responds.

        `channel` and `target` determine the delivery scope resolved once at
        beat entry (invariant 1). OOC actions bypass all fictional mechanics
        and return immediately (invariant 4). Whisper actions require a valid,
        known target (invariant 2).

        Phase 21 Edge mechanic params (v6 §13):
          `edge_spend`        — "lean_before", "lean_after", "push", or "shield".
          `edge_justification`— Trait/Bond/Truth citation required for Lean.
          `edge_shield_target`— ally entity_id this actor is shielding (for "shield").
          `_shield_registry`  — cross-beat registry {shielded_id: shielder_id} built
                                by run_round() before the round begins.

        Edge spends at steps 4c and 5b happen outside the beat transaction
        (mechanical facts that persist even on post-narration abort, matching
        the step-5 dice roll — see D-035). Shield (6b) is inside the transaction
        because it is a fictional consequence of effect application.

        Beat loop steps (CORE §5):
          2.  Assemble context views.
          4.  Stakes gate (adjudicator).
          4b. Apply trade.
          4c. Pre-roll Lean (Phase 21).
          5.  Resolve (rules engine, if stakes).
          5b. Post-roll Lean / Push (Phase 21).
          6.  Extract and commit declared facts.
          6b. Apply consequence palette; Shield redirect (Phase 21).
          8.  Narrate (narrator, prose only, delivery-scoped context).
          9.  Log narration event; tick world simulator.
        """
        sheet = self._sheets.get(actor)
        if sheet is None:
            raise ValueError(
                f"no CharacterSheet registered for actor {actor!r} — "
                f"register one in the sheets dict passed to BeatRunner"
            )

        # Resolve delivery scope at beat entry — computed once, never reconstructed.
        scope = _resolve_delivery(channel, actor, target, self._world, self._gm)

        # Audience shortcuts for lifecycle events (D-027).
        # Internal processing states are GM-only; interactive pauses include the
        # actor; terminal states reach all present.
        _gm_only: tuple[str, ...] = (self._gm,)
        _actor_gm: tuple[str, ...] = (actor, self._gm)
        _all_present: tuple[str, ...] = scope.audience

        self._emit_lifecycle(ActionLifecycleState.SUBMITTED, _all_present)

        # OOC: bypass all fiction. Emit one OOC event and return (invariant 4).
        if scope.channel == "ooc":
            ooc_event = self._log.append(
                author=actor,
                channel="ooc",
                type="ooc",
                content=action,
                audience=scope.audience,
                visibility="content",
            )
            self._emit_lifecycle(ActionLifecycleState.COMMITTED, _all_present)
            return BeatResult(
                actor=actor,
                action=action,
                channel="ooc",
                had_stakes=False,
                stakes_reasoning="out-of-character; no adjudication",
                resolution=None,
                narration="",
                narration_event_id=ooc_event.id,
                committed_fact_count=0,
                lifecycle_state=ActionLifecycleState.COMMITTED,
            )

        self._emit_lifecycle(ActionLifecycleState.VALIDATING, _gm_only)

        # Step 2: build context views.
        # GM gets the full (GM-audience) event view for adjudication.
        # Narrator context is filtered to the delivery scope (invariant 5).
        gm_store = self._assembler.belief_store(self._gm)
        player_store = self._assembler.belief_store(actor)

        world_summary = _world_summary(self._world, self._pipeline, self._plot_manager)
        _adj_window = (
            self._budgeter.event_window("gm_adjudicator")
            if self._budgeter else CONTEXT_EVENT_WINDOW
        )
        _nar_window = (
            self._budgeter.event_window("gm_narrator")
            if self._budgeter else CONTEXT_EVENT_WINDOW
        )
        gm_events = _events_summary(gm_store, limit=_adj_window)
        narrator_ctx = _narrator_context(player_store, scope.channel, limit=_nar_window)

        # Step 4: stakes gate (D-027: adjudicating state).
        # ModelCallError / ToolOutputError here exit before any state is written;
        # emit FAILED and return a clean aborted BeatResult.
        self._emit_lifecycle(ActionLifecycleState.ADJUDICATING, _gm_only)
        try:
            stakes = self._adjudicator.evaluate(
                action=action,
                actor_sheet=sheet,
                world_summary=world_summary,
                recent_events=gm_events,
            )
        except (ModelCallError, ToolOutputError):
            self._emit_lifecycle(ActionLifecycleState.FAILED, _all_present)
            return BeatResult(
                actor=actor, action=action, channel=scope.channel,
                had_stakes=False, stakes_reasoning="model call failed",
                resolution=None, narration="", narration_event_id="",
                committed_fact_count=0, beat_aborted=True,
                lifecycle_state=ActionLifecycleState.FAILED,
            )

        # Step 4b: apply trade (Phase 13 / D-025).
        # Trade adjusts Exposure (danger) and Effect (quality of success). NEVER TN.
        # D-027: emit pending_player_choice whenever there are stakes — the production
        # API will pause here awaiting the player's trade selection; in the synchronous
        # implementation the choice is already in the proposal and we continue at once.
        effective_trade = "Balanced"
        effective_exposure = stakes.exposure if stakes.exposure is not None else 2
        effective_effect = stakes.effect if stakes.effect else "Standard"
        if stakes.has_stakes:
            self._emit_lifecycle(ActionLifecycleState.PENDING_PLAYER_CHOICE, _actor_gm)
            effective_trade = trade or stakes.trade_default or "Balanced"
            if stakes.exposure is not None and stakes.effect:
                effective_exposure, effective_effect = _apply_trade(
                    stakes.exposure, stakes.effect, effective_trade
                )

        # Step 4c: pre-roll Lean (Phase 21 / v6 §13).
        # Happens outside the transaction — like the roll itself, this mechanical
        # spend persists even if the beat later aborts (D-035 philosophy).
        edge_pre_lean = False
        if (
            edge_spend == "lean_before"
            and self._executor is not None
            and stakes.has_stakes
            and effective_exposure > 0
        ):
            lean_result = self._executor.apply(
                SpendEdge(kind="spend_edge", entity_id=actor, amount=1, spend_type="lean"),
                audience=(actor, self._gm),
                source_event_id=None,
            )
            if lean_result.accepted:
                effective_exposure = max(0, effective_exposure - 1)
                edge_pre_lean = True

        # Step 5: resolve if stakes exist.
        resolution: CheckResult | None = None
        if stakes.has_stakes:
            self._emit_lifecycle(ActionLifecycleState.ROLLING, _gm_only)
            resolution = self._rules.resolve_check(
                actor=actor,
                skill=stakes.skill_rating,  # type: ignore[arg-type]
                tn=stakes.tn,              # type: ignore[arg-type]
                audience=(actor, self._gm),
                reason=f"{actor}: {action[:80]}",
            )

        # Step 5b: post-roll band step-up via Lean-after or Push (Phase 21 / v6 §13).
        # Happens outside the transaction — mechanical cost paid before fiction commits.
        # Invariant: at most one step-up per roll; no step-up past Triumph.
        # D-027: emit pending_edge_decision when the actor declared a post-roll Edge spend
        # (lean_after or push). Production API pauses here; synchronous path continues.
        effective_band: Band | None = resolution.band if resolution else None
        edge_step_applied = False
        edge_any_spent = edge_pre_lean
        if resolution is not None and self._executor is not None and effective_band is not None:
            if edge_spend in ("lean_after", "push"):
                self._emit_lifecycle(ActionLifecycleState.PENDING_EDGE_DECISION, _actor_gm)
            if edge_spend == "lean_after":
                # Requires justification (Trait/Bond/Truth); nothing to spend at Triumph.
                if edge_justification and effective_band != Band.TRIUMPH:
                    step_result = self._executor.apply(
                        SpendEdge(kind="spend_edge", entity_id=actor, amount=1, spend_type="lean"),
                        audience=(actor, self._gm),
                        source_event_id=resolution.resolution_event_id,
                    )
                    if step_result.accepted:
                        effective_band = _step_band_up(effective_band)
                        edge_step_applied = True
                        edge_any_spent = True

            elif edge_spend == "push":
                # Push costs 1 Edge + 2 Stress. Reject if Triumph (nothing to step),
                # or if 2 more Stress would overflow (character doesn't have headroom).
                if effective_band != Band.TRIUMPH:
                    entity = self._world.entities.get(actor)
                    current_stress = entity.resources.get("stress", 0) if entity else 0
                    if current_stress + 2 <= STRESS_CAP:
                        spend_result = self._executor.apply(
                            SpendEdge(kind="spend_edge", entity_id=actor, amount=1, spend_type="push"),
                            audience=(actor, self._gm),
                            source_event_id=resolution.resolution_event_id,
                        )
                        if spend_result.accepted:
                            stress_result = self._executor.apply(
                                ApplyStress(kind="apply_stress", entity_id=actor, amount=2),
                                audience=(actor, self._gm),
                                source_event_id=resolution.resolution_event_id,
                            )
                            if stress_result.accepted:
                                effective_band = _step_band_up(effective_band)
                                edge_step_applied = True
                                edge_any_spent = True

        # Step 6: build the declared effects/commitments from adjudicator output.
        # Adjudicator still produces untyped {subject,predicate,value,revealed} dicts;
        # convert to CreateTruth typed effects for the executor path (Phase 12).
        # For the pre-audit and the fallback path we also extract plain Commitments.
        declared_effects: list[CreateTruth] = [
            CreateTruth(
                kind="create_truth",
                subject=f["subject"],
                predicate=f["predicate"],
                value=f["value"],
                revealed=bool(f.get("revealed", True)),
            )
            for f in stakes.declared_facts
        ]
        pre_audit_commitments: list[Commitment] = [
            Commitment(
                subject=e.subject, predicate=e.predicate,
                value=e.value, revealed=e.revealed, epistemic_type="fact",
            )
            for e in declared_effects
        ]

        # Pre-commit audit (step 7, hook 1): runs OUTSIDE the beat transaction
        # so audit events auto-commit even when the beat itself is later aborted.
        all_audit_flags: list[AuditFlag] = []
        if self._auditor and pre_audit_commitments:
            pre_audit = self._auditor.check_commitments(
                pre_audit_commitments, self._pipeline.canon_ledger()
            )
            all_audit_flags.extend(pre_audit.flags)
            self._emit_audit_events(pre_audit.flags)
            if pre_audit.any_blocking:
                self._emit_lifecycle(ActionLifecycleState.ABORTED, _all_present)
                return BeatResult(
                    actor=actor, action=action, channel=scope.channel,
                    had_stakes=stakes.has_stakes,
                    stakes_reasoning=stakes.reasoning, resolution=resolution,
                    narration="", narration_event_id="", committed_fact_count=0,
                    audit_flags=all_audit_flags, beat_aborted=True,
                    lifecycle_state=ActionLifecycleState.ABORTED,
                )

        # Steps 6–9 run inside a single transaction (Phase 10 invariant 3).
        # On success: fact commit + narration event + clock ticks are committed
        # atomically. On post-narration audit block: _BeatAborted triggers
        # rollback, undoing the step-6 facts so no partial beat state persists.
        # (For in-memory EventLog, transaction() is a no-op and behaviour is
        # unchanged from the pre-Phase-10 code.)
        narration: str = ""
        narration_event = None
        clocks_fired: list[str] = []
        beat_effect_results: list[EffectResult] = []

        try:
            with self._log.transaction():
                self._emit_lifecycle(ActionLifecycleState.APPLYING_EFFECTS, _gm_only)
                # Step 6: apply declared effects through the executor (Phase 12)
                # or fall back to the direct pipeline commit (pre-Phase-12 path).
                source_id = resolution.resolution_event_id if resolution else None
                if self._executor and declared_effects:
                    beat_effect_results = self._executor.apply_all(
                        declared_effects,  # type: ignore[arg-type]
                        audience=(actor, self._gm),
                        source_event_id=source_id,
                    )
                    committed_count = sum(1 for r in beat_effect_results if r.accepted)
                elif declared_effects:
                    self._pipeline.commit(
                        author=self._gm,
                        channel="system",
                        content=f"[adjudicator: {action[:80]}]",
                        audience=(actor, self._gm),
                        visibility="content",
                        commitments=pre_audit_commitments,
                    )
                    committed_count = len(declared_effects)
                else:
                    committed_count = 0

                # Step 6b: apply consequence palette typed effects (Phase 13 / D-025).
                # Use effective_band (which may have been stepped up in step 5b) to
                # select palette entries. Conversion/application failures are logged as
                # advisories and do NOT abort the beat.
                #
                # Phase 21 additions:
                #   - Shield redirect: Harm (ApplyStress / ApplyScar) targeting an entity
                #     in _shield_registry is redirected to the shielder and costs the
                #     shielder 1 Edge. The shielder's Edge spend is inside the transaction
                #     because it is a fictional consequence of effect application.
                #   - GainEdge filter: if the effective band is Triumph reached via Edge
                #     step-up, GainEdge effects in triumph_effects are stripped
                #     (v6 §13: "a band reached by spending Edge generates no Edge").
                palette_effects: list[TypedEffect] = []
                if resolution is not None and self._executor is not None and effective_band is not None:
                    if effective_band == Band.TRIUMPH:
                        raw_palette = list(stakes.triumph_effects)
                        if edge_step_applied:
                            raw_palette = [e for e in raw_palette if e.get("kind") != "gain_edge"]
                    elif effective_band == Band.COST:
                        raw_palette = stakes.consequence_palette.get("cost", [])
                    elif effective_band == Band.SETBACK:
                        raw_palette = stakes.consequence_palette.get("setback", [])
                    else:
                        raw_palette = []
                    for raw in raw_palette:
                        try:
                            typed = effect_from_dict(raw)
                        except (ValueError, KeyError) as exc:
                            self._log.append(
                                author=self._gm,
                                channel="system",
                                type="audit_advisory",
                                content=f"[palette] invalid effect entry skipped: {exc}",
                                audience=(self._gm,),
                                visibility="content",
                            )
                            continue
                        # Shield redirect: when Harm targets a shielded entity,
                        # redirect to the shielder and spend 1 Edge from them.
                        if (
                            _shield_registry
                            and isinstance(typed, (ApplyStress, ApplyScar))
                            and typed.entity_id in _shield_registry
                        ):
                            shielder_id = _shield_registry[typed.entity_id]
                            shield_spend = self._executor.apply(
                                SpendEdge(kind="spend_edge", entity_id=shielder_id, amount=1, spend_type="shield"),
                                audience=(shielder_id, actor, self._gm),
                                source_event_id=resolution.resolution_event_id,
                            )
                            if shield_spend.accepted:
                                typed = replace(typed, entity_id=shielder_id)
                        palette_effects.append(typed)
                    if palette_effects:
                        palette_results = self._executor.apply_all(
                            palette_effects,
                            audience=(actor, self._gm),
                            source_event_id=resolution.resolution_event_id,
                        )
                        for pr in palette_results:
                            if not pr.accepted:
                                self._log.append(
                                    author=self._gm,
                                    channel="system",
                                    type="audit_advisory",
                                    content=f"[palette] rejected effect: {pr.rejection_reason}",
                                    audience=(self._gm,),
                                    visibility="content",
                                )
                        beat_effect_results.extend(palette_results)

                # Build a plain-English summary of all accepted effects for the narrator.
                applied_effects: list[TypedEffect] = [
                    r.effect for r in beat_effect_results if r.accepted
                ]
                applied_summary: str | None = (
                    "; ".join(describe_effect(e) for e in applied_effects)
                    or None
                )

                # Step 8: narrate. Narrator sees the effective band (which may have
                # been stepped up by Edge spend) and effect tier, never the dice.
                # ModelCallError from the narrator propagates out, triggers transaction
                # rollback via __exit__, and is caught as FAILED below.
                self._emit_lifecycle(ActionLifecycleState.NARRATING, _gm_only)
                narration = self._narrator.narrate(
                    action=action,
                    stakes=stakes,
                    band=effective_band,
                    player_context=narrator_ctx,
                    effective_effect=effective_effect,
                    applied_summary=applied_summary,
                )

                # Post-narration audit (step 7, hook 2).
                # Raise _BeatAborted to trigger transaction rollback on block —
                # this undoes the step-6 fact commits atomically.
                self._emit_lifecycle(ActionLifecycleState.AUDITING, _gm_only)
                if self._auditor:
                    post_audit = self._auditor.check_narration(
                        narration=narration,
                        actor=actor,
                        action=action,
                        canon=self._pipeline.canon_ledger(),
                    )
                    all_audit_flags.extend(post_audit.flags)
                    self._emit_audit_events(post_audit.flags)
                    if post_audit.any_blocking:
                        raise _BeatAborted(BeatResult(
                            actor=actor, action=action, channel=scope.channel,
                            had_stakes=stakes.has_stakes,
                            stakes_reasoning=stakes.reasoning, resolution=resolution,
                            narration=narration, narration_event_id="",
                            committed_fact_count=committed_count,
                            audit_flags=all_audit_flags, beat_aborted=True,
                            edge_spend=edge_spend,
                            edge_spent=edge_any_spent,
                            edge_step_applied=edge_step_applied,
                            lifecycle_state=ActionLifecycleState.ABORTED,
                        ))

                # Step 9: log narration using the resolved delivery scope (invariant 1).
                # audience and channel come from scope — no component may widen them.
                narration_event = self._log.append(
                    author=self._gm,
                    channel=scope.channel,
                    type="narration",
                    content=narration,
                    audience=scope.audience,
                    visibility="content",
                )

                # Tick clocks / fire fronts. Use the plan's action_domain tag so only
                # domain-matching pressure clocks advance (D-026).
                if self._simulator is not None:
                    clocks_fired = self._simulator.advance(stakes.action_domain or "beat")

                # Advance beat counter in the time anchor (D-030). Happens inside the
                # transaction so it rolls back with the rest of the beat on abort.
                self._world.advance_beat()

                if self._plot_manager is not None:
                    self._plot_manager.post_beat(clocks_fired)

                if self._interest_accumulator is not None:
                    self._interest_accumulator.emit(
                        subject=actor,
                        category="action",
                        weight=0.5,
                        causal_event_id=narration_event.id,
                    )

        except _BeatAborted as e:
            self._emit_lifecycle(ActionLifecycleState.ABORTED, _all_present)
            return e.result
        except ModelCallError:
            self._emit_lifecycle(ActionLifecycleState.FAILED, _all_present)
            return BeatResult(
                actor=actor, action=action, channel=scope.channel,
                had_stakes=False, stakes_reasoning="model call failed",
                resolution=None, narration="", narration_event_id="",
                committed_fact_count=0, beat_aborted=True,
                lifecycle_state=ActionLifecycleState.FAILED,
            )

        self._emit_lifecycle(ActionLifecycleState.COMMITTED, _all_present)
        assert narration_event is not None  # always set on the non-aborted path
        return BeatResult(
            actor=actor,
            action=action,
            channel=scope.channel,
            had_stakes=stakes.has_stakes,
            stakes_reasoning=stakes.reasoning,
            resolution=resolution,
            narration=narration,
            narration_event_id=narration_event.id,
            committed_fact_count=committed_count,
            clocks_fired=clocks_fired,
            audit_flags=all_audit_flags,
            effect_results=beat_effect_results,
            applied_trade=effective_trade,
            effective_exposure=effective_exposure,
            effective_effect=effective_effect,
            edge_spend=edge_spend,
            edge_spent=edge_any_spent,
            edge_step_applied=edge_step_applied,
            lifecycle_state=ActionLifecycleState.COMMITTED,
        )

    def run_with_agent(
        self,
        agent: CharacterAgent,
        queue: ActionQueue | None = None,
    ) -> BeatResult:
        """Run one beat where an AI-driven agent proposes its own action (phase 7).

        Channel and target are preserved from the agent's Proposal through queue
        transit and into run() — they are never discarded or reconstructed.
        """
        proposal = agent.propose(self._assembler, budgeter=self._budgeter)
        if queue is not None:
            queue.enqueue(proposal)
            proposals = queue.drain()
            proposal = proposals[0]

        action = proposal.intent
        if proposal.dialogue:
            action = f'{proposal.intent} (says: "{proposal.dialogue}")'

        return self.run(
            actor=agent.entity_id,
            action=action,
            channel=proposal.channel,
            target=proposal.target,
            edge_spend=proposal.edge_spend,
            edge_justification=proposal.edge_justification,
            edge_shield_target=proposal.edge_shield_target,
        )

    def run_round(
        self,
        orchestrator: Orchestrator,
        agents: dict[str, CharacterAgent],
        player_proposals: dict[str, str | Proposal] | None = None,
        present: list[str] | None = None,
        queue: ActionQueue | None = None,
        scene_cadence: SceneCadence | None = None,
    ) -> list[BeatResult]:
        """Run one full round: each present (and activated) seat gets one beat.

        The orchestrator (routing metadata only) decides turn order. For each seat:
          - AI seats: agent.propose(assembler) → run_with_agent
          - Human seats: player_proposals value (str or Proposal) → run

        When scene_cadence is supplied (Phase 16), AI companion seats are filtered
        through SceneCadence.select_companions before the round begins. Gated
        companions are removed from the rotation and receive no model call that
        round. Human seats (those without an agent entry) are never gated.

        String values in player_proposals are treated as public-channel actions.
        Pass a Proposal to specify whisper or OOC channel with a target.

        `present` defaults to the orchestrator's full roster when omitted.
        Raises ValueError if a seat has neither an agent nor a player proposal.
        """
        player_proposals = player_proposals or {}
        remaining = list(present) if present is not None else list(orchestrator.seats)

        # Phase 16: gate AI companions that the scene cadence does not activate.
        # Human seats (present in player_proposals but not in agents) are never gated.
        if scene_cadence is not None:
            ai_seats = [s for s in remaining if s in agents]
            spotlight = orchestrator.sorted_by_spotlight(ai_seats)
            active_ai = set(scene_cadence.select_companions(ai_seats, spotlight_order=spotlight))
            remaining = [s for s in remaining if s not in agents or s in active_ai]

        # Phase 21: pre-collect all proposals before any beat runs so the shield
        # registry is complete before the first beat begins. AI agents propose now
        # (before seeing other agents' beats this round — same window as before).
        pre_proposals: dict[str, Proposal] = {}
        for seat in remaining:
            if seat in agents:
                pre_proposals[seat] = agents[seat].propose(
                    self._assembler, budgeter=self._budgeter
                )
            elif seat in player_proposals:
                raw = player_proposals[seat]
                pre_proposals[seat] = (
                    Proposal(agent=seat, intent=raw, channel="public")
                    if isinstance(raw, str)
                    else raw
                )
            else:
                raise ValueError(
                    f"seat {seat!r} has no registered agent and no player proposal — "
                    f"provide one or the other in `agents` or `player_proposals`"
                )

        # Build shield registry: {shielded_entity_id: shielder_entity_id}.
        shield_registry: dict[str, str] = {
            p.edge_shield_target: seat
            for seat, p in pre_proposals.items()
            if p.edge_spend == "shield" and p.edge_shield_target
        }

        results: list[BeatResult] = []
        while remaining:
            grant = orchestrator.grant_turn(remaining)
            actor = grant.actor
            remaining.remove(actor)

            proposal = pre_proposals[actor]
            if queue is not None:
                queue.enqueue(proposal)
                proposal = queue.drain()[0]

            action = proposal.intent
            if proposal.dialogue:
                action = f'{proposal.intent} (says: "{proposal.dialogue}")'

            result = self.run(
                actor=actor,
                action=action,
                channel=proposal.channel,
                target=proposal.target,
                edge_spend=proposal.edge_spend,
                edge_justification=proposal.edge_justification,
                edge_shield_target=proposal.edge_shield_target,
                _shield_registry=shield_registry if shield_registry else None,
            )
            orchestrator.record_acted(actor)
            results.append(result)

        return results
