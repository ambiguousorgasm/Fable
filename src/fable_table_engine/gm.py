"""GM decomposition — cold adjudicator, warm narrator, world-simulator (CORE §4.2, §7.2; phase 5).

Three separated roles, each with a strict information boundary:

  AdjudicatorGM (cold)
    Runs the FABLE stakes gate; decides TN/skill/exposure/effect/trade, pre-declares
    consequence palette (Phase 13 / D-025). Has full world-state context. Produces NO
    player-facing prose — every output is structured (D-007). Forced tool call.

  NarratorGM (warm)
    Renders the resolved result into prose. Receives ONLY the player's filtered belief
    store and the applied outcome — never dice values, never the consequence palette,
    never hidden world state (CORE principle 2, D-007).

  WorldSimulator
    Advances clocks and fires fronts between beats (CORE §4.2). Receives the
    action_domain tag from the ResolutionPlan to advance only domain-matching clocks
    (D-026).

Provider: Anthropic SDK, model configurable (default claude-sonnet-4-6).
Provider agnosticism is a named future goal tracked as D-017.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import anthropic

from .character_sheet import CharacterSheet
from .events import Commitment
from .provider import ModelGateway, ToolOutputError
from .rules import Band, CheckResult
from .world_state import WorldState

if TYPE_CHECKING:
    from .access import CommitPipeline


# --------------------------------------------------------------------------- #
# Adjudicator tool definition (D-007, D-025)                                   #
# --------------------------------------------------------------------------- #

_EFFECT_ENTRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "A typed effect. The 'kind' field is the discriminant. "
        "Field requirements by kind:\n"
        "  advance_clock    — clock_name (str), steps (int, default 1)\n"
        "  apply_stress     — entity_id (str), amount (int; positive = harm, negative = relief)\n"
        "  create_truth     — subject, predicate, value, revealed (bool)\n"
        "  change_truth     — subject, predicate, value, revealed (bool), reason (str)\n"
        "  expire_truth     — subject, predicate, revealed (bool)\n"
        "  move_entity      — entity_id, to_zone\n"
        "  change_resource  — entity_id, resource, delta OR set_value (not both)\n"
        "  change_access    — operation ('darken'|'illuminate'|'close'|'open'), "
        "zone_a, zone_b (close/open only)\n"
        "  create_maintained_truth — subject, predicate, value, lapse_condition, revealed\n"
        "  expire_maintained_truth — subject, predicate, revealed"
    ),
    "required": ["kind"],
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                "create_truth", "change_truth", "expire_truth",
                "advance_clock", "apply_stress", "change_access",
                "move_entity", "change_resource",
                "create_maintained_truth", "expire_maintained_truth",
            ],
        },
    },
    "additionalProperties": True,
}

_ADJUDICATE_TOOL: dict[str, Any] = {
    "name": "adjudicate_action",
    "description": (
        "Submit your cold adjudication of the declared action. "
        "Call this exactly once. Do NOT produce prose — this output is never shown to the player."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "has_stakes": {
                "type": "boolean",
                "description": (
                    "True if the action has genuine risk, meaningful opposition, or an uncertain "
                    "outcome that matters. False for trivial, guaranteed, or purely descriptive "
                    "actions (FABLE_Engine_Schema_v6.md §5, §11: no-empty-rolls rule)."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "Brief cold rationale for your decision. Not shown to the player.",
            },
            "skill": {
                "type": "string",
                "description": (
                    "If has_stakes=true: the skill being tested (lowercase, e.g. 'fighting'). "
                    "The engine will look up the actor's current rating — do not supply it."
                ),
            },
            "tn": {
                "type": "integer",
                "description": (
                    "If has_stakes=true: target number for the check (typically 9–15). "
                    "TN measures DIFFICULTY, not danger — do not raise TN because consequences "
                    "are severe. Use exposure for consequence severity."
                ),
                "minimum": 4,
                "maximum": 20,
            },
            "action_domain": {
                "type": "string",
                "description": (
                    "A tag for the kind of action. Used to advance domain-matching pressure "
                    "clocks (e.g. 'stealth', 'social', 'combat', 'exploration', 'research'). "
                    "Use 'beat' as a generic catch-all."
                ),
            },
            "exposure": {
                "type": "integer",
                "description": (
                    "If has_stakes=true: consequence severity on a Cost or Setback. "
                    "1 = minor complication, 2 = real setback, "
                    "3 = significant harm or loss, 4 = drastic and lasting. "
                    "Captures danger independently from TN (difficulty)."
                ),
                "minimum": 1,
                "maximum": 4,
            },
            "effect": {
                "type": "string",
                "description": (
                    "If has_stakes=true: quality of success on a clean Success or Triumph. "
                    "Minimal = limited/partial, Standard = full clean success, "
                    "Superior = beyond what was asked, Extreme = transformative."
                ),
                "enum": ["Minimal", "Standard", "Superior", "Extreme"],
            },
            "trade_options": {
                "type": "array",
                "description": (
                    "Available trade choices for the player before committing. "
                    "Aggressive: Exposure +1, Effect +1 tier. "
                    "Balanced: no change. "
                    "Guarded: Exposure -1, Effect -1 tier. "
                    "Omit choices that fiction rules out."
                ),
                "items": {"type": "string", "enum": ["Aggressive", "Balanced", "Guarded"]},
            },
            "trade_default": {
                "type": "string",
                "description": "The suggested default trade. Usually 'Balanced'.",
                "enum": ["Aggressive", "Balanced", "Guarded"],
            },
            "consequence_palette": {
                "type": "object",
                "description": (
                    "Pre-declared consequences for Cost and Setback bands. "
                    "Declare BEFORE the roll — these are the announced stakes. "
                    "The engine selects the matching band and applies these typed effects."
                ),
                "properties": {
                    "cost": {
                        "type": "array",
                        "description": "Effects applied on a Cost (success at a price).",
                        "items": _EFFECT_ENTRY_SCHEMA,
                    },
                    "setback": {
                        "type": "array",
                        "description": "Effects applied on a Setback (failure).",
                        "items": _EFFECT_ENTRY_SCHEMA,
                    },
                },
            },
            "triumph_effects": {
                "type": "array",
                "description": (
                    "Bonus typed effects applied on a Triumph, above and beyond declared_facts."
                ),
                "items": _EFFECT_ENTRY_SCHEMA,
            },
            "edge_label": {
                "type": "string",
                "description": (
                    "If the actor has a relevant Edge or Bond that could be spent for a bonus die, "
                    "describe the fictional justification here. Omit if no Edge spend applies."
                ),
            },
            "declared_facts": {
                "type": "array",
                "description": (
                    "Facts this action establishes regardless of roll outcome "
                    "(fiction the GM commits to unconditionally). "
                    "Use consequence_palette entries for outcome-conditional facts."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "predicate": {"type": "string"},
                        "value": {},
                        "revealed": {
                            "type": "boolean",
                            "description": "True if this fact is visible to the player.",
                        },
                    },
                    "required": ["subject", "predicate", "value", "revealed"],
                },
            },
        },
        "required": ["has_stakes", "reasoning"],
    },
}

_ADJUDICATOR_SYSTEM = """\
You are the cold adjudicator for a FABLE tabletop RPG session.

Your sole job: evaluate the declared action and produce a structured ResolutionPlan.

FABLE stakes gate (FABLE_Engine_Schema_v6.md §5, §11):
- Roll only when there is genuine risk, meaningful opposition, or uncertain outcome.
- Do NOT roll for trivial actions, guaranteed successes, or pure description.
- Stakes-free actions still ripple through fiction but do not hit the dice.

When stakes exist, supply all of these:
  skill         — the most applicable skill (lowercase). Engine supplies the rating.
  tn            — difficulty (easy ~9, standard ~11, hard ~13, very hard ~15+).
                  TN measures DIFFICULTY, not danger. Never raise TN for severity.
  action_domain — a domain tag for clock advancement ('stealth', 'social', 'combat',
                  'exploration', 'research', or 'beat' as catch-all).
  exposure      — consequence severity (1–4). Independent of TN.
  effect        — quality of success on a clean win (Minimal/Standard/Superior/Extreme).
  trade_options — which of Aggressive/Balanced/Guarded apply (usually all three).
  trade_default — suggested default (usually 'Balanced').
  consequence_palette — pre-declare what happens on Cost and Setback as typed effects.
  triumph_effects — bonus effects on a Triumph (optional; omit for routine actions).

Consequence effect kinds: advance_clock, apply_stress, create_truth, change_truth,
expire_truth, move_entity, change_resource, change_access, create_maintained_truth,
expire_maintained_truth. Use 'advance_clock' for pressure escalation on Cost/Setback;
use 'apply_stress' for harm.

You MUST call `adjudicate_action` exactly once. Produce no prose.\
"""


# --------------------------------------------------------------------------- #
# ResolutionPlan (formerly StakesDecision)                                     #
# --------------------------------------------------------------------------- #

@dataclass
class ResolutionPlan:
    """The cold adjudicator's structured plan for one declared action (Phase 13 / D-025).

    Extends the phase-5 StakesDecision with pre-declared consequence palette,
    action domain tag, exposure/effect/trade, and triumph extras.

    All Phase-13 fields are optional with sensible defaults so existing test
    code that constructs StakesDecision(has_stakes=..., ...) still passes.
    """

    has_stakes: bool
    reasoning: str
    skill: str | None = None
    skill_rating: int | None = None
    tn: int | None = None
    declared_facts: list[dict[str, Any]] = field(default_factory=list)

    # Phase 13 additions (D-025)
    action_domain: str = "beat"
    exposure: int | None = None
    effect: str | None = None
    trade_options: list[str] = field(default_factory=list)
    trade_default: str = "Balanced"
    consequence_palette: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    triumph_effects: list[dict[str, Any]] = field(default_factory=list)
    edge_label: str | None = None
    seam: bool = False

    def __post_init__(self) -> None:
        if self.has_stakes:
            missing = [f for f in ("skill", "skill_rating", "tn") if getattr(self, f) is None]
            if missing:
                raise ValueError(
                    f"ResolutionPlan has_stakes=True but missing fields: {missing}"
                )


# Backward-compatibility alias so existing imports of StakesDecision keep working.
StakesDecision = ResolutionPlan


# --------------------------------------------------------------------------- #
# AdjudicatorGM                                                                #
# --------------------------------------------------------------------------- #

class AdjudicatorGM:
    """Cold GM — stakes gate + structured ResolutionPlan via tool use (D-007, D-025).

    Forces `adjudicate_action` via tool_choice so the model cannot drift into
    prose. The resulting ResolutionPlan is entirely structured; nothing it
    contains is shown to the player directly.
    """

    def __init__(
        self,
        gateway: ModelGateway,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self._gateway = gateway
        self._model = model

    def evaluate(
        self,
        action: str,
        actor_sheet: CharacterSheet,
        world_summary: str,
        recent_events: str,
        lore_context: str = "",
    ) -> ResolutionPlan:
        """Evaluate `action` and return a structured resolution plan.

        Retries once on a malformed tool response (Phase 22 structured-output
        normalization). Raises ToolOutputError after two failed parse attempts
        so BeatRunner can abort cleanly without propagating a raw exception.
        """
        user_content = (
            f"Actor: {actor_sheet.entity_id} ({actor_sheet.concept})\n"
            f"Skills: {actor_sheet.skills or '(none listed — all 0)'}\n"
            f"Edge: {actor_sheet.edge}  Stress: {actor_sheet.stress}\n\n"
            f"World state:\n{world_summary}\n\n"
            f"Recent events:\n{recent_events}\n"
        )
        if lore_context:
            user_content += f"\n{lore_context}\n"
        user_content += f"\nDeclared action: {action}"
        call_kwargs = dict(
            model=self._model,
            max_tokens=512,
            system=_ADJUDICATOR_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
            tools=[_ADJUDICATE_TOOL],
            tool_choice={"type": "tool", "name": "adjudicate_action"},
        )
        last_parse_error: Exception | None = None
        for attempt in range(2):
            response = self._gateway.call("adjudicator", **call_kwargs)
            try:
                return self._parse_response(response, actor_sheet)
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                last_parse_error = exc
        raise ToolOutputError("adjudicator", 2, str(last_parse_error))

    def _parse_response(self, response: Any, actor_sheet: CharacterSheet) -> ResolutionPlan:
        """Extract ResolutionPlan from a raw adjudicator API response.

        Raises KeyError / TypeError / RuntimeError on malformed content so that
        the caller (evaluate) can retry or convert to ToolOutputError.
        """
        for block in response.content:
            if block.type == "tool_use" and block.name == "adjudicate_action":
                inp = block.input
                has_stakes = inp["has_stakes"]
                skill = inp.get("skill")
                # Engine owns skill ratings — look up from the authoritative sheet,
                # never trust a model-supplied value (determinism boundary, CORE §1.3).
                skill_rating = actor_sheet.skill(skill) if (has_stakes and skill) else None
                return ResolutionPlan(
                    has_stakes=has_stakes,
                    reasoning=inp["reasoning"],
                    skill=skill,
                    skill_rating=skill_rating,
                    tn=inp.get("tn"),
                    declared_facts=inp.get("declared_facts", []),
                    action_domain=inp.get("action_domain", "beat"),
                    exposure=inp.get("exposure"),
                    effect=inp.get("effect"),
                    trade_options=inp.get("trade_options", []),
                    trade_default=inp.get("trade_default", "Balanced"),
                    consequence_palette=inp.get("consequence_palette", {}),
                    triumph_effects=inp.get("triumph_effects", []),
                    edge_label=inp.get("edge_label"),
                    seam=bool(inp.get("seam", False)),
                )
        raise RuntimeError(
            "adjudicator response contained no adjudicate_action tool call"
        )


# --------------------------------------------------------------------------- #
# NarratorGM                                                                   #
# --------------------------------------------------------------------------- #

_NARRATOR_SYSTEM = """\
You are the warm narrator for a FABLE tabletop RPG session.

Your role: render the resolved action result into vivid, immersive prose for the player.

Rules:
- Write in second person, present tense ("You step forward…").
- You know the result band and the Effect quality — interpret them dramatically.
  Minimal = limited, partial win; Standard = clean success; Superior = more than asked;
  Extreme = transformative. Match the description to the scale.
  Do NOT mention dice, numbers, TN, or the word "roll".
- If mechanical consequences were applied (stress gained, clock advanced, etc.),
  weave them into the fiction — do not name them mechanically.
- You receive only what the player can see. Do not introduce facts the player has not witnessed.
- Keep it tight: 2–4 sentences for routine actions, more for high-stakes moments.
- No meta-commentary, no system references, no fourth-wall breaks.\
"""


class NarratorGM:
    """Warm GM — prose renderer (D-007).

    Receives only the player's filtered belief store and the resolved outcome —
    never dice values, never the consequence palette, never hidden world state.
    Cannot leak secrets it was never given.
    """

    def __init__(
        self,
        gateway: ModelGateway,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self._gateway = gateway
        self._model = model

    def narrate(
        self,
        action: str,
        stakes: ResolutionPlan | None,
        band: Band | None,
        player_context: str,
        effective_effect: str = "Standard",
        applied_summary: str | None = None,
        lore_context: str = "",
    ) -> str:
        """Return prose narration for the player.

        `stakes` is accepted for backward compatibility but not used in the
        prompt — the narrator must not see adjudicator reasoning.
        `effective_effect` is the post-trade effect quality tier.
        `applied_summary` is a brief plain-English summary of mechanical
        consequences applied; the narrator should weave these into the fiction
        without naming them as game mechanics.
        `lore_context` is an optional lorebook block injected before player
        context so the narrator has relevant background without GM reasoning.
        """
        if band is not None:
            result_line = f"Resolution: {band.value} — Effect quality: {effective_effect}"
        else:
            result_line = "No roll needed."

        parts = []
        if lore_context:
            parts.append(lore_context)
        parts += [
            f"What the player knows:\n{player_context}",
            f"Declared action: {action}",
            result_line,
        ]
        if applied_summary:
            parts.append(f"Mechanical consequences (weave into fiction, do not name): {applied_summary}")

        user_content = "\n".join(parts)
        response = self._gateway.call(
            "narrator",
            model=self._model,
            max_tokens=400,
            system=_NARRATOR_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text.strip()


# --------------------------------------------------------------------------- #
# WorldSimulator                                                                #
# --------------------------------------------------------------------------- #

class WorldSimulator:
    """Advances clocks and fires fronts between beats (CORE §4.2, D-026).

    Phase 9: `advance(trigger)` only ticks clocks whose `trigger_types` set
    contains the supplied trigger tag (default ``"beat"``). Clocks without a
    `trigger_types` field default to ``{"beat"}`` for backward compatibility.
    Inactive clocks (`active=False`) are skipped entirely.

    Clock schema additions (D-026):
      trigger_types  — set of trigger tags that advance this clock
      active         — bool; False to pause the clock
      domain         — narrative domain label (e.g. "dungeon", "politics")
      advance_policy — "per_beat" | "per_scene" | "manual"
      landing_truth  — Truth to commit when the clock fills (handled by PlotManager)
      front_owner    — Front id that owns this clock
      addressed_by   — scene/event id that resolved the front (post-fire note)
    """

    def __init__(
        self,
        log,
        world: WorldState,
        gm_entity: str = "gm",
    ) -> None:
        self._log = log
        self._world = world
        self._gm = gm_entity

    def advance(self, trigger: str = "beat") -> list[str]:
        """Tick clocks matching `trigger`. Return names of any that fired."""
        fired: list[str] = []
        for name, clock in list(self._world.clocks.items()):
            current = int(clock.get("current", 0))
            max_ = int(clock.get("max", 6))
            step = int(clock.get("step", 1))
            if clock.get("fired"):
                continue
            if not clock.get("active", True):
                continue
            trigger_types = set(clock.get("trigger_types") or ["beat"])
            if trigger not in trigger_types:
                continue
            new_val = current + step
            if new_val >= max_:
                self._world.set_clock(name, {**clock, "current": max_, "fired": True})
                self._log.append(
                    author=self._gm,
                    channel="system",
                    type="front_advance",
                    content=f"Clock '{name}' filled ({max_}/{max_}) — front fires.",
                    audience=(self._gm,),
                    visibility="content",
                )
                fired.append(name)
            else:
                self._world.set_clock(name, {**clock, "current": new_val})
        return fired

    def declare_scene_transition(
        self,
        scene_phase: str = "quiet",
        elapsed_category: str = "scene",
        prose_time_label: str | None = None,
    ) -> str:
        """Declare a scene boundary. Updates world time anchor and emits the structural event.

        Returns the new scene_id. The client reads scene_id from the event stream
        and never declares scene transitions itself (D-030 client contract).
        """
        import json
        new_scene_id = self._world.begin_scene_transition(
            scene_phase=scene_phase,
            elapsed_category=elapsed_category,
            prose_time_label=prose_time_label,
        )
        payload: dict = {
            "scene_id": new_scene_id,
            "scene_phase": scene_phase,
            "elapsed_category": elapsed_category,
        }
        if prose_time_label is not None:
            payload["prose_time_label"] = prose_time_label
        self._log.append(
            author=self._gm,
            channel="system",
            type="scene_transition",
            content=json.dumps(payload),
            audience=(self._gm,),
            visibility="content",
        )
        return new_scene_id
