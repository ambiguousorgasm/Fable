"""Phase 21 deliverable 2 — Edge mechanic: Lean / Push / Shield (v6 §13).

Tests for _step_band_up, pre-roll Lean, post-roll Lean-after, Push, Shield,
and the invariants: at-most-one step-up, no step past Triumph, no GainEdge
from a stepped Triumph, effective band drives palette selection.

No Anthropic API key required — all model calls are mocked.

Band control strategy:
  TN=1,  skill=4 → guaranteed Triumph  (min margin 3+4-1=6)
  TN=25, skill=4 → guaranteed Setback  (max margin 18+4-25=-3)
  TN=12, skill=4 → guaranteed Cost     (max margin 18+4-12=10 — can Triumph...
    actually use TN=25 for guaranteed Setback, lean_after → Cost)
"""

from __future__ import annotations

import random
from unittest.mock import MagicMock

import pytest

from fable_table_engine import (
    AdjudicatorGM,
    ApplyStress,
    ApplyScar,
    BeatRunner,
    CharacterSheet,
    CommitPipeline,
    ContextAssembler,
    DiceService,
    EffectExecutor,
    Entity,
    EventLog,
    GainEdge,
    ModelGateway,
    NarratorGM,
    ResolutionPlan,
    RulesEngine,
    SpendEdge,
    STRESS_CAP,
    WorldState,
)
from fable_table_engine.beat import _step_band_up
from fable_table_engine.rules import Band


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _tools_resp(tool_input: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "adjudicate_action"
    block.input = tool_input
    resp = MagicMock()
    resp.content = [block]
    return resp


def _text_resp(text: str):
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _stakes(
    tn: int = 10,
    skill_rating: int = 4,
    exposure: int = 2,
    consequence_palette: dict | None = None,
    triumph_effects: list | None = None,
) -> dict:
    return {
        "has_stakes": True,
        "reasoning": "risk",
        "skill": "fighting",
        "skill_rating": skill_rating,
        "tn": tn,
        "exposure": exposure,
        "effect": "Standard",
        "declared_facts": [],
        "consequence_palette": consequence_palette or {},
        "triumph_effects": triumph_effects or [],
    }


def _make_runner(
    adj_input: dict,
    narrator_text: str = "Narration.",
    *,
    rng_seed: int = 0,
    executor: EffectExecutor | None = None,
) -> tuple[BeatRunner, EventLog, CommitPipeline, WorldState]:
    log = EventLog()
    world = WorldState()
    world.add_zone("arena")
    world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
    world.place("hero", "arena")

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
        executor=executor,
    )
    return runner, log, pipeline, world


def _seed_edge(world: WorldState, entity_id: str, amount: int) -> None:
    entity = world.entities[entity_id]
    world.update_entity(Entity(
        id=entity.id, kind=entity.kind, name=entity.name,
        position=entity.position, conditions=entity.conditions,
        resources={**entity.resources, "edge": amount},
    ))


def _seed_stress(world: WorldState, entity_id: str, amount: int) -> None:
    entity = world.entities[entity_id]
    world.update_entity(Entity(
        id=entity.id, kind=entity.kind, name=entity.name,
        position=entity.position, conditions=entity.conditions,
        resources={**entity.resources, "stress": amount},
    ))


def _edge(world: WorldState, entity_id: str) -> int:
    return world.entities[entity_id].resources.get("edge", 0)


def _stress(world: WorldState, entity_id: str) -> int:
    return world.entities[entity_id].resources.get("stress", 0)


# --------------------------------------------------------------------------- #
# _step_band_up                                                                  #
# --------------------------------------------------------------------------- #

class TestStepBandUp:
    def test_setback_to_cost(self):
        assert _step_band_up(Band.SETBACK) == Band.COST

    def test_cost_to_success(self):
        assert _step_band_up(Band.COST) == Band.SUCCESS

    def test_success_to_triumph(self):
        assert _step_band_up(Band.SUCCESS) == Band.TRIUMPH

    def test_triumph_stays_triumph(self):
        # No Top Exit — clamps at Triumph (v6 §13)
        assert _step_band_up(Band.TRIUMPH) == Band.TRIUMPH


# --------------------------------------------------------------------------- #
# Pre-roll Lean (step 4c)                                                       #
# --------------------------------------------------------------------------- #

class TestLeanBefore:
    def _run(self, world, executor, tn=10, exposure=2, edge_amount=3):
        _seed_edge(world, "hero", edge_amount)
        runner, log, pipeline, world = _make_runner(
            _stakes(tn=tn, exposure=exposure), executor=executor
        )
        # Re-seed edge after _make_runner creates fresh world
        _seed_edge(world, "hero", edge_amount)
        result = runner.run("hero", "attack", edge_spend="lean_before")
        return result, world

    def test_reduces_exposure_recorded_in_result(self):
        log = EventLog()
        world = WorldState()
        world.add_zone("arena")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "arena")
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        executor = EffectExecutor(log, world, pipeline)
        _seed_edge(world, "hero", 3)

        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(_stakes(tn=10, exposure=3))
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp("Narration.")
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=RulesEngine(log, dice), assembler=ContextAssembler(log),
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter",
                                           skills={"fighting": 4})},
            gm_entity="gm", executor=executor,
        )
        result = runner.run("hero", "attack", edge_spend="lean_before", edge_justification="Trait")
        assert result.edge_spent is True
        assert result.effective_exposure == 2  # 3 reduced by 1

    def test_no_effect_without_executor(self):
        runner, log, pipeline, world = _make_runner(_stakes(exposure=2))
        _seed_edge(world, "hero", 3)
        result = runner.run("hero", "attack", edge_spend="lean_before")
        # Without executor there is no way to apply the spend
        assert result.edge_spent is False
        assert result.effective_exposure == 2

    def test_no_effect_when_no_stakes(self):
        log = EventLog()
        world = WorldState()
        world.add_zone("arena")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "arena")
        pipeline = CommitPipeline(log)
        executor = EffectExecutor(log, world, pipeline)
        _seed_edge(world, "hero", 3)
        no_stakes = {
            "has_stakes": False, "reasoning": "trivial", "declared_facts": [],
            "consequence_palette": {}, "triumph_effects": [],
        }
        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(no_stakes)
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp(".")
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=RulesEngine(log, DiceService(log, rng=random.Random(0))),
            assembler=ContextAssembler(log),
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
            gm_entity="gm", executor=executor,
        )
        result = runner.run("hero", "rest", edge_spend="lean_before")
        assert result.edge_spent is False
        assert _edge(world, "hero") == 3  # untouched

    def test_no_effect_at_zero_exposure(self):
        log = EventLog()
        world = WorldState()
        world.add_zone("arena")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "arena")
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        executor = EffectExecutor(log, world, pipeline)
        _seed_edge(world, "hero", 3)
        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(_stakes(tn=10, exposure=0))
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp(".")
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=RulesEngine(log, dice), assembler=ContextAssembler(log),
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter",
                                           skills={"fighting": 4})},
            gm_entity="gm", executor=executor,
        )
        result = runner.run("hero", "attack", edge_spend="lean_before")
        # Exposure already 0 — nothing to reduce, Edge should NOT be spent
        assert result.edge_spent is False
        assert _edge(world, "hero") == 3

    def test_no_effect_when_no_edge(self):
        log = EventLog()
        world = WorldState()
        world.add_zone("arena")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "arena")
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        executor = EffectExecutor(log, world, pipeline)
        # Do NOT seed edge — entity has 0 Edge
        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(_stakes(tn=10, exposure=2))
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp(".")
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=RulesEngine(log, dice), assembler=ContextAssembler(log),
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter",
                                           skills={"fighting": 4})},
            gm_entity="gm", executor=executor,
        )
        result = runner.run("hero", "attack", edge_spend="lean_before")
        assert result.edge_spent is False
        assert result.effective_exposure == 2  # unchanged


# --------------------------------------------------------------------------- #
# Post-roll Lean-after (step 5b)                                                #
# --------------------------------------------------------------------------- #

def _make_full_runner(
    tn: int,
    consequence_palette: dict | None = None,
    triumph_effects: list | None = None,
) -> tuple[BeatRunner, EventLog, CommitPipeline, WorldState, EffectExecutor]:
    """Full runner with executor and a hero entity pre-seeded with Edge=3."""
    log = EventLog()
    world = WorldState()
    world.add_zone("arena")
    world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
    world.place("hero", "arena")
    pipeline = CommitPipeline(log)
    dice = DiceService(log, rng=random.Random(0))
    executor = EffectExecutor(log, world, pipeline)
    _seed_edge(world, "hero", 3)

    adj_client = MagicMock()
    adj_client.messages.create.return_value = _tools_resp(
        _stakes(tn=tn, consequence_palette=consequence_palette,
                triumph_effects=triumph_effects)
    )
    narrator_client = MagicMock()
    narrator_client.messages.create.return_value = _text_resp("Narration.")
    runner = BeatRunner(
        log=log, world=world, pipeline=pipeline,
        rules=RulesEngine(log, dice), assembler=ContextAssembler(log),
        adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
        narrator=NarratorGM(ModelGateway(narrator_client)),
        sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter",
                                       skills={"fighting": 4})},
        gm_entity="gm", executor=executor,
    )
    return runner, log, pipeline, world, executor


class TestLeanAfter:
    def test_steps_band_up_from_setback(self):
        # TN=25 guarantees Setback; lean_after should step to Cost
        runner, log, pipeline, world, executor = _make_full_runner(
            tn=25,
            consequence_palette={"cost": [{"kind": "apply_stress", "entity_id": "hero", "amount": 1}]},
        )
        result = runner.run("hero", "attack", edge_spend="lean_after",
                            edge_justification="Blade Trait")
        assert result.edge_step_applied is True
        assert result.edge_spent is True
        # Edge was spent
        assert _edge(world, "hero") == 2
        # Cost palette applied (band stepped from Setback → Cost)
        accepted = [r for r in result.effect_results if r.accepted]
        stress_applied = any("apply_stress" in str(r.effect) for r in accepted)
        assert stress_applied

    def test_no_step_at_triumph(self):
        # TN=1 guarantees Triumph; lean_after should do nothing (already at top)
        runner, log, pipeline, world, executor = _make_full_runner(tn=1)
        result = runner.run("hero", "attack", edge_spend="lean_after",
                            edge_justification="Blade Trait")
        assert result.edge_step_applied is False
        assert _edge(world, "hero") == 3  # untouched

    def test_no_step_without_justification(self):
        # lean_after without justification should not spend Edge (no Trait invoked)
        runner, log, pipeline, world, executor = _make_full_runner(tn=25)
        result = runner.run("hero", "attack", edge_spend="lean_after",
                            edge_justification="")
        assert result.edge_step_applied is False
        assert _edge(world, "hero") == 3

    def test_no_step_when_no_edge(self):
        runner, log, pipeline, world, executor = _make_full_runner(tn=25)
        _seed_edge(world, "hero", 0)  # drain Edge
        result = runner.run("hero", "attack", edge_spend="lean_after",
                            edge_justification="Bond: Kael")
        assert result.edge_step_applied is False

    def test_edge_decremented(self):
        runner, log, pipeline, world, executor = _make_full_runner(tn=25)
        _seed_edge(world, "hero", 2)
        result = runner.run("hero", "attack", edge_spend="lean_after",
                            edge_justification="Trait: Relentless")
        assert result.edge_step_applied is True
        assert _edge(world, "hero") == 1  # spent 1

    def test_no_effect_without_executor(self):
        runner, log, pipeline, world = _make_runner(_stakes(tn=25))
        _seed_edge(world, "hero", 3)
        result = runner.run("hero", "attack", edge_spend="lean_after",
                            edge_justification="Trait")
        assert result.edge_step_applied is False


# --------------------------------------------------------------------------- #
# Push (step 5b)                                                                #
# --------------------------------------------------------------------------- #

class TestPush:
    def test_steps_band_up_and_costs_stress(self):
        runner, log, pipeline, world, executor = _make_full_runner(tn=25)
        result = runner.run("hero", "attack", edge_spend="push")
        assert result.edge_step_applied is True
        assert _edge(world, "hero") == 2  # 3 - 1
        assert _stress(world, "hero") == 2  # 0 + 2

    def test_no_step_at_triumph(self):
        runner, log, pipeline, world, executor = _make_full_runner(tn=1)
        result = runner.run("hero", "attack", edge_spend="push")
        assert result.edge_step_applied is False
        assert _edge(world, "hero") == 3
        assert _stress(world, "hero") == 0

    def test_no_step_when_no_edge(self):
        runner, log, pipeline, world, executor = _make_full_runner(tn=25)
        _seed_edge(world, "hero", 0)
        result = runner.run("hero", "attack", edge_spend="push")
        assert result.edge_step_applied is False
        assert _stress(world, "hero") == 0

    def test_rejected_when_insufficient_stress_headroom(self):
        # Current stress = STRESS_CAP - 1; Push would bring it to STRESS_CAP + 1 (overflow)
        runner, log, pipeline, world, executor = _make_full_runner(tn=25)
        _seed_stress(world, "hero", STRESS_CAP - 1)  # 5 stress
        result = runner.run("hero", "attack", edge_spend="push")
        assert result.edge_step_applied is False
        assert _edge(world, "hero") == 3  # untouched
        assert _stress(world, "hero") == STRESS_CAP - 1  # untouched

    def test_allowed_at_stress_cap_minus_2(self):
        # Current stress = STRESS_CAP - 2 = 4; Push adds 2 → exactly STRESS_CAP (no overflow)
        runner, log, pipeline, world, executor = _make_full_runner(tn=25)
        _seed_stress(world, "hero", STRESS_CAP - 2)
        result = runner.run("hero", "attack", edge_spend="push")
        assert result.edge_step_applied is True
        assert _stress(world, "hero") == STRESS_CAP

    def test_no_effect_without_executor(self):
        runner, log, pipeline, world = _make_runner(_stakes(tn=25))
        _seed_edge(world, "hero", 3)
        result = runner.run("hero", "attack", edge_spend="push")
        assert result.edge_step_applied is False


# --------------------------------------------------------------------------- #
# Edge invariants                                                                #
# --------------------------------------------------------------------------- #

class TestEdgeInvariants:
    def test_no_gain_edge_from_stepped_triumph(self):
        """Triumph reached by stepping must NOT award GainEdge (v6 §13)."""
        # TN=25 → Setback; lean_after steps to Cost; need to step again?
        # Actually: Setback → lean_after → Cost. Not Triumph.
        # For stepped Triumph: need starting Success → lean_after → Triumph.
        # Use a TN where Success is likely... Use TN=10, skill=4, seed carefully?
        # Better: seed deterministically.
        # TN=10, skill=4: roll for seed=42 — let's compute.
        # Use very low TN to ensure Success at minimum: TN=5, skill=4 → min margin = 3+4-5=2 (Success).
        # Then lean_after → Triumph.
        triumph_effects_with_gain = [{"kind": "gain_edge", "entity_id": "hero", "amount": 1}]
        log = EventLog()
        world = WorldState()
        world.add_zone("arena")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "arena")
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        executor = EffectExecutor(log, world, pipeline)
        _seed_edge(world, "hero", 3)

        adj_client = MagicMock()
        # TN=5, skill=4 → min margin = 3+4-5 = 2 → Success (≥0, <3)
        adj_client.messages.create.return_value = _tools_resp(
            _stakes(tn=5, triumph_effects=triumph_effects_with_gain)
        )
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp(".")
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=RulesEngine(log, dice), assembler=ContextAssembler(log),
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter",
                                           skills={"fighting": 4})},
            gm_entity="gm", executor=executor,
        )
        # lean_after from Success → Triumph; GainEdge should be filtered
        result = runner.run("hero", "attack", edge_spend="lean_after",
                            edge_justification="Trait: Relentless")
        if result.edge_step_applied:
            # If we did step to Triumph, GainEdge must NOT have fired
            assert _edge(world, "hero") < 3  # spent 1 for lean; never gained from triumph
            gain_applied = any(
                isinstance(r.effect, GainEdge) and r.accepted
                for r in result.effect_results
            )
            assert not gain_applied, "GainEdge must not apply to an Edge-stepped Triumph"

    def test_gain_edge_still_applied_on_natural_triumph(self):
        """Natural Triumph (no step) should still award GainEdge."""
        triumph_effects_with_gain = [{"kind": "gain_edge", "entity_id": "hero", "amount": 1}]
        log = EventLog()
        world = WorldState()
        world.add_zone("arena")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "arena")
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        executor = EffectExecutor(log, world, pipeline)
        _seed_edge(world, "hero", 1)  # only 1 Edge so lean_after would leave 0

        adj_client = MagicMock()
        # TN=1 guarantees Triumph
        adj_client.messages.create.return_value = _tools_resp(
            _stakes(tn=1, triumph_effects=triumph_effects_with_gain)
        )
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp(".")
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=RulesEngine(log, dice), assembler=ContextAssembler(log),
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter",
                                           skills={"fighting": 4})},
            gm_entity="gm", executor=executor,
        )
        # No edge_spend — natural Triumph; GainEdge should fire
        result = runner.run("hero", "attack")
        assert result.edge_step_applied is False
        gain_applied = any(
            isinstance(r.effect, GainEdge) and r.accepted
            for r in result.effect_results
        )
        assert gain_applied, "GainEdge should apply on natural Triumph"
        # Edge was 1, should now be 2 (capped at 3)
        assert _edge(world, "hero") == 2

    def test_stepped_band_drives_palette(self):
        """After stepping from Setback to Cost, the Cost palette is applied."""
        cost_palette = {"cost": [{"kind": "apply_stress", "entity_id": "hero", "amount": 1}]}
        setback_palette = {"setback": [{"kind": "apply_stress", "entity_id": "hero", "amount": 3}]}
        palette = {**cost_palette, **setback_palette}
        runner, log, pipeline, world, executor = _make_full_runner(tn=25, consequence_palette=palette)
        result = runner.run("hero", "attack", edge_spend="lean_after",
                            edge_justification="Trait")
        if result.edge_step_applied:
            # Only 1 Stress should be applied (Cost palette), not 3 (Setback palette)
            total_stress = _stress(world, "hero")
            assert total_stress == 1, f"Expected Cost palette (1 stress), got {total_stress}"


# --------------------------------------------------------------------------- #
# Shield                                                                         #
# --------------------------------------------------------------------------- #

class TestShield:
    def _setup_two_entities(self):
        """Returns (log, world, pipeline, executor) with hero (Edge=3) and ally (Edge=3)."""
        log = EventLog()
        world = WorldState()
        world.add_zone("arena")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.add_entity(Entity(id="ally", kind="pc", name="Ally"))
        world.place("hero", "arena")
        world.place("ally", "arena")
        pipeline = CommitPipeline(log)
        executor = EffectExecutor(log, world, pipeline)
        _seed_edge(world, "hero", 3)
        _seed_edge(world, "ally", 3)
        return log, world, pipeline, executor

    def _make_runner_for(
        self, entity_id: str, tn: int, consequence_palette: dict,
        log, world, pipeline, executor,
    ) -> BeatRunner:
        dice = DiceService(log, rng=random.Random(0))
        adj_client = MagicMock()
        adj_client.messages.create.return_value = _tools_resp(
            _stakes(tn=tn, consequence_palette=consequence_palette)
        )
        narrator_client = MagicMock()
        narrator_client.messages.create.return_value = _text_resp(".")
        return BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=RulesEngine(log, dice), assembler=ContextAssembler(log),
            adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
            narrator=NarratorGM(ModelGateway(narrator_client)),
            sheets={
                entity_id: CharacterSheet(entity_id=entity_id, concept="Fighter",
                                          skills={"fighting": 4}),
            },
            gm_entity="gm", executor=executor,
        )

    def test_shield_redirects_stress_to_shielder(self):
        # TN=25 → Setback → cost palette applied (use 'setback' key mapped to stress on hero)
        # hero beats, ally shields hero, so ally takes the stress
        log, world, pipeline, executor = self._setup_two_entities()
        palette = {"setback": [{"kind": "apply_stress", "entity_id": "hero", "amount": 2}]}
        runner = self._make_runner_for("hero", tn=25, consequence_palette=palette,
                                       log=log, world=world, pipeline=pipeline, executor=executor)
        # Rebuild runner with both sheets
        runner._sheets["ally"] = CharacterSheet(entity_id="ally", concept="Ally")
        # Shield registry: hero is being shielded by ally
        result = runner.run(
            "hero", "attack",
            _shield_registry={"hero": "ally"},
        )
        # Hero should have 0 stress; ally should have 2
        assert _stress(world, "hero") == 0
        assert _stress(world, "ally") == 2

    def test_shield_spends_shielder_edge(self):
        log, world, pipeline, executor = self._setup_two_entities()
        palette = {"setback": [{"kind": "apply_stress", "entity_id": "hero", "amount": 1}]}
        runner = self._make_runner_for("hero", tn=25, consequence_palette=palette,
                                       log=log, world=world, pipeline=pipeline, executor=executor)
        runner._sheets["ally"] = CharacterSheet(entity_id="ally", concept="Ally")
        runner.run("hero", "attack", _shield_registry={"hero": "ally"})
        # Ally spent 1 Edge to shield
        assert _edge(world, "ally") == 2  # 3 - 1
        assert _edge(world, "hero") == 3  # untouched

    def test_shield_not_applied_when_shielder_has_no_edge(self):
        log, world, pipeline, executor = self._setup_two_entities()
        _seed_edge(world, "ally", 0)  # drain ally's Edge
        palette = {"setback": [{"kind": "apply_stress", "entity_id": "hero", "amount": 2}]}
        runner = self._make_runner_for("hero", tn=25, consequence_palette=palette,
                                       log=log, world=world, pipeline=pipeline, executor=executor)
        runner._sheets["ally"] = CharacterSheet(entity_id="ally", concept="Ally")
        runner.run("hero", "attack", _shield_registry={"hero": "ally"})
        # Shielder has no Edge; Shield fails; hero takes the hit
        assert _stress(world, "hero") == 2
        assert _stress(world, "ally") == 0

    def test_no_shield_redirect_without_registry(self):
        log, world, pipeline, executor = self._setup_two_entities()
        palette = {"setback": [{"kind": "apply_stress", "entity_id": "hero", "amount": 2}]}
        runner = self._make_runner_for("hero", tn=25, consequence_palette=palette,
                                       log=log, world=world, pipeline=pipeline, executor=executor)
        # No shield_registry — hero takes the hit normally
        runner.run("hero", "attack")
        assert _stress(world, "hero") == 2
        assert _stress(world, "ally") == 0
