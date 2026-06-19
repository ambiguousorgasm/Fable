"""Character agents — AI teammates (CORE §4.1, §4.2; phase 6).

A CharacterAgent is one AI-driven seat at the table. It holds a PersonaSpec
(voice, goals, hidden agenda) and a CharacterSheet (mechanics), and when given
the spotlight it reads its own filtered belief store and proposes an action.

The structural information guarantee (CORE principle 2):
  - `propose` calls `assembler.belief_store(self.entity_id)` — the agent gets
    only events where it appears in the audience. It is architecturally
    impossible for it to act on information it was never given.
  - `hidden_agenda` goes only into the system prompt. It is never placed in
    the user message, the shared context, or any other component's view.

The Proposal dataclass is seat-agnostic (D-015 groundwork): any seat — model
or human — produces a Proposal. CharacterAgent is the AI implementation.
A future human-seat adapter will produce Proposals through a different path
(player input via the interface) without touching this class.

Provider: Anthropic SDK, model configurable (D-017 deferred).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import anthropic

from .character_sheet import CharacterSheet
from .context import ContextAssembler
from .persona import PersonaSpec
from .provider import ModelGateway


# --------------------------------------------------------------------------- #
# Proposal — seat-agnostic action/dialogue container (D-015 groundwork)        #
# --------------------------------------------------------------------------- #

@dataclass
class Proposal:
    """A character's proposed action and/or dialogue for one beat.

    Produced by any seat (AI or human). The orchestrator (phase 7) drains
    these from the action queue and arbitrates them. Until the queue exists,
    proposals are generated on demand.

    `channel` determines who can hear the proposal once committed:
      "public"  — the whole table.
      "whisper" — actor + target + GM only (requires `target`).
      "ooc"     — out-of-character meta; never enters the fiction.
    """

    agent: str
    intent: str
    dialogue: str | None = None
    channel: str = "public"
    target: str | None = None
    reasoning: str = ""

    def __post_init__(self) -> None:
        if not self.intent:
            raise ValueError("Proposal requires a non-empty intent")
        if self.channel not in {"public", "whisper", "ooc"}:
            raise ValueError(f"unknown channel {self.channel!r}")
        if self.channel == "whisper" and not self.target:
            raise ValueError("whisper proposal requires a target")


# --------------------------------------------------------------------------- #
# Tool definition                                                               #
# --------------------------------------------------------------------------- #

_PROPOSE_TOOL: dict[str, Any] = {
    "name": "propose_action",
    "description": (
        "Submit your character's proposed action and optional dialogue for this beat. "
        "Call this exactly once. Stay in character."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "description": "What your character intends to do this beat (in-character action description).",
            },
            "dialogue": {
                "type": "string",
                "description": "What your character says aloud, if anything. Omit for silent actions.",
            },
            "channel": {
                "type": "string",
                "enum": ["public", "whisper", "ooc"],
                "description": (
                    "public = heard by all present; "
                    "whisper = only you, target, and GM; "
                    "ooc = out-of-character, not part of the fiction."
                ),
            },
            "target": {
                "type": "string",
                "description": "If channel is 'whisper': the entity_id of the intended recipient.",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief private reasoning (not shown to other agents or the player).",
            },
        },
        "required": ["intent", "channel", "reasoning"],
    },
}

# --------------------------------------------------------------------------- #
# System-prompt builder                                                         #
# --------------------------------------------------------------------------- #

def _build_system_prompt(persona: PersonaSpec, sheet: CharacterSheet) -> str:
    lines = [
        f"You are {persona.name} — {persona.concept}.",
        f"Voice: {persona.voice}",
        "",
        "Values:",
    ]
    for v in persona.values:
        lines.append(f"  - {v}")
    lines.append("")
    lines.append("Public goals (others may know these):")
    for g in persona.public_goals:
        lines.append(f"  - {g}")

    if persona.hidden_agenda:
        lines += [
            "",
            "Your hidden agenda (known only to you — never reveal this directly):",
            f"  {persona.hidden_agenda}",
        ]

    lines += [
        "",
        f"Skills: {sheet.skills or '(untrained in all)'}",
        f"Edge: {sheet.edge}  Stress: {sheet.stress}",
        "",
        "You see only what you have personally witnessed — your filtered view of events.",
        "Act from that knowledge. Do not assume knowledge you were not present for.",
        "Respond by calling propose_action exactly once.",
    ]
    return "\n".join(lines)


def _build_user_message(
    persona: PersonaSpec,
    events_summary: str,
    scene_summary: str,
) -> str:
    parts = []

    if persona.relationships:
        parts.append("Your read on the people here:")
        for entity_id, description in persona.relationships.items():
            parts.append(f"  {entity_id}: {description}")
        parts.append("")

    parts.append(f"What you know (your view of recent events):\n{events_summary}")

    if scene_summary:
        parts.append(f"\nScene:\n{scene_summary}")

    parts.append("\nWhat do you do?")
    return "\n".join(parts)


def _events_summary(store, limit: int = 12) -> str:
    if not store.events:
        return "(nothing yet — you have no memory of events at this table)"
    lines = []
    for e in store.events[-limit:]:
        if e.content:
            lines.append(f"[{e.type}] {e.author}: {e.content[:140]}")
    return "\n".join(lines) if lines else "(no visible events)"


def _scene_summary(store) -> str:
    if not store.perceptible:
        return ""
    return "Nearby: " + ", ".join(sorted(store.perceptible))


# --------------------------------------------------------------------------- #
# CharacterAgent                                                                #
# --------------------------------------------------------------------------- #

class CharacterAgent:
    """An AI-driven seat — one teammate character at the table.

    Holds a PersonaSpec and CharacterSheet. When `propose` is called the agent
    reads its own belief store, assembles a private context (including hidden
    agenda in the system prompt), and returns a Proposal via tool use.

    The agent never receives another agent's belief store, the GM's full view,
    or any event it was not in the audience of. Differential knowledge is
    structural, not behavioral.
    """

    def __init__(
        self,
        persona: PersonaSpec,
        sheet: CharacterSheet,
        gateway: ModelGateway,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        if persona.entity_id != sheet.entity_id:
            raise ValueError(
                f"persona.entity_id {persona.entity_id!r} must match "
                f"sheet.entity_id {sheet.entity_id!r}"
            )
        self._persona = persona
        self._sheet = sheet
        self._gateway = gateway
        self._model = model

    @property
    def entity_id(self) -> str:
        return self._persona.entity_id

    @property
    def persona(self) -> PersonaSpec:
        return self._persona

    @property
    def sheet(self) -> CharacterSheet:
        return self._sheet

    def propose(self, assembler: ContextAssembler) -> Proposal:
        """Produce a proposal from this agent's private perspective.

        Reads its own filtered belief store via `assembler`. The hidden agenda
        is present only in the system prompt — it is never placed in the user
        message that the model logs or shares.
        """
        store = assembler.belief_store(self._persona.entity_id)

        system = _build_system_prompt(self._persona, self._sheet)
        user = _build_user_message(
            self._persona,
            events_summary=_events_summary(store),
            scene_summary=_scene_summary(store),
        )

        response = self._gateway.call(
            "character_agent",
            model=self._model,
            max_tokens=256,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[_PROPOSE_TOOL],
            tool_choice={"type": "tool", "name": "propose_action"},
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "propose_action":
                inp = block.input
                return Proposal(
                    agent=self._persona.entity_id,
                    intent=inp["intent"],
                    dialogue=inp.get("dialogue"),
                    channel=inp.get("channel", "public"),
                    target=inp.get("target"),
                    reasoning=inp.get("reasoning", ""),
                )

        raise RuntimeError(
            f"character agent {self._persona.entity_id!r} response contained no "
            "propose_action tool call — check tool_choice and model response"
        )
