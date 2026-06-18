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
from typing import Any, Mapping

from .events import ProjectedEvent
from .perception import Scene, perceptible_entities


@dataclass(frozen=True)
class Belief:
    """A fact a POV holds, with the projected event it learned it from.

    Derived from the POV's projection, so it only ever reflects what that POV
    was entitled to see. `source_event_id` is the projected event's id (stable
    cross-POV identity), not a position.
    """

    subject: str
    predicate: str
    value: Any
    source_event_id: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.subject, self.predicate)


@dataclass(frozen=True)
class BeliefStore:
    """One POV's assembled context — its entire epistemic world.

    `events` is the POV's projection; `beliefs` are the facts folded from it;
    `perceptible` is who the POV can currently sense (empty when no Scene was
    supplied). Frozen: a belief store is a derived snapshot, never authoritative.
    """

    pov: str
    events: tuple[ProjectedEvent, ...]
    beliefs: Mapping[tuple[str, str], Belief]
    perceptible: frozenset[str]

    def believes(self, subject: str, predicate: str) -> bool:
        return (subject, predicate) in self.beliefs

    def value_of(self, subject: str, predicate: str) -> Any:
        """The POV's believed value for a fact, or None if it holds no belief."""
        belief = self.beliefs.get((subject, predicate))
        return belief.value if belief is not None else None


class ContextAssembler:
    """Builds belief stores from the event log (+ optional Scene for situation).

    Owns no authoritative state — it reads the log and the scene. Pass a `Scene`
    to populate the ambient perceptual situation; omit it for a pure
    log-projection belief store.
    """

    def __init__(self, log, scene: Scene | None = None) -> None:
        self._log = log
        self._scene = scene

    def beliefs_from(self, events: tuple[ProjectedEvent, ...]) -> dict[tuple[str, str], Belief]:
        """Fold a POV's projected events into believed facts.

        Only content-level events carry commitments (metadata withholds them in
        `project_for`), so this naturally includes only what the POV truly saw.
        Latest seen value per (subject, predicate) wins, in the POV's order.
        """
        beliefs: dict[tuple[str, str], Belief] = {}
        for pe in events:
            for c in pe.commitments:
                beliefs[(c.subject, c.predicate)] = Belief(
                    subject=c.subject,
                    predicate=c.predicate,
                    value=c.value,
                    source_event_id=pe.id,
                )
        return beliefs

    def belief_store(self, pov: str) -> BeliefStore:
        events = self._log.project_for(pov)
        beliefs = self.beliefs_from(events)
        perceptible = (
            frozenset(perceptible_entities(self._scene, pov))
            if self._scene is not None
            else frozenset()
        )
        return BeliefStore(pov=pov, events=events, beliefs=beliefs, perceptible=perceptible)
