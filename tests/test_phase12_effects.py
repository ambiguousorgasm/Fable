"""Phase 12 acceptance tests — Typed Effect Executor.

Invariants exercised:
  1. State changes occur only through validated typed effects.
  2. Narration cannot create state changes (structural; narrator never holds executor).
  3. Invalid effects are rejected before any state mutation.
  4. Clock advancement includes trigger provenance in the logged event.
  5. A private effect respects its scoped audience and disclosure status.
  6. Replay from the event log reconstructs the same world state.

Exit gate: the engine can say exactly how every durable change occurred without
relying on freeform narrator prose.
"""

import pytest

from fable_table_engine import (
    AdvanceClock,
    ApplyStress,
    ChangeAccess,
    ChangeResource,
    ChangeTruth,
    CommitPipeline,
    CreateMaintainedTruth,
    CreateTruth,
    EffectExecutor,
    Entity,
    EventLog,
    ExpireMaintainedTruth,
    ExpireTruth,
    MoveEntity,
    WorldState,
    canon_ledger,
    committed_facts,
)
from fable_table_engine.access import Fact
from fable_table_engine.effects import EFFECT_AUTHOR, EFFECT_EVENT_TYPE
from fable_table_engine.perception import Scene


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _setup():
    log = EventLog()
    world = WorldState()
    pipeline = CommitPipeline(log)
    executor = EffectExecutor(log, world, pipeline)
    return log, world, pipeline, executor


def _setup_with_scene():
    log = EventLog()
    world = WorldState()
    pipeline = CommitPipeline(log)
    scene = Scene(world)
    executor = EffectExecutor(log, world, pipeline, scene=scene)
    return log, world, pipeline, scene, executor


AUDIENCE = ("player", "gm")


# --------------------------------------------------------------------------- #
# CreateTruth                                                                   #
# --------------------------------------------------------------------------- #

class TestCreateTruth:

    def test_valid_create_truth_enters_committed_facts(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        effect = CreateTruth(kind="create_truth", subject="door", predicate="state", value="locked")
        result = executor.apply(effect, audience=AUDIENCE)
        assert result.accepted
        assert result.event_id is not None
        facts = committed_facts(log.all())
        assert ("door", "state") in facts
        assert facts[("door", "state")].value == "locked"

    def test_create_truth_logs_effect_applied_event(self):
        log, world, pipeline, executor = _setup()
        effect = CreateTruth(kind="create_truth", subject="tower", predicate="height", value="100ft")
        result = executor.apply(effect, audience=AUDIENCE)
        event = log._by_id[result.event_id]
        assert event.type == EFFECT_EVENT_TYPE
        assert event.author == EFFECT_AUTHOR

    def test_create_truth_with_source_event_id_links_provenance(self):  # acceptance 4
        log, world, pipeline, executor = _setup()
        src = log.append(author="gm", channel="system", type="declaration",
                         content="setup", audience=AUDIENCE)
        effect = CreateTruth(kind="create_truth", subject="tower", predicate="height", value="100ft")
        result = executor.apply(effect, audience=AUDIENCE, source_event_id=src.id)
        event = log._by_id[result.event_id]
        assert src.id in event.derived_from

    def test_create_truth_unrevealed_stays_out_of_canon(self):  # acceptance 5
        log, world, pipeline, executor = _setup()
        effect = CreateTruth(kind="create_truth", subject="vault", predicate="code",
                             value="7734", revealed=False)
        result = executor.apply(effect, audience=("gm",))
        assert result.accepted
        ledger = canon_ledger(log.all())
        assert ("vault", "code") not in ledger
        facts = committed_facts(log.all())
        assert ("vault", "code") in facts

    def test_create_truth_conflict_returns_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        # First establish a canon fact
        pipeline.commit(author="gm", channel="system", content="setup", audience=AUDIENCE,
                        visibility="content",
                        commitments=[__import__("fable_table_engine").Commitment(
                            subject="duke", predicate="role", value="funder", revealed=True)])
        # Contradicting create_truth should be rejected without mutation
        effect = CreateTruth(kind="create_truth", subject="duke", predicate="role",
                             value="traitor", revealed=True)
        result = executor.apply(effect, audience=AUDIENCE)
        assert not result.accepted
        assert result.rejection_reason is not None
        facts = committed_facts(log.all())
        assert facts[("duke", "role")].value == "funder"  # unchanged

    def test_create_truth_empty_subject_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        effect = CreateTruth(kind="create_truth", subject="", predicate="role", value="x")
        result = executor.apply(effect, audience=AUDIENCE)
        assert not result.accepted

    def test_applied_effects_appear_in_apply_all_results(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        effects = [
            CreateTruth(kind="create_truth", subject="a", predicate="p", value=1),
            CreateTruth(kind="create_truth", subject="b", predicate="q", value=2),
        ]
        results = executor.apply_all(effects, audience=AUDIENCE)
        assert len(results) == 2
        assert all(r.accepted for r in results)
        facts = committed_facts(log.all())
        assert ("a", "p") in facts
        assert ("b", "q") in facts


# --------------------------------------------------------------------------- #
# ChangeTruth                                                                   #
# --------------------------------------------------------------------------- #

class TestChangeTruth:

    def test_change_truth_revises_existing_fact(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        from fable_table_engine import Commitment
        pipeline.commit(author="gm", channel="system", content="setup", audience=AUDIENCE,
                        visibility="content",
                        commitments=[Commitment(subject="door", predicate="state", value="open", revealed=True)])
        effect = ChangeTruth(kind="change_truth", subject="door", predicate="state",
                             value="locked", reason="player locked the door")
        result = executor.apply(effect, audience=AUDIENCE)
        assert result.accepted
        facts = committed_facts(log.all())
        assert facts[("door", "state")].value == "locked"

    def test_change_truth_uses_override_event_type(self):
        log, world, pipeline, executor = _setup()
        effect = ChangeTruth(kind="change_truth", subject="x", predicate="y", value="z",
                             reason="test override")
        executor.apply(effect, audience=AUDIENCE)
        from fable_table_engine.access import OVERRIDE_TYPE
        override_events = [e for e in log.all() if e.type == OVERRIDE_TYPE]
        assert len(override_events) == 1

    def test_change_truth_does_not_require_prior_existence(self):
        log, world, pipeline, executor = _setup()
        effect = ChangeTruth(kind="change_truth", subject="new", predicate="fact",
                             value="value", reason="initial via change")
        result = executor.apply(effect, audience=AUDIENCE)
        assert result.accepted


# --------------------------------------------------------------------------- #
# ExpireTruth                                                                   #
# --------------------------------------------------------------------------- #

class TestExpireTruth:

    def test_expire_truth_removes_from_committed_facts(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        from fable_table_engine import Commitment
        pipeline.commit(author="gm", channel="system", content="setup", audience=AUDIENCE,
                        visibility="content",
                        commitments=[Commitment(subject="torch", predicate="lit", value=True, revealed=True)])
        assert ("torch", "lit") in committed_facts(log.all())

        effect = ExpireTruth(kind="expire_truth", subject="torch", predicate="lit")
        result = executor.apply(effect, audience=AUDIENCE)
        assert result.accepted
        assert ("torch", "lit") not in committed_facts(log.all())

    def test_expire_truth_also_removes_from_canon_ledger(self):
        log, world, pipeline, executor = _setup()
        from fable_table_engine import Commitment
        pipeline.commit(author="gm", channel="system", content="setup", audience=AUDIENCE,
                        visibility="content",
                        commitments=[Commitment(subject="torch", predicate="lit", value=True, revealed=True)])
        executor.apply(ExpireTruth(kind="expire_truth", subject="torch", predicate="lit"),
                       audience=AUDIENCE)
        assert ("torch", "lit") not in canon_ledger(log.all())

    def test_expire_nonexistent_truth_still_accepted(self):
        log, world, pipeline, executor = _setup()
        result = executor.apply(
            ExpireTruth(kind="expire_truth", subject="ghost", predicate="exists"),
            audience=AUDIENCE,
        )
        # No pre-existing truth: tombstone commits without conflict, dict.pop is no-op
        assert result.accepted

    def test_expire_truth_only_once_changes_state(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        from fable_table_engine import Commitment
        pipeline.commit(author="gm", channel="system", content="setup", audience=AUDIENCE,
                        visibility="content",
                        commitments=[Commitment(subject="fire", predicate="burning", value=True, revealed=True)])
        effect = ExpireTruth(kind="expire_truth", subject="fire", predicate="burning")
        executor.apply(effect, audience=AUDIENCE)
        count_before = len(log.all())
        executor.apply(effect, audience=AUDIENCE)
        count_after = len(log.all())
        assert count_after == count_before + 1  # second tombstone appended but changes nothing


# --------------------------------------------------------------------------- #
# AdvanceClock                                                                  #
# --------------------------------------------------------------------------- #

class TestAdvanceClock:

    def test_advance_clock_ticks_current(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        world.set_clock("patrol", {"current": 2, "max": 6, "step": 1})
        result = executor.apply(
            AdvanceClock(kind="advance_clock", clock_name="patrol", steps=2),
            audience=AUDIENCE,
        )
        assert result.accepted
        assert world.clocks["patrol"]["current"] == 4
        assert not world.clocks["patrol"]["fired"]

    def test_advance_clock_logs_provenance_event(self):  # acceptance 4
        log, world, pipeline, executor = _setup()
        src = log.append(author="gm", channel="system", type="declaration",
                         content="roll result", audience=AUDIENCE)
        world.set_clock("suspicion", {"current": 0, "max": 4, "step": 1})
        result = executor.apply(
            AdvanceClock(kind="advance_clock", clock_name="suspicion", steps=1),
            audience=AUDIENCE, source_event_id=src.id,
        )
        event = log._by_id[result.event_id]
        assert event.type == EFFECT_EVENT_TYPE
        assert src.id in event.derived_from
        assert "suspicion" in event.content

    def test_advance_clock_fires_when_full(self):
        log, world, pipeline, executor = _setup()
        world.set_clock("countdown", {"current": 5, "max": 6, "step": 1})
        executor.apply(
            AdvanceClock(kind="advance_clock", clock_name="countdown", steps=1),
            audience=AUDIENCE,
        )
        assert world.clocks["countdown"]["fired"]
        front_events = [e for e in log.all() if e.type == "front_advance"]
        assert len(front_events) == 1

    def test_advance_clock_caps_at_max(self):
        log, world, pipeline, executor = _setup()
        world.set_clock("ritual", {"current": 4, "max": 6, "step": 1})
        executor.apply(
            AdvanceClock(kind="advance_clock", clock_name="ritual", steps=10),
            audience=AUDIENCE,
        )
        assert world.clocks["ritual"]["current"] == 6

    def test_advance_fired_clock_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        world.set_clock("done", {"current": 6, "max": 6, "fired": True})
        result = executor.apply(
            AdvanceClock(kind="advance_clock", clock_name="done", steps=1),
            audience=AUDIENCE,
        )
        assert not result.accepted

    def test_advance_missing_clock_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        result = executor.apply(
            AdvanceClock(kind="advance_clock", clock_name="ghost_clock", steps=1),
            audience=AUDIENCE,
        )
        assert not result.accepted

    def test_advance_zero_steps_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        world.set_clock("x", {"current": 0, "max": 4})
        result = executor.apply(
            AdvanceClock(kind="advance_clock", clock_name="x", steps=0),
            audience=AUDIENCE,
        )
        assert not result.accepted


# --------------------------------------------------------------------------- #
# ApplyStress                                                                   #
# --------------------------------------------------------------------------- #

class TestApplyStress:

    def test_apply_stress_increases_stress(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        world.add_entity(Entity(id="vale", kind="ally", name="Vale"))
        result = executor.apply(
            ApplyStress(kind="apply_stress", entity_id="vale", amount=2),
            audience=AUDIENCE,
        )
        assert result.accepted
        assert world.entities["vale"].resources["stress"] == 2

    def test_apply_stress_accumulates(self):
        log, world, pipeline, executor = _setup()
        world.add_entity(Entity(id="vale", kind="ally", name="Vale",
                                resources={"stress": 3}))
        executor.apply(ApplyStress(kind="apply_stress", entity_id="vale", amount=2),
                       audience=AUDIENCE)
        assert world.entities["vale"].resources["stress"] == 5

    def test_apply_negative_stress_reduces(self):
        log, world, pipeline, executor = _setup()
        world.add_entity(Entity(id="vale", kind="ally", name="Vale",
                                resources={"stress": 5}))
        executor.apply(ApplyStress(kind="apply_stress", entity_id="vale", amount=-2),
                       audience=AUDIENCE)
        assert world.entities["vale"].resources["stress"] == 3

    def test_apply_stress_missing_entity_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        result = executor.apply(
            ApplyStress(kind="apply_stress", entity_id="nobody", amount=1),
            audience=AUDIENCE,
        )
        assert not result.accepted

    def test_apply_zero_stress_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        world.add_entity(Entity(id="vale", kind="ally", name="Vale"))
        result = executor.apply(
            ApplyStress(kind="apply_stress", entity_id="vale", amount=0),
            audience=AUDIENCE,
        )
        assert not result.accepted


# --------------------------------------------------------------------------- #
# MoveEntity                                                                    #
# --------------------------------------------------------------------------- #

class TestMoveEntity:

    def test_move_entity_updates_position(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        world.add_zone("tavern")
        world.add_zone("alley")
        world.add_entity(Entity(id="player", kind="pc", name="Player"))
        world.place("player", "tavern")

        result = executor.apply(
            MoveEntity(kind="move_entity", entity_id="player", to_zone="alley"),
            audience=AUDIENCE,
        )
        assert result.accepted
        assert world.zone_of("player") == "alley"

    def test_move_entity_missing_entity_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        world.add_zone("zone_a")
        result = executor.apply(
            MoveEntity(kind="move_entity", entity_id="ghost", to_zone="zone_a"),
            audience=AUDIENCE,
        )
        assert not result.accepted

    def test_move_entity_missing_zone_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        world.add_entity(Entity(id="player", kind="pc", name="Player"))
        result = executor.apply(
            MoveEntity(kind="move_entity", entity_id="player", to_zone="nowhere"),
            audience=AUDIENCE,
        )
        assert not result.accepted


# --------------------------------------------------------------------------- #
# ChangeResource                                                                 #
# --------------------------------------------------------------------------- #

class TestChangeResource:

    def test_change_resource_delta(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        world.add_entity(Entity(id="rook", kind="ally", name="Rook",
                                resources={"gold": 10}))
        result = executor.apply(
            ChangeResource(kind="change_resource", entity_id="rook",
                           resource="gold", delta=-3),
            audience=AUDIENCE,
        )
        assert result.accepted
        assert world.entities["rook"].resources["gold"] == 7

    def test_change_resource_set_value(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        world.add_entity(Entity(id="rook", kind="ally", name="Rook"))
        result = executor.apply(
            ChangeResource(kind="change_resource", entity_id="rook",
                           resource="stamina", set_value=5),
            audience=AUDIENCE,
        )
        assert result.accepted
        assert world.entities["rook"].resources["stamina"] == 5

    def test_change_resource_both_delta_and_set_value_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        world.add_entity(Entity(id="rook", kind="ally", name="Rook"))
        result = executor.apply(
            ChangeResource(kind="change_resource", entity_id="rook",
                           resource="gold", delta=1, set_value=5),
            audience=AUDIENCE,
        )
        assert not result.accepted

    def test_change_resource_neither_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        world.add_entity(Entity(id="rook", kind="ally", name="Rook"))
        result = executor.apply(
            ChangeResource(kind="change_resource", entity_id="rook",
                           resource="gold", delta=None, set_value=None),
            audience=AUDIENCE,
        )
        assert not result.accepted


# --------------------------------------------------------------------------- #
# ChangeAccess                                                                   #
# --------------------------------------------------------------------------- #

class TestChangeAccess:

    def test_change_access_close_connection(self):  # acceptance 1
        log, world, pipeline, scene, executor = _setup_with_scene()
        world.add_zone("hall")
        world.add_zone("vault")
        world.connect("hall", "vault")

        result = executor.apply(
            ChangeAccess(kind="change_access", operation="close",
                         zone_a="hall", zone_b="vault"),
            audience=AUDIENCE,
        )
        assert result.accepted
        assert frozenset({"hall", "vault"}) in scene.closed_connections

    def test_change_access_open_connection(self):
        log, world, pipeline, scene, executor = _setup_with_scene()
        world.add_zone("hall")
        world.add_zone("vault")
        world.connect("hall", "vault")
        scene.close("hall", "vault")

        result = executor.apply(
            ChangeAccess(kind="change_access", operation="open",
                         zone_a="hall", zone_b="vault"),
            audience=AUDIENCE,
        )
        assert result.accepted
        assert frozenset({"hall", "vault"}) not in scene.closed_connections

    def test_change_access_darken_zone(self):  # acceptance 1
        log, world, pipeline, scene, executor = _setup_with_scene()
        world.add_zone("cellar")

        result = executor.apply(
            ChangeAccess(kind="change_access", operation="darken", zone_a="cellar"),
            audience=AUDIENCE,
        )
        assert result.accepted
        assert "cellar" in scene.dark_zones

    def test_change_access_illuminate_zone(self):
        log, world, pipeline, scene, executor = _setup_with_scene()
        world.add_zone("cellar")
        scene.darken("cellar")

        result = executor.apply(
            ChangeAccess(kind="change_access", operation="illuminate", zone_a="cellar"),
            audience=AUDIENCE,
        )
        assert result.accepted
        assert "cellar" not in scene.dark_zones

    def test_change_access_requires_scene(self):  # acceptance 3
        log, world, pipeline, executor = _setup()  # no scene
        world.add_zone("hall")
        result = executor.apply(
            ChangeAccess(kind="change_access", operation="darken", zone_a="hall"),
            audience=AUDIENCE,
        )
        assert not result.accepted
        assert "Scene" in result.rejection_reason

    def test_change_access_close_unconnected_zones_rejected(self):  # acceptance 3
        log, world, pipeline, scene, executor = _setup_with_scene()
        world.add_zone("a")
        world.add_zone("b")
        # not connected
        result = executor.apply(
            ChangeAccess(kind="change_access", operation="close", zone_a="a", zone_b="b"),
            audience=AUDIENCE,
        )
        assert not result.accepted

    def test_change_access_missing_zone_b_for_close_rejected(self):  # acceptance 3
        log, world, pipeline, scene, executor = _setup_with_scene()
        world.add_zone("hall")
        result = executor.apply(
            ChangeAccess(kind="change_access", operation="close", zone_a="hall", zone_b=None),
            audience=AUDIENCE,
        )
        assert not result.accepted


# --------------------------------------------------------------------------- #
# Maintained truths                                                              #
# --------------------------------------------------------------------------- #

class TestMaintainedTruth:

    def test_create_maintained_truth_commits_fact(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        result = executor.apply(
            CreateMaintainedTruth(kind="create_maintained_truth",
                                  subject="lantern", predicate="lit", value=True,
                                  lapse_condition="when lantern fuel is exhausted"),
            audience=AUDIENCE,
        )
        assert result.accepted
        facts = committed_facts(log.all())
        assert ("lantern", "lit") in facts

    def test_create_maintained_truth_registers_lapse(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        executor.apply(
            CreateMaintainedTruth(kind="create_maintained_truth",
                                  subject="lantern", predicate="lit", value=True,
                                  lapse_condition="when fuel exhausted"),
            audience=AUDIENCE,
        )
        key = "lantern::lit"
        assert key in world.maintained_truths
        assert world.maintained_truths[key]["lapse_condition"] == "when fuel exhausted"

    def test_expire_maintained_truth_removes_lapse_and_tombstones_fact(self):  # acceptance 1
        log, world, pipeline, executor = _setup()
        executor.apply(
            CreateMaintainedTruth(kind="create_maintained_truth",
                                  subject="lantern", predicate="lit", value=True,
                                  lapse_condition="when fuel exhausted"),
            audience=AUDIENCE,
        )
        result = executor.apply(
            ExpireMaintainedTruth(kind="expire_maintained_truth",
                                  subject="lantern", predicate="lit"),
            audience=AUDIENCE,
        )
        assert result.accepted
        assert "lantern::lit" not in world.maintained_truths
        assert ("lantern", "lit") not in committed_facts(log.all())

    def test_expire_nonexistent_maintained_truth_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        result = executor.apply(
            ExpireMaintainedTruth(kind="expire_maintained_truth",
                                  subject="ghost", predicate="exists"),
            audience=AUDIENCE,
        )
        assert not result.accepted

    def test_create_maintained_truth_empty_lapse_rejected(self):  # acceptance 3
        log, world, pipeline, executor = _setup()
        result = executor.apply(
            CreateMaintainedTruth(kind="create_maintained_truth",
                                  subject="x", predicate="y", value=True,
                                  lapse_condition=""),
            audience=AUDIENCE,
        )
        assert not result.accepted


# --------------------------------------------------------------------------- #
# Audience / disclosure invariant (acceptance 5)                                #
# --------------------------------------------------------------------------- #

class TestPrivateEffect:

    def test_private_effect_not_visible_in_player_projection(self):  # acceptance 5
        log, world, pipeline, executor = _setup()
        gm_only = ("gm",)
        executor.apply(
            CreateTruth(kind="create_truth", subject="safe", predicate="combination",
                        value="1234", revealed=False),
            audience=gm_only,
        )
        player_events = log.project_for("player")
        assert len(player_events) == 0  # player not in audience

    def test_public_effect_visible_in_player_projection(self):
        log, world, pipeline, executor = _setup()
        executor.apply(
            CreateTruth(kind="create_truth", subject="inn", predicate="name",
                        value="Salt Lantern", revealed=True),
            audience=AUDIENCE,
        )
        player_events = log.project_for("player")
        assert len(player_events) == 1


# --------------------------------------------------------------------------- #
# Replay consistency (acceptance 6)                                             #
# --------------------------------------------------------------------------- #

class TestReplayConsistency:

    def test_committed_facts_from_replay_matches_applied_effects(self):  # acceptance 6
        log, world, pipeline, executor = _setup()
        world.add_zone("tavern")
        world.add_entity(Entity(id="rook", kind="ally", name="Rook"))
        world.place("rook", "tavern")

        executor.apply_all([
            CreateTruth(kind="create_truth", subject="door", predicate="state", value="locked"),
            CreateTruth(kind="create_truth", subject="vault", predicate="owner", value="duke"),
            AdvanceClock(kind="advance_clock", clock_name="patrol",  # skipped — no clock
                         steps=1) if "patrol" in world.clocks else
            CreateTruth(kind="create_truth", subject="sky", predicate="condition", value="clear"),
            MoveEntity(kind="move_entity", entity_id="rook", to_zone="tavern"),
        ], audience=AUDIENCE)

        # The world state derivable from committed_facts should match what we applied
        facts = committed_facts(log.all())
        assert facts[("door", "state")].value == "locked"
        assert facts[("vault", "owner")].value == "duke"

    def test_expire_then_recreate_truth_reflects_latest(self):  # acceptance 6
        log, world, pipeline, executor = _setup()
        from fable_table_engine import Commitment
        pipeline.commit(author="gm", channel="system", content="init", audience=AUDIENCE,
                        visibility="content",
                        commitments=[Commitment(subject="torch", predicate="lit",
                                                value=True, revealed=True)])
        executor.apply(ExpireTruth(kind="expire_truth", subject="torch", predicate="lit"),
                       audience=AUDIENCE)
        executor.apply(CreateTruth(kind="create_truth", subject="torch", predicate="lit",
                                   value=False), audience=AUDIENCE)

        facts = committed_facts(log.all())
        assert ("torch", "lit") in facts
        assert facts[("torch", "lit")].value is False

    def test_effect_provenance_chain_is_auditable(self):  # acceptance 4 / 6
        log, world, pipeline, executor = _setup()
        src = log.append(author="gm", channel="system", type="declaration",
                         content="the roll", audience=AUDIENCE)
        result = executor.apply(
            CreateTruth(kind="create_truth", subject="sword", predicate="drawn", value=True),
            audience=AUDIENCE, source_event_id=src.id,
        )
        effect_event = log._by_id[result.event_id]
        assert src.id in effect_event.derived_from
        assert effect_event.type == EFFECT_EVENT_TYPE


# --------------------------------------------------------------------------- #
# BeatRunner integration                                                         #
# --------------------------------------------------------------------------- #

class TestBeatRunnerWithExecutor:
    """Verify the executor integrates into BeatRunner.run() for step-6 effects."""

    def _make_runner(self, log, world, pipeline, executor):
        from unittest.mock import MagicMock
        from fable_table_engine.beat import BeatRunner
        from fable_table_engine import CharacterSheet
        from fable_table_engine.gm import StakesDecision

        adjudicator = MagicMock()
        adjudicator.evaluate.return_value = StakesDecision(
            has_stakes=False,
            reasoning="trivial",
            declared_facts=[{"subject": "test", "predicate": "ran", "value": True, "revealed": True}],
        )
        narrator = MagicMock()
        narrator.narrate.return_value = "Narration here."

        sheet = CharacterSheet(entity_id="player", concept="Adventurer")
        world.add_entity(Entity(id="player", kind="pc", name="Player"))

        return BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=MagicMock(), assembler=MagicMock(
                belief_store=MagicMock(return_value=MagicMock(events=(), claims=(), observations=()))
            ),
            adjudicator=adjudicator, narrator=narrator,
            sheets={"player": sheet},
            executor=executor,
        )

    def test_beat_with_executor_applies_declared_fact_as_create_truth(self):
        log, world, pipeline, executor = _setup()
        runner = self._make_runner(log, world, pipeline, executor)
        result = runner.run("player", "do something trivial")
        assert result.committed_fact_count == 1
        facts = committed_facts(log.all())
        assert ("test", "ran") in facts

    def test_beat_with_executor_populates_effect_results(self):
        log, world, pipeline, executor = _setup()
        runner = self._make_runner(log, world, pipeline, executor)
        result = runner.run("player", "do something trivial")
        assert len(result.effect_results) == 1
        assert result.effect_results[0].accepted

    def test_beat_without_executor_falls_back_to_pipeline_commit(self):
        log, world, pipeline, _ = _setup()
        runner = self._make_runner(log, world, pipeline, executor=None)
        result = runner.run("player", "do something trivial")
        assert result.committed_fact_count == 1
        facts = committed_facts(log.all())
        assert ("test", "ran") in facts
        assert result.effect_results == []
