"""Stress/Scar pull-forward tests (pre-Phase-21 live play prerequisite).

Covers:
- ApplyScar: 3-slot cap, Scar Route Invariant, scar types, character_broken event
- ApplyStress: 6-box cap, stress floor at 0, overflow cascade (clear + Scar)
- effect_from_dict / describe_effect round-trip for new types
- Integration: overflow cascade fills last Scar slot → character_broken
"""

import pytest

from fable_table_engine import (
    ApplyScar,
    ApplyStress,
    CommitPipeline,
    EffectExecutor,
    Entity,
    EventLog,
    WorldState,
    SCAR_CAP,
    STRESS_CAP,
    describe_effect,
    effect_from_dict,
)
from fable_table_engine.effects import EFFECT_AUTHOR, EFFECT_EVENT_TYPE


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _setup():
    log = EventLog()
    world = WorldState()
    pipeline = CommitPipeline(log)
    executor = EffectExecutor(log, world, pipeline)
    return log, world, pipeline, executor


def _add_entity(world: WorldState, entity_id: str) -> Entity:
    world.add_zone("arena")
    entity = Entity(id=entity_id, kind="character", name=entity_id, resources={})
    world.add_entity(entity)
    world.place(entity_id, "arena")
    return entity


def _seed_stress(world: WorldState, entity_id: str, amount: int) -> None:
    entity = world.entities[entity_id]
    entity.resources["stress"] = amount
    world.update_entity(entity)


def _seed_scars(world: WorldState, entity_id: str, count: int) -> None:
    entity = world.entities[entity_id]
    entity.resources["scars"] = [
        {"scar_type": "wound", "description": f"old scar {i}"} for i in range(count)
    ]
    world.update_entity(entity)


AUD = ("table",)


# --------------------------------------------------------------------------- #
# ApplyScar basics                                                              #
# --------------------------------------------------------------------------- #

class TestApplyScar:
    def test_accept_via_overflow(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        effect = ApplyScar(
            kind="apply_scar", entity_id="hero",
            scar_type="wound", description="slashed side",
            via_overflow=True,
        )
        result = executor.apply(effect, audience=AUD)
        assert result.accepted
        scars = world.entities["hero"].resources["scars"]
        assert len(scars) == 1
        assert scars[0] == {"scar_type": "wound", "description": "slashed side"}

    def test_accept_via_seam(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        effect = ApplyScar(
            kind="apply_scar", entity_id="hero",
            scar_type="loss", description="weapon destroyed",
            seam_event_id="seam-evt-001",
        )
        result = executor.apply(effect, audience=AUD)
        assert result.accepted
        scars = world.entities["hero"].resources["scars"]
        assert scars[0]["scar_type"] == "loss"

    def test_accept_mark_type(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        effect = ApplyScar(
            kind="apply_scar", entity_id="hero",
            scar_type="mark", description="branded as traitor",
            via_overflow=True,
        )
        result = executor.apply(effect, audience=AUD)
        assert result.accepted

    def test_reject_route_invariant(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        effect = ApplyScar(
            kind="apply_scar", entity_id="hero",
            scar_type="wound", description="direct scar with no route",
        )
        result = executor.apply(effect, audience=AUD)
        assert not result.accepted
        assert "Scar Route Invariant" in result.rejection_reason

    def test_reject_empty_description(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        effect = ApplyScar(
            kind="apply_scar", entity_id="hero",
            scar_type="wound", description="", via_overflow=True,
        )
        result = executor.apply(effect, audience=AUD)
        assert not result.accepted
        assert "description" in result.rejection_reason

    def test_reject_entity_not_found(self):
        log, world, _, executor = _setup()
        effect = ApplyScar(
            kind="apply_scar", entity_id="ghost",
            scar_type="wound", description="phantom pain",
            via_overflow=True,
        )
        result = executor.apply(effect, audience=AUD)
        assert not result.accepted
        assert "ghost" in result.rejection_reason

    def test_reject_at_scar_cap(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        _seed_scars(world, "hero", SCAR_CAP)
        effect = ApplyScar(
            kind="apply_scar", entity_id="hero",
            scar_type="wound", description="one more",
            via_overflow=True,
        )
        result = executor.apply(effect, audience=AUD)
        assert not result.accepted
        assert "Broken" in result.rejection_reason or "cap" in result.rejection_reason.lower()

    def test_character_broken_event_at_cap(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        _seed_scars(world, "hero", SCAR_CAP - 1)  # one slot remaining
        effect = ApplyScar(
            kind="apply_scar", entity_id="hero",
            scar_type="loss", description="loses everything",
            via_overflow=True,
        )
        result = executor.apply(effect, audience=AUD)
        assert result.accepted
        broken_events = [e for e in log.all() if e.type == "character_broken"]
        assert len(broken_events) == 1
        assert "hero" in broken_events[0].content

    def test_no_broken_event_below_cap(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        effect = ApplyScar(
            kind="apply_scar", entity_id="hero",
            scar_type="wound", description="first scar",
            via_overflow=True,
        )
        result = executor.apply(effect, audience=AUD)
        assert result.accepted
        broken_events = [e for e in log.all() if e.type == "character_broken"]
        assert len(broken_events) == 0

    def test_scars_accumulate(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        for i in range(SCAR_CAP):
            e = ApplyScar(
                kind="apply_scar", entity_id="hero",
                scar_type="wound", description=f"scar {i}",
                via_overflow=True,
            )
            result = executor.apply(e, audience=AUD)
            assert result.accepted, f"scar {i} rejected: {result.rejection_reason}"
        assert len(world.entities["hero"].resources["scars"]) == SCAR_CAP

    def test_event_logged_with_route(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        effect = ApplyScar(
            kind="apply_scar", entity_id="hero",
            scar_type="wound", description="test",
            seam_event_id="seam-123",
        )
        result = executor.apply(effect, audience=AUD)
        assert result.accepted
        evt = log._by_id[result.event_id]
        assert "seam:seam-123" in evt.content


# --------------------------------------------------------------------------- #
# ApplyStress cap and floor                                                     #
# --------------------------------------------------------------------------- #

class TestApplyStressCap:
    def test_normal_stress(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        result = executor.apply(
            ApplyStress(kind="apply_stress", entity_id="hero", amount=3),
            audience=AUD,
        )
        assert result.accepted
        assert world.entities["hero"].resources["stress"] == 3

    def test_stress_exactly_at_cap(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        result = executor.apply(
            ApplyStress(kind="apply_stress", entity_id="hero", amount=STRESS_CAP),
            audience=AUD,
        )
        assert result.accepted
        assert world.entities["hero"].resources["stress"] == STRESS_CAP

    def test_reject_overflow_without_scar_params(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        _seed_stress(world, "hero", 5)
        result = executor.apply(
            ApplyStress(kind="apply_stress", entity_id="hero", amount=2),
            audience=AUD,
        )
        assert not result.accepted
        assert "overflow" in result.rejection_reason.lower()
        assert "overflow_scar_type" in result.rejection_reason
        # Stress must not have changed
        assert world.entities["hero"].resources["stress"] == 5

    def test_stress_floor_at_zero(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        _seed_stress(world, "hero", 2)
        result = executor.apply(
            ApplyStress(kind="apply_stress", entity_id="hero", amount=-10),
            audience=AUD,
        )
        assert result.accepted
        assert world.entities["hero"].resources["stress"] == 0

    def test_stress_relief_no_overflow(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        _seed_stress(world, "hero", 4)
        result = executor.apply(
            ApplyStress(kind="apply_stress", entity_id="hero", amount=-2),
            audience=AUD,
        )
        assert result.accepted
        assert world.entities["hero"].resources["stress"] == 2


# --------------------------------------------------------------------------- #
# Stress overflow cascade                                                        #
# --------------------------------------------------------------------------- #

class TestStressOverflow:
    def test_overflow_clears_stress_and_applies_scar(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        _seed_stress(world, "hero", 5)
        result = executor.apply(
            ApplyStress(
                kind="apply_stress", entity_id="hero", amount=2,
                overflow_scar_type="wound", overflow_scar_desc="burned in the blast",
            ),
            audience=AUD,
        )
        assert result.accepted
        entity = world.entities["hero"]
        assert entity.resources["stress"] == 0
        scars = entity.resources["scars"]
        assert len(scars) == 1
        assert scars[0] == {"scar_type": "wound", "description": "burned in the blast"}

    def test_overflow_from_zero_stress(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        result = executor.apply(
            ApplyStress(
                kind="apply_stress", entity_id="hero", amount=STRESS_CAP + 1,
                overflow_scar_type="mark", overflow_scar_desc="mark of the outcast",
            ),
            audience=AUD,
        )
        assert result.accepted
        entity = world.entities["hero"]
        assert entity.resources["stress"] == 0
        assert len(entity.resources["scars"]) == 1

    def test_overflow_uses_default_desc_when_empty(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        _seed_stress(world, "hero", 6)
        result = executor.apply(
            ApplyStress(
                kind="apply_stress", entity_id="hero", amount=1,
                overflow_scar_type="loss", overflow_scar_desc="",
            ),
            audience=AUD,
        )
        assert result.accepted
        scars = world.entities["hero"].resources["scars"]
        assert scars[0]["description"]  # non-empty fallback

    def test_overflow_logs_two_events(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        _seed_stress(world, "hero", 5)
        before_count = len(log.all())
        result = executor.apply(
            ApplyStress(
                kind="apply_stress", entity_id="hero", amount=3,
                overflow_scar_type="wound", overflow_scar_desc="deep cut",
            ),
            audience=AUD,
        )
        assert result.accepted
        new_events = log.all()[before_count:]
        types = [e.type for e in new_events]
        assert EFFECT_EVENT_TYPE in types  # stress overflow event
        # scar event also logged
        scar_events = [e for e in new_events if "apply_scar" in e.content]
        assert scar_events

    def test_overflow_rejected_when_at_scar_cap(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        _seed_stress(world, "hero", 5)
        _seed_scars(world, "hero", SCAR_CAP)
        result = executor.apply(
            ApplyStress(
                kind="apply_stress", entity_id="hero", amount=2,
                overflow_scar_type="wound", overflow_scar_desc="too many",
            ),
            audience=AUD,
        )
        assert not result.accepted
        assert "scar" in result.rejection_reason.lower()

    def test_overflow_cascade_triggers_broken_at_third_scar(self):
        log, world, _, executor = _setup()
        _add_entity(world, "hero")
        _seed_stress(world, "hero", 5)
        _seed_scars(world, "hero", SCAR_CAP - 1)  # 2 scars, one slot left
        result = executor.apply(
            ApplyStress(
                kind="apply_stress", entity_id="hero", amount=2,
                overflow_scar_type="loss", overflow_scar_desc="loses the last ally",
            ),
            audience=AUD,
        )
        assert result.accepted
        broken_events = [e for e in log.all() if e.type == "character_broken"]
        assert len(broken_events) == 1


# --------------------------------------------------------------------------- #
# effect_from_dict round-trip                                                   #
# --------------------------------------------------------------------------- #

class TestEffectFromDict:
    def test_apply_scar_round_trip_overflow(self):
        d = {
            "kind": "apply_scar", "entity_id": "hero",
            "scar_type": "wound", "description": "slashed",
            "via_overflow": True,
        }
        effect = effect_from_dict(d)
        assert isinstance(effect, ApplyScar)
        assert effect.scar_type == "wound"
        assert effect.via_overflow is True
        assert effect.seam_event_id is None

    def test_apply_scar_round_trip_seam(self):
        d = {
            "kind": "apply_scar", "entity_id": "hero",
            "scar_type": "loss", "description": "arm gone",
            "seam_event_id": "evt-abc",
        }
        effect = effect_from_dict(d)
        assert isinstance(effect, ApplyScar)
        assert effect.seam_event_id == "evt-abc"
        assert effect.via_overflow is False

    def test_apply_stress_round_trip_with_overflow(self):
        d = {
            "kind": "apply_stress", "entity_id": "hero", "amount": 4,
            "overflow_scar_type": "mark", "overflow_scar_desc": "branded",
        }
        effect = effect_from_dict(d)
        assert isinstance(effect, ApplyStress)
        assert effect.overflow_scar_type == "mark"
        assert effect.overflow_scar_desc == "branded"

    def test_apply_stress_round_trip_plain(self):
        d = {"kind": "apply_stress", "entity_id": "hero", "amount": 2}
        effect = effect_from_dict(d)
        assert isinstance(effect, ApplyStress)
        assert effect.overflow_scar_type is None
        assert effect.overflow_scar_desc == ""


# --------------------------------------------------------------------------- #
# describe_effect                                                                #
# --------------------------------------------------------------------------- #

class TestDescribeEffect:
    def test_describe_scar_overflow(self):
        e = ApplyScar(
            kind="apply_scar", entity_id="hero",
            scar_type="wound", description="arrow through shoulder",
            via_overflow=True,
        )
        desc = describe_effect(e)
        assert "wound" in desc
        assert "overflow" in desc
        assert "hero" in desc

    def test_describe_scar_seam(self):
        e = ApplyScar(
            kind="apply_scar", entity_id="hero",
            scar_type="loss", description="sword lost",
            seam_event_id="seam-99",
        )
        desc = describe_effect(e)
        assert "seam:seam-99" in desc
        assert "loss" in desc

    def test_describe_stress_with_overflow_param(self):
        e = ApplyStress(
            kind="apply_stress", entity_id="hero", amount=5,
            overflow_scar_type="wound",
        )
        desc = describe_effect(e)
        assert "overflow" in desc
        assert "wound" in desc

    def test_describe_stress_plain(self):
        e = ApplyStress(kind="apply_stress", entity_id="hero", amount=2)
        desc = describe_effect(e)
        assert "stress" in desc
        assert "overflow" not in desc
