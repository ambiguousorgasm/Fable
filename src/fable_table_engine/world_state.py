"""World-state skeleton — authoritative present state (CORE §4.1, §8).

The structured, deterministic representation of everything with a correct
answer. Phase 1 is a minimal container; the rules engine and the
commit/causation pipeline (phase 2+) drive its evolution.

Position is fiction-positional (D-002): a fictional fact anchored to a
scene/zone and described in prose, never a coordinate. See
`schemas/world_state.schema.json`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    entities: dict[str, Entity] = field(default_factory=dict)
    scenes: dict[str, Any] = field(default_factory=dict)
    clocks: dict[str, Any] = field(default_factory=dict)
    fronts: dict[str, Any] = field(default_factory=dict)

    def add_entity(self, entity: Entity) -> None:
        if entity.id in self.entities:
            raise ValueError(f"entity {entity.id!r} already exists")
        self.entities[entity.id] = entity

    def get_entity(self, entity_id: str) -> Entity:
        return self.entities[entity_id]
