"""World-state skeleton — authoritative present state (CORE §4.1, §8).

The structured, deterministic representation of everything with a correct
answer. Phase 1 is a minimal container; the rules engine and the
commit/causation pipeline (phase 2+) drive its evolution.

Position is fiction-positional (D-002): a fictional fact anchored to a
scene/zone and described in prose, never a coordinate. See
`schemas/world_state.schema.json`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

# Elapsed-category values for the time anchor (D-030). Maps to D-026 clock
# trigger_types so a scene_transition with elapsed_category="breather" advances
# only clocks that trigger on "breather", etc.
ELAPSED_CATEGORIES = frozenset({"beat", "exchange", "scene", "travel", "breather", "downtime"})


@dataclass
class Entity:
    id: str
    kind: str
    name: str
    position: dict[str, Any] | None = None
    conditions: tuple[str, ...] = ()
    resources: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorldState:
    """Durable present state, including the fiction-positional zone graph (D-002).

    The zone graph is *topology*: which fictional locations exist (`zones`) and
    which are linked (`connections`, undirected). Presence is an entity's
    `position` (`{"zone": <id>}`) — coarse position. Intra-zone proximity is the
    fine grain, carried as relational closeness Truths (`closeness`) rather than
    measured distance. None of this is metric (D-002): code owns which position
    facts exist and whether they're consistent, not a coordinate system.

    What it deliberately does *not* hold: the volatile sensory conditions
    (lighting now, which doorways are open) that gate perception — those live in
    the Scene (`perception.py`), the registered Scene/perception state.
    """

    entities: dict[str, Entity] = field(default_factory=dict)
    scenes: dict[str, Any] = field(default_factory=dict)
    clocks: dict[str, Any] = field(default_factory=dict)
    fronts: dict[str, Any] = field(default_factory=dict)
    zones: set[str] = field(default_factory=set)
    connections: set[frozenset[str]] = field(default_factory=set)
    closeness: set[frozenset[str]] = field(default_factory=set)
    maintained_truths: dict[str, Any] = field(default_factory=dict)
    # Time anchor fields (D-030). Backend-owned; client reads these from the
    # event stream and never declares scene transitions itself.
    scene_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    beat_index: int = 0
    scene_phase: str = "quiet"          # current SceneMode value
    prose_time_label: str | None = None # aesthetic only; no mechanical weight
    elapsed_category: str = "beat"      # most recent elapsed-time unit

    def add_entity(self, entity: Entity) -> None:
        if entity.id in self.entities:
            raise ValueError(f"entity {entity.id!r} already exists")
        self.entities[entity.id] = entity

    def update_entity(self, entity: Entity) -> None:
        """Replace an existing entity entry (e.g. after resource mutation)."""
        if entity.id not in self.entities:
            raise ValueError(f"entity {entity.id!r} not found")
        self.entities[entity.id] = entity

    def get_entity(self, entity_id: str) -> Entity:
        return self.entities[entity_id]

    # --- zone topology ---------------------------------------------------

    def add_zone(self, zone: str) -> None:
        self.zones.add(zone)

    def connect(self, a: str, b: str) -> None:
        """Link two zones (undirected). Both must already exist."""
        for z in (a, b):
            if z not in self.zones:
                raise ValueError(f"unknown zone {z!r}")
        if a == b:
            raise ValueError("a zone cannot connect to itself")
        self.connections.add(frozenset({a, b}))

    def adjacent(self, zone: str) -> set[str]:
        """Zones directly linked to `zone`."""
        return {z for c in self.connections if zone in c for z in c if z != zone}

    def are_connected(self, a: str, b: str) -> bool:
        return frozenset({a, b}) in self.connections

    # --- presence (coarse position) -------------------------------------

    def place(self, entity_id: str, zone: str) -> None:
        if zone not in self.zones:
            raise ValueError(f"unknown zone {zone!r}")
        self.get_entity(entity_id).position = {"zone": zone}

    def zone_of(self, entity_id: str) -> str | None:
        entity = self.entities.get(entity_id)
        if entity is None:
            return None
        pos = entity.position
        return pos.get("zone") if pos else None

    def entities_in(self, zone: str) -> set[str]:
        return {e.id for e in self.entities.values() if (e.position or {}).get("zone") == zone}

    # --- intra-zone proximity (fine position; relational Truth) ----------

    def set_close(self, a: str, b: str) -> None:
        """Record that two entities are within close range (e.g. whisper range)."""
        if a == b:
            raise ValueError("an entity cannot be close to itself")
        self.closeness.add(frozenset({a, b}))

    def are_close(self, a: str, b: str) -> bool:
        return frozenset({a, b}) in self.closeness

    def close_to(self, entity_id: str) -> set[str]:
        return {e for c in self.closeness if entity_id in c for e in c if e != entity_id}

    # --- clocks and fronts -----------------------------------------------

    def set_clock(self, name: str, data: dict) -> None:
        """Create or replace a clock entry."""
        self.clocks[name] = data

    def set_front(self, name: str, data: dict) -> None:
        """Create or replace a front entry."""
        self.fronts[name] = data

    def set_maintained_truth(self, key: str, data: dict) -> None:
        """Register or replace a maintained truth (key = 'subject::predicate')."""
        self.maintained_truths[key] = data

    def expire_maintained_truth(self, key: str) -> None:
        """Remove a maintained truth entry. No-op if already absent."""
        self.maintained_truths.pop(key, None)

    # --- time anchor (D-030) ------------------------------------------------

    def advance_beat(self, elapsed_category: str = "beat") -> None:
        """Increment beat_index and record the elapsed-time category."""
        if elapsed_category not in ELAPSED_CATEGORIES:
            raise ValueError(
                f"elapsed_category must be one of {sorted(ELAPSED_CATEGORIES)}, "
                f"got {elapsed_category!r}"
            )
        self.beat_index += 1
        self.elapsed_category = elapsed_category

    def begin_scene_transition(
        self,
        scene_phase: str,
        elapsed_category: str = "scene",
        prose_time_label: str | None = None,
    ) -> str:
        """Open a new scene: fresh scene_id, beat_index reset, phase updated.

        Returns the new scene_id so callers can include it in the structural
        event content without a second read.
        """
        if elapsed_category not in ELAPSED_CATEGORIES:
            raise ValueError(
                f"elapsed_category must be one of {sorted(ELAPSED_CATEGORIES)}, "
                f"got {elapsed_category!r}"
            )
        self.scene_id = str(uuid.uuid4())
        self.beat_index = 0
        self.scene_phase = scene_phase
        self.elapsed_category = elapsed_category
        self.prose_time_label = prose_time_label
        return self.scene_id
