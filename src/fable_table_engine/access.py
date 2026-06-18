"""Access model + commit boundary (CORE §6; roadmap phase 2).

Implements the declaration -> extract -> consistency-check -> bind lifecycle
(CORE §6.1): the moment a declaration stops being fiat and becomes binding law.

Committed facts and the canon ledger are *derived* from the event log, never
separate authoritative stores (D-001, D-009): one source of truth, no desync.
Two materialized stores drifting apart is the omniscience bug returning by the
back door, so we fold the log on read and let callers cache if needed.

MVP defaults exercised here:
  * Facts arrive as structured commitment blocks on a declaration event
    (D-007 option (b)) — there is no prose-extraction pass yet. `commit`
    is the sanctioned entry point for any event that carries commitments,
    the way the dice service is the sanctioned path for a roll.
  * The canon ledger is a view over committed-and-revealed events
    (D-009 option (b)).
  * A committed fact becomes "canon" once revealed to players; for MVP that
    is the `Commitment.revealed` flag. Later, once player roles exist,
    revelation can be derived from disclosure to a player audience at content
    visibility, and this flag retired.

Boundary of the consistency-check (the operational definition of
"contradictory", CORE §6.1 step 3): a candidate contradicts canon when the
canon ledger already holds the same (subject, predicate) with a *different*
value. This is structural, not semantic — it catches "tower is 100ft" vs.
"tower is 10ft", not "gate is barred" vs. "gate is open" across two different
predicates. Semantic contradiction is out of scope until the perception/auditor
phases give it more to work with.

Why the check targets canon (revealed) rather than all committed facts: this is
the deliberate reconciliation of CORE §6.1 and §6.2. Revealed facts are the
immutable boundary above which nothing may be silently changed; contradicting
one without an override is the one forbidden move. Hidden committed facts are
still the fluid future — revising them is the plot-manager's whole job (§7.4),
so a new commitment may freely supersede a hidden one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .events import Commitment, Event, Visibility

# An override is a deliberate, logged revision of committed state, read by the
# auditor as intentional fiat rather than a bug (CORE §3, §6.2; D-008). It is
# the escape hatch that bypasses the canon consistency-check.
OVERRIDE_TYPE = "override"


@dataclass(frozen=True)
class Fact:
    """A committed (subject, predicate) -> value, with provenance.

    Derived from the event log, not authored independently. `revealed` carries
    whether this fact has been disclosed to players (and is therefore canon);
    `via_override` records that it was committed through an override event, so
    downstream (the auditor) can tell fiat from a bug.
    """

    subject: str
    predicate: str
    value: Any
    revealed: bool
    event_id: str
    via_override: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return (self.subject, self.predicate)


@dataclass(frozen=True)
class Conflict:
    """A candidate commitment that contradicts a canon fact."""

    candidate: Commitment
    existing: Fact

    def describe(self) -> str:
        return (
            f"{self.candidate.subject}.{self.candidate.predicate}: "
            f"canon holds {self.existing.value!r} (event {self.existing.event_id}), "
            f"candidate asserts {self.candidate.value!r}"
        )


class CanonConflictError(Exception):
    """Raised when a commitment would silently contradict the canon ledger.

    This is the system refusing the forbidden move (CORE §6.2). The author must
    correct the declaration, or revise deliberately through an override.
    """

    def __init__(self, conflicts: list[Conflict]) -> None:
        self.conflicts = conflicts
        joined = "; ".join(c.describe() for c in conflicts)
        super().__init__(f"commitment contradicts the canon ledger: {joined}")


def committed_facts(events: Iterable[Event]) -> dict[tuple[str, str], Fact]:
    """Fold the event log into the current set of bound facts (CORE §6.1).

    Latest commitment per (subject, predicate) wins, in append order. This is
    safe because `commit` guards every write against the canon boundary, so a
    later differing value for a canon key only exists if it arrived via an
    override (intentional fiat) — never a silent contradiction.
    """
    facts: dict[tuple[str, str], Fact] = {}
    for event in events:
        via_override = event.type == OVERRIDE_TYPE
        for c in event.commitments:
            facts[(c.subject, c.predicate)] = Fact(
                subject=c.subject,
                predicate=c.predicate,
                value=c.value,
                revealed=c.revealed,
                event_id=event.id,
                via_override=via_override,
            )
    return facts


def canon_ledger(events: Iterable[Event]) -> dict[tuple[str, str], Fact]:
    """The revealed subset of committed facts — the immutable boundary (CORE §8).

    A view over the event log (D-009 option (b)), not a materialized store.
    """
    return {key: fact for key, fact in committed_facts(events).items() if fact.revealed}


class CommitPipeline:
    """The sanctioned path for appending events that carry commitments.

    Runs the consistency-check against the canon ledger before binding, so an
    improvised declaration cannot silently contradict what players were already
    told. Owns no authoritative state of its own — it reads and writes the log.
    """

    def __init__(self, log) -> None:
        self._log = log

    # --- derivations over the log ---------------------------------------

    def committed_facts(self) -> dict[tuple[str, str], Fact]:
        return committed_facts(self._log.all())

    def canon_ledger(self) -> dict[tuple[str, str], Fact]:
        return canon_ledger(self._log.all())

    # --- the consistency-check -----------------------------------------

    def check(
        self, commitments: Iterable[Commitment], *, override: bool = False
    ) -> list[Conflict]:
        """Return the canon conflicts a set of candidate commitments would cause.

        Empty list == consistent (safe to bind). An override is intentional fiat
        and conflicts nothing.
        """
        if override:
            return []
        canon = self.canon_ledger()
        conflicts: list[Conflict] = []
        for c in commitments:
            existing = canon.get((c.subject, c.predicate))
            if existing is not None and existing.value != c.value:
                conflicts.append(Conflict(candidate=c, existing=existing))
        return conflicts

    # --- the bind step --------------------------------------------------

    def commit(
        self,
        *,
        author: str,
        channel: str,
        content: str,
        type: str = "declaration",
        audience: tuple[str, ...] | list[str] = (),
        visibility: Visibility = "content",
        commitments: tuple[Commitment, ...] | list[Commitment] = (),
        derived_from: tuple[str, ...] | list[str] = (),
        override: bool = False,
        reason: str | None = None,
    ) -> Event:
        """Consistency-check the commitments, then append the event if clean.

        Raises `CanonConflictError` if any commitment would silently contradict
        canon (the event is not appended — nothing is canonized on conflict).
        Pass `override=True` with a `reason` to deliberately revise canon; the
        event is logged as an `override` so the auditor reads it as fiat.
        """
        commitments = tuple(commitments)

        if override:
            if not reason:
                raise ValueError("an override requires a reason (D-008)")
            type = OVERRIDE_TYPE
            content = f"{content} [override: {reason}]" if content else f"[override: {reason}]"

        conflicts = self.check(commitments, override=override)
        if conflicts:
            raise CanonConflictError(conflicts)

        return self._log.append(
            author=author,
            channel=channel,
            type=type,
            content=content,
            audience=audience,
            visibility=visibility,
            commitments=commitments,
            derived_from=derived_from,
        )
