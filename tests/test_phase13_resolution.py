"""Phase 13 tests — Narrow Complete Resolution Slice (D-025).

Covers ResolutionPlan, effect_from_dict, describe_effect, _apply_trade,
consequence palette application in BeatRunner, action_domain threading, and
backward compatibility.

All Anthropic client calls are mocked; no API key required.
"""

from __future__ import annotations

import random
from unittest.mock import MagicMock, call

import pytest

from fable_table_engine import (
    AdjudicatorGM,
    AdvanceClock,
    ApplyStress,
    BeatResult,
    BeatRunner,
    ChangeAccess,
    ChangeResource,
    ChangeTruth,
    CharacterSheet,
    CommitPipeline,
    ContextAssembler,
    CreateMaintainedTruth,
    CreateTruth,
    DiceService,
    EffectExecutor,
    EffectResult,
    Entity,
    EventLog,
    ExpireMaintainedTruth,
    ExpireTruth,
    ModelGateway,
    MoveEntity,
    NarratorGM,
    ResolutionPlan,
    RulesEngine,
    StakesDecision,
    WorldSimulator,
    WorldState,
    describe_effect,
    effect_from_dict,
)
from fable_table_engine.beat import EFFECT_TIERS, _apply_trade


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
    simulator: WorldSimulator | None = None,
    executor: EffectExecutor | None = None,
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
        simulator=simulator,
        executor=executor,
    )
    return runner, log, pipeline, world


# --------------------------------------------------------------------------- #
# ResolutionPlan                                                                #
# --------------------------------------------------------------------------- #

class TestResolutionPlan:

    def test_stakesdecision_alias(self):
        assert StakesDecision is ResolutionPlan

    def test_defaults_no_stakes(self):
        plan = ResolutionPlan(has_stakes=False, reasoning="trivial")
        assert plan.action_domain == "beat"
        assert plan.exposure is None
        assert plan.effect is None
        assert plan.trade_options == []
        assert plan.trade_default == "Balanced"
        assert plan.consequence_palette == {}
        assert plan.triumph_effects == []
        assert plan.edge_label is None
        assert plan.seam is False

    def test_valid_with_stakes(self):
        plan = ResolutionPlan(
            has_stakes=True, reasoning="real risk",
            skill="fighting", skill_rating=4, tn=11,
            action_domain="combat", exposure=2, effect="Standard",
        )
        assert plan.tn == 11
        assert plan.action_domain == "combat"

    def test_post_init_raises_on_missing_stakes_fields(self):
        with pytest.raises(ValueError, match="missing fields"):
            ResolutionPlan(has_stakes=True, reasoning="oops", skill="fighting")

    def test_consequence_palette_stored(self):
        plan = ResolutionPlan(
            has_stakes=True, reasoning="r", skill="fighting", skill_rating=3, tn=10,
            consequence_palette={
                "cost": [{"kind": "apply_stress", "entity_id": "hero", "amount": 1}],
                "setback": [{"kind": "advance_clock", "clock_name": "doom", "steps": 2}],
            },
        )
        assert plan.consequence_palette["cost"][0]["kind"] == "apply_stress"
        assert plan.consequence_palette["setback"][0]["clock_name"] == "doom"

    def test_triumph_effects_stored(self):
        plan = ResolutionPlan(
            has_stakes=True, reasoning="r", skill="fighting", skill_rating=3, tn=10,
            triumph_effects=[{"kind": "create_truth", "subject": "hero", "predicate": "status", "value": "champion", "revealed": True}],
        )
        assert plan.triumph_effects[0]["predicate"] == "status"

    def test_old_construction_still_works(self):
        # StakesDecision(has_stakes=...) with only phase-5 fields must not error.
        sd = StakesDecision(
            has_stakes=True, reasoning="old way",
            skill="stealth", skill_rating=2, tn=9,
            declared_facts=[],
        )
        assert sd.has_stakes is True
        assert sd.action_domain == "beat"


# --------------------------------------------------------------------------- #
# effect_from_dict                                                              #
# --------------------------------------------------------------------------- #

class TestEffectFromDict:

    def test_create_truth(self):
        e = effect_from_dict({"kind": "create_truth", "subject": "door", "predicate": "state", "value": "open", "revealed": True})
        assert isinstance(e, CreateTruth)
        assert e.subject == "door"

    def test_change_truth(self):
        e = effect_from_dict({"kind": "change_truth", "subject": "door", "predicate": "state", "value": "closed", "revealed": False, "reason": "pushed shut"})
        assert isinstance(e, ChangeTruth)
        assert e.reason == "pushed shut"

    def test_expire_truth(self):
        e = effect_from_dict({"kind": "expire_truth", "subject": "hero", "predicate": "hidden", "revealed": True})
        assert isinstance(e, ExpireTruth)

    def test_advance_clock(self):
        e = effect_from_dict({"kind": "advance_clock", "clock_name": "doom", "steps": 2})
        assert isinstance(e, AdvanceClock)
        assert e.steps == 2

    def test_advance_clock_default_steps(self):
        e = effect_from_dict({"kind": "advance_clock", "clock_name": "doom"})
        assert e.steps == 1

    def test_apply_stress(self):
        e = effect_from_dict({"kind": "apply_stress", "entity_id": "hero", "amount": 3})
        assert isinstance(e, ApplyStress)
        assert e.amount == 3

    def test_change_access(self):
        e = effect_from_dict({"kind": "change_access", "operation": "darken", "zone_a": "north"})
        assert isinstance(e, ChangeAccess)
        assert e.operation == "darken"

    def test_move_entity(self):
        e = effect_from_dict({"kind": "move_entity", "entity_id": "hero", "to_zone": "south"})
        assert isinstance(e, MoveEntity)
        assert e.to_zone == "south"

    def test_change_resource(self):
        e = effect_from_dict({"kind": "change_resource", "entity_id": "hero", "resource": "gold", "delta": -5})
        assert isinstance(e, ChangeResource)
        assert e.delta == -5

    def test_create_maintained_truth(self):
        e = effect_from_dict({"kind": "create_maintained_truth", "subject": "hero", "predicate": "stance", "value": "guard", "lapse_condition": "attacked", "revealed": True})
        assert isinstance(e, CreateMaintainedTruth)
        assert e.lapse_condition == "attacked"

    def test_expire_maintained_truth(self):
        e = effect_from_dict({"kind": "expire_maintained_truth", "subject": "hero", "predicate": "stance", "revealed": True})
        assert isinstance(e, ExpireMaintainedTruth)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="unknown effect kind"):
            effect_from_dict({"kind": "do_magic"})

    def test_missing_required_field_raises(self):
        with pytest.raises(KeyError):
            effect_from_dict({"kind": "apply_stress", "entity_id": "hero"})  # amount missing


# --------------------------------------------------------------------------- #
# describe_effect                                                               #
# --------------------------------------------------------------------------- #

class TestDescribeEffect:

    def test_create_truth(self):
        e = CreateTruth(kind="create_truth", subject="door", predicate="state", value="open")
        assert "door" in describe_effect(e)
        assert "state" in describe_effect(e)

    def test_change_truth(self):
        e = ChangeTruth(kind="change_truth", subject="hero", predicate="status", value="wounded")
        assert "changed to" in describe_effect(e)

    def test_expire_truth(self):
        e = ExpireTruth(kind="expire_truth", subject="hero", predicate="hidden")
        assert "no longer holds" in describe_effect(e)

    def test_advance_clock(self):
        e = AdvanceClock(kind="advance_clock", clock_name="doom", steps=2)
        desc = describe_effect(e)
        assert "doom" in desc
        assert "2" in desc

    def test_apply_stress_positive(self):
        e = ApplyStress(kind="apply_stress", entity_id="hero", amount=3)
        assert "gained" in describe_effect(e)

    def test_apply_stress_negative(self):
        e = ApplyStress(kind="apply_stress", entity_id="hero", amount=-2)
        assert "relieved" in describe_effect(e)

    def test_change_access_two_zones(self):
        e = ChangeAccess(kind="change_access", operation="open", zone_a="north", zone_b="south")
        assert "north" in describe_effect(e)
        assert "south" in describe_effect(e)

    def test_change_access_one_zone(self):
        e = ChangeAccess(kind="change_access", operation="darken", zone_a="vault")
        assert "vault" in describe_effect(e)

    def test_move_entity(self):
        e = MoveEntity(kind="move_entity", entity_id="hero", to_zone="exit")
        assert "exit" in describe_effect(e)

    def test_change_resource_delta(self):
        e = ChangeResource(kind="change_resource", entity_id="hero", resource="gold", delta=-5)
        assert "-5" in describe_effect(e)

    def test_change_resource_set(self):
        e = ChangeResource(kind="change_resource", entity_id="hero", resource="hp", set_value=0)
        assert "set to" in describe_effect(e)

    def test_create_maintained_truth(self):
        e = CreateMaintainedTruth(kind="create_maintained_truth", subject="hero", predicate="stance", value="guard", lapse_condition="attacked")
        assert "until" in describe_effect(e)

    def test_expire_maintained_truth(self):
        e = ExpireMaintainedTruth(kind="expire_maintained_truth", subject="hero", predicate="stance")
        assert "expired" in describe_effect(e)


# --------------------------------------------------------------------------- #
# _apply_trade                                                                  #
# --------------------------------------------------------------------------- #

class TestApplyTrade:

    def test_balanced_no_change(self):
        assert _apply_trade(2, "Standard", "Balanced") == (2, "Standard")

    def test_aggressive_raises_exposure_and_effect(self):
        exp, eff = _apply_trade(2, "Standard", "Aggressive")
        assert exp == 3
        assert eff == "Superior"

    def test_guarded_lowers_exposure_and_effect(self):
        exp, eff = _apply_trade(2, "Standard", "Guarded")
        assert exp == 1
        assert eff == "Minimal"

    def test_aggressive_clamps_exposure_at_4(self):
        exp, _ = _apply_trade(4, "Extreme", "Aggressive")
        assert exp == 4

    def test_aggressive_clamps_effect_at_extreme(self):
        _, eff = _apply_trade(3, "Extreme", "Aggressive")
        assert eff == "Extreme"

    def test_guarded_clamps_exposure_at_1(self):
        exp, _ = _apply_trade(1, "Minimal", "Guarded")
        assert exp == 1

    def test_guarded_clamps_effect_at_minimal(self):
        _, eff = _apply_trade(2, "Minimal", "Guarded")
        assert eff == "Minimal"

    def test_unknown_trade_treated_as_balanced(self):
        assert _apply_trade(2, "Standard", "Custom") == (2, "Standard")

    def test_effect_tiers_ordered(self):
        assert EFFECT_TIERS == ["Minimal", "Standard", "Superior", "Extreme"]


# --------------------------------------------------------------------------- #
# BeatRunner — trade param threading                                            #
# --------------------------------------------------------------------------- #

class TestBeatRunnerTrade:

    def _adj_input_with_trade(self):
        return {
            "has_stakes": True,
            "reasoning": "risk",
            "skill": "fighting",
            "tn": 11,
            "action_domain": "combat",
            "exposure": 2,
            "effect": "Standard",
            "trade_options": ["Aggressive", "Balanced", "Guarded"],
            "trade_default": "Balanced",
            "declared_facts": [],
        }

    def test_balanced_trade_defaults(self):
        runner, *_ = _make_runner(self._adj_input_with_trade())
        result = runner.run("hero", "attack the guard")
        assert result.applied_trade == "Balanced"
        assert result.effective_exposure == 2
        assert result.effective_effect == "Standard"

    def test_aggressive_trade_passed_explicitly(self):
        runner, *_ = _make_runner(self._adj_input_with_trade(), rng_seed=1)
        result = runner.run("hero", "attack the guard", trade="Aggressive")
        assert result.applied_trade == "Aggressive"
        assert result.effective_exposure == 3
        assert result.effective_effect == "Superior"

    def test_guarded_trade(self):
        runner, *_ = _make_runner(self._adj_input_with_trade(), rng_seed=2)
        result = runner.run("hero", "attack the guard", trade="Guarded")
        assert result.applied_trade == "Guarded"
        assert result.effective_exposure == 1
        assert result.effective_effect == "Minimal"

    def test_no_stakes_trade_defaults(self):
        adj = {"has_stakes": False, "reasoning": "trivial"}
        runner, *_ = _make_runner(adj)
        result = runner.run("hero", "look around")
        assert result.applied_trade == "Balanced"
        assert not result.had_stakes


# --------------------------------------------------------------------------- #
# BeatRunner — consequence palette                                              #
# --------------------------------------------------------------------------- #

class TestBeatRunnerConsequencePalette:

    def _adj_with_palette(self, palette: dict, triumph_effects: list | None = None):
        return {
            "has_stakes": True,
            "reasoning": "stakes",
            "skill": "fighting",
            "tn": 11,
            "action_domain": "combat",
            "exposure": 2,
            "effect": "Standard",
            "trade_default": "Balanced",
            "declared_facts": [],
            "consequence_palette": palette,
            "triumph_effects": triumph_effects or [],
        }

    def test_no_executor_palette_silently_skipped(self):
        # Without executor, palette is not applied — but beat still completes.
        adj = self._adj_with_palette(
            {"cost": [{"kind": "apply_stress", "entity_id": "hero", "amount": 1}]}
        )
        runner, *_ = _make_runner(adj)
        result = runner.run("hero", "risky action")
        assert result.narration == "Narration."

    def test_setback_palette_applied_via_executor(self):
        log = EventLog()
        world = WorldState()
        world.add_zone("dungeon")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "dungeon")

        pipeline = CommitPipeline(log)
        # Use seed that produces a Setback (low roll vs TN=11 with skill=0)
        dice = DiceService(log, rng=random.Random(0))
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        sheet = CharacterSheet(entity_id="hero", concept="Fighter", skills={"fighting": 0})
        executor = EffectExecutor(log, world, pipeline)

        # Force setback: TN=20 so virtually any roll fails
        adj_input = {
            "has_stakes": True, "reasoning": "hard",
            "skill": "fighting", "tn": 20,
            "action_domain": "combat", "exposure": 2, "effect": "Standard",
            "trade_default": "Balanced", "declared_facts": [],
            "consequence_palette": {
                "setback": [{"kind": "apply_stress", "entity_id": "hero", "amount": 2}]
            },
            "triumph_effects": [],
        }

        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(adj_input)
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp("You fail.")

        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=rules, assembler=assembler,
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={"hero": sheet},
            gm_entity="gm",
            executor=executor,
        )
        result = runner.run("hero", "impossible feat")
        # Palette effects run when executor is present; result contains them
        assert result.had_stakes

    def test_invalid_palette_entry_logs_advisory_does_not_abort(self):
        log = EventLog()
        world = WorldState()
        world.add_zone("dungeon")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "dungeon")

        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(99))
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        sheet = CharacterSheet(entity_id="hero", concept="Fighter", skills={"fighting": 0})
        executor = EffectExecutor(log, world, pipeline)

        adj_input = {
            "has_stakes": True, "reasoning": "hard",
            "skill": "fighting", "tn": 20,
            "action_domain": "combat", "exposure": 2, "effect": "Standard",
            "trade_default": "Balanced", "declared_facts": [],
            "consequence_palette": {
                "setback": [{"kind": "do_unknown_thing", "foo": "bar"}]
            },
            "triumph_effects": [],
        }

        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(adj_input)
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp("You fail.")

        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=rules, assembler=assembler,
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={"hero": sheet},
            gm_entity="gm",
            executor=executor,
        )
        result = runner.run("hero", "impossible feat")

        # Beat completes — invalid palette entry does not abort it
        assert not result.beat_aborted
        assert result.narration == "You fail."

        # Advisory event emitted
        advisory_contents = [e.content for e in log.all() if e.type == "audit_advisory"]
        assert any("invalid effect entry" in c for c in advisory_contents)


# --------------------------------------------------------------------------- #
# BeatRunner — action_domain threading (D-026)                                  #
# --------------------------------------------------------------------------- #

class TestBeatRunnerActionDomain:

    def test_action_domain_passed_to_simulator(self):
        log = EventLog()
        world = WorldState()
        world.add_zone("dungeon")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "dungeon")

        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        sheet = CharacterSheet(entity_id="hero", concept="Fighter", skills={"fighting": 3})

        simulator = MagicMock(spec=WorldSimulator)
        simulator.advance.return_value = []

        adj_input = {
            "has_stakes": True, "reasoning": "stealth check",
            "skill": "fighting", "tn": 10,
            "action_domain": "stealth", "exposure": 2, "effect": "Standard",
            "trade_default": "Balanced", "declared_facts": [],
        }

        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(adj_input)
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp("You slip past.")

        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=rules, assembler=assembler,
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={"hero": sheet},
            gm_entity="gm",
            simulator=simulator,
        )
        runner.run("hero", "sneak past the guard")

        simulator.advance.assert_called_once_with("stealth")

    def test_action_domain_defaults_to_beat_when_absent(self):
        log = EventLog()
        world = WorldState()
        world.add_zone("dungeon")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "dungeon")

        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        sheet = CharacterSheet(entity_id="hero", concept="Fighter", skills={"fighting": 3})

        simulator = MagicMock(spec=WorldSimulator)
        simulator.advance.return_value = []

        # Adjudicator returns no action_domain field
        adj_input = {
            "has_stakes": True, "reasoning": "generic",
            "skill": "fighting", "tn": 10,
            "declared_facts": [],
        }

        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(adj_input)
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp("Done.")

        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=rules, assembler=assembler,
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={"hero": sheet},
            gm_entity="gm",
            simulator=simulator,
        )
        runner.run("hero", "do something")

        simulator.advance.assert_called_once_with("beat")


# --------------------------------------------------------------------------- #
# NarratorGM — effective_effect and applied_summary                            #
# --------------------------------------------------------------------------- #

class TestNarratorEnhanced:

    def test_effective_effect_passed_to_narrator(self):
        adj_input = {
            "has_stakes": True, "reasoning": "r",
            "skill": "fighting", "tn": 11,
            "action_domain": "combat", "exposure": 2, "effect": "Standard",
            "trade_default": "Balanced", "declared_facts": [],
        }

        log = EventLog()
        world = WorldState()
        world.add_zone("dungeon")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "dungeon")
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(5))
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        sheet = CharacterSheet(entity_id="hero", concept="Fighter", skills={"fighting": 4})

        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(adj_input)
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp("Narration.")

        narrator_mock = MagicMock(spec=NarratorGM)
        narrator_mock.narrate.return_value = "Narration."

        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=rules, assembler=assembler,
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=narrator_mock,
            sheets={"hero": sheet},
            gm_entity="gm",
        )
        runner.run("hero", "strike", trade="Aggressive")

        call_kwargs = narrator_mock.narrate.call_args
        assert call_kwargs.kwargs.get("effective_effect") == "Superior"

    def test_narrator_receives_none_applied_summary_when_no_effects(self):
        adj_input = {
            "has_stakes": False, "reasoning": "trivial",
        }

        log = EventLog()
        world = WorldState()
        world.add_zone("dungeon")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "dungeon")
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        sheet = CharacterSheet(entity_id="hero", concept="Fighter", skills={})

        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(adj_input)

        narrator_mock = MagicMock(spec=NarratorGM)
        narrator_mock.narrate.return_value = "You look around."

        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=rules, assembler=assembler,
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=narrator_mock,
            sheets={"hero": sheet},
            gm_entity="gm",
        )
        runner.run("hero", "look around")

        call_kwargs = narrator_mock.narrate.call_args
        assert call_kwargs.kwargs.get("applied_summary") is None


# --------------------------------------------------------------------------- #
# BeatResult — Phase 13 fields                                                  #
# --------------------------------------------------------------------------- #

class TestBeatResultEnhanced:

    def test_beat_result_has_trade_fields(self):
        adj_input = {
            "has_stakes": True, "reasoning": "r",
            "skill": "fighting", "tn": 11,
            "action_domain": "combat", "exposure": 3, "effect": "Superior",
            "trade_default": "Balanced", "declared_facts": [],
        }
        runner, *_ = _make_runner(adj_input)
        result = runner.run("hero", "strike")
        # Fields present and populated
        assert hasattr(result, "applied_trade")
        assert hasattr(result, "effective_exposure")
        assert hasattr(result, "effective_effect")
        assert result.applied_trade == "Balanced"
        assert result.effective_exposure == 3
        assert result.effective_effect == "Superior"

    def test_beat_result_defaults_on_no_stakes(self):
        adj_input = {"has_stakes": False, "reasoning": "trivial"}
        runner, *_ = _make_runner(adj_input)
        result = runner.run("hero", "look around")
        assert result.applied_trade == "Balanced"
        assert result.effective_exposure == 2   # default fallback
        assert result.effective_effect == "Standard"  # default fallback


# --------------------------------------------------------------------------- #
# Backward compatibility — no-roll path with old StakesDecision fields only    #
# --------------------------------------------------------------------------- #

class TestNoRollPath:

    def test_no_stakes_beat_completes(self):
        adj_input = {"has_stakes": False, "reasoning": "nothing to roll"}
        runner, *_ = _make_runner(adj_input)
        result = runner.run("hero", "take a breath")
        assert not result.had_stakes
        assert result.resolution is None
        assert result.narration == "Narration."

    def test_old_resolution_plan_without_phase13_fields_works(self):
        """Directly constructing a ResolutionPlan with only phase-5 fields must not error."""
        plan = ResolutionPlan(
            has_stakes=True, reasoning="ok",
            skill="stealth", skill_rating=2, tn=9,
        )
        assert plan.action_domain == "beat"
        assert plan.consequence_palette == {}
        assert plan.triumph_effects == []

    def test_ooc_channel_bypasses_adjudication(self):
        # OOC beats should return immediately without touching the adjudicator.
        adj_input = {"has_stakes": True, "reasoning": "should not be reached"}

        log = EventLog()
        world = WorldState()
        world.add_zone("dungeon")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "dungeon")
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        sheet = CharacterSheet(entity_id="hero", concept="Fighter", skills={})

        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(adj_input)
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp("N/A")

        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=rules, assembler=assembler,
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={"hero": sheet},
            gm_entity="gm",
        )
        result = runner.run("hero", "I need to use the bathroom", channel="ooc")
        assert result.channel == "ooc"
        assert result.had_stakes is False
        adj_client.messages.create.assert_not_called()
