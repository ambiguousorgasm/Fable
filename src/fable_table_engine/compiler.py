"""Campaign compiler — converts raw user input to a validated CampaignPackage (E-1, D-040).

Pipeline:
    user_input → CampaignCompiler.compile() → raw_dict
               → _validate(raw_dict) → errors
               → CampaignCompiler.repair(user_input, draft, errors)  [if errors]
               → repeat up to max_attempts
               → load_campaign_dict(raw_dict) → CampaignPackage

Non-negotiable boundary: raw user input is compiler source material only.
It must never be placed in GM context, narrator context, or any player-facing surface.
Only the validated CampaignPackage output enters the game.
"""

from __future__ import annotations

from typing import Any

from .campaign import CampaignPackage, load_campaign_dict


# --------------------------------------------------------------------------- #
# Public errors                                                                 #
# --------------------------------------------------------------------------- #

class CompilerError(Exception):
    """Raised when campaign compilation fails after max_attempts."""


# --------------------------------------------------------------------------- #
# Tool schema — drives structured output via Anthropic tool-use                #
# --------------------------------------------------------------------------- #

_CAMPAIGN_TOOL: dict[str, Any] = {
    "name": "create_campaign",
    "description": (
        "Create a fully playable FABLE Table Engine campaign package. "
        "All cross-references must be internally consistent: every front's "
        "clock_name must match a name in world_clocks; every hook's function_id "
        "must match an id in function_nodes."
    ),
    "input_schema": {
        "type": "object",
        "required": [
            "version", "title", "description",
            "player_intro", "gm_context",
            "starting_scene", "starting_location",
            "initial_visible_truths", "initial_hidden_truths",
            "world_clocks", "fronts", "npcs", "tone_boundaries",
        ],
        "properties": {
            "version": {
                "type": "string",
                "description": "Schema version, always \"1.0\".",
            },
            "title": {
                "type": "string",
                "description": "Short, evocative campaign title.",
            },
            "description": {
                "type": "string",
                "description": "1–3 sentence campaign premise (player-safe summary).",
            },
            "player_intro": {
                "type": "string",
                "description": (
                    "Opening narration delivered to the player at session start. "
                    "Sets tone and stakes. Must not contain GM secrets."
                ),
            },
            "gm_context": {
                "type": "string",
                "description": (
                    "GM-private context: hidden villain plans, true motives, "
                    "secrets the player must not learn prematurely. "
                    "Never shown to the player or ally agents."
                ),
            },
            "starting_scene": {
                "type": "string",
                "description": (
                    "First scene prompt for the GM narrator. Describes the opening "
                    "situation in detail. This is GM-side input, not player narration."
                ),
            },
            "starting_location": {
                "type": "string",
                "description": "Name or ID of the starting zone/location (e.g. 'The Saltmere Docks').",
            },
            "initial_visible_truths": {
                "type": "array",
                "description": (
                    "3–6 plain-English fact statements committed as player-visible truths "
                    "at session open. Example: 'The city is under martial law.'"
                ),
                "items": {"type": "string"},
                "minItems": 1,
            },
            "initial_hidden_truths": {
                "type": "array",
                "description": (
                    "2–4 GM-private facts committed at session open. "
                    "Example: 'The commander is secretly a cult member.' "
                    "Never surfaced to the player."
                ),
                "items": {"type": "string"},
                "minItems": 1,
            },
            "world_clocks": {
                "type": "array",
                "description": (
                    "At least one clock tracking an off-screen threat. "
                    "Clock names must match front clock_name values exactly."
                ),
                "items": {
                    "type": "object",
                    "required": ["name", "max"],
                    "properties": {
                        "name":           {"type": "string"},
                        "current":        {"type": "integer"},
                        "max":            {"type": "integer"},
                        "trigger_types":  {"type": "array", "items": {"type": "string"}},
                        "active":         {"type": "boolean"},
                        "advance_policy": {"type": "string"},
                        "domain":         {"type": "string"},
                        "landing_truth":  {"type": "string"},
                        "front_owner":    {"type": "string"},
                    },
                },
                "minItems": 1,
            },
            "fronts": {
                "type": "array",
                "description": (
                    "At least one off-screen threat. "
                    "clock_name must exactly match a name in world_clocks."
                ),
                "items": {
                    "type": "object",
                    "required": ["id", "name", "threat", "clock_name", "consequence_truth"],
                    "properties": {
                        "id":                {"type": "string"},
                        "name":              {"type": "string"},
                        "threat":            {"type": "string"},
                        "clock_name":        {"type": "string"},
                        "consequence_truth": {"type": "string"},
                        "faction_id":        {"type": "string"},
                    },
                },
                "minItems": 1,
            },
            "npcs": {
                "type": "array",
                "description": "Key NPCs in this campaign.",
                "items": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id":          {"type": "string"},
                        "name":        {"type": "string"},
                        "description": {"type": "string"},
                        "faction_id":  {"type": "string"},
                        "disposition": {
                            "type": "string",
                            "enum": ["friendly", "neutral", "hostile", "unknown"],
                        },
                    },
                },
            },
            "tone_boundaries": {
                "type": "object",
                "description": "Content constraints for this campaign.",
                "properties": {
                    "content_rating":   {"type": "string"},
                    "forbidden_themes": {"type": "array", "items": {"type": "string"}},
                    "advisory_themes":  {"type": "array", "items": {"type": "string"}},
                },
            },
            "factions": {
                "type": "array",
                "description": "Standing organizations with goals and momentum.",
                "items": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id":       {"type": "string"},
                        "name":     {"type": "string"},
                        "goals":    {"type": "array", "items": {"type": "string"}},
                        "momentum": {"type": "integer"},
                    },
                },
            },
            "function_nodes": {
                "type": "array",
                "description": "Abstract narrative needs the plot must fulfill.",
                "items": {
                    "type": "object",
                    "required": ["id", "description"],
                    "properties": {
                        "id":          {"type": "string"},
                        "description": {"type": "string"},
                        "required":    {"type": "boolean"},
                    },
                },
            },
            "hooks": {
                "type": "array",
                "description": "Live narrative functions with current fixture bindings. function_id must match a function_nodes id.",
                "items": {
                    "type": "object",
                    "required": ["function_id", "binding"],
                    "properties": {
                        "function_id": {"type": "string"},
                        "binding": {
                            "type": "object",
                            "required": ["function_id", "fixture_entity_id", "description"],
                            "properties": {
                                "function_id":       {"type": "string"},
                                "fixture_entity_id": {"type": "string"},
                                "description":       {"type": "string"},
                            },
                        },
                        "preconditions": {"type": "array", "items": {"type": "string"}},
                        "active":        {"type": "boolean"},
                    },
                },
            },
            "hidden_nodes": {
                "type": "array",
                "description": "Prepared-but-unrevealed plot nodes.",
                "items": {
                    "type": "object",
                    "required": ["id", "description"],
                    "properties": {
                        "id":          {"type": "string"},
                        "description": {"type": "string"},
                        "required":    {"type": "boolean"},
                    },
                },
            },
            "lore_entries": {
                "type": "array",
                "description": "Lorebook entries injected when triggered by keyword matching.",
                "items": {
                    "type": "object",
                    "required": ["entry_id", "title", "content"],
                    "properties": {
                        "entry_id":       {"type": "string"},
                        "title":          {"type": "string"},
                        "content":        {"type": "string"},
                        "keywords":       {"type": "array", "items": {"type": "string"}},
                        "audience_class": {"type": "string"},
                        "priority":       {"type": "integer"},
                    },
                },
            },
        },
    },
}

_SYSTEM_PROMPT = """\
You are the FABLE Campaign Compiler. Your sole task is to convert raw user input \
(a premise, setting, themes, or partial draft) into a fully playable FABLE Table \
Engine campaign package by calling the create_campaign tool.

Rules:
- Call create_campaign exactly once with a complete, internally consistent package.
- Every front's clock_name must exactly match a name in world_clocks.
- Every hook's function_id must exactly match an id in function_nodes.
- player_intro must be player-safe — no hidden truths, no villain reveals.
- gm_context is private — include secrets, hidden motivations, and twist information here.
- starting_scene is the GM's first scene prompt, not player narration.
- initial_visible_truths: facts the player knows at session open (3–6 statements).
- initial_hidden_truths: facts only the GM knows at session open (2–4 statements).
- Invent vivid, specific details. Generic placeholders are not acceptable.
- version must be "1.0".
"""


# --------------------------------------------------------------------------- #
# CampaignCompiler                                                              #
# --------------------------------------------------------------------------- #

class CampaignCompiler:
    """One model call: raw user input → campaign JSON dict (structured output via tool-use).

    Never passes the raw user input into any game context. The raw input feeds
    only this compiler call; the output dict is validated before use.
    """

    ROLE = "campaign_compiler"

    def __init__(self, gateway: Any) -> None:
        self._gw = gateway

    def compile(self, user_input: str) -> dict[str, Any]:
        """Single model call. Returns raw dict (not yet validated by load_campaign_dict)."""
        response = self._gw.call(
            self.ROLE,
            max_tokens=8192,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_input}],
            tools=[_CAMPAIGN_TOOL],
            tool_choice={"type": "tool", "name": "create_campaign"},
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "create_campaign":
                return dict(block.input)  # type: ignore[arg-type]
        raise CompilerError("Model did not return a create_campaign tool call")

    def repair(
        self,
        user_input: str,
        draft: dict[str, Any],
        errors: list[str],
    ) -> dict[str, Any]:
        """Follow-up call: sends draft + validation errors back to the model for a fix."""
        import json
        repair_prompt = (
            f"{user_input}\n\n"
            "Your previous draft had the following validation errors. "
            "Return a corrected campaign using the create_campaign tool.\n\n"
            "Errors:\n"
            + "\n".join(f"- {e}" for e in errors)
            + "\n\nPrevious draft (for reference):\n"
            + json.dumps(draft, indent=2)
        )
        return self.compile(repair_prompt)


# --------------------------------------------------------------------------- #
# CampaignCompilerGateway                                                       #
# --------------------------------------------------------------------------- #

def _validate(draft: dict[str, Any]) -> list[str]:
    """Run load_campaign_dict and return a list of error strings (empty = valid)."""
    try:
        load_campaign_dict(draft)
        return []
    except ValueError as exc:
        return [str(exc)]


class CampaignCompilerGateway:
    """Orchestrates compile → validate → repair/retry loop.

    max_attempts controls the total number of model calls (1 compile + up to
    max_attempts-1 repairs). Raises CompilerError if the package still fails
    validation after all attempts.
    """

    def __init__(self, compiler: CampaignCompiler, max_attempts: int = 3) -> None:
        self._compiler = compiler
        self._max_attempts = max(1, max_attempts)

    def generate(self, user_input: str) -> CampaignPackage:
        """Run the compile → validate → repair loop. Returns a validated CampaignPackage."""
        if not user_input or not user_input.strip():
            raise ValueError("user_input must not be empty")

        draft = self._compiler.compile(user_input)

        for attempt in range(self._max_attempts):
            errors = _validate(draft)
            if not errors:
                return load_campaign_dict(draft)

            if attempt + 1 >= self._max_attempts:
                raise CompilerError(
                    f"Campaign failed validation after {self._max_attempts} attempt(s): "
                    + "; ".join(errors)
                )

            draft = self._compiler.repair(user_input, draft, errors)

        # Unreachable — loop always returns or raises above.
        raise CompilerError("generate() loop exited unexpectedly")  # pragma: no cover
