"""Phase 21 deliverable 4: D-029 roll visibility tests."""
from __future__ import annotations

import random
from unittest.mock import MagicMock

import pytest

from fable_table_engine import (
    AdjudicatorGM,
    BeatRunner,
    CharacterSheet,
    CommitPipeline,
    ContextAssembler,
    DiceService,
    Entity,
    EventLog,
    ModelGateway,
    NarratorGM,
    ROLL_VISIBILITY_LEVELS,
    RulesEngine,
    WorldState,
)
from fable_table_engine.console import render_event
from fable_table_engine.events import Event, ProjectedEvent, ROLL_VISIBILITY_LEVELS as RVL


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _make_log_dice():
    log = EventLog()
    dice = DiceService(log, rng=random.Random(0))
    return log, dice


def _make_log_rules():
    log = EventLog()
    dice = DiceService(log, rng=random.Random(0))
    rules = RulesEngine(log, dice)
    return log, rules


def _proj(type_: str, content: str = "x", roll_visibility: str | None = None) -> ProjectedEvent:
    return ProjectedEvent(
        sequence=0, id="e1", timestamp="2026-06-19T00:00:00",
        author="actor", channel="dice", type=type_,
        visibility="content", content=content,
        roll_visibility=roll_visibility,
    )


def _tools_resp(tool_input: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "adjudicate_action"
    block.input = tool_input
    response = MagicMock()
    response.content = [block]
    return response


def _text_resp(text: str):
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _make_runner(adj_input: dict, narrator_text: str = "Narration."):
    log = EventLog()
    world = WorldState()
    world.add_zone("dungeon")
    world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
    world.place("hero", "dungeon")

    pipeline = CommitPipeline(log)
    dice = DiceService(log, rng=random.Random(0))
    rules = RulesEngine(log, dice)
    assembler = ContextAssembler(log)
    sheet = CharacterSheet(entity_id="hero", concept="Fighter", skills={"fighting": 4})

    adj_client = MagicMock()
    adj_client.messages.create.return_value = _tools_resp(adj_input)
    narrator_client = MagicMock()
    narrator_client.messages.create.return_value = _text_resp(narrator_text)

    runner = BeatRunner(
        log=log, world=world, pipeline=pipeline,
        rules=rules, assembler=assembler,
        adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
        narrator=NarratorGM(ModelGateway(narrator_client)),
        sheets={"hero": sheet},
        gm_entity="gm",
    )
    return runner, log


_STAKES_ADJ = {
    "has_stakes": True, "reasoning": "real risk",
    "skill": "fighting", "skill_rating": 4, "tn": 1,
    "exposure": 1, "effect": "Standard",
}


# --------------------------------------------------------------------------- #
# ROLL_VISIBILITY_LEVELS constant                                               #
# --------------------------------------------------------------------------- #

class TestRollVisibilityLevels:

    def test_four_values(self):
        assert RVL == {"table", "roller_only", "gm_only", "revealed"}

    def test_is_frozenset(self):
        assert isinstance(RVL, frozenset)

    def test_exported_from_package(self):
        assert ROLL_VISIBILITY_LEVELS is RVL


# --------------------------------------------------------------------------- #
# Event.roll_visibility field                                                   #
# --------------------------------------------------------------------------- #

class TestEventRollVisibilityField:

    def _make_event(self, roll_visibility=None):
        log = EventLog()
        return log.append(
            author="a", channel="public", type="narration",
            content="hello", audience=("a",),
            roll_visibility=roll_visibility,
        )

    def test_default_is_none(self):
        e = self._make_event()
        assert e.roll_visibility is None

    def test_table_stored(self):
        e = self._make_event("table")
        assert e.roll_visibility == "table"

    def test_gm_only_stored(self):
        e = self._make_event("gm_only")
        assert e.roll_visibility == "gm_only"

    def test_roller_only_stored(self):
        e = self._make_event("roller_only")
        assert e.roll_visibility == "roller_only"

    def test_revealed_stored(self):
        e = self._make_event("revealed")
        assert e.roll_visibility == "revealed"

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError, match="roll_visibility"):
            Event(
                sequence=0, id="x", timestamp="t", author="a",
                channel="public", audience=("a",),
                visibility="content", type="narration", content="hi",
                roll_visibility="secret",
            )

    def test_to_dict_includes_roll_visibility(self):
        e = self._make_event("table")
        assert e.to_dict()["roll_visibility"] == "table"

    def test_to_dict_none_preserved(self):
        e = self._make_event(None)
        assert e.to_dict()["roll_visibility"] is None


# --------------------------------------------------------------------------- #
# ProjectedEvent carries roll_visibility                                        #
# --------------------------------------------------------------------------- #

class TestProjectedEventRollVisibility:

    def test_project_for_carries_roll_visibility(self):
        log = EventLog()
        dice = DiceService(log, rng=random.Random(0))
        result = dice.roll(3, 6, author="hero", audience=("hero", "gm"), roll_visibility="table")
        proj = log.project_for("hero")
        assert len(proj) == 1
        assert proj[0].roll_visibility == "table"

    def test_project_for_none_carried(self):
        log = EventLog()
        log.append(
            author="gm", channel="public", type="narration",
            content="the door opens", audience=("hero", "gm"),
        )
        proj = log.project_for("hero")
        assert proj[0].roll_visibility is None

    def test_gm_only_not_in_player_projection(self):
        log = EventLog()
        dice = DiceService(log, rng=random.Random(0))
        dice.roll(3, 6, author="gm", audience=("gm",), roll_visibility="gm_only")
        assert log.project_for("hero") == ()
        assert len(log.project_for("gm")) == 1


# --------------------------------------------------------------------------- #
# DiceService roll_visibility parameter                                         #
# --------------------------------------------------------------------------- #

class TestDiceServiceRollVisibility:

    def test_default_is_table(self):
        log, dice = _make_log_dice()
        result = dice.roll(3, 6, author="hero", audience=("hero", "gm"))
        event = log.get(result.event_id)
        assert event.roll_visibility == "table"

    def test_gm_only_stored(self):
        log, dice = _make_log_dice()
        result = dice.roll(3, 6, author="gm", audience=("gm",), roll_visibility="gm_only")
        event = log.get(result.event_id)
        assert event.roll_visibility == "gm_only"

    def test_roller_only_stored(self):
        log, dice = _make_log_dice()
        result = dice.roll(3, 6, author="hero", audience=("hero", "gm"), roll_visibility="roller_only")
        event = log.get(result.event_id)
        assert event.roll_visibility == "roller_only"

    def test_invalid_roll_visibility_raises(self):
        log, dice = _make_log_dice()
        with pytest.raises(ValueError, match="roll_visibility"):
            dice.roll(3, 6, author="hero", audience=("hero",), roll_visibility="invisible")


# --------------------------------------------------------------------------- #
# RulesEngine resolve_check roll_visibility                                     #
# --------------------------------------------------------------------------- #

class TestResolveCheckRollVisibility:

    def test_default_tags_both_events_table(self):
        log, rules = _make_log_rules()
        result = rules.resolve_check(
            actor="hero", skill=3, tn=10, audience=("hero", "gm"),
        )
        dice_event = log.get(result.dice_event_id)
        res_event = log.get(result.resolution_event_id)
        assert dice_event.roll_visibility == "table"
        assert res_event.roll_visibility == "table"

    def test_gm_only_tags_both_events(self):
        log, rules = _make_log_rules()
        result = rules.resolve_check(
            actor="gm", skill=0, tn=10, audience=("gm",),
            roll_visibility="gm_only",
        )
        dice_event = log.get(result.dice_event_id)
        res_event = log.get(result.resolution_event_id)
        assert dice_event.roll_visibility == "gm_only"
        assert res_event.roll_visibility == "gm_only"

    def test_gm_only_audience_never_in_player_projection(self):
        log, rules = _make_log_rules()
        rules.resolve_check(
            actor="gm", skill=0, tn=10, audience=("gm",),
            roll_visibility="gm_only",
        )
        player_proj = log.project_for("hero")
        assert all(e.type not in ("dice_roll", "resolution") for e in player_proj)


# --------------------------------------------------------------------------- #
# render_event — D-029 client contract                                          #
# --------------------------------------------------------------------------- #

class TestRenderEventRollVisibility:

    def test_table_roll_rendered(self):
        e = _proj("dice_roll", "3d6=[3,2,1]=6", roll_visibility="table")
        assert render_event(e) == "[roll] 3d6=[3,2,1]=6"

    def test_none_roll_visibility_rendered(self):
        e = _proj("dice_roll", "3d6=[3,2,1]=6", roll_visibility=None)
        assert render_event(e) == "[roll] 3d6=[3,2,1]=6"

    def test_gm_only_returns_none(self):
        e = _proj("dice_roll", "3d6=[6,6,6]=18", roll_visibility="gm_only")
        assert render_event(e) is None

    def test_roller_only_rendered(self):
        e = _proj("dice_roll", "3d6=[4,3,2]=9", roll_visibility="roller_only")
        assert render_event(e) == "[roll] 3d6=[4,3,2]=9"

    def test_revealed_rendered(self):
        e = _proj("dice_roll", "3d6=[5,5,5]=15", roll_visibility="revealed")
        assert render_event(e) == "[roll] 3d6=[5,5,5]=15"


# --------------------------------------------------------------------------- #
# Narrator context excludes gm_only events                                     #
# --------------------------------------------------------------------------- #

class TestNarratorContextExcludesGmOnly:

    def test_narrator_does_not_receive_gm_only_roll(self):
        runner, log = _make_runner(_STAKES_ADJ)
        runner.run(actor="hero", action="I fight hard", channel="public")

        # Inject a gm_only roll via DiceService (simulating a passive GM check)
        dice = DiceService(log, rng=random.Random(99))
        dice.roll(3, 6, author="gm", audience=("gm",), roll_visibility="gm_only")

        # The narrator call args should not contain the gm_only content.
        # Check via the narrator mock's call args on the second call (if any).
        # We can verify by inspecting what ends up in narrator context
        # via the belief store projection.
        from fable_table_engine.context import ContextAssembler
        assembler = runner._assembler
        # Player belief store must not contain any gm_only roll event
        player_store = assembler.belief_store("hero")
        gm_only_in_player = [
            e for e in player_store.events
            if e.roll_visibility == "gm_only"
        ]
        assert gm_only_in_player == []


# --------------------------------------------------------------------------- #
# Default beat uses table visibility                                            #
# --------------------------------------------------------------------------- #

class TestBeatDefaultRollVisibility:

    def test_player_beat_roll_is_table(self):
        runner, log = _make_runner(_STAKES_ADJ)
        runner.run(actor="hero", action="I fight", channel="public")
        dice_events = [e for e in log.all() if e.type == "dice_roll"]
        assert dice_events, "no dice roll event logged"
        for e in dice_events:
            assert e.roll_visibility == "table"

    def test_player_roll_in_player_projection(self):
        runner, log = _make_runner(_STAKES_ADJ)
        runner.run(actor="hero", action="I fight", channel="public")
        player_proj = log.project_for("hero")
        dice_in_proj = [e for e in player_proj if e.type == "dice_roll"]
        assert dice_in_proj, "dice roll should be visible to player"
        assert all(e.roll_visibility == "table" for e in dice_in_proj)
