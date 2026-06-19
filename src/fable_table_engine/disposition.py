"""Disposition graph — directed, asymmetric, multi-axis relationship state (CORE §7.5, Phase 19).

The disposition graph is event-derived ground truth: every delta is linked to a
causal event ID so attitudes are auditable and explainable, never free-floating.
Disposition couples to mechanics only through FABLE's native Edge/Bond structure
(D-004) — no passive modifier, no separate currency.

The DispositionEngine is the sole writer of the graph. Other components read the
graph for context assembly; nothing writes disposition state directly.

D-011 resolution (deterministic half): the engine's rule table fires on
mechanically legible commitment predicates. Model-proposed deltas for ambiguous
social cues are Phase 20; the engine is the commit point either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .events import Event


class DispositionAxis(str, Enum):
    """The four primary relationship axes (CORE §7.5)."""

    TRUST = "trust"
    AFFECTION = "affection"
    RESPECT = "respect"
    OBLIGATION = "obligation"


@dataclass(frozen=True)
class DispositionDelta:
    """A single change to one axis of one directed relationship.

    `causal_event_id` is required — every delta must trace back to a logged
    event so the state is auditable (architecture invariant: the event log is
    the single source of historical truth).
    """

    from_id: str
    to_id: str
    axis: DispositionAxis
    delta: int
    causal_event_id: str
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.from_id or not self.to_id:
            raise ValueError("DispositionDelta requires non-empty from_id and to_id")
        if not self.causal_event_id:
            raise ValueError("DispositionDelta requires a causal_event_id")
        if self.delta == 0:
            raise ValueError("DispositionDelta delta must be non-zero")

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "axis": self.axis.value,
            "delta": self.delta,
            "causal_event_id": self.causal_event_id,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DispositionDelta:
        return cls(
            from_id=d["from_id"],
            to_id=d["to_id"],
            axis=DispositionAxis(d["axis"]),
            delta=d["delta"],
            causal_event_id=d["causal_event_id"],
            reason=d.get("reason", ""),
        )


class DispositionGraph:
    """Directed, asymmetric, multi-axis relationship graph (CORE §7.5).

    Edges are `(from_id, to_id)` pairs; each edge stores per-axis integer values
    (positive or negative; zero is neutral / absent). Every write goes through
    `apply_delta` so the history remains consistent with the edge totals.

    Relationship state is read by context assembly for agent prompts; it is never
    visible in player belief stores and never referenced by `project_for` or
    `CommitPipeline`.
    """

    def __init__(self) -> None:
        self._edges: dict[tuple[str, str], dict[DispositionAxis, int]] = {}
        self._history: list[DispositionDelta] = []
        self._by_event: dict[str, list[DispositionDelta]] = {}

    # ------------------------------------------------------------------ writes #

    def apply_delta(self, delta: DispositionDelta) -> None:
        """Apply `delta` and record it in history.

        The only write path. `delta.causal_event_id` is enforced by
        `DispositionDelta.__post_init__` — there is no way to call this without
        a causal event reference.
        """
        key = (delta.from_id, delta.to_id)
        axes = self._edges.setdefault(key, {})
        axes[delta.axis] = axes.get(delta.axis, 0) + delta.delta
        self._history.append(delta)
        self._by_event.setdefault(delta.causal_event_id, []).append(delta)

    # ------------------------------------------------------------------ reads  #

    def edge(self, from_id: str, to_id: str) -> dict[DispositionAxis, int]:
        """Current axis values for `from_id → to_id` (empty dict if no relationship)."""
        return dict(self._edges.get((from_id, to_id), {}))

    def deltas_for_event(self, event_id: str) -> list[DispositionDelta]:
        """All deltas caused by the given event, in application order."""
        return list(self._by_event.get(event_id, []))

    def all_deltas(self) -> list[DispositionDelta]:
        """Full delta history in application order."""
        return list(self._history)

    def context_block(self, from_id: str) -> str:
        """Summary of non-zero relationships originating from `from_id`, for prompts.

        Returns an empty string when there are no non-zero relationships.
        """
        lines: list[str] = []
        for (fid, tid), axes in self._edges.items():
            if fid != from_id:
                continue
            nonzero = {ax.value: v for ax, v in axes.items() if v != 0}
            if not nonzero:
                continue
            parts = ", ".join(f"{ax}={v:+d}" for ax, v in sorted(nonzero.items()))
            lines.append(f"{tid}: {parts}")
        if not lines:
            return ""
        return "Relationships:\n" + "\n".join(sorted(lines))

    # ------------------------------------------------------------------ serde  #

    def to_dict(self) -> dict[str, Any]:
        return {
            "edges": [
                {
                    "from_id": fid,
                    "to_id": tid,
                    "axes": {ax.value: v for ax, v in axes.items()},
                }
                for (fid, tid), axes in self._edges.items()
            ],
            "history": [d.to_dict() for d in self._history],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DispositionGraph:
        g = cls()
        for e in d.get("edges", []):
            key = (e["from_id"], e["to_id"])
            g._edges[key] = {DispositionAxis(ax): v for ax, v in e["axes"].items()}
        for h in d.get("history", []):
            delta = DispositionDelta.from_dict(h)
            g._history.append(delta)
            g._by_event.setdefault(delta.causal_event_id, []).append(delta)
        return g


# ----------------------------------------------------------------------------- #
# DispositionEngine                                                               #
# ----------------------------------------------------------------------------- #

_RECOGNIZED_PREDICATES = frozenset({
    "disposition_delta",
    "stress_taken_for",
    "triumph_for",
})


class DispositionEngine:
    """Sole authoritative writer of the DispositionGraph (D-011 deterministic half).

    Processes logged events through a deterministic rule table. Model-proposed
    deltas for ambiguous social cues are Phase 20; this engine is always the
    commit point regardless of how a delta is sourced.

    Deterministic recognition rules:
    - ``"disposition_delta"`` commitment — explicit signal with value dict
      ``{from_id, to_id, axis, delta, reason?}``. Used by the GM or beat runner
      for unambiguous relational moments.
    - ``"stress_taken_for"`` commitment — value is an entity ID; actor took Stress
      to protect that entity → +1 trust from that entity toward the actor.
    - ``"triumph_for"`` commitment — value is an entity ID; actor achieved Triumph
      on behalf of / witnessed by that entity → +1 respect from that entity toward
      the actor.
    """

    def __init__(self, graph: DispositionGraph) -> None:
        self._graph = graph

    @property
    def graph(self) -> DispositionGraph:
        return self._graph

    def process_event(self, event: Event) -> list[DispositionDelta]:
        """Recognize mechanically legible triggers and apply resulting deltas.

        Returns the deltas applied (empty if no triggers fire).
        """
        deltas = self._recognize(event)
        for d in deltas:
            self._graph.apply_delta(d)
        return deltas

    def _recognize(self, event: Event) -> list[DispositionDelta]:
        deltas: list[DispositionDelta] = []
        for commitment in event.commitments:
            pred = commitment.predicate
            if pred not in _RECOGNIZED_PREDICATES:
                continue
            value = commitment.value

            if pred == "disposition_delta":
                if not isinstance(value, dict):
                    continue
                try:
                    deltas.append(
                        DispositionDelta(
                            from_id=str(value["from_id"]),
                            to_id=str(value["to_id"]),
                            axis=DispositionAxis(value["axis"]),
                            delta=int(value["delta"]),
                            causal_event_id=event.id,
                            reason=str(value.get("reason", "")),
                        )
                    )
                except (KeyError, ValueError):
                    pass

            elif pred == "stress_taken_for":
                protected = value if isinstance(value, str) else None
                if not protected or not event.author:
                    continue
                deltas.append(
                    DispositionDelta(
                        from_id=protected,
                        to_id=event.author,
                        axis=DispositionAxis.TRUST,
                        delta=1,
                        causal_event_id=event.id,
                        reason="stress taken on their behalf",
                    )
                )

            elif pred == "triumph_for":
                witness = value if isinstance(value, str) else None
                if not witness or not event.author:
                    continue
                deltas.append(
                    DispositionDelta(
                        from_id=witness,
                        to_id=event.author,
                        axis=DispositionAxis.RESPECT,
                        delta=1,
                        causal_event_id=event.id,
                        reason="triumph witnessed",
                    )
                )

        return deltas
