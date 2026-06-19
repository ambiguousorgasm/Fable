"""Persona spec — per-agent voice, values, goals, and private knowledge (CORE §8; phase 6).

A PersonaSpec is the non-mechanical identity of one character agent: how they
speak, what they care about, what they're trying to achieve, and — critically —
what they want that they're not admitting. The `hidden_agenda` field goes only
into the agent's *system prompt*; it is never placed in shared context or any
other agent's view (CORE principle 2).

Relationships are a lightweight map of entity_id → prose description. These are
the character's private assessment of others, not the authoritative disposition
graph (phase 10). The disposition engine will eventually feed richer relational
state here; for now they are authored by the GM at session setup.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PersonaSpec:
    """Voice and private knowledge for one character agent.

    Fields shared with other agents (via context assembly):
        entity_id, name, concept, voice, values, public_goals, relationships

    Fields kept private to this agent's system prompt only:
        hidden_agenda

    `voice` is a short prose description of *how* the character speaks —
    not what they say but the register, affect, and style. E.g.:
    "Clipped, dry. Never raises her voice. Speaks in short declaratives."
    """

    entity_id: str
    name: str
    concept: str
    voice: str
    values: list[str] = field(default_factory=list)
    public_goals: list[str] = field(default_factory=list)
    hidden_agenda: str = ""
    relationships: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("PersonaSpec requires a non-empty entity_id")
        if not self.name:
            raise ValueError("PersonaSpec requires a non-empty name")
