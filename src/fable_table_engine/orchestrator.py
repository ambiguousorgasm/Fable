"""Orchestrator / Director — turn routing, action queue, and scene cadence (CORE §4.3, §5 step 1; phases 7, 16).

Three components:

  ActionQueue — the blackboard's transient write surface (D-010). Non-authoritative.
    Proposals live here between step 3 (agents propose) and steps 4–9 (adjudicate /
    commit / narrate). A proposal becomes a logged event only once resolved and
    committed; until then it never enters any belief projection — no omniscience
    leak via the back door. Cleared each beat after the orchestrator drains it.

  Orchestrator — routes turns on routing metadata only: presence, spotlight history,
    or initiative order. Never reads event content or private state. If it did, it
    would become an omniscience conduit — the exact failure mode the architecture
    exists to prevent.

    Two modes (D-005):
      SPOTLIGHT — director-picks-next. Cycles through active seats favouring those
        who haven't recently acted. MVP default (D-005). Agent bidding deferred until
        a cost/latency budget exists.
      INITIATIVE — structured round-robin in the order set by `set_initiative`.
        Used for combat. The caller sets the order before the round begins.

  SceneCadence — companion activation gate (D-021 option b). Holds the current
    SceneMode and any always-active designations. Mode transitions are deterministic
    state changes — no model call required. BeatRunner.run_round passes companions
    through select_companions before granting turns; gated companions consume zero
    model calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .character_agent import Proposal


class TurnMode(str, Enum):
    SPOTLIGHT = "spotlight"
    INITIATIVE = "initiative"


@dataclass
class TurnGrant:
    """A routing decision — this seat may act next."""

    actor: str
    mode: TurnMode
    reason: str


class ActionQueue:
    """Transient proposal buffer — the blackboard's write surface (CORE §4.3, D-010).

    Agents write Proposals here in beat-loop step 3. The orchestrator drains it
    before adjudication (step 4). Non-authoritative: proposals are candidates,
    not committed truth.
    """

    def __init__(self) -> None:
        self._pending: list[Proposal] = []

    def enqueue(self, proposal: Proposal) -> None:
        self._pending.append(proposal)

    def drain(self) -> list[Proposal]:
        """Return all pending proposals and clear the queue."""
        out, self._pending = list(self._pending), []
        return out

    def peek(self) -> tuple[Proposal, ...]:
        return tuple(self._pending)

    def __len__(self) -> int:
        return len(self._pending)

    def __bool__(self) -> bool:
        return bool(self._pending)


class SceneMode(str, Enum):
    """Narrative scene modes that control companion activation per round (D-021)."""

    QUIET = "quiet"           # exploration, stealth — at most 1 companion
    DIALOGUE = "dialogue"     # conversation, negotiation — at most 2 companions
    TACTICAL = "tactical"     # planning, positioning — all companions
    COMBAT = "combat"         # full engagement — all companions (use INITIATIVE)
    DOWNTIME = "downtime"     # recovery, crafting — at most 1 companion
    HIGH_DRAMA = "high_drama" # revelation, climax — all companions


_ALL_SEATS = 2 ** 20  # sentinel meaning "no companion limit"

_COMPANION_LIMITS: dict[SceneMode, int] = {
    SceneMode.QUIET:      1,
    SceneMode.DIALOGUE:   2,
    SceneMode.TACTICAL:   _ALL_SEATS,
    SceneMode.COMBAT:     _ALL_SEATS,
    SceneMode.DOWNTIME:   1,
    SceneMode.HIGH_DRAMA: _ALL_SEATS,
}


class SceneCadence:
    """Deterministic companion activation gate for a scene (D-021 option b).

    Holds the current scene mode and any always-active companion designations.
    Mode changes are pure state transitions — no model call required.

    `select_companions` returns which AI companions may act this round;
    companions not returned must receive no model call that round.

    Invariant: reads routing metadata only (entity IDs, mode string). Never
    reads event content or private fictional state.
    """

    def __init__(self, mode: SceneMode = SceneMode.TACTICAL) -> None:
        self._mode = mode
        self._always_active: set[str] = set()

    @property
    def mode(self) -> SceneMode:
        return self._mode

    def set_mode(self, mode: SceneMode) -> None:
        """Transition to a different scene mode. Deterministic; no model call."""
        self._mode = mode

    def set_always_active(self, entity_id: str) -> None:
        """Mark a companion as always active regardless of scene mode."""
        self._always_active.add(entity_id)

    def clear_always_active(self, entity_id: str) -> None:
        """Remove an always-active designation."""
        self._always_active.discard(entity_id)

    @property
    def always_active(self) -> frozenset[str]:
        return frozenset(self._always_active)

    @property
    def companion_limit(self) -> int:
        """Maximum AI companions activated per round (always-active companions
        are included first and count toward this limit)."""
        return _COMPANION_LIMITS[self._mode]

    @property
    def is_full_activation(self) -> bool:
        """True when the scene mode activates all present companions."""
        return _COMPANION_LIMITS[self._mode] >= _ALL_SEATS

    def select_companions(
        self,
        candidates: list[str],
        *,
        spotlight_order: list[str] | None = None,
    ) -> list[str]:
        """Return the subset of candidates invited to act this round.

        Always-active companions are always included first.
        Remaining slots (up to companion_limit − len(always_active present))
        fill from conditional candidates in spotlight_order (least-recently-
        acted first) when supplied, or in candidates order otherwise.

        A companion absent from the returned list must receive no model call.
        """
        limit = self.companion_limit
        always = [c for c in candidates if c in self._always_active]
        conditional = [c for c in candidates if c not in self._always_active]

        if spotlight_order is not None:
            order_idx = {s: i for i, s in enumerate(spotlight_order)}
            conditional = sorted(
                conditional,
                key=lambda c: order_idx.get(c, len(spotlight_order)),
            )

        remaining_slots = max(0, limit - len(always))
        return always + conditional[:remaining_slots]


class Orchestrator:
    """Routes turns on routing metadata alone — never on event content (CORE §4.3, D-005).

    `seats` is the full roster of entity IDs at this table. Pass a subset as
    `present` to `grant_turn` to restrict routing to who is currently in scene.

    SPOTLIGHT (default): director-picks-next. Picks the present seat least
      recently granted a turn. Deterministic; no model call needed.

    INITIATIVE: structured order for combat. Call `set_initiative(order)` before
      the round; the orchestrator cycles through the list, skipping absent seats.
    """

    def __init__(
        self,
        seats: list[str],
        mode: TurnMode = TurnMode.SPOTLIGHT,
    ) -> None:
        if not seats:
            raise ValueError("orchestrator requires at least one seat")
        self._seats = list(seats)
        self._mode = mode
        self._initiative_order: list[str] = []
        self._initiative_index: int = 0
        self._history: list[str] = []

    @property
    def mode(self) -> TurnMode:
        return self._mode

    @property
    def seats(self) -> tuple[str, ...]:
        return tuple(self._seats)

    def set_initiative(self, order: list[str]) -> None:
        """Switch to INITIATIVE mode with `order` as the rotation."""
        if not order:
            raise ValueError("initiative order cannot be empty")
        self._initiative_order = list(order)
        self._initiative_index = 0
        self._mode = TurnMode.INITIATIVE

    def set_spotlight_mode(self) -> None:
        """Switch (back) to SPOTLIGHT mode."""
        self._mode = TurnMode.SPOTLIGHT

    def grant_turn(self, present: list[str] | None = None) -> TurnGrant:
        """Return who acts next among the present seats.

        `present` defaults to the full roster when omitted. Pass a subset to
        restrict to seats currently in scene.
        """
        active = list(present) if present is not None else list(self._seats)
        if not active:
            raise ValueError("grant_turn: no active seats")
        return (
            self._next_initiative(active)
            if self._mode == TurnMode.INITIATIVE
            else self._next_spotlight(active)
        )

    def record_acted(self, actor: str) -> None:
        """Record that `actor` completed a turn (updates spotlight history)."""
        self._history.append(actor)
        cap = max(len(self._seats) * 2, 8)
        if len(self._history) > cap:
            self._history = self._history[-cap:]

    def sorted_by_spotlight(self, candidates: list[str]) -> list[str]:
        """Sort candidates by least-recently-acted first.

        Candidates absent from history sort before all others (never acted =
        highest priority). Among those with history, earlier history position
        → higher priority. Used by SceneCadence to fill limited companion
        slots with the longest-idle companions.
        """
        def last_acted_index(c: str) -> int:
            for i in range(len(self._history) - 1, -1, -1):
                if self._history[i] == c:
                    return i
            return -1

        return sorted(candidates, key=last_acted_index)

    # ------------------------------------------------------------------ #

    def _next_spotlight(self, active: list[str]) -> TurnGrant:
        window = set(self._history[-len(active):])
        candidates = [s for s in active if s not in window] or active
        return TurnGrant(actor=candidates[0], mode=TurnMode.SPOTLIGHT,
                         reason="least-recently-acted")

    def _next_initiative(self, active: list[str]) -> TurnGrant:
        if not self._initiative_order:
            raise ValueError("initiative mode but no order set — call set_initiative first")
        for _ in range(len(self._initiative_order)):
            idx = self._initiative_index % len(self._initiative_order)
            self._initiative_index += 1
            candidate = self._initiative_order[idx]
            if candidate in active:
                return TurnGrant(actor=candidate, mode=TurnMode.INITIATIVE,
                                 reason=f"initiative position {idx + 1}")
        raise ValueError(
            f"no initiative-order seat is present — order={self._initiative_order!r}, "
            f"present={active!r}"
        )
