"""Phase 5 tests — cold/warm GM split (D-007, CORE §4.2, §7.2).

All tests mock the Anthropic client so no API key is needed. The mocks
return valid tool-use responses for the adjudicator and plain text for the
narrator, exactly as the real API would.

What is verified:
  - AdjudicatorGM parses tool-use responses into StakesDecision.
  - Adjudicator forces has_stakes=False correctly (no rules-engine call).
  - Adjudicator forces has_stakes=True → rules engine resolves + logs events.
  - NarratorGM receives band name, not dice values.
  - BeatRunner wires steps 2–9 end-to-end:
      - No-stakes beat: no dice events, one narration event.
      - Stakes beat: dice + resolution events, one narration event.
      - Declared facts are committed to the canon ledger.
  - WorldSimulator ticks clocks and fires fronts.
  - CharacterSheet validation.
  - Information boundary: narrator mock is never given dice values.
"""

from __future__ import annotations

import random
from unittest.mock import MagicMock, patch

import pytest

from fable_table_engine import (
    AdjudicatorGM,
    Band,
    BeatRunner,
    CharacterSheet,
    CommitPipeline,
    ContextAssembler,
    DiceService,
    Entity,
    EventLog,
    ModelGateway,
    NarratorGM,
    RulesEngine,
    StakesDecision,
    WorldSimulator,
    WorldState,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _make_tools_response(tool_input: dict):
    """Build a minimal mock Anthropic tool-use response."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "adjudicate_action"
    block.input = tool_input
    response = MagicMock()
    response.content = [block]
    return response


def _make_text_response(text: str):
    """Build a minimal mock Anthropic text response."""
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _basic_setup():
    """Return (log, world, pipeline, rules, dice, assembler, sheets) with one actor."""
    log = EventLog()
    world = WorldState()
    world.add_zone("tavern")
    world.add_entity(Entity(id="rook", kind="pc", name="Rook"))
    world.place("rook", "tavern")

    pipeline = CommitPipeline(log)
    dice = DiceService(log, rng=random.Random(42))
    rules = RulesEngine(log, dice)
    assembler = ContextAssembler(log)

    sheet = CharacterSheet(
        entity_id="rook",
        concept="Wandering blade",
        skills={"fighting": 3, "sneaking": 2},
    )
    sheets = {"rook": sheet}
    return log, world, pipeline, rules, assembler, sheets


# --------------------------------------------------------------------------- #
# CharacterSheet                                                                #
# --------------------------------------------------------------------------- #

class TestCharacterSheet:

    def test_skill_lookup(self):
        sheet = CharacterSheet(entity_id="x", concept="Test", skills={"fighting": 3})
        assert sheet.skill("fighting") == 3
        assert sheet.skill("sneaking") == 0  # unlisted defaults to 0
        assert sheet.skill("FIGHTING") == 3  # case-insensitive

    def test_invalid_skill_rating(self):
        with pytest.raises(ValueError):
            CharacterSheet(entity_id="x", concept="Test", skills={"fighting": 5})

    def test_invalid_edge(self):
        with pytest.raises(ValueError):
            CharacterSheet(entity_id="x", concept="Test", edge=4)

    def test_invalid_stress(self):
        with pytest.raises(ValueError):
            CharacterSheet(entity_id="x", concept="Test", stress=-1)


# --------------------------------------------------------------------------- #
# AdjudicatorGM                                                                #
# --------------------------------------------------------------------------- #

class TestAdjudicatorGM:

    def _make_adjudicator(self, tool_input: dict) -> tuple[AdjudicatorGM, MagicMock]:
        client = MagicMock()
        client.messages.create.return_value = _make_tools_response(tool_input)
        return AdjudicatorGM(ModelGateway(client), model="claude-sonnet-4-6"), client

    def test_no_stakes_action(self):
        adj, _ = self._make_adjudicator({
            "has_stakes": False,
            "reasoning": "Looking around is trivial and risk-free.",
        })
        sheet = CharacterSheet(entity_id="rook", concept="Blade", skills={"fighting": 3})
        result = adj.evaluate("I look around the tavern.", sheet, "Zones: tavern", "(no events)")
        assert result.has_stakes is False
        assert result.skill is None
        assert result.tn is None

    def test_stakes_action(self):
        adj, _ = self._make_adjudicator({
            "has_stakes": True,
            "reasoning": "Guard is alert; a failed sneak will raise the alarm.",
            "skill": "sneaking",
            "tn": 11,
            "declared_facts": [],
        })
        sheet = CharacterSheet(entity_id="rook", concept="Blade", skills={"sneaking": 2})
        result = adj.evaluate("I slip past the guard.", sheet, "...", "...")
        assert result.has_stakes is True
        assert result.skill == "sneaking"
        assert result.skill_rating == 2  # looked up from CharacterSheet, not the model
        assert result.tn == 11

    def test_stakes_decision_validation(self):
        with pytest.raises(ValueError, match="missing fields"):
            StakesDecision(has_stakes=True, reasoning="needs a roll")

    def test_declared_facts_parsed(self):
        adj, _ = self._make_adjudicator({
            "has_stakes": False,
            "reasoning": "Trivial, but establishes a fact.",
            "declared_facts": [
                {"subject": "door", "predicate": "state", "value": "open", "revealed": True}
            ],
        })
        sheet = CharacterSheet(entity_id="rook", concept="Blade")
        result = adj.evaluate("I open the door.", sheet, "...", "...")
        assert len(result.declared_facts) == 1
        assert result.declared_facts[0]["subject"] == "door"

    def test_missing_tool_call_raises(self):
        client = MagicMock()
        response = MagicMock()
        response.content = []  # no tool_use block
        client.messages.create.return_value = response
        adj = AdjudicatorGM(ModelGateway(client))
        sheet = CharacterSheet(entity_id="rook", concept="Blade")
        with pytest.raises(RuntimeError, match="adjudicate_action"):
            adj.evaluate("do something", sheet, "...", "...")


# --------------------------------------------------------------------------- #
# NarratorGM                                                                   #
# --------------------------------------------------------------------------- #

class TestNarratorGM:

    def test_narrates_prose(self):
        client = MagicMock()
        client.messages.create.return_value = _make_text_response(
            "You duck under the guard's lazy arm and slip into the alley."
        )
        narrator = NarratorGM(ModelGateway(client))
        stakes = StakesDecision(
            has_stakes=True, reasoning="Guard patrol",
            skill="sneaking", skill_rating=2, tn=11,
        )
        prose = narrator.narrate("I slip past the guard.", stakes, Band.SUCCESS, "(context)")
        assert "You" in prose
        assert len(prose) > 10

    def test_no_dice_values_in_narrator_call(self):
        """Verify the narrator is never given dice totals or margins."""
        client = MagicMock()
        client.messages.create.return_value = _make_text_response("Narration.")
        narrator = NarratorGM(ModelGateway(client))
        stakes = StakesDecision(
            has_stakes=True, reasoning="some reasoning",
            skill="fighting", skill_rating=3, tn=12,
        )
        narrator.narrate("I attack.", stakes, Band.TRIUMPH, "player context")
        call_kwargs = client.messages.create.call_args
        # Extract the user message content
        messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][3]
        user_content = next(
            m["content"] for m in messages if m["role"] == "user"
        )
        # The user message must not contain numeric dice totals or the word "margin"
        assert "margin" not in user_content.lower()
        assert "3d6" not in user_content
        # The band name IS present — that is expected
        assert "Triumph" in user_content

    def test_no_stakes_narration(self):
        client = MagicMock()
        client.messages.create.return_value = _make_text_response(
            "You glance around; dusty tables, a fire burning low."
        )
        narrator = NarratorGM(ModelGateway(client))
        stakes = StakesDecision(has_stakes=False, reasoning="Trivial observation.")
        prose = narrator.narrate("I look around.", stakes, None, "(context)")
        assert len(prose) > 5


# --------------------------------------------------------------------------- #
# WorldSimulator                                                                #
# --------------------------------------------------------------------------- #

class TestWorldSimulator:

    def test_clock_ticks(self):
        log = EventLog()
        world = WorldState()
        world.set_clock("alarm", {"current": 3, "max": 6, "step": 1})
        sim = WorldSimulator(log, world)
        fired = sim.advance()
        assert fired == []
        assert world.clocks["alarm"]["current"] == 4

    def test_clock_fires_at_max(self):
        log = EventLog()
        world = WorldState()
        world.set_clock("alarm", {"current": 5, "max": 6, "step": 1})
        sim = WorldSimulator(log, world)
        fired = sim.advance()
        assert "alarm" in fired
        assert world.clocks["alarm"]["fired"] is True
        assert len(log) == 1  # front_advance event logged

    def test_fired_clock_not_ticked_again(self):
        log = EventLog()
        world = WorldState()
        world.set_clock("alarm", {"current": 6, "max": 6, "fired": True})
        sim = WorldSimulator(log, world)
        fired = sim.advance()
        assert fired == []
        assert len(log) == 0

    def test_multi_step_clock(self):
        log = EventLog()
        world = WorldState()
        world.set_clock("ritual", {"current": 0, "max": 4, "step": 2})
        sim = WorldSimulator(log, world)
        sim.advance()
        assert world.clocks["ritual"]["current"] == 2
        fired = sim.advance()
        assert "ritual" in fired


# --------------------------------------------------------------------------- #
# BeatRunner — end to end                                                       #
# --------------------------------------------------------------------------- #

class TestBeatRunner:

    def _make_runner(self, adj_input: dict, narrator_text: str, with_simulator=False):
        log, world, pipeline, rules, assembler, sheets = _basic_setup()

        adj_client = MagicMock()
        adj_client.messages.create.return_value = _make_tools_response(adj_input)

        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _make_text_response(narrator_text)

        adjudicator = AdjudicatorGM(ModelGateway(adj_client))
        narrator = NarratorGM(ModelGateway(narrator_client))
        simulator = WorldSimulator(log, world) if with_simulator else None

        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=rules, assembler=assembler,
            adjudicator=adjudicator, narrator=narrator,
            sheets=sheets, gm_entity="gm",
            simulator=simulator,
        )
        runner._narrator = narrator  # keep reference for inspection in tests
        return runner, log

    def test_no_stakes_beat_logs_one_narration_event(self):
        runner, log = self._make_runner(
            {"has_stakes": False, "reasoning": "Trivial."},
            "You glance around the tavern.",
        )
        result = runner.run("rook", "I look around.")
        assert result.had_stakes is False
        assert result.resolution is None
        # Only the narration event — no dice events.
        events = log.all()
        types = [e.type for e in events]
        assert "narration" in types
        assert "dice_roll" not in types

    def test_stakes_beat_logs_dice_and_narration(self):
        runner, log = self._make_runner(
            {
                "has_stakes": True,
                "reasoning": "Genuine risk.",
                "skill": "fighting",
                "tn": 11,
                "declared_facts": [],
            },
            "Your blade finds a gap in his guard.",
        )
        result = runner.run("rook", "I attack the guard.")
        assert result.had_stakes is True
        assert result.resolution is not None
        assert result.resolution.band in list(Band)
        types = [e.type for e in log.all()]
        assert "dice_roll" in types
        assert "resolution" in types
        assert "narration" in types

    def test_declared_facts_enter_canon_ledger(self):
        runner, log = self._make_runner(
            {
                "has_stakes": False,
                "reasoning": "Establishes a fact.",
                "declared_facts": [
                    {"subject": "door", "predicate": "state", "value": "ajar", "revealed": True}
                ],
            },
            "The door creaks open at your touch.",
        )
        result = runner.run("rook", "I open the door.")
        assert result.committed_fact_count == 1
        pipeline = CommitPipeline(log)
        canon = pipeline.canon_ledger()
        assert ("door", "state") in canon
        assert canon[("door", "state")].value == "ajar"

    def test_narration_event_content_matches_narrator_output(self):
        prose = "Shadows swallow you whole as you slip past the patrol."
        runner, log = self._make_runner(
            {"has_stakes": False, "reasoning": "No opposition."},
            prose,
        )
        result = runner.run("rook", "I hide in the shadows.")
        assert result.narration == prose
        narration_event = log.get(result.narration_event_id)
        assert narration_event.content == prose
        assert narration_event.channel == "public"

    def test_missing_sheet_raises(self):
        runner, _ = self._make_runner(
            {"has_stakes": False, "reasoning": "..."},
            "narration",
        )
        with pytest.raises(ValueError, match="CharacterSheet"):
            runner.run("nonexistent_actor", "do something")

    def test_clock_fires_after_beat(self):
        runner, log = self._make_runner(
            {"has_stakes": False, "reasoning": "Trivial."},
            "You look around.",
            with_simulator=True,
        )
        # Manually plant a clock that will fire.
        runner._world.set_clock("patrol", {"current": 5, "max": 6, "step": 1})
        result = runner.run("rook", "I look around.")
        assert "patrol" in result.clocks_fired

    def test_information_boundary_narrator_has_no_dice(self):
        """The narrator mock should never be called with dice values in the message."""
        runner, _ = self._make_runner(
            {
                "has_stakes": True,
                "reasoning": "Risk present.",
                "skill": "fighting",
                "tn": 11,
                "declared_facts": [],
            },
            "Your attack lands.",
        )
        runner.run("rook", "I swing at the guard.")
        # Inspect what the narrator client was called with.
        call = runner._narrator._gateway._client.messages.create.call_args
        messages = call[1]["messages"] if call[1] else call.args[3]
        user_text = next(m["content"] for m in messages if m["role"] == "user")
        assert "3d6" not in user_text
        assert "margin" not in user_text.lower()
        # Band name is expected; dice number is not.
        assert any(b.value in user_text for b in Band)
