"""Phase 22 golden transcript suite.

End-to-end regression tests that run the full deterministic engine stack with
mocked model responses and seeded dice. These are the primary regression guard:
any refactor that changes what events are appended, what facts are committed,
what effects land, or what each POV is entitled to see will be caught here.

What is fixed (golden):
  - Event types in order (full log and per-POV belief store)
  - Committed fact subject / predicate / value
  - World state after typed effects (stress, truths, edge)
  - Audience membership on each event class
  - BeatResult fields (actor, channel, had_stakes, lifecycle_state)

What is NOT fixed (intentionally flexible):
  - Event IDs and timestamps (non-deterministic)
  - Exact narration prose (model is mocked but text is arbitrary)
  - Specific dice band when the outcome varies by seed — we check band is valid

All model calls are mocked; no API key required.
"""
from __future__ import annotations

import random
import tempfile
from unittest.mock import MagicMock

import pytest

from fable_table_engine.access import CommitPipeline
from fable_table_engine.beat import BeatRunner, ActionLifecycleState
from fable_table_engine.character_sheet import CharacterSheet
from fable_table_engine.context import ContextAssembler
from fable_table_engine.dice import DiceService
from fable_table_engine.effects import EffectExecutor, EFFECT_EVENT_TYPE, STRESS_CAP
from fable_table_engine.event_log import EventLog
from fable_table_engine.gm import AdjudicatorGM, NarratorGM
from fable_table_engine.perception import Scene
from fable_table_engine.provider import ModelGateway, TelemetrySink
from fable_table_engine.rules import Band, RulesEngine
from fable_table_engine.world_state import WorldState, Entity


# --------------------------------------------------------------------------- #
# Helpers                                                                        #
# --------------------------------------------------------------------------- #

def _gateway(response):
    client = MagicMock()
    client.messages.create = MagicMock(return_value=response)
    return ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)


def _tool_response(name: str, data: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = data
    resp = MagicMock()
    resp.content = [block]
    return resp


def _text_response(text: str = "You act decisively."):
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _no_stakes(**extra) -> dict:
    base = {
        "has_stakes": False,
        "reasoning": "no conflict here",
        "action_domain": "social",
        "skill": None, "tn": None,
        "declared_facts": [],
        "exposure": 0,
        "effect": "standard",
        "consequence_palette": {},
        "triumph_effects": [],
        "trade_options": [],
        "trade_default": "Balanced",
        "edge_label": None,
        "seam": False,
        "narrative_hint": "ok",
    }
    base.update(extra)
    return base


def _with_stakes(**extra) -> dict:
    base = {
        "has_stakes": True,
        "reasoning": "real risk here",
        "action_domain": "action",
        "skill": "Physique",
        "tn": 10,
        "declared_facts": [],
        "exposure": 1,
        "effect": "standard",
        "consequence_palette": {
            "triumph": [{"kind": "apply_stress", "entity_id": "hero", "amount": 1}],
            "success": [{"kind": "apply_stress", "entity_id": "hero", "amount": 1}],
            "cost":    [{"kind": "apply_stress", "entity_id": "hero", "amount": 1}],
            "setback": [{"kind": "apply_stress", "entity_id": "hero", "amount": 1}],
        },
        "triumph_effects": [],
        "trade_options": ["Balanced"],
        "trade_default": "Balanced",
        "edge_label": None,
        "seam": False,
        "narrative_hint": "ok",
    }
    base.update(extra)
    return base


class _Engine:
    """Wired in-memory engine for golden transcript tests."""

    def __init__(
        self,
        adj_data: dict,
        narr_text: str = "You act.",
        seed: int = 0,
        player_id: str = "hero",
    ) -> None:
        self.player_id = player_id
        self.log = EventLog()
        self.world = WorldState()
        self.world.add_zone("hall")
        self.world.add_entity(Entity(id=player_id, kind="pc", name="Hero"))
        self.world.place(player_id, "hall")

        pipeline = CommitPipeline(self.log)
        dice = DiceService(self.log, rng=random.Random(seed))
        rules = RulesEngine(self.log, dice)
        self.executor = EffectExecutor(self.log, self.world, pipeline)
        self.assembler = ContextAssembler(self.log, Scene(self.world))

        adj_resp = _tool_response("adjudicate_action", adj_data)
        narr_resp = _text_response(narr_text)
        adj = AdjudicatorGM(_gateway(adj_resp))
        narr = NarratorGM(_gateway(narr_resp))

        self.runner = BeatRunner(
            log=self.log,
            world=self.world,
            pipeline=pipeline,
            rules=rules,
            assembler=self.assembler,
            adjudicator=adj,
            narrator=narr,
            sheets={player_id: CharacterSheet(entity_id=player_id, concept="Fighter")},
            executor=self.executor,
        )

    def run(self, action: str = "look around", **kwargs):
        return self.runner.run(self.player_id, action, **kwargs)

    def all_events(self):
        return self.log.all()

    def player_events(self):
        store = self.assembler.belief_store(self.player_id)
        return list(store.events)

    def gm_events(self):
        store = self.assembler.belief_store("gm")
        return list(store.events)

    def event_types(self, events=None):
        if events is None:
            events = self.all_events()
        return [e.type for e in events]

    def lifecycle_contents(self, events=None):
        if events is None:
            events = self.all_events()
        return [e.content for e in events if e.type == "action_lifecycle"]


# --------------------------------------------------------------------------- #
# Stakeless beat                                                                 #
# --------------------------------------------------------------------------- #

class TestStakelessBeat:

    @pytest.fixture
    def engine(self):
        return _Engine(_no_stakes())

    def test_beat_result_had_stakes_false(self, engine):
        result = engine.run()
        assert result.had_stakes is False

    def test_beat_result_actor(self, engine):
        result = engine.run()
        assert result.actor == "hero"

    def test_beat_result_channel(self, engine):
        result = engine.run()
        assert result.channel == "public"

    def test_beat_result_lifecycle_resolved(self, engine):
        result = engine.run()
        assert result.lifecycle_state == ActionLifecycleState.COMMITTED

    def test_beat_not_aborted(self, engine):
        result = engine.run()
        assert result.beat_aborted is False

    def test_lifecycle_sequence_submitted_then_committed(self, engine):
        engine.run()
        lc = engine.lifecycle_contents()
        assert lc[0] == ActionLifecycleState.SUBMITTED.value
        assert lc[-1] == ActionLifecycleState.COMMITTED.value

    def test_applying_effects_fires(self, engine):
        engine.run()
        lc = engine.lifecycle_contents()
        assert ActionLifecycleState.APPLYING_EFFECTS.value in lc

    def test_narration_event_in_log(self, engine):
        engine.run()
        assert "narration" in engine.event_types()

    def test_no_dice_roll_event(self, engine):
        engine.run()
        assert "dice_roll" not in engine.event_types()

    def test_player_sees_submitted_lifecycle(self, engine):
        engine.run()
        player_types = engine.event_types(engine.player_events())
        assert "action_lifecycle" in player_types
        submitted = [
            e for e in engine.player_events()
            if e.type == "action_lifecycle" and e.content == ActionLifecycleState.SUBMITTED.value
        ]
        assert len(submitted) == 1

    def test_player_sees_narration(self, engine):
        engine.run()
        player_types = engine.event_types(engine.player_events())
        assert "narration" in player_types

    def test_player_does_not_see_gm_lifecycle(self, engine):
        engine.run()
        player_events = engine.player_events()
        gm_only_lc = [
            e for e in player_events
            if e.type == "action_lifecycle"
            and e.content == ActionLifecycleState.ADJUDICATING.value
        ]
        assert gm_only_lc == []

    def test_gm_sees_all_lifecycle_states(self, engine):
        engine.run()
        gm_lc = engine.lifecycle_contents(engine.gm_events())
        for state_value in [
            ActionLifecycleState.SUBMITTED.value,
            ActionLifecycleState.VALIDATING.value,
            ActionLifecycleState.ADJUDICATING.value,
            ActionLifecycleState.APPLYING_EFFECTS.value,
            ActionLifecycleState.NARRATING.value,
            ActionLifecycleState.COMMITTED.value,
        ]:
            assert state_value in gm_lc, f"GM missing lifecycle: {state_value}"

    def test_gm_sees_narration(self, engine):
        engine.run()
        assert "narration" in engine.event_types(engine.gm_events())

    def test_narration_text_in_player_store(self, engine):
        engine.run("scout the room", )
        store = engine.assembler.belief_store("hero")
        narrations = [e for e in store.events if e.type == "narration"]
        assert len(narrations) == 1
        assert narrations[0].content == "You act."

    def test_world_beat_counter_increments(self, engine):
        assert engine.world.beat_index == 0
        engine.run()
        assert engine.world.beat_index == 1


# --------------------------------------------------------------------------- #
# Stakes beat (with dice)                                                        #
# --------------------------------------------------------------------------- #

class TestStakesBeat:

    @pytest.fixture
    def engine(self):
        return _Engine(_with_stakes(), seed=7)

    def test_beat_result_had_stakes_true(self, engine):
        result = engine.run()
        assert result.had_stakes is True

    def test_dice_roll_event_emitted(self, engine):
        engine.run()
        assert "dice_roll" in engine.event_types()

    def test_resolution_event_emitted(self, engine):
        engine.run()
        assert "resolution" in engine.event_types()

    def test_beat_result_resolution_not_none(self, engine):
        result = engine.run()
        assert result.resolution is not None

    def test_beat_result_resolution_band_is_valid(self, engine):
        result = engine.run()
        assert result.resolution.band in Band

    def test_rolling_lifecycle_fires(self, engine):
        engine.run()
        lc = engine.lifecycle_contents()
        assert ActionLifecycleState.ROLLING.value in lc

    def test_dice_roll_audience_includes_player(self, engine):
        engine.run()
        roll_events = [e for e in engine.all_events() if e.type == "dice_roll"]
        assert len(roll_events) >= 1
        assert "hero" in roll_events[0].audience

    def test_dice_roll_audience_includes_gm(self, engine):
        engine.run()
        roll_events = [e for e in engine.all_events() if e.type == "dice_roll"]
        assert "gm" in roll_events[0].audience

    def test_effect_applied_for_stress(self, engine):
        """All bands in consequence_palette apply 1 stress; effect must land."""
        engine.run()
        effect_events = [e for e in engine.all_events() if e.type == EFFECT_EVENT_TYPE]
        assert len(effect_events) >= 1

    def test_stress_on_hero_after_beat(self, engine):
        """All bands apply stress — hero stress must be 1 after the beat."""
        engine.run()
        hero = engine.world.get_entity("hero")
        assert hero.resources.get("stress", 0) == 1

    def test_narration_in_log(self, engine):
        engine.run()
        assert "narration" in engine.event_types()


# --------------------------------------------------------------------------- #
# Fact commits                                                                   #
# --------------------------------------------------------------------------- #

class TestFactCommit:

    def _engine_with_fact(self, subject, predicate, value):
        data = _no_stakes(declared_facts=[
            {"subject": subject, "predicate": predicate, "value": value, "revealed": True}
        ])
        return _Engine(data)

    def test_committed_fact_in_player_belief_store(self):
        engine = self._engine_with_fact("hero", "location", "hall")
        engine.run()
        store = engine.assembler.belief_store("hero")
        assert store.value_of("hero", "location") == "hall"

    def test_committed_fact_in_gm_belief_store(self):
        engine = self._engine_with_fact("hero", "location", "hall")
        engine.run()
        store = engine.assembler.belief_store("gm")
        assert store.value_of("hero", "location") == "hall"

    def test_committed_fact_subject(self):
        engine = self._engine_with_fact("target", "status", "wounded")
        engine.run()
        store = engine.assembler.belief_store("hero")
        assert store.value_of("target", "status") == "wounded"

    def test_multiple_facts_all_committed(self):
        data = _no_stakes(declared_facts=[
            {"subject": "hero", "predicate": "condition", "value": "alert", "revealed": True},
            {"subject": "door", "predicate": "state", "value": "open", "revealed": True},
        ])
        engine = _Engine(data)
        engine.run()
        store = engine.assembler.belief_store("hero")
        assert store.value_of("hero", "condition") == "alert"
        assert store.value_of("door", "state") == "open"

    def test_fact_from_second_beat_accumulates(self):
        """Facts committed across beats are all visible to the player."""
        data1 = _no_stakes(declared_facts=[
            {"subject": "hero", "predicate": "location", "value": "hall", "revealed": True}
        ])
        data2 = _no_stakes(declared_facts=[
            {"subject": "hero", "predicate": "mood", "value": "tense", "revealed": True}
        ])

        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        rules = RulesEngine(log, dice)
        executor = EffectExecutor(log, world, pipeline)
        assembler = ContextAssembler(log, Scene(world))
        sheets = {"hero": CharacterSheet(entity_id="hero", concept="Fighter")}

        def _make_runner(adj_data):
            adj = AdjudicatorGM(_gateway(_tool_response("adjudicate_action", adj_data)))
            narr = NarratorGM(_gateway(_text_response()))
            return BeatRunner(
                log=log, world=world, pipeline=pipeline, rules=rules,
                assembler=assembler, adjudicator=adj, narrator=narr,
                sheets=sheets, executor=executor,
            )

        _make_runner(data1).run("hero", "move forward")
        _make_runner(data2).run("hero", "pause and think")

        store = assembler.belief_store("hero")
        assert store.value_of("hero", "location") == "hall"
        assert store.value_of("hero", "mood") == "tense"


# --------------------------------------------------------------------------- #
# Effect application (world state)                                               #
# --------------------------------------------------------------------------- #

class TestEffectApplication:
    # seed=0: rolls=[4,4,1] → total=9 vs TN=10 → Cost → fires consequence_palette["cost"]

    def test_apply_stress_increments_hero_stress(self):
        """A Cost outcome applies stress from the cost palette."""
        engine = _Engine(_with_stakes(), seed=0)
        assert engine.world.get_entity("hero").resources.get("stress", 0) == 0
        engine.run()
        assert engine.world.get_entity("hero").resources.get("stress", 0) == 1

    def test_effect_event_type_in_log(self):
        engine = _Engine(_with_stakes(), seed=0)
        engine.run()
        assert EFFECT_EVENT_TYPE in engine.event_types()

    def test_effect_event_audience_includes_hero(self):
        engine = _Engine(_with_stakes(), seed=0)
        engine.run()
        effects = [e for e in engine.all_events() if e.type == EFFECT_EVENT_TYPE]
        assert all("hero" in e.audience for e in effects)

    def test_effect_event_audience_includes_gm(self):
        engine = _Engine(_with_stakes(), seed=0)
        engine.run()
        effects = [e for e in engine.all_events() if e.type == EFFECT_EVENT_TYPE]
        assert all("gm" in e.audience for e in effects)

    def test_stress_overflow_rejected_without_scar_type(self):
        """apply_stress without overflow_scar_type is rejected when stress is at cap.

        The effect must declare an overflow_scar_type to use the scar route;
        without it the executor rejects the effect and stress stays at STRESS_CAP.
        """
        engine = _Engine(_with_stakes(), seed=0)
        # Pre-fill to cap.
        hero = engine.world.get_entity("hero")
        from dataclasses import replace as _replace
        engine.world.update_entity(_replace(hero, resources={**hero.resources, "stress": STRESS_CAP}))
        # Run beat — Cost palette fires apply_stress (no overflow_scar_type set).
        engine.run()
        # Effect rejected → stress unchanged at STRESS_CAP.
        hero_after = engine.world.get_entity("hero")
        assert hero_after.resources.get("stress", 0) == STRESS_CAP


# --------------------------------------------------------------------------- #
# Audience separation (secrecy invariant)                                        #
# --------------------------------------------------------------------------- #

class TestAudienceSeparation:

    def test_gm_internal_lifecycle_absent_from_player_store(self):
        engine = _Engine(_no_stakes())
        engine.run()
        player_events = engine.player_events()
        gm_internal = [
            e for e in player_events
            if e.type == "action_lifecycle"
            and e.content in {
                ActionLifecycleState.VALIDATING.value,
                ActionLifecycleState.ADJUDICATING.value,
                ActionLifecycleState.APPLYING_EFFECTS.value,
                ActionLifecycleState.NARRATING.value,
            }
        ]
        assert gm_internal == [], \
            f"Player store contains GM-internal lifecycle events: {[e.content for e in gm_internal]}"

    def test_player_store_contains_only_entitled_events(self):
        """Every event projected to the player is one the player was entitled to see.

        ProjectedEvent doesn't expose audience (by design), so we cross-reference
        event IDs against the raw log where audience is available.
        """
        engine = _Engine(_no_stakes())
        engine.run()
        raw_by_id = {e.id: e for e in engine.all_events()}
        for pe in engine.player_events():
            raw = raw_by_id[pe.id]
            assert "hero" in raw.audience, \
                f"Player store contains event with wrong audience: {pe.type} {raw.audience}"

    def test_dice_roll_visible_to_actor_in_public_beat(self):
        engine = _Engine(_with_stakes(), seed=5)
        engine.run()
        player_dice = [e for e in engine.player_events() if e.type == "dice_roll"]
        assert len(player_dice) >= 1

    def test_gm_sees_more_events_than_player(self):
        engine = _Engine(_no_stakes())
        engine.run()
        assert len(engine.gm_events()) > len(engine.player_events())


# --------------------------------------------------------------------------- #
# OOC bypass                                                                     #
# --------------------------------------------------------------------------- #

class TestOOCBypass:

    def test_ooc_event_emitted(self):
        engine = _Engine(_no_stakes())
        engine.run("//asking a rules question", channel="ooc")
        assert "ooc" in engine.event_types()

    def test_no_narration_on_ooc(self):
        engine = _Engine(_no_stakes())
        engine.run("//ooc comment", channel="ooc")
        assert "narration" not in engine.event_types()

    def test_no_dice_roll_on_ooc(self):
        engine = _Engine(_no_stakes())
        engine.run("//ooc query", channel="ooc")
        assert "dice_roll" not in engine.event_types()

    def test_beat_result_channel_ooc(self):
        engine = _Engine(_no_stakes())
        result = engine.run("//testing", channel="ooc")
        assert result.channel == "ooc"

    def test_ooc_lifecycle_is_submitted_then_committed(self):
        engine = _Engine(_no_stakes())
        engine.run("//meta question", channel="ooc")
        lc = engine.lifecycle_contents()
        assert lc[0] == ActionLifecycleState.SUBMITTED.value
        assert lc[-1] == ActionLifecycleState.COMMITTED.value
        assert len(lc) == 2


# --------------------------------------------------------------------------- #
# Multi-beat sequence                                                            #
# --------------------------------------------------------------------------- #

class TestMultiBeatSequence:

    def test_two_beats_accumulate_events(self):
        engine = _Engine(_no_stakes())
        engine.run("first action")
        engine.run("second action")
        narrations = [e for e in engine.all_events() if e.type == "narration"]
        assert len(narrations) == 2

    def test_beat_counter_increments_each_beat(self):
        engine = _Engine(_no_stakes())
        assert engine.world.beat_index == 0
        engine.run()
        assert engine.world.beat_index == 1
        engine.run()
        assert engine.world.beat_index == 2

    def test_player_sees_both_narrations(self):
        engine = _Engine(_no_stakes())
        engine.run()
        engine.run()
        player_narrations = [e for e in engine.player_events() if e.type == "narration"]
        assert len(player_narrations) == 2

    def test_facts_from_both_beats_visible(self):
        """Facts from two separate beats both land in the player's belief store.

        Note: committed facts are immutable (canon ledger); we use distinct
        (subject, predicate) pairs so neither beat conflicts with the other.
        """
        data1 = _no_stakes(declared_facts=[
            {"subject": "door", "predicate": "state", "value": "locked", "revealed": True}
        ])
        data2 = _no_stakes(declared_facts=[
            {"subject": "hero", "predicate": "mood", "value": "resolute", "revealed": True}
        ])

        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        rules = RulesEngine(log, dice)
        executor = EffectExecutor(log, world, pipeline)
        assembler = ContextAssembler(log, Scene(world))
        sheets = {"hero": CharacterSheet(entity_id="hero", concept="Fighter")}

        def _runner(adj_data):
            return BeatRunner(
                log=log, world=world, pipeline=pipeline, rules=rules,
                assembler=assembler,
                adjudicator=AdjudicatorGM(_gateway(_tool_response("adjudicate_action", adj_data))),
                narrator=NarratorGM(_gateway(_text_response())),
                sheets=sheets, executor=executor,
            )

        _runner(data1).run("hero", "try the door")
        _runner(data2).run("hero", "steel yourself")

        store = assembler.belief_store("hero")
        assert store.value_of("door", "state") == "locked"
        assert store.value_of("hero", "mood") == "resolute"

    def test_stress_accumulates_across_beats(self):
        engine = _Engine(_with_stakes(), seed=1)
        engine.run()
        stress_after_1 = engine.world.get_entity("hero").resources.get("stress", 0)
        assert stress_after_1 == 1
        engine.run()
        stress_after_2 = engine.world.get_entity("hero").resources.get("stress", 0)
        assert stress_after_2 == 2


# --------------------------------------------------------------------------- #
# SQLite round-trip (persistence golden)                                         #
# --------------------------------------------------------------------------- #

class TestSQLiteRoundTrip:

    def test_events_survive_close_and_reopen(self):
        from fable_table_engine.persistence import open_session
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/session.db"
            log, world, scene = open_session(db)
            world.add_zone("hall")
            world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
            world.place("hero", "hall")
            pipeline = CommitPipeline(log)
            dice = DiceService(log, rng=random.Random(0))
            rules = RulesEngine(log, dice)
            executor = EffectExecutor(log, world, pipeline)
            assembler = ContextAssembler(log, scene)
            adj = AdjudicatorGM(_gateway(_tool_response("adjudicate_action", _no_stakes())))
            narr = NarratorGM(_gateway(_text_response()))
            runner = BeatRunner(
                log=log, world=world, pipeline=pipeline, rules=rules,
                assembler=assembler, adjudicator=adj, narrator=narr,
                sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
                executor=executor,
            )
            runner.run("hero", "look around")
            event_count = len(log.all())
            log.close()

            log2, world2, scene2 = open_session(db)
            assert len(log2.all()) == event_count
            narrations = [e for e in log2.all() if e.type == "narration"]
            assert len(narrations) == 1
            log2.close()

    def test_world_state_survives_round_trip(self):
        from fable_table_engine.persistence import open_session
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/session.db"
            log, world, scene = open_session(db)
            world.add_zone("hall")
            world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
            world.place("hero", "hall")
            pipeline = CommitPipeline(log)
            dice = DiceService(log, rng=random.Random(0))
            rules = RulesEngine(log, dice)
            executor = EffectExecutor(log, world, pipeline)
            assembler = ContextAssembler(log, scene)
            adj = AdjudicatorGM(_gateway(_tool_response("adjudicate_action", _no_stakes())))
            narr = NarratorGM(_gateway(_text_response()))
            runner = BeatRunner(
                log=log, world=world, pipeline=pipeline, rules=rules,
                assembler=assembler, adjudicator=adj, narrator=narr,
                sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
                executor=executor,
            )
            runner.run("hero", "look around")
            beat_after = world.beat_index
            log.close()

            log2, world2, scene2 = open_session(db)
            assert world2.beat_index == beat_after
            log2.close()
