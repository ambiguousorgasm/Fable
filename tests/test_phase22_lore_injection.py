"""Phase 22: lorebook injection into adjudicator, narrator, and character-agent prompts.

Tests that ContextAssembler.lore_block() is wired through to each prompt
builder, and that the audience gate (set in D-043) is respected end-to-end.

All model calls are mocked; no API key required.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from fable_table_engine.context import ContextAssembler, BeliefStore
from fable_table_engine.event_log import EventLog
from fable_table_engine.lorebook import LoreAssembler, LoreDeck, LoreEntry
from fable_table_engine.gm import AdjudicatorGM, NarratorGM
from fable_table_engine.character_agent import CharacterAgent, _build_user_message
from fable_table_engine.character_sheet import CharacterSheet
from fable_table_engine.persona import PersonaSpec
from fable_table_engine.provider import ModelGateway, TelemetrySink


# --------------------------------------------------------------------------- #
# Helpers                                                                        #
# --------------------------------------------------------------------------- #

def _gateway(response):
    client = MagicMock()
    client.messages.create = MagicMock(return_value=response)
    return ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)


def _text_response(text: str):
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _tool_response(name: str, data: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = data
    resp = MagicMock()
    resp.content = [block]
    return resp


_NO_STAKES = {
    "has_stakes": False,
    "reasoning": "stakes-free",
    "action_domain": "social",
    "exposure": 0,
    "effect": "standard",
    "consequence_palette": [],
    "skill": None,
    "tn": None,
    "declared_facts": [],
    "triumph_effects": [],
    "trade_options": [],
    "trade_default": "Balanced",
    "edge_label": None,
    "seam": False,
    "narrative_hint": "ok",
}

_SHEET = CharacterSheet(entity_id="hero", concept="Fighter")


def _deck_with_entry(**kwargs) -> LoreDeck:
    defaults = dict(
        entry_id="e1",
        title="Test Lore",
        content="The ancient forge burns eternal.",
        keywords=("forge",),
        audience_class="all",
    )
    defaults.update(kwargs)
    return LoreDeck([LoreEntry(**defaults)])


def _assembler_with_lore(log, deck: LoreDeck) -> ContextAssembler:
    return ContextAssembler(log, lore_assembler=LoreAssembler(deck, max_entries=5))


# --------------------------------------------------------------------------- #
# ContextAssembler.lore_block                                                   #
# --------------------------------------------------------------------------- #

class TestLoreBlock:

    def test_returns_empty_string_without_assembler(self):
        log = EventLog()
        ctx = ContextAssembler(log)
        store = ctx.belief_store("hero")
        assert ctx.lore_block(store, "hero") == ""

    def test_returns_empty_string_on_no_match(self):
        log = EventLog()
        deck = _deck_with_entry(keywords=("dragon",))
        ctx = _assembler_with_lore(log, deck)
        store = ctx.belief_store("hero")
        assert ctx.lore_block(store, "hero") == ""

    def test_returns_formatted_block_on_match(self):
        log = EventLog()
        log.append(type="narration", author="narrator", content="the forge glows", channel="public", audience=("hero",))
        deck = _deck_with_entry(keywords=("forge",))
        ctx = _assembler_with_lore(log, deck)
        store = ctx.belief_store("hero")
        result = ctx.lore_block(store, "hero")
        assert "Background lore" in result
        assert "Test Lore" in result
        assert "ancient forge" in result

    def test_gm_only_entry_absent_for_player(self):
        log = EventLog()
        log.append(type="narration", author="narrator", content="the forge glows", channel="public", audience=("hero",))
        deck = _deck_with_entry(keywords=("forge",), audience_class="gm_only")
        ctx = _assembler_with_lore(log, deck)
        store = ctx.belief_store("hero")
        assert ctx.lore_block(store, "hero") == ""

    def test_gm_only_entry_present_for_gm(self):
        log = EventLog()
        log.append(type="narration", author="narrator", content="the forge glows", channel="public", audience=("gm",))
        deck = _deck_with_entry(keywords=("forge",), audience_class="gm_only")
        ctx = _assembler_with_lore(log, deck)
        store = ctx.belief_store("gm")
        result = ctx.lore_block(store, "gm")
        assert "Test Lore" in result


# --------------------------------------------------------------------------- #
# AdjudicatorGM.evaluate — lore_context param                                   #
# --------------------------------------------------------------------------- #

class TestAdjudicatorLoreContext:

    def test_lore_context_included_in_user_message(self):
        captured = {}

        def fake_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _tool_response("adjudicate_action", _NO_STAKES)

        client = MagicMock()
        client.messages.create.side_effect = fake_create
        gw = ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)
        adj = AdjudicatorGM(gw)

        adj.evaluate(
            action="test",
            actor_sheet=_SHEET,
            world_summary="quiet",
            recent_events="nothing",
            lore_context="[Background lore]\n\n## The Forge\nIt burns.",
        )

        content = captured["messages"][0]["content"]
        assert "Background lore" in content
        assert "The Forge" in content

    def test_empty_lore_context_not_injected(self):
        captured = {}

        def fake_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _tool_response("adjudicate_action", _NO_STAKES)

        client = MagicMock()
        client.messages.create.side_effect = fake_create
        gw = ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)
        adj = AdjudicatorGM(gw)

        adj.evaluate(
            action="test",
            actor_sheet=_SHEET,
            world_summary="quiet",
            recent_events="nothing",
            lore_context="",
        )

        content = captured["messages"][0]["content"]
        assert "Background lore" not in content

    def test_lore_context_default_is_empty(self):
        """lore_context defaults to '' — existing callers need no change."""
        client = MagicMock()
        client.messages.create.return_value = _tool_response("adjudicate_action", _NO_STAKES)
        gw = ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)
        adj = AdjudicatorGM(gw)
        result = adj.evaluate(
            action="test", actor_sheet=_SHEET,
            world_summary="quiet", recent_events="nothing",
        )
        assert result is not None


# --------------------------------------------------------------------------- #
# NarratorGM.narrate — lore_context param                                       #
# --------------------------------------------------------------------------- #

class TestNarratorLoreContext:

    def test_lore_context_included_in_user_message(self):
        captured = {}

        def fake_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _text_response("You see the forge.")

        client = MagicMock()
        client.messages.create.side_effect = fake_create
        gw = ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)
        narr = NarratorGM(gw)

        narr.narrate(
            action="look around",
            stakes=None,
            band=None,
            player_context="you see a room",
            lore_context="[Background lore]\n\n## The Forge\nIt burns.",
        )

        content = captured["messages"][0]["content"]
        assert "Background lore" in content

    def test_lore_context_precedes_player_context(self):
        captured = {}

        def fake_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _text_response("ok")

        client = MagicMock()
        client.messages.create.side_effect = fake_create
        gw = ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)
        narr = NarratorGM(gw)

        narr.narrate(
            action="look",
            stakes=None,
            band=None,
            player_context="player knows this",
            lore_context="LORE_SENTINEL",
        )

        content = captured["messages"][0]["content"]
        assert content.index("LORE_SENTINEL") < content.index("player knows this")

    def test_empty_lore_context_not_injected(self):
        captured = {}

        def fake_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _text_response("ok")

        client = MagicMock()
        client.messages.create.side_effect = fake_create
        gw = ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)
        narr = NarratorGM(gw)

        narr.narrate(
            action="look", stakes=None, band=None, player_context="ctx", lore_context=""
        )

        content = captured["messages"][0]["content"]
        assert "Background lore" not in content

    def test_lore_context_default_is_empty(self):
        client = MagicMock()
        client.messages.create.return_value = _text_response("ok")
        gw = ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)
        narr = NarratorGM(gw)
        result = narr.narrate(action="look", stakes=None, band=None, player_context="ctx")
        assert result == "ok"


# --------------------------------------------------------------------------- #
# _build_user_message — lore_context param                                      #
# --------------------------------------------------------------------------- #

class TestBuildUserMessageLore:

    def _persona(self) -> PersonaSpec:
        return PersonaSpec(entity_id="ally", name="Ally", concept="Scout", voice="steady", values="honour", public_goals="survive")

    def test_lore_context_injected_at_top(self):
        persona = self._persona()
        msg = _build_user_message(
            persona,
            events_summary="nothing happened",
            scene_summary="",
            lore_context="LORE_BLOCK",
        )
        assert msg.startswith("LORE_BLOCK")

    def test_lore_context_precedes_events(self):
        persona = self._persona()
        msg = _build_user_message(
            persona,
            events_summary="EVENT_MARKER",
            scene_summary="",
            lore_context="LORE_MARKER",
        )
        assert msg.index("LORE_MARKER") < msg.index("EVENT_MARKER")

    def test_empty_lore_context_not_injected(self):
        persona = self._persona()
        msg = _build_user_message(
            persona, events_summary="events", scene_summary="", lore_context=""
        )
        assert "Background lore" not in msg

    def test_lore_context_default_is_empty(self):
        persona = self._persona()
        msg = _build_user_message(persona, events_summary="events", scene_summary="")
        assert "Background lore" not in msg


# --------------------------------------------------------------------------- #
# CharacterAgent.propose — lore flows from assembler                            #
# --------------------------------------------------------------------------- #

class TestCharacterAgentLoreInjection:

    def _agent(self, response) -> CharacterAgent:
        persona = PersonaSpec(entity_id="ally", name="Ally", concept="Scout", voice="calm", values="honour", public_goals="protect")
        sheet = CharacterSheet(entity_id="ally", concept="Scout")
        gw = _gateway(response)
        return CharacterAgent(persona, sheet, gw)

    def test_propose_calls_with_no_lore_when_no_assembler(self):
        captured = {}

        def fake_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _tool_response("propose_action", {"intent": "wait", "channel": "public"})

        client = MagicMock()
        client.messages.create.side_effect = fake_create
        gw = ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)
        persona = PersonaSpec(entity_id="ally", name="Ally", concept="Scout", voice="calm", values="honour", public_goals="protect")
        sheet = CharacterSheet(entity_id="ally", concept="Scout")
        agent = CharacterAgent(persona, sheet, gw)

        log = EventLog()
        ctx = ContextAssembler(log)
        agent.propose(ctx)

        content = captured["messages"][0]["content"]
        assert "Background lore" not in content

    def test_propose_injects_lore_when_assembler_matches(self):
        captured = {}

        def fake_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _tool_response("propose_action", {"intent": "wait", "channel": "public"})

        client = MagicMock()
        client.messages.create.side_effect = fake_create
        gw = ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)
        persona = PersonaSpec(entity_id="ally", name="Ally", concept="Scout", voice="calm", values="honour", public_goals="protect")
        sheet = CharacterSheet(entity_id="ally", concept="Scout")
        agent = CharacterAgent(persona, sheet, gw)

        log = EventLog()
        log.append(type="narration", author="narrator", content="the forge glows", channel="public", audience=("ally",))
        deck = _deck_with_entry(keywords=("forge",))
        ctx = _assembler_with_lore(log, deck)
        agent.propose(ctx)

        content = captured["messages"][0]["content"]
        assert "Background lore" in content
        assert "Test Lore" in content

    def test_gm_only_lore_not_injected_into_character_agent(self):
        captured = {}

        def fake_create(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _tool_response("propose_action", {"intent": "wait", "channel": "public"})

        client = MagicMock()
        client.messages.create.side_effect = fake_create
        gw = ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)
        persona = PersonaSpec(entity_id="ally", name="Ally", concept="Scout", voice="calm", values="honour", public_goals="protect")
        sheet = CharacterSheet(entity_id="ally", concept="Scout")
        agent = CharacterAgent(persona, sheet, gw)

        log = EventLog()
        log.append(type="narration", author="narrator", content="the forge glows", channel="public", audience=("ally",))
        deck = _deck_with_entry(keywords=("forge",), audience_class="gm_only")
        ctx = _assembler_with_lore(log, deck)
        agent.propose(ctx)

        content = captured["messages"][0]["content"]
        assert "Background lore" not in content
