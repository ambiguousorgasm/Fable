"""Social interpretation and Bond compels (Phase 20; FABLE_Engine_Schema_v6.md §12–13).

SocialInterpreter analyzes events for relationship changes and Bond-compel
opportunities via model tool calls. Proposals are validated against known
entities and Bonds before the caller can act on them. Player interiority is
screened at validation time and never reaches the game state.

Compel lifecycle:
  1. SocialInterpreter.analyze_event() returns PendingCompel(s).
  2. Beat loop presents the compel to the player and waits for accept/refuse.
  3. resolve_compel() commits the outcome events and applies effects.

Architecture invariants:
  - analyze_event() never mutates state. It returns validated proposals only.
  - The DispositionEngine is the sole writer for disposition deltas.
  - GainEdge on accept flows through EffectExecutor — no direct resource write.
  - Interiority screening runs on every compel proposal before it reaches the
    caller. Language that directs character feelings/beliefs/choices is rejected.
  - A model call failure gracefully returns empty proposals (safe degradation).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .character_sheet import BondRef
from .disposition import DispositionAxis, DispositionDelta
from .effects import EDGE_CAP, EffectResult, GainEdge, TypedEffect

if TYPE_CHECKING:
    from .effects import EffectExecutor
    from .event_log import EventLog
    from .events import Event
    from .provider import ModelGateway


COMPEL_AUTHOR = "compel-engine"

# Interiority flag phrases. Each must appear as a substring of the lowercased text.
_INTERIORITY_PATTERNS = frozenset({
    "you feel ", "you believe ", "you want ", "you choose ",
    "you decide ", "you love ", "you hate ", "you fear ",
    "you know you", "your feelings", "your emotions",
    "makes you feel", "makes you want", "makes you think",
    "you must feel", "you must want", "you must believe",
})


def _check_interiority(text: str) -> str | None:
    """Return the matched pattern if text contains interiority language, else None."""
    lower = text.lower()
    for pattern in _INTERIORITY_PATTERNS:
        if pattern in lower:
            return pattern
    return None


# --------------------------------------------------------------------------- #
# Tool definitions                                                               #
# --------------------------------------------------------------------------- #

_PROPOSE_SOCIAL_DELTA_TOOL: dict[str, Any] = {
    "name": "propose_social_delta",
    "description": (
        "Propose a relationship change caused by a social cue in the scene. "
        "The disposition engine validates and commits. "
        "Do not assert player-character interiority (feelings, beliefs, choices)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "from_id": {"type": "string", "description": "Entity whose attitude changes"},
            "to_id": {"type": "string", "description": "Entity the attitude is toward"},
            "axis": {
                "type": "string",
                "enum": ["trust", "affection", "respect", "obligation"],
                "description": "Which relationship axis changes",
            },
            "delta": {
                "type": "integer",
                "description": "Signed change magnitude; non-zero; typically -2 to +2",
            },
            "reason": {
                "type": "string",
                "description": "One sentence linking this delta to the specific event",
            },
        },
        "required": ["from_id", "to_id", "axis", "delta", "reason"],
    },
}

_PROPOSE_COMPEL_TOOL: dict[str, Any] = {
    "name": "propose_compel",
    "description": (
        "Propose world pressure on a character's Bond/Held Truth. "
        "The player will choose Accept (gain 1 Edge) or Refuse. "
        "Frame as external pressure on situation, reputation, obligation, or relationship. "
        "NEVER assert what the character feels, believes, wants, or chooses."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "bond_id": {
                "type": "string",
                "description": "bond_id of the Bond being pressured (must match a known BondRef)",
            },
            "target_character_id": {
                "type": "string",
                "description": "ID of the player character whose Bond is pressured",
            },
            "source_entity": {
                "type": "string",
                "description": "Who or what is applying the pressure",
            },
            "pressure_description": {
                "type": "string",
                "description": (
                    "Concrete situation complication. "
                    "Example: 'Your Bond with Mira puts you in a difficult position.' "
                    "No interiority language."
                ),
            },
            "accept_consequence": {
                "type": "string",
                "description": (
                    "Concrete cost of accepting. "
                    "Example: 'Accepting means losing travel time.' "
                    "No interiority language."
                ),
            },
            "refuse_note": {
                "type": "string",
                "description": (
                    "Brief note on visible fictional consequence of refusing. "
                    "Example: 'Refusing may be noticed by Mira.' "
                    "No interiority language."
                ),
            },
        },
        "required": [
            "bond_id", "target_character_id", "source_entity",
            "pressure_description", "accept_consequence",
        ],
    },
}

_SOCIAL_INTERPRETER_SYSTEM = """\
You are the social interpreter for a FABLE tabletop RPG session.

Your job: analyze one event for social meaning — relationship shifts and Bond compels.
Use tools to propose these. Do not narrate; do not act on behalf of characters.

FABLE interiority rule:
Compels may pressure SITUATION, REPUTATION, OBLIGATIONS, RELATIONSHIPS, RESOURCES,
OPPORTUNITY, or SAFETY.
Compels must NEVER decide what a character FEELS, BELIEVES, WANTS, or CHOOSES.

Good: "Your Bond with Mira puts you in a difficult position. Accepting means losing time."
Bad: "You feel guilty. You must help her."

Call propose_social_delta for clear relationship shifts with a named cause.
Call propose_compel only when a Bond/Held Truth is under genuine world pressure.
If neither applies, call neither tool. Proposing nothing is correct when the scene
has no social consequence.
"""


# --------------------------------------------------------------------------- #
# Dataclasses                                                                   #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PendingCompel:
    """A validated, unresolved compel waiting for the player's accept/refuse choice.

    Created by SocialInterpreter.analyze_event(). Resolved by resolve_compel().
    Never mutates state — it is a proposal, not a commitment.
    """

    compel_id: str
    bond_ref: BondRef
    pressure_description: str
    accept_consequence: str
    refuse_note: str
    proposed_accept_effects: tuple[TypedEffect, ...]
    compel_proposed_event_id: str
    source_entity: str
    target_character_id: str


@dataclass
class CompelResolution:
    """Outcome of resolve_compel(). Records what was committed and what effects fired."""

    accepted: bool
    pending: PendingCompel
    compel_accepted_event_id: str | None
    compel_refused_event_id: str | None
    applied_effects: list[EffectResult] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# SocialInterpreter                                                             #
# --------------------------------------------------------------------------- #

class SocialInterpreter:
    """Analyzes social events via model tool calls and returns validated proposals.

    Proposals are validated but not committed. The caller feeds delta proposals
    through DispositionEngine.apply_delta() and handles PendingCompel(s) via
    resolve_compel(). This class never writes to the event log or world state.
    """

    ROLE = "social_interpreter"

    def __init__(self, gateway: "ModelGateway", model: str = "claude-sonnet-4-6") -> None:
        self._gateway = gateway
        self._model = model

    def analyze_event(
        self,
        event: "Event",
        social_context: str,
        character_bonds: dict[str, list[BondRef]],
        valid_entities: set[str],
    ) -> tuple[list[DispositionDelta], list[PendingCompel]]:
        """Analyze a social event and return (validated_deltas, validated_compels).

        Validated deltas have causal_event_id=event.id. Caller applies them via
        DispositionEngine.apply_delta(). Validated compels are ready for
        resolve_compel(). On model failure, returns ([], []).
        """
        user_content = (
            f"Event to analyze (id={event.id}):\n"
            f"  author: {event.author}\n"
            f"  type: {event.type}\n"
            f"  content: {event.content}\n"
            f"  channel: {event.channel}\n\n"
            f"Social context:\n{social_context or '(none)'}\n\n"
            "Known characters with Bonds:\n"
        )
        for char_id, bonds in character_bonds.items():
            bond_list = "; ".join(f"{b.bond_id}: {b.description!r}" for b in bonds)
            user_content += f"  {char_id}: [{bond_list}]\n"

        try:
            from .provider import ModelCallError
            response = self._gateway.call(
                self.ROLE,
                model=self._model,
                max_tokens=1024,
                tools=[_PROPOSE_SOCIAL_DELTA_TOOL, _PROPOSE_COMPEL_TOOL],
                tool_choice={"type": "auto"},
                system=_SOCIAL_INTERPRETER_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception:
            return [], []

        deltas: list[DispositionDelta] = []
        compels: list[PendingCompel] = []

        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            inp = getattr(block, "input", {}) or {}
            name = getattr(block, "name", None)
            if name == "propose_social_delta":
                delta = self._validate_delta(inp, event, valid_entities)
                if delta is not None:
                    deltas.append(delta)
            elif name == "propose_compel":
                compel = self._validate_compel(inp, event, character_bonds, valid_entities)
                if compel is not None:
                    compels.append(compel)

        return deltas, compels

    def _validate_delta(
        self,
        inp: dict[str, Any],
        event: "Event",
        valid_entities: set[str],
    ) -> DispositionDelta | None:
        try:
            from_id = str(inp["from_id"]).strip()
            to_id = str(inp["to_id"]).strip()
            axis = DispositionAxis(str(inp["axis"]).strip().lower())
            delta = int(inp["delta"])
            reason = str(inp.get("reason", "")).strip()
        except (KeyError, ValueError):
            return None

        if delta == 0:
            return None
        if not from_id or not to_id:
            return None
        if from_id not in valid_entities or to_id not in valid_entities:
            return None
        if from_id == to_id:
            return None

        try:
            return DispositionDelta(
                from_id=from_id,
                to_id=to_id,
                axis=axis,
                delta=delta,
                causal_event_id=event.id,
                reason=reason,
            )
        except ValueError:
            return None

    def _validate_compel(
        self,
        inp: dict[str, Any],
        event: "Event",
        character_bonds: dict[str, list[BondRef]],
        valid_entities: set[str],
    ) -> PendingCompel | None:
        try:
            bond_id = str(inp["bond_id"]).strip()
            target_char_id = str(inp["target_character_id"]).strip()
            source_entity = str(inp["source_entity"]).strip()
            pressure = str(inp["pressure_description"]).strip()
            accept_consequence = str(inp["accept_consequence"]).strip()
            refuse_note = str(inp.get("refuse_note", "")).strip()
        except (KeyError, ValueError):
            return None

        if not bond_id or not pressure or not accept_consequence:
            return None
        if not target_char_id or target_char_id not in valid_entities:
            return None

        for text in (pressure, accept_consequence, refuse_note):
            if text and _check_interiority(text) is not None:
                return None

        target_bonds = character_bonds.get(target_char_id, [])
        bond_ref = next((b for b in target_bonds if b.bond_id == bond_id), None)
        if bond_ref is None:
            return None

        return PendingCompel(
            compel_id=str(uuid.uuid4()),
            bond_ref=bond_ref,
            pressure_description=pressure,
            accept_consequence=accept_consequence,
            refuse_note=refuse_note,
            proposed_accept_effects=(),
            compel_proposed_event_id=event.id,
            source_entity=source_entity,
            target_character_id=target_char_id,
        )


# --------------------------------------------------------------------------- #
# resolve_compel                                                                 #
# --------------------------------------------------------------------------- #

def resolve_compel(
    pending: PendingCompel,
    accepted: bool,
    log: "EventLog",
    executor: "EffectExecutor | None",
    audience: tuple[str, ...],
    *,
    source_event_id: str | None = None,
) -> CompelResolution:
    """Commit compel resolution events and apply effects.

    Accept path:
      1. Log compel_accepted (derived from compel_proposed_event_id).
      2. Apply GainEdge(1) via executor.
      3. Apply proposed_accept_effects via executor.
      4. Log compel_resolved (derived from compel_accepted event).

    Refuse path:
      1. Log compel_refused (no mechanical effects).
      2. Log compel_resolved.

    This is the authoritative write point for compel outcomes. No caller may
    bypass it to directly write compel events or apply Edge outside this path.
    """
    base_derived = (pending.compel_proposed_event_id,)
    if source_event_id:
        base_derived = base_derived + (source_event_id,)

    if accepted:
        accepted_event = log.append(
            author=pending.target_character_id,
            channel="system",
            type="compel_accepted",
            content=f"Compel accepted: {pending.pressure_description}",
            audience=audience,
            derived_from=base_derived,
        )
        applied: list[EffectResult] = []
        if executor is not None:
            gain = GainEdge(kind="gain_edge", entity_id=pending.target_character_id, amount=1)
            applied.append(executor.apply(gain, audience=audience, source_event_id=accepted_event.id))
            for effect in pending.proposed_accept_effects:
                applied.append(executor.apply(effect, audience=audience, source_event_id=accepted_event.id))
        log.append(
            author=COMPEL_AUTHOR,
            channel="system",
            type="compel_resolved",
            content=f"Compel resolved (accepted): Bond '{pending.bond_ref.description}'",
            audience=audience,
            derived_from=(accepted_event.id,),
        )
        return CompelResolution(
            accepted=True,
            pending=pending,
            compel_accepted_event_id=accepted_event.id,
            compel_refused_event_id=None,
            applied_effects=applied,
        )
    else:
        refused_event = log.append(
            author=pending.target_character_id,
            channel="system",
            type="compel_refused",
            content=f"Compel refused: {pending.pressure_description}",
            audience=audience,
            derived_from=base_derived,
        )
        log.append(
            author=COMPEL_AUTHOR,
            channel="system",
            type="compel_resolved",
            content=f"Compel resolved (refused): Bond '{pending.bond_ref.description}'",
            audience=audience,
            derived_from=(refused_event.id,),
        )
        return CompelResolution(
            accepted=False,
            pending=pending,
            compel_accepted_event_id=None,
            compel_refused_event_id=refused_event.id,
            applied_effects=[],
        )
