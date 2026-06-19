"""Context assembly — per-POV view construction (CORE §6.3, §6.4; phase 4).

Every agent acts from a *belief store*: the read-time projection of the event
log filtered by that agent's audience membership (D-001 — one source of truth,
derived on read, never a materialized per-agent store that could drift). This
module builds that projection into a usable context for one point of view.

What it composes today:
  * the projected event log for the POV (already audience/visibility filtered by
    `EventLog.project_for`, with per-POV contiguous ordering — D-013);
  * the facts the POV *believes*, folded only from the commitments it actually
    saw at content level — NOT the global canon ledger. A fact revealed in a
    scene the POV wasn't party to must not appear in its beliefs; deriving from
    the POV's own projection is what makes differential information automatic
    (CORE §7.1);
  * the POV's ambient perceptual situation (who it can currently sense), when a
    Scene is supplied.

What it deliberately omits until later phases: persona spec (phase 6),
disposition (phase 10), retrieved memory. Those slot in as additional fields on
`BeliefStore` without changing the projection seam.

Audience derivation (intended recipients + whoever perception says could
perceive, CORE §7.1) happens upstream at commit time via
`perception.derive_overhears`; context assembly only *consumes* the resulting
projection. The single chokepoint that runs derive-then-commit is the beat
loop (phase 7), not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from .events import ProjectedEvent
from .perception import Scene, perceptible_entities

if TYPE_CHECKING:
    from .lorebook import LoreAssembler, LoreEntry


@dataclass(frozen=True)
class Belief:
    """A commitment a POV holds, with the projected event it learned it from.

    Derived from the POV's projection, so it only ever reflects what that POV
    was entitled to see. `source_event_id` is the projected event's id (stable
    cross-POV identity), not a position.

    `epistemic_type` mirrors the originating Commitment (D-024, D-032):
      "fact"        — objective committed state; enters BeliefStore.beliefs
      "claim"       — asserted by a speaker; enters BeliefStore.claims
      "observation" — perceived by this POV; enters BeliefStore.observations
      "theory"      — character inference or explicit suspicion; enters
                      BeliefStore.theories (D-032, Phase 21)

    Provenance fields carry who asserted or observed this. Both default to None
    so existing sites that don't supply them are unaffected.
    """

    subject: str
    predicate: str
    value: Any
    source_event_id: str
    epistemic_type: str = "fact"
    asserting_entity: str | None = None   # who made this claim (claims only)
    observing_entity: str | None = None   # who observed this (observations only)

    @property
    def key(self) -> tuple[str, str]:
        return (self.subject, self.predicate)


@dataclass(frozen=True)
class BeliefStore:
    """One POV's assembled context — its entire epistemic world.

    `events` is the POV's projection; `beliefs` are the *facts* folded from it
    (latest per (subject, predicate) — objective committed state this POV saw);
    `claims` are all heard claims in POV order (may repeat subject/predicate keys
    — multiple speakers may have claimed different things); `observations` are all
    observations this POV made in POV order; `theories` are character inferences or
    explicit suspicions in POV order (D-032). `perceptible` is who the POV can
    currently sense (empty when no Scene was supplied).

    Invariant (D-024, Phase 11, D-032): `believes()` and `value_of()` operate only
    on the facts dict. Claims and theories never silently enter the facts dict, and
    observations remain POV-private to the audience they were scoped to.

    Frozen: a belief store is a derived snapshot, never authoritative.
    """

    pov: str
    events: tuple[ProjectedEvent, ...]
    beliefs: Mapping[tuple[str, str], Belief]   # facts only
    perceptible: frozenset[str]
    claims: tuple[Belief, ...] = ()             # heard claims, in POV order
    observations: tuple[Belief, ...] = ()       # POV observations, in POV order
    theories: tuple[Belief, ...] = ()           # character inferences/suspicions, in POV order (D-032)

    def believes(self, subject: str, predicate: str) -> bool:
        """True only when the POV holds an objective *fact* about (subject, predicate)."""
        return (subject, predicate) in self.beliefs

    def value_of(self, subject: str, predicate: str) -> Any:
        """The POV's factual value for a (subject, predicate), or None."""
        belief = self.beliefs.get((subject, predicate))
        return belief.value if belief is not None else None

    def claims_about(self, subject: str, predicate: str) -> tuple[Belief, ...]:
        """All claims the POV has heard about this (subject, predicate)."""
        return tuple(b for b in self.claims if b.subject == subject and b.predicate == predicate)

    def observations_about(self, subject: str, predicate: str) -> tuple[Belief, ...]:
        """All observations this POV holds about this (subject, predicate)."""
        return tuple(
            b for b in self.observations if b.subject == subject and b.predicate == predicate
        )


class ContextAssembler:
    """Builds belief stores from the event log (+ optional Scene for situation).

    Owns no authoritative state — it reads the log and the scene. Pass a `Scene`
    to populate the ambient perceptual situation; omit it for a pure
    log-projection belief store.

    ``budgeter`` (Phase 22 D-042) is stored as a collaborator for prompt-assembly
    callers (BeatRunner, CharacterAgent) that need per-role event windows. The
    assembler itself never filters events for budget — belief stores must remain
    complete so canon and differential-knowledge projections are accurate.
    """

    def __init__(
        self,
        log,
        scene: Scene | None = None,
        budgeter=None,
        lore_assembler: LoreAssembler | None = None,
    ) -> None:
        self._log = log
        self._scene = scene
        self._budgeter = budgeter
        self._lore_assembler = lore_assembler

    @property
    def budgeter(self):
        """The ContextBudgeter collaborator, or None if not configured."""
        return self._budgeter

    @property
    def lore_assembler(self) -> LoreAssembler | None:
        """The LoreAssembler collaborator, or None if lorebook is disabled."""
        return self._lore_assembler

    def lore_for(self, store: BeliefStore, pov: str) -> list[LoreEntry]:
        """Return matched lorebook entries for this POV.

        Returns an empty list when no LoreAssembler is configured (opt-in).
        Audience class gate fires inside LoreAssembler.matching() — this method
        never bypasses it.
        """
        if self._lore_assembler is None:
            return []
        return self._lore_assembler.matching(store, pov)

    def lore_block(self, store: BeliefStore, pov: str) -> str:
        """Return a formatted lorebook context block for prompt injection.

        Combines lore_for() + LoreAssembler.lore_context_block() in one step.
        Returns an empty string when no LoreAssembler is configured or when no
        entries match — callers can inject this directly without checking.
        """
        if self._lore_assembler is None:
            return ""
        entries = self._lore_assembler.matching(store, pov)
        if not entries:
            return ""
        return self._lore_assembler.lore_context_block(entries)

    def _fold_epistemic(
        self,
        events: tuple[ProjectedEvent, ...],
    ) -> tuple[dict[tuple[str, str], Belief], list[Belief], list[Belief], list[Belief]]:
        """Split projected events into (facts_dict, claims_list, observations_list, theories_list).

        facts: latest objective commitment per (subject, predicate), in POV order.
        claims: all heard claims in POV order (repeats allowed; multiple speakers
                may claim different values for the same key).
        observations: all POV observations in POV order.
        theories: all character inferences/suspicions in POV order (D-032).
        """
        facts: dict[tuple[str, str], Belief] = {}
        claims: list[Belief] = []
        obs_list: list[Belief] = []
        theories: list[Belief] = []
        for pe in events:
            for c in pe.commitments:
                belief = Belief(
                    subject=c.subject,
                    predicate=c.predicate,
                    value=c.value,
                    source_event_id=pe.id,
                    epistemic_type=c.epistemic_type,
                    asserting_entity=c.asserting_entity,
                    observing_entity=c.observing_entity,
                )
                if c.epistemic_type == "fact":
                    facts[(c.subject, c.predicate)] = belief
                elif c.epistemic_type == "claim":
                    claims.append(belief)
                elif c.epistemic_type == "observation":
                    obs_list.append(belief)
                elif c.epistemic_type == "theory":
                    theories.append(belief)
        return facts, claims, obs_list, theories

    def beliefs_from(self, events: tuple[ProjectedEvent, ...]) -> dict[tuple[str, str], Belief]:
        """Fold a POV's projected events into believed *facts* only.

        Claims and observations are excluded — use `_fold_epistemic` or
        `belief_store` when the full epistemic picture is needed. Only
        content-level events carry commitments (`project_for` withholds them at
        metadata level), so this naturally includes only what the POV truly saw.
        Latest fact per (subject, predicate) wins, in the POV's order.
        """
        facts, _, _, _ = self._fold_epistemic(events)
        return facts

    def belief_store(self, pov: str) -> BeliefStore:
        events = self._log.project_for(pov)
        facts, claims, obs_list, theories = self._fold_epistemic(events)
        perceptible = (
            frozenset(perceptible_entities(self._scene, pov))
            if self._scene is not None
            else frozenset()
        )
        return BeliefStore(
            pov=pov,
            events=events,
            beliefs=facts,
            perceptible=perceptible,
            claims=tuple(claims),
            observations=tuple(obs_list),
            theories=tuple(theories),
        )
