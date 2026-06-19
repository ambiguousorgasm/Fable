"""Typed effect executor — validated, deterministic state operations (CORE §3; Phase 12).

Every durable world-state change flows through the EffectExecutor. A GM or
rules-engine component proposes a TypedEffect; the executor validates it against
current world state, applies the mutation, and logs a provenance event with a
`derived_from` link to the source beat or resolution event.

Architecture invariants enforced here:
  * State changes occur only through validated typed effects (invariant 1).
  * Narration cannot create state changes — narrators never hold an executor
    reference; the structural boundary is at BeatRunner, not inside the executor
    (invariant 2).
  * Invalid effects are rejected before any state mutation (invariant 5).
  * Effects preserve existing canon and transaction boundaries (invariant 6):
    truth effects route through CommitPipeline; CanonConflictError surfaces as
    an accepted=False EffectResult rather than an exception, so the caller can
    decide whether to abort or continue the beat.

Truth expiry (ExpireTruth / ExpireMaintainedTruth) uses the "expired" epistemic
type as a tombstone; committed_facts() removes the prior fact when it encounters
one (Phase 12 / D-024 extension).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Union

from .access import CanonConflictError
from .events import Commitment

if TYPE_CHECKING:
    from .access import CommitPipeline
    from .event_log import EventLog
    from .perception import Scene
    from .world_state import Entity, WorldState


# --------------------------------------------------------------------------- #
# Effect operations                                                             #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CreateTruth:
    """Establish a new objective fact. Fails if it would contradict canon."""
    kind: Literal["create_truth"]
    subject: str
    predicate: str
    value: Any
    revealed: bool = True


@dataclass(frozen=True)
class ChangeTruth:
    """Revise an existing objective fact (intentional override; always accepted)."""
    kind: Literal["change_truth"]
    subject: str
    predicate: str
    value: Any
    revealed: bool = True
    reason: str = "typed effect revision"


@dataclass(frozen=True)
class ExpireTruth:
    """Tombstone a prior fact; removes it from committed_facts going forward."""
    kind: Literal["expire_truth"]
    subject: str
    predicate: str
    revealed: bool = True


@dataclass(frozen=True)
class AdvanceClock:
    """Advance a named clock by `steps` segments."""
    kind: Literal["advance_clock"]
    clock_name: str
    steps: int = 1


@dataclass(frozen=True)
class ApplyScar:
    """Apply a lasting Scar (Wound, Mark, or Loss) to a character (v6 §14).

    **Scar Route Invariant** (v6 §14, invariant 9): a Scar lands ONLY through
    Stress overflow or a live Seam exploited by a terminal consequence. Set
    `via_overflow=True` for the overflow path, or supply `seam_event_id` for
    the Seam path. Both absent → rejected.

    The executor enforces the 3-slot cap. A 4th Scar is rejected. When the
    3rd Scar lands the executor appends a `character_broken` event.

    Scars are stored on the entity as `entity.resources["scars"]`: a list of
    ``{"scar_type": ..., "description": ...}`` dicts.
    """
    kind: Literal["apply_scar"]
    entity_id: str
    scar_type: Literal["wound", "mark", "loss"]
    description: str
    via_overflow: bool = False
    seam_event_id: str | None = None


@dataclass(frozen=True)
class ApplyStress:
    """Add (or subtract, if negative) stress to an entity's stress resource.

    **Cap enforcement** (v6 §14): STRESS_CAP = 6 boxes.
    - Positive amounts that keep stress ≤ 6 are applied normally.
    - Positive amounts that would push stress above 6 trigger the overflow
      route: `overflow_scar_type` and `overflow_scar_desc` must be set. The
      executor clears stress to 0 and automatically applies the named Scar
      with `via_overflow=True`.
    - Negative amounts floor at 0 (stress relief cannot produce negative stress).
    """
    kind: Literal["apply_stress"]
    entity_id: str
    amount: int
    overflow_scar_type: Literal["wound", "mark", "loss"] | None = None
    overflow_scar_desc: str = ""


@dataclass(frozen=True)
class ChangeAccess:
    """Alter lighting or connection state on the Scene.

    operation:
      "darken"      — zone_a goes dark (zone_b must be None)
      "illuminate"  — zone_a goes lit (zone_b must be None)
      "close"       — close the connection between zone_a and zone_b
      "open"        — reopen the connection between zone_a and zone_b
    """
    kind: Literal["change_access"]
    operation: Literal["darken", "illuminate", "close", "open"]
    zone_a: str
    zone_b: str | None = None


@dataclass(frozen=True)
class MoveEntity:
    """Place an entity in a zone."""
    kind: Literal["move_entity"]
    entity_id: str
    to_zone: str


@dataclass(frozen=True)
class ChangeResource:
    """Mutate a named resource on an entity.

    Exactly one of `delta` (signed increment) or `set_value` (absolute) must
    be supplied.
    """
    kind: Literal["change_resource"]
    entity_id: str
    resource: str
    delta: int | None = None
    set_value: int | None = None


@dataclass(frozen=True)
class CreateMaintainedTruth:
    """Establish a fact that persists under a named lapse condition.

    Also commits the fact to the event log so it appears in belief stores and
    registers the lapse condition in WorldState.maintained_truths for later
    retrieval by the GM.
    """
    kind: Literal["create_maintained_truth"]
    subject: str
    predicate: str
    value: Any
    lapse_condition: str
    revealed: bool = True


@dataclass(frozen=True)
class ExpireMaintainedTruth:
    """Retire a maintained truth: tombstone the fact and remove the lapse record."""
    kind: Literal["expire_maintained_truth"]
    subject: str
    predicate: str
    revealed: bool = True


STRESS_CAP = 6  # v6 §14 — 6-box track
SCAR_CAP = 3   # v6 §14 — 3 slots; at cap the character is Broken
EDGE_CAP = 3   # v6 §13


@dataclass(frozen=True)
class GainEdge:
    """Grant Edge to an entity, respecting the cap-3 invariant (v6 §13).

    Used by the compel-accept path and Triumph consequence. Excess above cap is
    silently dropped — the result is always clamped to EDGE_CAP.
    """
    kind: Literal["gain_edge"]
    entity_id: str
    amount: int = 1


@dataclass(frozen=True)
class SpendEdge:
    """Spend Edge from an entity. Fails if insufficient Edge available (v6 §13).

    spend_type: "lean" | "push" | "shield" (logged for provenance; not enforced
    here — the calling code (beat / compel resolver) enforces pre/post-roll rules).
    """
    kind: Literal["spend_edge"]
    entity_id: str
    amount: int
    spend_type: str = "lean"


TypedEffect = Union[
    CreateTruth,
    ChangeTruth,
    ExpireTruth,
    AdvanceClock,
    ApplyScar,
    ApplyStress,
    ChangeAccess,
    MoveEntity,
    ChangeResource,
    CreateMaintainedTruth,
    ExpireMaintainedTruth,
    GainEdge,
    SpendEdge,
]

# Event type written by the executor for all applied effects.
EFFECT_EVENT_TYPE = "effect_applied"

# The executor always logs under this author (determinism boundary; not a model role).
EFFECT_AUTHOR = "rules-engine"


# --------------------------------------------------------------------------- #
# Result                                                                        #
# --------------------------------------------------------------------------- #

@dataclass
class EffectResult:
    """Outcome of executing one TypedEffect."""

    effect: TypedEffect
    accepted: bool
    rejection_reason: str | None = None
    event_id: str | None = None      # ID of the logged provenance event (accepted only)


# --------------------------------------------------------------------------- #
# Executor                                                                      #
# --------------------------------------------------------------------------- #

def _derived_from(source_event_id: str | None) -> tuple[str, ...]:
    return (source_event_id,) if source_event_id else ()


class EffectExecutor:
    """Validates and applies TypedEffect operations to world state.

    Owns no authoritative state. Construct once per session (or per beat if
    preferred) and pass to BeatRunner. The narrator never receives a reference
    to this object — that structural gap is the enforcement of invariant 2
    (narration cannot create state changes).

    Pass `scene` to enable ChangeAccess operations (lighting, connections).
    Omit it to reject those operations gracefully rather than raising.
    """

    def __init__(
        self,
        log: "EventLog",
        world: "WorldState",
        pipeline: "CommitPipeline",
        scene: "Scene | None" = None,
    ) -> None:
        self._log = log
        self._world = world
        self._pipeline = pipeline
        self._scene = scene

    def apply(
        self,
        effect: TypedEffect,
        *,
        audience: tuple[str, ...],
        source_event_id: str | None = None,
    ) -> EffectResult:
        """Validate and apply one typed effect.

        Returns an EffectResult. On validation failure or canon conflict the
        result has accepted=False and no state is mutated. Never raises on
        expected failures (CanonConflictError, missing entity/zone, etc.).
        """
        if isinstance(effect, CreateTruth):
            return self._create_truth(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, ChangeTruth):
            return self._change_truth(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, ExpireTruth):
            return self._expire_truth(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, AdvanceClock):
            return self._advance_clock(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, ApplyScar):
            return self._apply_scar(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, ApplyStress):
            return self._apply_stress(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, ChangeAccess):
            return self._change_access(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, MoveEntity):
            return self._move_entity(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, ChangeResource):
            return self._change_resource(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, CreateMaintainedTruth):
            return self._create_maintained_truth(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, ExpireMaintainedTruth):
            return self._expire_maintained_truth(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, GainEdge):
            return self._gain_edge(effect, audience=audience, source_event_id=source_event_id)
        if isinstance(effect, SpendEdge):
            return self._spend_edge(effect, audience=audience, source_event_id=source_event_id)
        return EffectResult(
            effect=effect, accepted=False,
            rejection_reason=f"unsupported effect type: {type(effect).__name__}",
        )

    def apply_all(
        self,
        effects: list[TypedEffect],
        *,
        audience: tuple[str, ...],
        source_event_id: str | None = None,
    ) -> list[EffectResult]:
        """Apply a list of effects in order. Each is independent; a rejection
        does not stop subsequent effects."""
        return [
            self.apply(e, audience=audience, source_event_id=source_event_id)
            for e in effects
        ]

    # ---------------------------------------------------------------------- #
    # Truth operations                                                         #
    # ---------------------------------------------------------------------- #

    def _commit_truth(
        self,
        effect: TypedEffect,
        *,
        subject: str,
        predicate: str,
        value: Any,
        revealed: bool,
        epistemic_type: str,
        content: str,
        audience: tuple[str, ...],
        source_event_id: str | None,
        override: bool = False,
        override_reason: str | None = None,
    ) -> EffectResult:
        commitment = Commitment(
            subject=subject, predicate=predicate, value=value,
            revealed=revealed, epistemic_type=epistemic_type,
        )
        try:
            event = self._pipeline.commit(
                author=EFFECT_AUTHOR,
                channel="system",
                type=EFFECT_EVENT_TYPE,
                content=content,
                audience=audience,
                commitments=[commitment],
                derived_from=_derived_from(source_event_id),
                override=override,
                reason=override_reason,
            )
        except CanonConflictError as exc:
            return EffectResult(effect=effect, accepted=False, rejection_reason=str(exc))
        return EffectResult(effect=effect, accepted=True, event_id=event.id)

    def _create_truth(
        self, effect: CreateTruth, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if not effect.subject or not effect.predicate:
            return EffectResult(effect=effect, accepted=False, rejection_reason="subject and predicate must be non-empty")
        return self._commit_truth(
            effect, subject=effect.subject, predicate=effect.predicate,
            value=effect.value, revealed=effect.revealed, epistemic_type="fact",
            content=f"create_truth: {effect.subject}.{effect.predicate} = {effect.value!r}",
            audience=audience, source_event_id=source_event_id,
        )

    def _change_truth(
        self, effect: ChangeTruth, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if not effect.subject or not effect.predicate:
            return EffectResult(effect=effect, accepted=False, rejection_reason="subject and predicate must be non-empty")
        return self._commit_truth(
            effect, subject=effect.subject, predicate=effect.predicate,
            value=effect.value, revealed=effect.revealed, epistemic_type="fact",
            content=f"change_truth: {effect.subject}.{effect.predicate} = {effect.value!r}",
            audience=audience, source_event_id=source_event_id,
            override=True, override_reason=effect.reason,
        )

    def _expire_truth(
        self, effect: ExpireTruth, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if not effect.subject or not effect.predicate:
            return EffectResult(effect=effect, accepted=False, rejection_reason="subject and predicate must be non-empty")
        return self._commit_truth(
            effect, subject=effect.subject, predicate=effect.predicate,
            value=None, revealed=effect.revealed, epistemic_type="expired",
            content=f"expire_truth: {effect.subject}.{effect.predicate}",
            audience=audience, source_event_id=source_event_id,
        )

    # ---------------------------------------------------------------------- #
    # Clock operations                                                         #
    # ---------------------------------------------------------------------- #

    def _advance_clock(
        self, effect: AdvanceClock, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if effect.clock_name not in self._world.clocks:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"clock {effect.clock_name!r} not found",
            )
        if effect.steps <= 0:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason="steps must be a positive integer",
            )
        clock = self._world.clocks[effect.clock_name]
        if clock.get("fired"):
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"clock {effect.clock_name!r} has already fired",
            )

        current = int(clock.get("current", 0))
        max_ = int(clock.get("max", 6))
        new_val = min(current + effect.steps, max_)
        fired = new_val >= max_

        self._world.set_clock(effect.clock_name, {**clock, "current": new_val, "fired": fired})

        event = self._log.append(
            author=EFFECT_AUTHOR,
            channel="system",
            type=EFFECT_EVENT_TYPE,
            content=(
                f"advance_clock: {effect.clock_name} {current} → {new_val}/{max_}"
                + (" [FIRED]" if fired else "")
            ),
            audience=audience,
            derived_from=_derived_from(source_event_id),
        )
        if fired:
            self._log.append(
                author=EFFECT_AUTHOR,
                channel="system",
                type="front_advance",
                content=f"Clock '{effect.clock_name}' filled ({max_}/{max_}) — front fires.",
                audience=audience,
                derived_from=(event.id,),
            )
        return EffectResult(effect=effect, accepted=True, event_id=event.id)

    # ---------------------------------------------------------------------- #
    # Entity operations                                                         #
    # ---------------------------------------------------------------------- #

    def _apply_scar(
        self, effect: ApplyScar, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if effect.entity_id not in self._world.entities:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"entity {effect.entity_id!r} not found",
            )
        # Scar Route Invariant (v6 §14, invariant 9)
        if not effect.via_overflow and effect.seam_event_id is None:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=(
                    "Scar Route Invariant: set via_overflow=True (stress overflow path) "
                    "or provide seam_event_id (live Seam terminal consequence path)"
                ),
            )
        if not effect.description:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason="scar description must be non-empty",
            )
        entity = self._world.entities[effect.entity_id]
        scars: list = list(entity.resources.get("scars", []))
        if len(scars) >= SCAR_CAP:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"scar cap reached ({SCAR_CAP}/{SCAR_CAP}); character is already Broken",
            )
        scars.append({"scar_type": effect.scar_type, "description": effect.description})
        entity.resources["scars"] = scars
        self._world.update_entity(entity)

        route = "overflow" if effect.via_overflow else f"seam:{effect.seam_event_id}"
        event = self._log.append(
            author=EFFECT_AUTHOR,
            channel="system",
            type=EFFECT_EVENT_TYPE,
            content=(
                f"apply_scar ({effect.scar_type}, {route}): {effect.entity_id} — "
                f"{effect.description} [{len(scars)}/{SCAR_CAP}]"
            ),
            audience=audience,
            derived_from=_derived_from(source_event_id),
        )
        if len(scars) >= SCAR_CAP:
            self._log.append(
                author=EFFECT_AUTHOR,
                channel="system",
                type="character_broken",
                content=f"{effect.entity_id} is Broken ({SCAR_CAP}/{SCAR_CAP} Scars).",
                audience=audience,
                derived_from=(event.id,),
            )
        return EffectResult(effect=effect, accepted=True, event_id=event.id)

    def _apply_stress(
        self, effect: ApplyStress, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if effect.entity_id not in self._world.entities:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"entity {effect.entity_id!r} not found",
            )
        if effect.amount == 0:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason="stress amount must be non-zero",
            )
        entity = self._world.entities[effect.entity_id]
        current = int(entity.resources.get("stress", 0))
        new_stress = current + effect.amount

        # Floor at 0: stress relief cannot go negative
        if new_stress < 0:
            new_stress = 0

        # Overflow: would exceed the 6-box cap
        if new_stress > STRESS_CAP:
            if not effect.overflow_scar_type:
                return EffectResult(
                    effect=effect, accepted=False,
                    rejection_reason=(
                        f"stress overflow (would reach {new_stress}/{STRESS_CAP}): "
                        "provide overflow_scar_type and overflow_scar_desc"
                    ),
                )
            # Clear stress and cascade to a Scar
            entity.resources["stress"] = 0
            self._world.update_entity(entity)
            stress_event = self._log.append(
                author=EFFECT_AUTHOR,
                channel="system",
                type=EFFECT_EVENT_TYPE,
                content=f"apply_stress: {effect.entity_id} stress overflow {current} → 0 (Scar route)",
                audience=audience,
                derived_from=_derived_from(source_event_id),
            )
            desc = effect.overflow_scar_desc or f"{effect.overflow_scar_type} from stress overflow"
            scar_result = self._apply_scar(
                ApplyScar(
                    kind="apply_scar",
                    entity_id=effect.entity_id,
                    scar_type=effect.overflow_scar_type,
                    description=desc,
                    via_overflow=True,
                ),
                audience=audience,
                source_event_id=stress_event.id,
            )
            if not scar_result.accepted:
                return EffectResult(
                    effect=effect, accepted=False,
                    rejection_reason=f"stress overflow scar rejected: {scar_result.rejection_reason}",
                )
            return EffectResult(effect=effect, accepted=True, event_id=stress_event.id)

        entity.resources["stress"] = new_stress
        self._world.update_entity(entity)
        event = self._log.append(
            author=EFFECT_AUTHOR,
            channel="system",
            type=EFFECT_EVENT_TYPE,
            content=f"apply_stress: {effect.entity_id} stress {current} → {new_stress}",
            audience=audience,
            derived_from=_derived_from(source_event_id),
        )
        return EffectResult(effect=effect, accepted=True, event_id=event.id)

    def _move_entity(
        self, effect: MoveEntity, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if effect.entity_id not in self._world.entities:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"entity {effect.entity_id!r} not found",
            )
        if effect.to_zone not in self._world.zones:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"zone {effect.to_zone!r} not found",
            )
        self._world.place(effect.entity_id, effect.to_zone)
        event = self._log.append(
            author=EFFECT_AUTHOR,
            channel="system",
            type=EFFECT_EVENT_TYPE,
            content=f"move_entity: {effect.entity_id} → {effect.to_zone}",
            audience=audience,
            derived_from=_derived_from(source_event_id),
        )
        return EffectResult(effect=effect, accepted=True, event_id=event.id)

    def _change_resource(
        self, effect: ChangeResource, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if effect.entity_id not in self._world.entities:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"entity {effect.entity_id!r} not found",
            )
        if (effect.delta is None) == (effect.set_value is None):
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason="exactly one of delta or set_value must be supplied",
            )
        entity = self._world.entities[effect.entity_id]
        if effect.delta is not None:
            new_val = entity.resources.get(effect.resource, 0) + effect.delta
        else:
            new_val = effect.set_value
        entity.resources[effect.resource] = new_val
        self._world.update_entity(entity)

        event = self._log.append(
            author=EFFECT_AUTHOR,
            channel="system",
            type=EFFECT_EVENT_TYPE,
            content=f"change_resource: {effect.entity_id}.{effect.resource} → {new_val}",
            audience=audience,
            derived_from=_derived_from(source_event_id),
        )
        return EffectResult(effect=effect, accepted=True, event_id=event.id)

    # ---------------------------------------------------------------------- #
    # Edge operations (v6 §13)                                                  #
    # ---------------------------------------------------------------------- #

    def _gain_edge(
        self, effect: GainEdge, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if effect.entity_id not in self._world.entities:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"entity {effect.entity_id!r} not found",
            )
        if effect.amount <= 0:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason="gain_edge amount must be positive",
            )
        entity = self._world.entities[effect.entity_id]
        current = int(entity.resources.get("edge", 0))
        new_edge = min(current + effect.amount, EDGE_CAP)
        entity.resources["edge"] = new_edge
        self._world.update_entity(entity)

        event = self._log.append(
            author=EFFECT_AUTHOR,
            channel="system",
            type=EFFECT_EVENT_TYPE,
            content=f"gain_edge: {effect.entity_id} edge {current} → {new_edge}",
            audience=audience,
            derived_from=_derived_from(source_event_id),
        )
        return EffectResult(effect=effect, accepted=True, event_id=event.id)

    def _spend_edge(
        self, effect: SpendEdge, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if effect.entity_id not in self._world.entities:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"entity {effect.entity_id!r} not found",
            )
        if effect.amount <= 0:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason="spend_edge amount must be positive",
            )
        entity = self._world.entities[effect.entity_id]
        current = int(entity.resources.get("edge", 0))
        if current < effect.amount:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"insufficient edge: have {current}, need {effect.amount}",
            )
        entity.resources["edge"] = current - effect.amount
        self._world.update_entity(entity)

        event = self._log.append(
            author=EFFECT_AUTHOR,
            channel="system",
            type=EFFECT_EVENT_TYPE,
            content=f"spend_edge ({effect.spend_type}): {effect.entity_id} edge {current} → {current - effect.amount}",
            audience=audience,
            derived_from=_derived_from(source_event_id),
        )
        return EffectResult(effect=effect, accepted=True, event_id=event.id)

    # ---------------------------------------------------------------------- #
    # Scene / access operations                                                 #
    # ---------------------------------------------------------------------- #

    def _change_access(
        self, effect: ChangeAccess, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if self._scene is None:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason="ChangeAccess requires a Scene; none was supplied to EffectExecutor",
            )
        op = effect.operation
        if op in ("close", "open"):
            if effect.zone_b is None:
                return EffectResult(
                    effect=effect, accepted=False,
                    rejection_reason="zone_b is required for close/open operations",
                )
            for z in (effect.zone_a, effect.zone_b):
                if z not in self._world.zones:
                    return EffectResult(
                        effect=effect, accepted=False,
                        rejection_reason=f"zone {z!r} not found in world topology",
                    )
            if not self._world.are_connected(effect.zone_a, effect.zone_b):
                return EffectResult(
                    effect=effect, accepted=False,
                    rejection_reason=f"zones {effect.zone_a!r} and {effect.zone_b!r} are not connected",
                )
            if op == "close":
                self._scene.close(effect.zone_a, effect.zone_b)
            else:
                self._scene.open_connection(effect.zone_a, effect.zone_b)
            desc = f"{op}: {effect.zone_a} ↔ {effect.zone_b}"
        else:
            if effect.zone_a not in self._world.zones:
                return EffectResult(
                    effect=effect, accepted=False,
                    rejection_reason=f"zone {effect.zone_a!r} not found in world topology",
                )
            if effect.zone_b is not None:
                return EffectResult(
                    effect=effect, accepted=False,
                    rejection_reason="zone_b must be None for darken/illuminate operations",
                )
            if op == "darken":
                self._scene.darken(effect.zone_a)
            else:
                self._scene.illuminate(effect.zone_a)
            desc = f"{op}: {effect.zone_a}"

        event = self._log.append(
            author=EFFECT_AUTHOR,
            channel="system",
            type=EFFECT_EVENT_TYPE,
            content=f"change_access: {desc}",
            audience=audience,
            derived_from=_derived_from(source_event_id),
        )
        return EffectResult(effect=effect, accepted=True, event_id=event.id)

    # ---------------------------------------------------------------------- #
    # Maintained truth operations                                               #
    # ---------------------------------------------------------------------- #

    def _create_maintained_truth(
        self, effect: CreateMaintainedTruth, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        if not effect.subject or not effect.predicate:
            return EffectResult(effect=effect, accepted=False, rejection_reason="subject and predicate must be non-empty")
        if not effect.lapse_condition:
            return EffectResult(effect=effect, accepted=False, rejection_reason="lapse_condition must be non-empty")

        commitment = Commitment(
            subject=effect.subject, predicate=effect.predicate, value=effect.value,
            revealed=effect.revealed, epistemic_type="fact",
        )
        try:
            event = self._pipeline.commit(
                author=EFFECT_AUTHOR,
                channel="system",
                type=EFFECT_EVENT_TYPE,
                content=(
                    f"create_maintained_truth: {effect.subject}.{effect.predicate} = {effect.value!r}"
                    f" [lapses: {effect.lapse_condition}]"
                ),
                audience=audience,
                commitments=[commitment],
                derived_from=_derived_from(source_event_id),
            )
        except CanonConflictError as exc:
            return EffectResult(effect=effect, accepted=False, rejection_reason=str(exc))

        key = f"{effect.subject}::{effect.predicate}"
        self._world.set_maintained_truth(key, {
            "subject": effect.subject,
            "predicate": effect.predicate,
            "value": effect.value,
            "lapse_condition": effect.lapse_condition,
            "revealed": effect.revealed,
        })
        return EffectResult(effect=effect, accepted=True, event_id=event.id)

    def _expire_maintained_truth(
        self, effect: ExpireMaintainedTruth, *, audience: tuple[str, ...], source_event_id: str | None
    ) -> EffectResult:
        key = f"{effect.subject}::{effect.predicate}"
        if key not in self._world.maintained_truths:
            return EffectResult(
                effect=effect, accepted=False,
                rejection_reason=f"maintained truth {key!r} not found",
            )
        self._world.expire_maintained_truth(key)

        commitment = Commitment(
            subject=effect.subject, predicate=effect.predicate, value=None,
            revealed=effect.revealed, epistemic_type="expired",
        )
        event = self._pipeline.commit(
            author=EFFECT_AUTHOR,
            channel="system",
            type=EFFECT_EVENT_TYPE,
            content=f"expire_maintained_truth: {effect.subject}.{effect.predicate}",
            audience=audience,
            commitments=[commitment],
            derived_from=_derived_from(source_event_id),
        )
        return EffectResult(effect=effect, accepted=True, event_id=event.id)


# --------------------------------------------------------------------------- #
# Palette utilities (Phase 13)                                                  #
# --------------------------------------------------------------------------- #

def effect_from_dict(d: dict) -> TypedEffect:
    """Convert a raw dict (e.g. from an adjudicator tool call) to a TypedEffect.

    Used to deserialise consequence-palette entries from the adjudicator's JSON
    output. Raises ValueError for unknown kinds and KeyError for missing fields.
    """
    kind = d.get("kind")
    if kind == "create_truth":
        return CreateTruth(
            kind="create_truth", subject=d["subject"], predicate=d["predicate"],
            value=d["value"], revealed=bool(d.get("revealed", True)),
        )
    if kind == "change_truth":
        return ChangeTruth(
            kind="change_truth", subject=d["subject"], predicate=d["predicate"],
            value=d["value"], revealed=bool(d.get("revealed", True)),
            reason=d.get("reason", "typed effect revision"),
        )
    if kind == "expire_truth":
        return ExpireTruth(
            kind="expire_truth", subject=d["subject"], predicate=d["predicate"],
            revealed=bool(d.get("revealed", True)),
        )
    if kind == "advance_clock":
        return AdvanceClock(
            kind="advance_clock", clock_name=d["clock_name"],
            steps=int(d.get("steps", 1)),
        )
    if kind == "apply_scar":
        return ApplyScar(
            kind="apply_scar",
            entity_id=d["entity_id"],
            scar_type=d["scar_type"],
            description=d["description"],
            via_overflow=bool(d.get("via_overflow", False)),
            seam_event_id=d.get("seam_event_id"),
        )
    if kind == "apply_stress":
        return ApplyStress(
            kind="apply_stress", entity_id=d["entity_id"], amount=int(d["amount"]),
            overflow_scar_type=d.get("overflow_scar_type"),
            overflow_scar_desc=str(d.get("overflow_scar_desc", "")),
        )
    if kind == "change_access":
        return ChangeAccess(
            kind="change_access", operation=d["operation"],
            zone_a=d["zone_a"], zone_b=d.get("zone_b"),
        )
    if kind == "move_entity":
        return MoveEntity(
            kind="move_entity", entity_id=d["entity_id"], to_zone=d["to_zone"],
        )
    if kind == "change_resource":
        return ChangeResource(
            kind="change_resource", entity_id=d["entity_id"], resource=d["resource"],
            delta=d.get("delta"), set_value=d.get("set_value"),
        )
    if kind == "create_maintained_truth":
        return CreateMaintainedTruth(
            kind="create_maintained_truth", subject=d["subject"],
            predicate=d["predicate"], value=d["value"],
            lapse_condition=d["lapse_condition"], revealed=bool(d.get("revealed", True)),
        )
    if kind == "expire_maintained_truth":
        return ExpireMaintainedTruth(
            kind="expire_maintained_truth", subject=d["subject"],
            predicate=d["predicate"], revealed=bool(d.get("revealed", True)),
        )
    if kind == "gain_edge":
        return GainEdge(
            kind="gain_edge", entity_id=d["entity_id"], amount=int(d.get("amount", 1)),
        )
    if kind == "spend_edge":
        return SpendEdge(
            kind="spend_edge", entity_id=d["entity_id"], amount=int(d["amount"]),
            spend_type=str(d.get("spend_type", "lean")),
        )
    raise ValueError(f"unknown effect kind {kind!r}")


def describe_effect(effect: TypedEffect) -> str:
    """Return a brief human-readable description of an effect for narrator context."""
    if isinstance(effect, CreateTruth):
        return f"{effect.subject} {effect.predicate}: {effect.value}"
    if isinstance(effect, ChangeTruth):
        return f"{effect.subject} {effect.predicate} changed to: {effect.value}"
    if isinstance(effect, ExpireTruth):
        return f"{effect.subject} {effect.predicate} no longer holds"
    if isinstance(effect, AdvanceClock):
        return f"clock '{effect.clock_name}' advanced {effect.steps} step(s)"
    if isinstance(effect, ApplyScar):
        route = "overflow" if effect.via_overflow else f"seam:{effect.seam_event_id}"
        return f"{effect.entity_id} takes {effect.scar_type} Scar ({route}): {effect.description}"
    if isinstance(effect, ApplyStress):
        direction = "gained" if effect.amount > 0 else "relieved"
        desc = f"{effect.entity_id} {direction} {abs(effect.amount)} stress"
        if effect.overflow_scar_type:
            desc += f" (overflow → {effect.overflow_scar_type} Scar if cap exceeded)"
        return desc
    if isinstance(effect, ChangeAccess):
        if effect.zone_b:
            return f"{effect.operation}: {effect.zone_a} ↔ {effect.zone_b}"
        return f"{effect.operation}: {effect.zone_a}"
    if isinstance(effect, MoveEntity):
        return f"{effect.entity_id} moved to {effect.to_zone}"
    if isinstance(effect, ChangeResource):
        if effect.delta is not None:
            sign = "+" if effect.delta >= 0 else ""
            return f"{effect.entity_id} {effect.resource} {sign}{effect.delta}"
        return f"{effect.entity_id} {effect.resource} set to {effect.set_value}"
    if isinstance(effect, CreateMaintainedTruth):
        return f"{effect.subject} {effect.predicate}: {effect.value} (until: {effect.lapse_condition})"
    if isinstance(effect, ExpireMaintainedTruth):
        return f"{effect.subject} {effect.predicate} expired"
    if isinstance(effect, GainEdge):
        return f"{effect.entity_id} gains {effect.amount} Edge (cap {EDGE_CAP})"
    if isinstance(effect, SpendEdge):
        return f"{effect.entity_id} spends {effect.amount} Edge ({effect.spend_type})"
    return str(effect)
