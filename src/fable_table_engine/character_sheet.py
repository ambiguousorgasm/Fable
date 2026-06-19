"""Character sheet — FABLE character anatomy (FABLE_Engine_Schema_v6.md §4, §13–14).

Phase 5 minimal: concept, skills, and Edge. The remaining surfaces (Traits,
Bonds, Drive, Question, Gear, Stress, Scars) are present as fields but not
mechanically enforced yet — they are filled out as the rules engine matures.

Phase 20: BondRef links a character's narrative Bonds to canonical Commitment
IDs so compels, Edge Lean, and Bond-change advancement can target a specific
Held Truth rather than a free string.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BondRef:
    """Stable reference to one of a character's Bonds / Held Truths.

    A Bond is a Held Truth (FABLE_Engine_Schema_v6.md §12). The mechanical
    target of a compel is always a specific BondRef, not a free string, so the
    engine can answer: "which Bond, when, by what event, what changed."

    `commitment_id` links to the Commitment in the event log that established
    this as a Held Truth. None for legacy entries migrated from `bonds: list[str]`.
    """

    bond_id: str
    character_id: str
    description: str
    commitment_id: str | None = None

    def __post_init__(self) -> None:
        if not self.bond_id:
            raise ValueError("BondRef requires non-empty bond_id")
        if not self.character_id:
            raise ValueError("BondRef requires non-empty character_id")
        if not self.description:
            raise ValueError("BondRef requires non-empty description")


@dataclass
class CharacterSheet:
    """Mechanical truth for one character (PC or significant NPC).

    `skills` maps lowercase skill names to ratings 0–4 (FABLE_Engine_Schema_v6.md §4).
    Skills not listed default to 0 (untrained). `edge` is the current Edge
    spend reserve, capped at 3 (FABLE_Engine_Schema_v6.md §13).
    """

    entity_id: str
    concept: str
    skills: dict[str, int] = field(default_factory=dict)
    traits: list[str] = field(default_factory=list)
    bonds: list[str] = field(default_factory=list)
    bond_refs: list[BondRef] = field(default_factory=list)
    drive: str = ""
    question: str = ""
    gear: list[str] = field(default_factory=list)
    stress: int = 0
    edge: int = 0
    scars: list[str] = field(default_factory=list)

    def skill(self, name: str) -> int:
        """Rating for `name` (0 if not listed)."""
        return self.skills.get(name.lower(), 0)

    def __post_init__(self) -> None:
        for name, rating in self.skills.items():
            if not (0 <= rating <= 4):
                raise ValueError(f"skill {name!r} rating must be 0–4, got {rating}")
        if not (0 <= self.edge <= 3):
            raise ValueError(f"edge must be 0–3, got {self.edge}")
        if self.stress < 0:
            raise ValueError(f"stress must be >= 0, got {self.stress}")
