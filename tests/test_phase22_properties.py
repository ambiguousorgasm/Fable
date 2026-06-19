"""Phase 22 property / invariant tests.

These tests verify structural invariants of the deterministic core that must
hold for any input — not just the seeded golden transcripts. They are the
machine-checkable form of the five CORE principles (CORE §1):

1. Determinism boundary: dice/rules/state are code-owned; voice is model-owned.
2. POV partitioning: projection is a strict subset of log events.
3. Blackboard not mesh: agents read filtered state, never each other's raw output.
4. Honesty enforceability: no event in player projection that player wasn't entitled to.
5. Fidelity tiering: committed facts survive close/reopen identically.

Test categories
---------------
A. Log append-only monotonicity
B. Projection subset and audience invariant
C. Secrecy: GM-internal events absent from player projection
D. Belief store determinism and idempotence
E. Canon ledger consistency with committed_facts
F. Transaction atomicity
G. Replay: closed+reopened session gives same derived state
H. CommitPipeline conflict detection
"""
from __future__ import annotations

import random
import tempfile
from itertools import combinations
from unittest.mock import MagicMock

import pytest

from fable_table_engine.access import CommitPipeline, CanonConflictError
from fable_table_engine.beat import BeatRunner, ActionLifecycleState
from fable_table_engine.character_sheet import CharacterSheet
from fable_table_engine.context import ContextAssembler
from fable_table_engine.dice import DiceService
from fable_table_engine.effects import EffectExecutor
from fable_table_engine.event_log import EventLog
from fable_table_engine.events import Event, Commitment
from fable_table_engine.gm import AdjudicatorGM, NarratorGM
from fable_table_engine.perception import Scene
from fable_table_engine.provider import ModelGateway, TelemetrySink
from fable_table_engine.rules import RulesEngine
from fable_table_engine.world_state import WorldState, Entity


# --------------------------------------------------------------------------- #
# Test helpers                                                                  #
# --------------------------------------------------------------------------- #

def _gateway(tool_name: str, data: dict):
    block = MagicMock(); block.type = "tool_use"; block.name = tool_name; block.input = data
    resp = MagicMock(); resp.content = [block]
    client = MagicMock(); client.messages.create = MagicMock(return_value=resp)
    return ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)


def _text_gateway(text: str = "Done."):
    block = MagicMock(); block.text = text
    resp = MagicMock(); resp.content = [block]
    client = MagicMock(); client.messages.create = MagicMock(return_value=resp)
    return ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)


def _adj_data(facts=None, has_stakes=False):
    return {
        "has_stakes": has_stakes,
        "reasoning": "ok",
        "action_domain": "social",
        "skill": None, "tn": None,
        "declared_facts": facts or [],
        "exposure": 0, "effect": "standard",
        "consequence_palette": {}, "triumph_effects": [],
        "trade_options": [], "trade_default": "Balanced",
        "edge_label": None, "seam": False, "narrative_hint": "ok",
    }


def _setup(facts=None, has_stakes=False, seed=0):
    log = EventLog()
    world = WorldState()
    world.add_zone("hall")
    world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
    world.place("hero", "hall")
    pipeline = CommitPipeline(log)
    dice = DiceService(log, rng=random.Random(seed))
    rules = RulesEngine(log, dice)
    executor = EffectExecutor(log, world, pipeline)
    assembler = ContextAssembler(log, Scene(world))
    adj = AdjudicatorGM(_gateway("adjudicate_action", _adj_data(facts, has_stakes)))
    narr = NarratorGM(_text_gateway())
    runner = BeatRunner(
        log=log, world=world, pipeline=pipeline, rules=rules,
        assembler=assembler, adjudicator=adj, narrator=narr,
        sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
        executor=executor,
    )
    return log, world, pipeline, assembler, runner


# --------------------------------------------------------------------------- #
# A. Log append-only monotonicity                                                #
# --------------------------------------------------------------------------- #

class TestLogMonotonicity:

    def test_log_count_increases_after_append(self):
        log = EventLog()
        assert len(log.all()) == 0
        log.append(author="system", channel="system", type="test",
                   content="x", audience=("a",), visibility="content")
        assert len(log.all()) == 1

    def test_log_count_never_decreases(self):
        log = EventLog()
        counts = []
        for i in range(5):
            log.append(author="gm", channel="system", type="test",
                       content=str(i), audience=("gm",), visibility="content")
            counts.append(len(log.all()))
        assert counts == sorted(counts)
        assert all(c > 0 for c in counts)

    def test_log_events_are_immutable_tuples(self):
        log = EventLog()
        log.append(author="a", channel="system", type="t", content="c",
                   audience=("a",), visibility="content")
        snap1 = log.all()
        log.append(author="b", channel="system", type="t", content="c",
                   audience=("b",), visibility="content")
        snap2 = log.all()
        assert len(snap2) == len(snap1) + 1
        # Earlier snapshot is unaffected.
        assert len(snap1) == 1

    def test_beat_appends_events_to_log(self):
        log, _, _, _, runner = _setup()
        before = len(log.all())
        runner.run("hero", "look around")
        assert len(log.all()) > before

    def test_second_beat_appends_more_events(self):
        log, _, _, _, runner = _setup()
        runner.run("hero", "first")
        after_one = len(log.all())
        # Re-build runner with fresh mocks (same log/world).
        runner2_adj = AdjudicatorGM(_gateway("adjudicate_action", _adj_data()))
        runner2_narr = NarratorGM(_text_gateway())
        from fable_table_engine.beat import BeatRunner
        log_ref, world_ref = log, runner._world  # noqa: SLF001
        pipeline = CommitPipeline(log_ref)
        dice = DiceService(log_ref, rng=random.Random(1))
        rules = RulesEngine(log_ref, dice)
        executor = EffectExecutor(log_ref, world_ref, pipeline)
        assembler = ContextAssembler(log_ref, Scene(world_ref))
        runner2 = BeatRunner(
            log=log_ref, world=world_ref, pipeline=pipeline, rules=rules,
            assembler=assembler, adjudicator=runner2_adj, narrator=runner2_narr,
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
            executor=executor,
        )
        runner2.run("hero", "second")
        assert len(log.all()) > after_one


# --------------------------------------------------------------------------- #
# B. Projection subset and audience invariant                                    #
# --------------------------------------------------------------------------- #

class TestProjectionInvariant:

    def _run_beat_and_get_events(self, facts=None):
        log, _, _, assembler, runner = _setup(facts)
        runner.run("hero", "explore")
        raw_by_id = {e.id: e for e in log.all()}
        player_events = list(assembler.belief_store("hero").events)
        gm_events = list(assembler.belief_store("gm").events)
        return raw_by_id, player_events, gm_events

    def test_player_projection_is_subset_of_log_by_id(self):
        raw_by_id, player_events, _ = self._run_beat_and_get_events()
        for pe in player_events:
            assert pe.id in raw_by_id, f"Projected event {pe.id!r} not in raw log"

    def test_gm_projection_is_subset_of_log_by_id(self):
        raw_by_id, _, gm_events = self._run_beat_and_get_events()
        for ge in gm_events:
            assert ge.id in raw_by_id, f"GM projected event {ge.id!r} not in raw log"

    def test_every_player_projected_event_has_hero_in_audience(self):
        """Cross-reference projected event IDs against raw log audience."""
        raw_by_id, player_events, _ = self._run_beat_and_get_events()
        for pe in player_events:
            raw = raw_by_id[pe.id]
            assert "hero" in raw.audience, (
                f"Event {pe.type!r} projected to player but hero not in audience: "
                f"{raw.audience}"
            )

    def test_every_gm_projected_event_has_gm_in_audience(self):
        raw_by_id, _, gm_events = self._run_beat_and_get_events()
        for ge in gm_events:
            raw = raw_by_id[ge.id]
            assert "gm" in raw.audience, (
                f"Event {ge.type!r} projected to GM but gm not in audience: "
                f"{raw.audience}"
            )

    def test_player_projected_count_leq_total_log_count(self):
        raw_by_id, player_events, _ = self._run_beat_and_get_events()
        assert len(player_events) <= len(raw_by_id)

    def test_gm_projected_count_leq_total_log_count(self):
        raw_by_id, _, gm_events = self._run_beat_and_get_events()
        assert len(gm_events) <= len(raw_by_id)

    def test_gm_receives_at_least_as_many_events_as_player(self):
        _, player_events, gm_events = self._run_beat_and_get_events()
        assert len(gm_events) >= len(player_events)

    def test_events_not_in_audience_absent_from_projection(self):
        """Introduce a third entity 'npc'; verify it doesn't appear in player projection."""
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        # Append event visible to NPC only.
        log.append(author="gm", channel="system", type="secret",
                   content="npc whisper", audience=("npc",), visibility="content")
        # Append public event.
        log.append(author="gm", channel="public", type="narration",
                   content="public line", audience=("hero", "gm"), visibility="content")
        assembler = ContextAssembler(log, Scene(world))
        player_store = assembler.belief_store("hero")
        player_ids = {pe.id for pe in player_store.events}
        all_events = log.all()
        secret_event = all_events[0]
        assert secret_event.id not in player_ids
        assert len(player_store.events) == 1  # only the public event


# --------------------------------------------------------------------------- #
# C. Secrecy: GM-internal lifecycle events absent from player                    #
# --------------------------------------------------------------------------- #

class TestSecrecyInvariant:

    GM_INTERNAL_STATES = {
        ActionLifecycleState.VALIDATING.value,
        ActionLifecycleState.ADJUDICATING.value,
        ActionLifecycleState.APPLYING_EFFECTS.value,
        ActionLifecycleState.NARRATING.value,
    }

    def _player_lifecycle_contents(self, facts=None):
        log, _, _, assembler, runner = _setup(facts)
        runner.run("hero", "act")
        store = assembler.belief_store("hero")
        return [
            pe.content for pe in store.events
            if pe.type == "action_lifecycle"
        ]

    def test_validating_absent_from_player_projection(self):
        lc = self._player_lifecycle_contents()
        assert ActionLifecycleState.VALIDATING.value not in lc

    def test_adjudicating_absent_from_player_projection(self):
        lc = self._player_lifecycle_contents()
        assert ActionLifecycleState.ADJUDICATING.value not in lc

    def test_applying_effects_absent_from_player_projection(self):
        lc = self._player_lifecycle_contents()
        assert ActionLifecycleState.APPLYING_EFFECTS.value not in lc

    def test_narrating_absent_from_player_projection(self):
        lc = self._player_lifecycle_contents()
        assert ActionLifecycleState.NARRATING.value not in lc

    def test_no_gm_internal_content_in_player_projection_multi_beat(self):
        log, _, _, assembler, runner = _setup()
        for action in ["move", "look", "speak"]:
            # Rebuild adjudicator per beat to avoid mock exhaustion.
            adj = AdjudicatorGM(_gateway("adjudicate_action", _adj_data()))
            narr = NarratorGM(_text_gateway())
            pipeline = CommitPipeline(log)
            dice = DiceService(log, rng=random.Random(0))
            rules = RulesEngine(log, dice)
            executor = EffectExecutor(log, runner._world, pipeline)
            assembler2 = ContextAssembler(log, Scene(runner._world))
            r = BeatRunner(
                log=log, world=runner._world, pipeline=pipeline, rules=rules,
                assembler=assembler2, adjudicator=adj, narrator=narr,
                sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
                executor=executor,
            )
            r.run("hero", action)

        store = assembler2.belief_store("hero")  # noqa: F821
        gm_internal = [
            pe for pe in store.events
            if pe.type == "action_lifecycle"
            and pe.content in self.GM_INTERNAL_STATES
        ]
        assert gm_internal == [], \
            f"GM-internal states in player projection: {[e.content for e in gm_internal]}"

    def test_gm_private_event_never_in_player_projection(self):
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        # Append GM-only event.
        log.append(author="gm", channel="system", type="adjudicator_note",
                   content="HIDDEN GM REASONING", audience=("gm",), visibility="content")
        log.append(author="gm", channel="public", type="narration",
                   content="Visible narration", audience=("hero", "gm"), visibility="content")
        assembler = ContextAssembler(log, Scene(world))
        player_store = assembler.belief_store("hero")
        player_contents = [pe.content for pe in player_store.events if pe.content]
        assert "HIDDEN GM REASONING" not in player_contents
        assert "Visible narration" in player_contents


# --------------------------------------------------------------------------- #
# D. Belief store determinism and idempotence                                    #
# --------------------------------------------------------------------------- #

class TestBeliefStoreDeterminism:

    def test_belief_store_is_idempotent(self):
        """Calling belief_store() twice on an unchanged log returns equal content."""
        log, _, _, assembler, runner = _setup(
            facts=[{"subject": "key", "predicate": "found", "value": True, "revealed": True}]
        )
        runner.run("hero", "search")
        store1 = assembler.belief_store("hero")
        store2 = assembler.belief_store("hero")
        assert store1.value_of("key", "found") == store2.value_of("key", "found")
        assert len(store1.events) == len(store2.events)
        assert tuple(e.id for e in store1.events) == tuple(e.id for e in store2.events)

    def test_belief_store_is_unchanged_by_observation(self):
        """Reading a belief store does not mutate the log or beliefs."""
        log, _, _, assembler, runner = _setup()
        runner.run("hero", "act")
        n_before = len(log.all())
        _ = assembler.belief_store("hero")
        _ = assembler.belief_store("gm")
        assert len(log.all()) == n_before

    def test_gm_and_player_belief_stores_consistent_on_shared_facts(self):
        """A revealed fact committed by the beat appears in both GM and player stores."""
        log, _, _, assembler, runner = _setup(
            facts=[{"subject": "door", "predicate": "material", "value": "iron", "revealed": True}]
        )
        runner.run("hero", "examine door")
        player_store = assembler.belief_store("hero")
        gm_store = assembler.belief_store("gm")
        assert player_store.value_of("door", "material") == "iron"
        assert gm_store.value_of("door", "material") == "iron"

    def test_multiple_independent_assemblers_same_result(self):
        """Two ContextAssemblers over the same log give the same belief stores."""
        log, _, _, assembler1, runner = _setup(
            facts=[{"subject": "gem", "predicate": "color", "value": "red", "revealed": True}]
        )
        runner.run("hero", "pick up gem")
        world = runner._world
        scene = Scene(world)
        assembler2 = ContextAssembler(log, scene)
        s1 = assembler1.belief_store("hero")
        s2 = assembler2.belief_store("hero")
        assert s1.value_of("gem", "color") == s2.value_of("gem", "color")

    def test_belief_store_event_sequence_is_chronological(self):
        """Events in the player's belief store are in log-append order."""
        log, _, _, assembler, runner = _setup()
        runner.run("hero", "step 1")
        # Run a second beat.
        adj = AdjudicatorGM(_gateway("adjudicate_action", _adj_data()))
        narr = NarratorGM(_text_gateway())
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(1))
        rules = RulesEngine(log, dice)
        executor = EffectExecutor(log, runner._world, pipeline)
        assembler2 = ContextAssembler(log, Scene(runner._world))
        BeatRunner(
            log=log, world=runner._world, pipeline=pipeline, rules=rules,
            assembler=assembler2, adjudicator=adj, narrator=narr,
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
            executor=executor,
        ).run("hero", "step 2")
        store = assembler2.belief_store("hero")
        seqs = [pe.sequence for pe in store.events]
        assert seqs == list(range(len(seqs)))


# --------------------------------------------------------------------------- #
# E. Canon ledger consistency with committed_facts                               #
# --------------------------------------------------------------------------- #

class TestCanonConsistency:

    def test_committed_fact_appears_in_canon_ledger(self):
        log, _, pipeline, _, runner = _setup(
            facts=[{"subject": "statue", "predicate": "destroyed", "value": True, "revealed": True}]
        )
        runner.run("hero", "smash it")
        canon = pipeline.canon_ledger()
        assert ("statue", "destroyed") in canon
        assert canon[("statue", "destroyed")].value is True

    def test_committed_fact_appears_in_committed_facts(self):
        from fable_table_engine.access import committed_facts
        log, _, pipeline, _, runner = _setup(
            facts=[{"subject": "gate", "predicate": "open", "value": True, "revealed": True}]
        )
        runner.run("hero", "push gate")
        facts = committed_facts(log.all())
        assert ("gate", "open") in facts
        assert facts[("gate", "open")].value is True

    def test_canon_ledger_and_committed_facts_agree(self):
        """Both derivations of canon state must be consistent."""
        from fable_table_engine.access import committed_facts
        log, _, pipeline, _, runner = _setup(
            facts=[{"subject": "amulet", "predicate": "held_by", "value": "hero", "revealed": True}]
        )
        runner.run("hero", "grab amulet")
        canon = pipeline.canon_ledger()
        facts = committed_facts(log.all())
        for key in canon:
            assert key in facts, f"Canon has {key!r} but committed_facts does not"
            assert canon[key].value == facts[key].value
        for key in facts:
            assert key in canon, f"committed_facts has {key!r} but canon does not"

    def test_two_beats_accumulate_distinct_facts(self):
        log, _, pipeline, _, runner = _setup(
            facts=[{"subject": "chest", "predicate": "open", "value": True, "revealed": True}]
        )
        runner.run("hero", "open chest")
        # Second beat — different fact.
        adj2 = AdjudicatorGM(_gateway("adjudicate_action", _adj_data(
            facts=[{"subject": "coin", "predicate": "found", "value": True, "revealed": True}]
        )))
        narr2 = NarratorGM(_text_gateway())
        pipeline2 = CommitPipeline(log)
        dice2 = DiceService(log, rng=random.Random(1))
        rules2 = RulesEngine(log, dice2)
        executor2 = EffectExecutor(log, runner._world, pipeline2)
        assembler2 = ContextAssembler(log, Scene(runner._world))
        BeatRunner(
            log=log, world=runner._world, pipeline=pipeline2, rules=rules2,
            assembler=assembler2, adjudicator=adj2, narrator=narr2,
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
            executor=executor2,
        ).run("hero", "take coins")
        canon = pipeline2.canon_ledger()
        assert ("chest", "open") in canon
        assert ("coin", "found") in canon


# --------------------------------------------------------------------------- #
# F. Transaction atomicity                                                        #
# --------------------------------------------------------------------------- #

class TestTransactionAtomicity:

    def test_ooc_beat_appends_only_lifecycle_events(self):
        """OOC beat skips adjudicator, narrator, commit — lifecycle only."""
        log, _, _, _, runner = _setup()
        log_before = len(log.all())
        result = runner.run("hero", "//ooc query", channel="ooc")
        assert result.beat_aborted is False
        # Only submitted + committed should fire for OOC.
        lc = [e for e in log.all() if e.type == "action_lifecycle"]
        # Exactly 2 lifecycle events: submitted + committed.
        ooc_lc = lc  # only events from this beat.
        assert len(ooc_lc) == 2
        assert ooc_lc[0].content == ActionLifecycleState.SUBMITTED.value
        assert ooc_lc[1].content == ActionLifecycleState.COMMITTED.value

    def test_aborted_beat_produces_aborted_result(self):
        """With an auditor that blocks, the beat aborts cleanly."""
        from fable_table_engine.auditor import Auditor, AuditResult, AuditFlag, AuditTier
        log, world, pipeline, assembler, _ = _setup()
        # Create an auditor that always blocks.
        blocking_auditor = MagicMock(spec=Auditor)
        blocking_flag = AuditFlag(tier=AuditTier.CRITICAL, category="test", description="blocked")
        blocking_result = AuditResult(passed=False, flags=[blocking_flag])
        blocking_auditor.check_commitments = MagicMock(return_value=blocking_result)
        adj = AdjudicatorGM(_gateway("adjudicate_action", _adj_data(
            facts=[{"subject": "x", "predicate": "y", "value": 1, "revealed": True}]
        )))
        narr = NarratorGM(_text_gateway())
        pipeline2 = CommitPipeline(log)
        dice2 = DiceService(log, rng=random.Random(0))
        rules2 = RulesEngine(log, dice2)
        executor2 = EffectExecutor(log, world, pipeline2)
        assembler2 = ContextAssembler(log, Scene(world))
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline2, rules=rules2,
            assembler=assembler2, adjudicator=adj, narrator=narr,
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
            executor=executor2, auditor=blocking_auditor,
        )
        result = runner.run("hero", "risky action")
        assert result.beat_aborted is True

    def test_aborted_beat_does_not_commit_facts(self):
        """A CRITICAL audit block must leave the canon ledger unchanged."""
        from fable_table_engine.auditor import Auditor, AuditResult, AuditFlag, AuditTier
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        pipeline = CommitPipeline(log)
        blocking_auditor = MagicMock(spec=Auditor)
        blocking_flag = AuditFlag(tier=AuditTier.CRITICAL, category="test", description="blocked")
        blocking_result = AuditResult(passed=False, flags=[blocking_flag])
        blocking_auditor.check_commitments = MagicMock(return_value=blocking_result)
        adj = AdjudicatorGM(_gateway("adjudicate_action", _adj_data(
            facts=[{"subject": "secret", "predicate": "revealed", "value": True, "revealed": True}]
        )))
        narr = NarratorGM(_text_gateway())
        pipeline2 = CommitPipeline(log)
        dice2 = DiceService(log, rng=random.Random(0))
        rules2 = RulesEngine(log, dice2)
        executor2 = EffectExecutor(log, world, pipeline2)
        assembler2 = ContextAssembler(log, Scene(world))
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline2, rules=rules2,
            assembler=assembler2, adjudicator=adj, narrator=narr,
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
            executor=executor2, auditor=blocking_auditor,
        )
        runner.run("hero", "risky action")
        canon = pipeline2.canon_ledger()
        assert ("secret", "revealed") not in canon


# --------------------------------------------------------------------------- #
# G. Replay: close+reopen gives same derived state                               #
# --------------------------------------------------------------------------- #

class TestReplay:

    def test_belief_store_survives_close_and_reopen(self):
        from fable_table_engine.persistence import open_session
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/session.db"
            log, world, scene = open_session(db)
            world.add_zone("hall")
            world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
            world.place("hero", "hall")
            pipeline = CommitPipeline(log)
            assembler = ContextAssembler(log, scene)
            adj = AdjudicatorGM(_gateway("adjudicate_action", _adj_data(
                facts=[{"subject": "relic", "predicate": "intact", "value": True, "revealed": True}]
            )))
            BeatRunner(
                log=log, world=world, pipeline=pipeline,
                rules=RulesEngine(log, DiceService(log, rng=random.Random(0))),
                assembler=assembler, adjudicator=adj,
                narrator=NarratorGM(_text_gateway()),
                sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
                executor=EffectExecutor(log, world, pipeline),
            ).run("hero", "examine relic")
            store_before = assembler.belief_store("hero")
            val_before = store_before.value_of("relic", "intact")
            event_count = len(log.all())
            log.close()

            log2, world2, scene2 = open_session(db)
            assembler2 = ContextAssembler(log2, scene2)
            store_after = assembler2.belief_store("hero")
            assert store_after.value_of("relic", "intact") == val_before
            assert len(log2.all()) == event_count
            log2.close()

    def test_canon_ledger_reconstructed_identically_after_reopen(self):
        from fable_table_engine.persistence import open_session
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/session.db"
            log, world, scene = open_session(db)
            world.add_zone("hall")
            world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
            world.place("hero", "hall")
            pipeline = CommitPipeline(log)
            assembler = ContextAssembler(log, scene)
            adj = AdjudicatorGM(_gateway("adjudicate_action", _adj_data(
                facts=[{"subject": "altar", "predicate": "defiled", "value": False, "revealed": True}]
            )))
            BeatRunner(
                log=log, world=world, pipeline=pipeline,
                rules=RulesEngine(log, DiceService(log, rng=random.Random(0))),
                assembler=assembler, adjudicator=adj,
                narrator=NarratorGM(_text_gateway()),
                sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
                executor=EffectExecutor(log, world, pipeline),
            ).run("hero", "pray at altar")
            canon_before = dict(pipeline.canon_ledger())
            log.close()

            log2, world2, scene2 = open_session(db)
            pipeline2 = CommitPipeline(log2)
            canon_after = dict(pipeline2.canon_ledger())
            assert set(canon_before.keys()) == set(canon_after.keys())
            for key in canon_before:
                assert canon_before[key].value == canon_after[key].value
            log2.close()

    def test_beat_index_and_narrations_survive_reopen(self):
        from fable_table_engine.persistence import open_session
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/session.db"
            log, world, scene = open_session(db)
            world.add_zone("hall")
            world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
            world.place("hero", "hall")
            pipeline = CommitPipeline(log)
            assembler = ContextAssembler(log, scene)
            # Run 2 beats.
            for i in range(2):
                adj = AdjudicatorGM(_gateway("adjudicate_action", _adj_data()))
                BeatRunner(
                    log=log, world=world, pipeline=pipeline,
                    rules=RulesEngine(log, DiceService(log, rng=random.Random(i))),
                    assembler=assembler, adjudicator=adj,
                    narrator=NarratorGM(_text_gateway(f"Narration {i}.")),
                    sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
                    executor=EffectExecutor(log, world, pipeline),
                ).run("hero", f"action {i}")
            beat_before = world.beat_index
            narration_count = len([e for e in log.all() if e.type == "narration"])
            log.close()

            log2, world2, scene2 = open_session(db)
            assert world2.beat_index == beat_before
            narrations2 = [e for e in log2.all() if e.type == "narration"]
            assert len(narrations2) == narration_count
            log2.close()


# --------------------------------------------------------------------------- #
# H. CommitPipeline conflict detection                                           #
# --------------------------------------------------------------------------- #

class TestCommitPipelineConflicts:

    def test_conflicting_commit_raises_canon_conflict_error(self):
        log = EventLog()
        pipeline = CommitPipeline(log)
        pipeline.commit(
            author="gm", channel="system", type="declaration",
            content="Initial fact", audience=("gm",), visibility="content",
            commitments=[Commitment(
                subject="box", predicate="open", value=True, revealed=True
            )],
        )
        with pytest.raises(CanonConflictError):
            pipeline.commit(
                author="gm", channel="system", type="declaration",
                content="Conflict", audience=("gm",), visibility="content",
                commitments=[Commitment(
                    subject="box", predicate="open", value=False, revealed=True
                )],
            )

    def test_same_value_recommit_does_not_conflict(self):
        """Committing the same (subject, predicate, value) twice is idempotent."""
        log = EventLog()
        pipeline = CommitPipeline(log)
        c = Commitment(subject="flag", predicate="planted", value=True, revealed=True)
        pipeline.commit(
            author="gm", channel="system", type="declaration",
            content="First", audience=("gm",), visibility="content",
            commitments=[c],
        )
        # Same value again — should not raise.
        pipeline.commit(
            author="gm", channel="system", type="declaration",
            content="Repeat", audience=("gm",), visibility="content",
            commitments=[c],
        )

    def test_override_bypasses_conflict_check(self):
        """Override commits are allowed even against existing canon."""
        log = EventLog()
        pipeline = CommitPipeline(log)
        pipeline.commit(
            author="gm", channel="system", type="declaration",
            content="Original", audience=("gm",), visibility="content",
            commitments=[Commitment(
                subject="gate", predicate="locked", value=True, revealed=True
            )],
        )
        # Override should succeed without raising.
        from fable_table_engine.access import OVERRIDE_TYPE
        pipeline.commit(
            author="gm", channel="system", type=OVERRIDE_TYPE,
            content="Override: gate is now open",
            audience=("gm",), visibility="content",
            commitments=[Commitment(
                subject="gate", predicate="locked", value=False, revealed=True
            )],
            override=True,
            reason="GM deliberate retcon — D-008",
        )
        # Canon should reflect the override.
        canon = pipeline.canon_ledger()
        assert canon[("gate", "locked")].value is False

    def test_claim_commitment_does_not_enter_canon(self):
        """Claims (epistemic_type='claim') are NOT folded into the canon ledger."""
        log = EventLog()
        pipeline = CommitPipeline(log)
        pipeline.commit(
            author="gm", channel="public", type="narration",
            content="NPC says the vault is open", audience=("hero", "gm"),
            visibility="content",
            commitments=[Commitment(
                subject="vault", predicate="open", value=True,
                revealed=True, epistemic_type="claim",
            )],
        )
        canon = pipeline.canon_ledger()
        # Claim should not enter canon.
        assert ("vault", "open") not in canon

    def test_expired_fact_removed_from_canon(self):
        """Expiring a committed fact removes it from the canon ledger."""
        log = EventLog()
        pipeline = CommitPipeline(log)
        pipeline.commit(
            author="gm", channel="system", type="declaration",
            content="Fact exists", audience=("gm",), visibility="content",
            commitments=[Commitment(
                subject="torch", predicate="lit", value=True, revealed=True
            )],
        )
        assert ("torch", "lit") in pipeline.canon_ledger()
        pipeline.commit(
            author="gm", channel="system", type="declaration",
            content="Fact expired", audience=("gm",), visibility="content",
            commitments=[Commitment(
                subject="torch", predicate="lit", value=None,
                revealed=True, epistemic_type="expired",
            )],
        )
        assert ("torch", "lit") not in pipeline.canon_ledger()
