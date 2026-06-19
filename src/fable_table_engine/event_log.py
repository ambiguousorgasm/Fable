"""The append-only event log — single source of historical truth (CORE §3, §8).

`append` is the one chokepoint through which all events enter the log. It:
  * assigns the monotonic `sequence`, a unique `id`, and a UTC `timestamp`
    (never caller-supplied, so ordering and identity cannot be forged);
  * refuses mechanical-outcome event types unless they arrive with the
    mechanical capability held only by the dice service and rules engine —
    this is the determinism boundary made structural (CORE §1.3 principle 1);
  * stores a `frozen` Event, so committed history cannot be mutated.

Belief stores are read-time projections over this log (CORE §6.3, D-001), seeded
here by `project_for`.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from .events import (
    CORRECTION_TYPES,
    MECHANICAL_TYPES,
    ROLL_VISIBILITY_LEVELS,
    Commitment,
    DeterminismBoundaryError,
    Event,
    ProjectedEvent,
    Visibility,
)

# Capability object proving a write came through the rules/dice path. It is
# module-private; the dice service and rules engine import it. A model-facing
# caller has no legitimate way to obtain it, so it cannot author a mechanical
# outcome directly.
_MECHANICAL_CAPABILITY = object()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventLog:
    """In-memory append-only log.

    Reads return copies/tuples so callers cannot reach in and mutate history.
    A persistent backend (SQLite) is a later increment that slots in behind the
    same `append`/read seam; nothing above this layer should care which it is.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._by_id: dict[str, Event] = {}

    def append(
        self,
        *,
        author: str,
        channel: str,
        type: str,
        content: str,
        audience: tuple[str, ...] | list[str] = (),
        visibility: Visibility = "content",
        commitments: tuple[Commitment, ...] | list[Commitment] = (),
        derived_from: tuple[str, ...] | list[str] = (),
        roll_visibility: str | None = None,
        authorized_by: tuple[str, ...] | list[str] = (),
        _capability: object | None = None,
    ) -> Event:
        """Append a new event and return it.

        Mechanical-outcome types (``MECHANICAL_TYPES``) are rejected unless
        `_capability` is the mechanical capability. Everything else — narration,
        declarations, dialogue, system notes — is free to append.
        """
        if type in MECHANICAL_TYPES and _capability is not _MECHANICAL_CAPABILITY:
            raise DeterminismBoundaryError(
                f"event type {type!r} is a mechanical outcome and may only be written "
                f"through the dice service or rules engine, not authored directly"
            )

        event = Event(
            sequence=len(self._events),
            id=uuid.uuid4().hex,
            timestamp=_utc_now_iso(),
            author=author,
            channel=channel,
            audience=tuple(audience),
            visibility=visibility,
            type=type,
            content=content,
            commitments=tuple(commitments),
            derived_from=tuple(derived_from),
            roll_visibility=roll_visibility,
            authorized_by=tuple(authorized_by),
        )
        self._events.append(event)
        self._by_id[event.id] = event
        return event

    @contextmanager
    def transaction(self):
        """No-op transaction for the in-memory log.

        The SQLiteEventLog override turns this into a real atomic SQLite
        commit with in-memory rollback on exception. Callers (BeatRunner)
        always use ``with self._log.transaction():`` so the same beat code
        works with both backends.
        """
        yield

    # --- reads -----------------------------------------------------------

    def all(self) -> tuple[Event, ...]:
        """Every event in append order. A tuple, so the caller cannot mutate it."""
        return tuple(self._events)

    def get(self, event_id: str) -> Event:
        return self._by_id[event_id]

    def get_by_sequence(self, sequence: int) -> Event:
        return self._events[sequence]

    def __len__(self) -> int:
        return len(self._events)

    def project_for(self, entity: str) -> tuple[ProjectedEvent, ...]:
        """The event log as `entity` perceives it (CORE §6.3, §6.4).

        Events the entity is not in the audience of are excluded entirely; the
        rest are rendered at the entity's visibility level (content vs metadata).
        This is the read-time projection that a belief store is built on.

        The projection's `sequence` is a *per-POV contiguous index* (0, 1, 2, …
        in this entity's own view), not the log's global sequence. Exposing the
        global sequence would let a POV infer that events it isn't party to
        occurred — and how many — from the gaps; the contiguous index preserves
        ordering while leaking nothing about hidden activity (D-013).
        """
        # Build superseded map: event_id → corrector_event_id (D-031).
        # A correction or retcon event's derived_from entries are superseded by it.
        superseded: dict[str, str] = {}
        for ev in self._events:
            if ev.type in CORRECTION_TYPES:
                for ref_id in ev.derived_from:
                    superseded[ref_id] = ev.id

        projected: list[ProjectedEvent] = []
        for event in self._events:
            level = event.visibility_for(entity)
            if level is None:
                continue
            is_content = level == "content"
            projected.append(
                ProjectedEvent(
                    sequence=len(projected),
                    id=event.id,
                    timestamp=event.timestamp,
                    author=event.author,
                    channel=event.channel,
                    type=event.type,
                    visibility=level,
                    content=event.content if is_content else None,
                    commitments=event.commitments if is_content else (),
                    roll_visibility=event.roll_visibility,
                    superseded_by=superseded.get(event.id),
                )
            )
        return tuple(projected)
