"""Phase 21 deliverable 3: D-027 action lifecycle state machine tests."""
from __future__ import annotations

import random
from unittest.mock import MagicMock, patch

import pytest

from fable_table_engine import (
    ActionLifecycleState,
    AdjudicatorGM,
    BeatResult,
    BeatRunner,
    CharacterSheet,
    CommitPipeline,
    ContextAssembler,
    DiceService,
    Entity,
    EventLog,
    ModelCallError,
    ModelGateway,
    NarratorGM,
    RulesEngine,
    WorldState,
)
from fable_table_engine.console import render_event
from fable_table_engine.events import ProjectedEvent


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

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


def _make_runner(
    adj_input: dict,
    narrator_text: str = "Narration.",
    *,
    rng_seed: int = 0,
):
    log = EventLog()
    world = WorldState()
    world.add_zone("dungeon")
    world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
    world.place("hero", "dungeon")

    pipeline = CommitPipeline(log)
    dice = DiceService(log, rng=random.Random(rng_seed))
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


_NO_STAKES_ADJ = {"has_stakes": False, "reasoning": "trivial"}
_STAKES_ADJ = {
    "has_stakes": True, "reasoning": "real risk",
    "skill": "fighting", "skill_rating": 4, "tn": 1,
    "exposure": 1, "effect": "Standard",
}


def _lifecycle_events(log: EventLog, actor: str = "hero") -> list[str]:
    """Return ordered list of lifecycle state values visible to gm."""
    return [
        e.content
        for e in log.all()
        if e.type == "action_lifecycle" and "gm" in (e.audience or [])
    ]


# --------------------------------------------------------------------------- #
# Enum shape                                                                    #
# --------------------------------------------------------------------------- #

class TestActionLifecycleStateEnum:

    def test_is_str_enum(self):
        assert isinstance(ActionLifecycleState.SUBMITTED, str)

    def test_expected_states_present(self):
        names = {s.name for s in ActionLifecycleState}
        expected = {
            "SUBMITTED", "VALIDATING", "ADJUDICATING",
            "PENDING_PLAYER_CHOICE", "ROLLING", "PENDING_EDGE_DECISION",
            "APPLYING_EFFECTS", "NARRATING", "AUDITING",
            "COMMITTED", "ABORTED", "FAILED", "CANCELLED",
        }
        assert names == expected

    def test_count(self):
        assert len(ActionLifecycleState) == 13

    def test_values_are_lowercase_strings(self):
        for state in ActionLifecycleState:
            assert state.value == state.value.lower()


# --------------------------------------------------------------------------- #
# OOC beat lifecycle                                                            #
# --------------------------------------------------------------------------- #

class TestOOCBeatLifecycle:

    def test_ooc_emits_submitted_then_committed(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        result = runner.run(actor="hero", action="ooc: hello", channel="ooc")
        states = _lifecycle_events(log)
        assert states[:2] == ["submitted", "committed"]

    def test_ooc_result_lifecycle_state_committed(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        result = runner.run(actor="hero", action="ooc: hello", channel="ooc")
        assert result.lifecycle_state == ActionLifecycleState.COMMITTED

    def test_ooc_no_validating_state(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner.run(actor="hero", action="ooc: hello", channel="ooc")
        states = _lifecycle_events(log)
        assert "validating" not in states


# --------------------------------------------------------------------------- #
# No-stakes beat lifecycle                                                      #
# --------------------------------------------------------------------------- #

class TestNoStakesBeatLifecycle:

    def test_no_stakes_full_chain_order(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner.run(actor="hero", action="I look around", channel="public")
        states = _lifecycle_events(log)
        expected_subsequence = [
            "submitted", "validating", "adjudicating",
            "applying_effects", "narrating", "auditing", "committed",
        ]
        # filter to only these values in order
        filtered = [s for s in states if s in set(expected_subsequence)]
        assert filtered == expected_subsequence

    def test_no_stakes_no_rolling(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner.run(actor="hero", action="I look around", channel="public")
        states = _lifecycle_events(log)
        assert "rolling" not in states

    def test_no_stakes_no_pending_player_choice(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner.run(actor="hero", action="I look around", channel="public")
        states = _lifecycle_events(log)
        assert "pending_player_choice" not in states

    def test_no_stakes_lifecycle_state_committed(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        result = runner.run(actor="hero", action="I look around", channel="public")
        assert result.lifecycle_state == ActionLifecycleState.COMMITTED


# --------------------------------------------------------------------------- #
# Stakes beat lifecycle                                                         #
# --------------------------------------------------------------------------- #

class TestStakesBeatLifecycle:

    def test_stakes_emits_rolling(self):
        runner, log = _make_runner(_STAKES_ADJ)
        runner.run(actor="hero", action="I fight", channel="public")
        states = _lifecycle_events(log)
        assert "rolling" in states

    def test_stakes_emits_pending_player_choice(self):
        runner, log = _make_runner(_STAKES_ADJ)
        runner.run(actor="hero", action="I fight", channel="public")
        states = _lifecycle_events(log)
        assert "pending_player_choice" in states

    def test_stakes_full_chain_order(self):
        runner, log = _make_runner(_STAKES_ADJ)
        runner.run(actor="hero", action="I fight", channel="public")
        states = _lifecycle_events(log)
        key = [
            "submitted", "validating", "adjudicating",
            "pending_player_choice", "rolling",
            "applying_effects", "narrating", "auditing", "committed",
        ]
        filtered = [s for s in states if s in set(key)]
        assert filtered == key

    def test_stakes_lifecycle_state_committed(self):
        runner, log = _make_runner(_STAKES_ADJ)
        result = runner.run(actor="hero", action="I fight", channel="public")
        assert result.lifecycle_state == ActionLifecycleState.COMMITTED


# --------------------------------------------------------------------------- #
# Audience policy                                                               #
# --------------------------------------------------------------------------- #

class TestLifecycleAudience:

    def _events_by_type(self, log: EventLog) -> list[tuple[str, tuple]]:
        return [
            (e.content, tuple(e.audience or []))
            for e in log.all()
            if e.type == "action_lifecycle"
        ]

    def test_internal_states_gm_only(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner.run(actor="hero", action="I look around", channel="public")
        pairs = self._events_by_type(log)
        internal = {"validating", "adjudicating", "applying_effects", "narrating", "auditing"}
        for state_val, audience in pairs:
            if state_val in internal:
                assert audience == ("gm",), f"{state_val} audience should be gm-only"

    def test_submitted_all_present(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner.run(actor="hero", action="I look", channel="public")
        pairs = self._events_by_type(log)
        submitted = [a for s, a in pairs if s == "submitted"]
        assert submitted, "no submitted event"
        assert "hero" in submitted[0]
        assert "gm" in submitted[0]

    def test_committed_all_present(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner.run(actor="hero", action="I look", channel="public")
        pairs = self._events_by_type(log)
        committed = [a for s, a in pairs if s == "committed"]
        assert committed, "no committed event"
        assert "hero" in committed[0]
        assert "gm" in committed[0]

    def test_pending_player_choice_actor_and_gm(self):
        runner, log = _make_runner(_STAKES_ADJ)
        runner.run(actor="hero", action="I fight", channel="public")
        pairs = self._events_by_type(log)
        ppc = [a for s, a in pairs if s == "pending_player_choice"]
        assert ppc, "no pending_player_choice event"
        assert "hero" in ppc[0]
        assert "gm" in ppc[0]


# --------------------------------------------------------------------------- #
# ModelCallError paths                                                          #
# --------------------------------------------------------------------------- #

class TestModelCallErrorLifecycle:

    def test_adjudicator_failure_emits_failed(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner._adjudicator = MagicMock()
        runner._adjudicator.evaluate.side_effect = ModelCallError("adj", 1, RuntimeError("boom"))
        result = runner.run(actor="hero", action="I do something", channel="public")
        states = _lifecycle_events(log)
        assert "failed" in states
        assert result.lifecycle_state == ActionLifecycleState.FAILED
        assert result.beat_aborted is True

    def test_adjudicator_failure_no_committed(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner._adjudicator = MagicMock()
        runner._adjudicator.evaluate.side_effect = ModelCallError("adj", 1, RuntimeError("boom"))
        runner.run(actor="hero", action="I do something", channel="public")
        states = _lifecycle_events(log)
        assert "committed" not in states

    def test_narrator_failure_emits_failed(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner._narrator = MagicMock()
        runner._narrator.narrate.side_effect = ModelCallError("narrator", 1, RuntimeError("narrator boom"))
        result = runner.run(actor="hero", action="I look around", channel="public")
        states = _lifecycle_events(log)
        assert "failed" in states
        assert result.lifecycle_state == ActionLifecycleState.FAILED
        assert result.beat_aborted is True

    def test_narrator_failure_no_committed(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner._narrator = MagicMock()
        runner._narrator.narrate.side_effect = ModelCallError("narrator", 1, RuntimeError("narrator boom"))
        runner.run(actor="hero", action="I look around", channel="public")
        states = _lifecycle_events(log)
        assert "committed" not in states

    def test_failed_audience_all_present(self):
        runner, log = _make_runner(_NO_STAKES_ADJ)
        runner._adjudicator = MagicMock()
        runner._adjudicator.evaluate.side_effect = ModelCallError("adj", 1, RuntimeError("boom"))
        runner.run(actor="hero", action="I do something", channel="public")
        pairs = [
            (e.content, tuple(e.audience or []))
            for e in log.all()
            if e.type == "action_lifecycle"
        ]
        failed = [a for s, a in pairs if s == "failed"]
        assert failed
        assert "hero" in failed[0]
        assert "gm" in failed[0]


# --------------------------------------------------------------------------- #
# BeatResult default lifecycle_state                                            #
# --------------------------------------------------------------------------- #

class TestBeatResultLifecycleDefault:

    def test_default_lifecycle_state(self):
        result = BeatResult(
            actor="hero", action="act", channel="public",
            had_stakes=False, stakes_reasoning="", resolution=None,
            narration="", narration_event_id="", committed_fact_count=0,
        )
        assert result.lifecycle_state == ActionLifecycleState.COMMITTED


# --------------------------------------------------------------------------- #
# render_event skips action_lifecycle                                           #
# --------------------------------------------------------------------------- #

class TestRenderEventLifecycle:

    def _make_event(self, state: str) -> ProjectedEvent:
        return ProjectedEvent(
            sequence=0, id="e1", timestamp="2026-06-19T00:00:00",
            author="gm", channel="system",
            type="action_lifecycle", content=state,
            visibility="content",
        )

    def test_submitted_returns_none(self):
        assert render_event(self._make_event("submitted")) is None

    def test_committed_returns_none(self):
        assert render_event(self._make_event("committed")) is None

    def test_validating_returns_none(self):
        assert render_event(self._make_event("validating")) is None

    def test_failed_returns_none(self):
        assert render_event(self._make_event("failed")) is None

    def test_aborted_returns_none(self):
        assert render_event(self._make_event("aborted")) is None
