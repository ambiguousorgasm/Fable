"""Event model — the atomic unit of everything that happens.

The event log is the single source of historical truth (CORE §3, §8). Events
are append-only and immutable: they are `frozen` dataclasses, and the log
(`event_log.py`) is the only thing that assigns `sequence`, `id`, and
`timestamp`, so those are never caller-supplied.

Field set tracks `schemas/event.schema.json` and CORE §3/§8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Union

# Channels an event may travel on (CORE §3). Channel shapes the default
# audience but does not solely determine it.
CHANNELS = frozenset({"public", "whisper", "ooc", "dice", "system"})

# Epistemic types for commitments (D-024). Only "fact" enters the canon ledger;
# "claim" and "observation" live in audience-scoped event history and POV
# projections. "expired" is a tombstone that removes a prior fact from
# committed_facts (Phase 12 typed effect executor). "Belief" and "theory" are
# derived annotations (deferred).
EPISTEMIC_TYPES = frozenset({"fact", "claim", "observation", "expired"})

# Visibility levels: whether an audience member receives the event's content
# or only the metadata that it happened (CORE §3).
VISIBILITY_LEVELS = frozenset({"content", "metadata"})

# Event types that carry a *mechanical outcome*. These live below the
# determinism boundary (CORE §1.3 principle 1) and may only be written through
# the dice service or rules engine — never authored directly by a model-facing
# caller. The event log enforces this (see event_log.EventLog.append).
MECHANICAL_TYPES = frozenset({"dice_roll", "resolution"})

# A visibility is either one level for the whole audience, or a per-member map.
Visibility = Union[str, Mapping[str, str]]


class DeterminismBoundaryError(Exception):
    """Raised when a mechanical outcome is appended outside the rules/dice path."""


@dataclass(frozen=True)
class Commitment:
    """A structured fact lifted from a declaration (CORE §3, §6.1).

    Committing is the moment a declaration stops being fiat and becomes law.
    Phase 1 only carries the shape; the commit/consistency pipeline is phase 2.
    """

    subject: str
    predicate: str
    value: Any
    confidence: float | None = None
    revealed: bool = False
    epistemic_type: str = "fact"
    # Provenance (Phase 11 / D-024): who asserted or observed this.
    # For claims the asserting_entity is the NPC or player who made the statement;
    # for observations the observing_entity is the POV that perceived it.
    # Both default to None so existing call sites are unaffected.
    asserting_entity: str | None = None
    observing_entity: str | None = None

    def __post_init__(self) -> None:
        if not self.subject or not self.predicate:
            raise ValueError("commitment requires non-empty subject and predicate")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("commitment confidence must be in [0, 1]")
        if self.epistemic_type not in EPISTEMIC_TYPES:
            raise ValueError(
                f"epistemic_type must be one of {sorted(EPISTEMIC_TYPES)}, "
                f"got {self.epistemic_type!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "subject": self.subject,
            "predicate": self.predicate,
            "value": self.value,
            "revealed": self.revealed,
            "epistemic_type": self.epistemic_type,
        }
        if self.confidence is not None:
            d["confidence"] = self.confidence
        if self.asserting_entity is not None:
            d["asserting_entity"] = self.asserting_entity
        if self.observing_entity is not None:
            d["observing_entity"] = self.observing_entity
        return d


@dataclass(frozen=True)
class Event:
    """An append-only, immutable record of one thing that happened.

    `sequence`, `id`, and `timestamp` are assigned by the event log, not the
    caller. Audience membership plus visibility is the complete access-control
    answer to "whose context changes" (CORE §6).
    """

    sequence: int
    id: str
    timestamp: str
    author: str
    channel: str
    audience: tuple[str, ...]
    visibility: Visibility
    type: str
    content: str
    commitments: tuple[Commitment, ...] = ()
    derived_from: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be >= 0")
        if not self.author:
            raise ValueError("event requires an author")
        if self.channel not in CHANNELS:
            raise ValueError(f"unknown channel {self.channel!r}; expected one of {sorted(CHANNELS)}")
        if not self.type:
            raise ValueError("event requires a type")
        if len(set(self.audience)) != len(self.audience):
            raise ValueError("audience must not contain duplicates")
        if len(set(self.derived_from)) != len(self.derived_from):
            raise ValueError("derived_from must not contain duplicates")
        self._validate_visibility()

    def _validate_visibility(self) -> None:
        vis = self.visibility
        if isinstance(vis, str):
            if vis not in VISIBILITY_LEVELS:
                raise ValueError(f"visibility must be one of {sorted(VISIBILITY_LEVELS)}")
            return
        if isinstance(vis, Mapping):
            for member, level in vis.items():
                if member not in self.audience:
                    raise ValueError(f"visibility names {member!r}, who is not in the audience")
                if level not in VISIBILITY_LEVELS:
                    raise ValueError(f"visibility level for {member!r} must be content/metadata")
            return
        raise TypeError("visibility must be a level string or a per-member mapping")

    def visibility_for(self, entity: str) -> str | None:
        """The level `entity` perceives this event at, or None if excluded.

        Not in the audience -> None (the entity does not even know it happened:
        the "—" column of the CORE §6.4 access matrix). In the audience ->
        "content" or "metadata". A per-member map defaults missing members to
        "metadata" (least disclosure).
        """
        if entity not in self.audience:
            return None
        if isinstance(self.visibility, str):
            return self.visibility
        return self.visibility.get(entity, "metadata")

    def to_dict(self) -> dict[str, Any]:
        vis = self.visibility if isinstance(self.visibility, str) else dict(self.visibility)
        return {
            "id": self.id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "author": self.author,
            "channel": self.channel,
            "audience": list(self.audience),
            "visibility": vis,
            "type": self.type,
            "content": self.content,
            "commitments": [c.to_dict() for c in self.commitments],
            "derived_from": list(self.derived_from),
        }


@dataclass(frozen=True)
class ProjectedEvent:
    """What a single entity perceives of an event (CORE §6.3 belief-store seed).

    At `content` level the entity sees everything; at `metadata` level it knows
    the event happened, by whom, and on what channel, but `content` is None and
    `commitments` are withheld.

    `sequence` is the event's position in *this entity's* projection (contiguous
    0, 1, 2, …), not the log's global sequence — so a POV cannot infer hidden
    activity from gaps (D-013). Use `id` for cross-POV identity.
    """

    sequence: int
    id: str
    timestamp: str
    author: str
    channel: str
    type: str
    visibility: str
    content: str | None
    commitments: tuple[Commitment, ...] = field(default=())
