"""Phase 10 acceptance tests — Atomic Session and Replayable Scene State.

Invariants exercised:
  1. Restarting cannot silently reopen a closed connection or relight a darkened zone.
  2. Scene/perception state survives restart unchanged.
  3. A persistence failure (or audit block) leaves no partial durable beat.
  4. Replaying events into fresh state produces the same canon ledger as the
     persisted materialized projection.
  5. Secrecy-relevant state fails closed, not permissive, on uncertainty.

All SQLite-backed tests use tmp_path so nothing leaks between runs.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fable_table_engine import (
    Auditor,
    AuditFlag,
    AuditResult,
    AuditTier,
    BeatResult,
    BeatRunner,
    CharacterSheet,
    CommitPipeline,
    Commitment,
    ContextAssembler,
    Entity,
    EventLog,
    SQLiteScene,
    WorldState,
    open_session,
)
from fable_table_engine.access import committed_facts, canon_ledger
from fable_table_engine.gm import StakesDecision
from fable_table_engine.rules import RulesEngine
from fable_table_engine.dice import DiceService


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _mock_adjudicator(has_stakes=False, declared_facts=None):
    """AdjudicatorGM that returns a deterministic StakesDecision."""
    adj = MagicMock()
    adj.evaluate.return_value = StakesDecision(
        has_stakes=has_stakes,
        reasoning="test",
        skill_rating=2 if has_stakes else None,
        tn=10 if has_stakes else None,
        declared_facts=declared_facts or [],
    )
    return adj


def _mock_narrator(text="Narration."):
    nar = MagicMock()
    nar.narrate.return_value = text
    return nar


def _mock_auditor(post_narration_blocking=False):
    aud = MagicMock(spec=Auditor)
    clean = AuditResult(passed=True, flags=[])
    blocking_flag = AuditFlag(
        tier=AuditTier.CRITICAL,
        category="test",
        description="blocked for test",
    )
    blocked = AuditResult(passed=False, flags=[blocking_flag])
    aud.check_commitments.return_value = clean
    aud.check_narration.return_value = blocked if post_narration_blocking else clean
    return aud


def _minimal_runner(log, world, adjudicator=None, narrator=None, auditor=None,
                    extra_sheets=None):
    """BeatRunner wired to the given log/world, with mocked GM components."""
    import random
    dice = DiceService(log, rng=random.Random(42))
    rules = RulesEngine(log, dice)
    pipeline = CommitPipeline(log)
    assembler = ContextAssembler(log)  # no scene — tests here don't need perception
    sheets = {"player": CharacterSheet(entity_id="player", concept="test")}
    if extra_sheets:
        sheets.update(extra_sheets)
    return BeatRunner(
        log=log,
        world=world,
        pipeline=pipeline,
        rules=rules,
        assembler=assembler,
        adjudicator=adjudicator or _mock_adjudicator(),
        narrator=narrator or _mock_narrator(),
        sheets=sheets,
        auditor=auditor,
    ), pipeline


# --------------------------------------------------------------------------- #
# Scene persistence                                                             #
# --------------------------------------------------------------------------- #

class TestScenePersistence:

    def test_dark_zone_survives_restart(self, tmp_path):
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_zone("crypt")
        scene.darken("crypt")
        assert not scene.lit("crypt")
        log.close()

        log2, world2, scene2 = open_session(db)
        assert not scene2.lit("crypt")  # invariant 1: restart cannot relight
        log2.close()

    def test_closed_connection_survives_restart(self, tmp_path):
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_zone("hall")
        world.add_zone("vault")
        world.connect("hall", "vault")
        scene.close("hall", "vault")
        assert not scene.transmits("hall", "vault")
        log.close()

        log2, world2, scene2 = open_session(db)
        assert not scene2.transmits("hall", "vault")  # invariant 1: restart cannot reopen
        log2.close()

    def test_multiple_scene_changes_survive_restart(self, tmp_path):
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_zone("a")
        world.add_zone("b")
        world.add_zone("c")
        world.connect("a", "b")
        world.connect("b", "c")
        scene.darken("a")
        scene.darken("b")
        scene.close("a", "b")
        log.close()

        log2, world2, scene2 = open_session(db)
        assert not scene2.lit("a")
        assert not scene2.lit("b")
        assert scene2.lit("c")  # c was never darkened
        assert not scene2.transmits("a", "b")
        assert scene2.transmits("b", "c")  # b<->c was never closed
        log2.close()

    def test_illuminate_persists(self, tmp_path):
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_zone("room")
        scene.darken("room")
        scene.illuminate("room")  # undo the darken
        assert scene.lit("room")
        log.close()

        log2, world2, scene2 = open_session(db)
        assert scene2.lit("room")
        log2.close()

    def test_open_connection_persists(self, tmp_path):
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_zone("x")
        world.add_zone("y")
        world.connect("x", "y")
        scene.close("x", "y")
        scene.open_connection("x", "y")  # undo the close
        assert scene.transmits("x", "y")
        log.close()

        log2, world2, scene2 = open_session(db)
        assert scene2.transmits("x", "y")
        log2.close()

    def test_scene_default_is_permissive_on_fresh_session(self, tmp_path):
        """A fresh session starts permissive; only explicit changes restrict perception."""
        log, world, scene = open_session(tmp_path / "session.db")
        world.add_zone("market")
        world.add_zone("alley")
        world.connect("market", "alley")
        assert scene.lit("market")
        assert scene.transmits("market", "alley")
        log.close()

    def test_perception_result_identical_after_restart(self, tmp_path):
        """After restart, who-can-see-what matches pre-restart state (invariant 2)."""
        from fable_table_engine.perception import perceivers, Stimulus

        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_zone("main")
        world.add_zone("side")
        world.connect("main", "side")
        world.add_entity(Entity(id="alice", kind="pc", name="Alice"))
        world.add_entity(Entity(id="bob", kind="npc", name="Bob"))
        world.place("alice", "main")
        world.place("bob", "side")
        # Close the connection — bob cannot hear alice
        scene.close("main", "side")
        stim = Stimulus(modality="auditory", volume="loud")
        before = perceivers(scene, origin="main", actor="alice", stimulus=stim)
        assert "bob" not in before
        log.close()

        log2, world2, scene2 = open_session(db)
        after = perceivers(scene2, origin="main", actor="alice", stimulus=stim)
        assert after == before  # identical perception after restart
        log2.close()

    def test_sqlite_scene_is_instance_of_scene(self, tmp_path):
        from fable_table_engine.perception import Scene
        log, world, scene = open_session(tmp_path / "session.db")
        assert isinstance(scene, Scene)
        assert isinstance(scene, SQLiteScene)
        log.close()


# --------------------------------------------------------------------------- #
# Atomic beat transactions                                                      #
# --------------------------------------------------------------------------- #

class TestAtomicBeat:

    def test_successful_beat_commits_atomically(self, tmp_path):
        """Fact commit and narration event appear together after restart."""
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_entity(Entity(id="player", kind="pc", name="Player"))
        runner, pipeline = _minimal_runner(
            log, world,
            adjudicator=_mock_adjudicator(
                has_stakes=False,
                declared_facts=[{"subject": "gate", "predicate": "state",
                                 "value": "barred", "revealed": True}],
            ),
        )
        result = runner.run("player", "bars the gate")
        assert not result.beat_aborted
        assert result.committed_fact_count == 1
        log.close()

        # Reload: both the commit event and narration event should be present
        log2, _w, _s = open_session(db)
        facts = canon_ledger(log2.all())
        assert ("gate", "state") in facts
        narrations = [e for e in log2.all() if e.type == "narration"]
        assert len(narrations) == 1
        log2.close()

    def test_post_audit_block_rolls_back_committed_facts(self, tmp_path):
        """When post-narration audit blocks, step-6 fact commits are rolled back (invariant 3)."""
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_entity(Entity(id="player", kind="pc", name="Player"))
        blocking_auditor = _mock_auditor(post_narration_blocking=True)
        runner, pipeline = _minimal_runner(
            log, world,
            adjudicator=_mock_adjudicator(
                has_stakes=False,
                declared_facts=[{"subject": "vault", "predicate": "state",
                                 "value": "open", "revealed": True}],
            ),
            auditor=blocking_auditor,
        )
        result = runner.run("player", "opens the vault")
        assert result.beat_aborted
        assert result.committed_fact_count == 1  # the runner counted the intended commit

        # In-memory: facts should be rolled back
        facts_in_memory = canon_ledger(log.all())
        assert ("vault", "state") not in facts_in_memory
        log.close()

        # After restart: facts must not be in the DB (rolled back atomically)
        log2, _w, _s = open_session(db)
        facts_reloaded = canon_ledger(log2.all())
        assert ("vault", "state") not in facts_reloaded
        narrations = [e for e in log2.all() if e.type == "narration"]
        assert narrations == []  # narration was also never written
        log2.close()

    def test_in_memory_beat_unaffected_by_no_op_transaction(self):
        """BeatRunner with in-memory log: transaction() is a no-op; behaviour unchanged."""
        from fable_table_engine.event_log import EventLog as InMemoryLog

        log = InMemoryLog()
        world = WorldState()
        world.add_entity(Entity(id="player", kind="pc", name="Player"))
        runner, pipeline = _minimal_runner(
            log, world,
            adjudicator=_mock_adjudicator(
                has_stakes=False,
                declared_facts=[{"subject": "door", "predicate": "state",
                                 "value": "open", "revealed": True}],
            ),
        )
        result = runner.run("player", "opens the door")
        assert not result.beat_aborted
        assert result.committed_fact_count == 1
        facts = canon_ledger(log.all())
        assert ("door", "state") in facts

    def test_exception_mid_transaction_rolls_back_all_writes(self, tmp_path):
        """A raw exception inside transaction() rolls back all writes atomically."""
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_zone("inn")
        scene.darken("inn")  # scene change before the tx — should persist
        log.close()

        log2, world2, scene2 = open_session(db)
        # Start a transaction that writes some events then raises
        try:
            with log2.transaction():
                log2.append(
                    author="gm", channel="public", type="narration",
                    content="should be rolled back",
                    audience=("gm",), visibility="content",
                )
                raise RuntimeError("simulated mid-beat crash")
        except RuntimeError:
            pass

        # In-memory: rolled back
        assert not any(e.type == "narration" for e in log2.all())
        log2.close()

        # DB: rolled back
        log3, _w, scene3 = open_session(db)
        assert not any(e.type == "narration" for e in log3.all())
        # Scene change from before the failed tx must still be there (it was committed)
        assert not scene3.lit("inn")
        log3.close()

    def test_beat_without_facts_commits_narration_only(self, tmp_path):
        """A no-stakes beat (no fact commit) still commits the narration atomically."""
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_entity(Entity(id="player", kind="pc", name="Player"))
        runner, _p = _minimal_runner(log, world, adjudicator=_mock_adjudicator(has_stakes=False))
        result = runner.run("player", "looks around")
        assert not result.beat_aborted
        log.close()

        log2, _w, _s = open_session(db)
        narrations = [e for e in log2.all() if e.type == "narration"]
        assert len(narrations) == 1
        assert narrations[0].content == "Narration."
        log2.close()


# --------------------------------------------------------------------------- #
# Whisper privacy across restart                                               #
# --------------------------------------------------------------------------- #

class TestWhisperPrivacyAfterRestart:

    def test_whisper_absent_from_third_party_projection_after_restart(self, tmp_path):
        """A whisper that was private before restart remains private after restart."""
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_entity(Entity(id="player", kind="pc", name="Player"))
        world.add_entity(Entity(id="vale", kind="npc", name="Vale"))
        world.add_entity(Entity(id="rook", kind="npc", name="Rook"))

        runner, _ = _minimal_runner(
            log, world,
            extra_sheets={
                "vale": CharacterSheet(entity_id="vale", concept="npc"),
                "rook": CharacterSheet(entity_id="rook", concept="npc"),
            },
        )
        result = runner.run("player", "whispers to vale", channel="whisper", target="vale")
        assert not result.beat_aborted
        assert "rook" not in log.get(result.narration_event_id).audience
        log.close()

        # After restart, rook still cannot see the whisper
        log2, _w, _s = open_session(db)
        rook_view = log2.project_for("rook")
        narration_ids = {e.id for e in rook_view if e.type == "narration"}
        assert result.narration_event_id not in narration_ids
        log2.close()


# --------------------------------------------------------------------------- #
# Replay consistency                                                            #
# --------------------------------------------------------------------------- #

class TestReplayConsistency:

    def test_canon_ledger_from_replay_matches_materialized(self, tmp_path):
        """Replaying events into a fresh pipeline produces the same canon as the persisted state."""
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_entity(Entity(id="player", kind="pc", name="Player"))
        runner, pipeline = _minimal_runner(
            log, world,
            adjudicator=_mock_adjudicator(
                has_stakes=False,
                declared_facts=[
                    {"subject": "innkeeper", "predicate": "attitude",
                     "value": "hostile", "revealed": True},
                    {"subject": "door", "predicate": "state",
                     "value": "locked", "revealed": True},
                ],
            ),
        )
        runner.run("player", "angers the innkeeper")
        # Materialized state (from persistent pipeline)
        materialized = pipeline.canon_ledger()
        log.close()

        # Reload from DB and replay into a fresh pipeline
        log2, _w, _s = open_session(db)
        replayed = canon_ledger(log2.all())
        assert replayed == materialized
        log2.close()

    def test_entity_position_from_events_matches_materialized(self, tmp_path):
        """World state rebuilt by reloading the DB matches the in-session state."""
        db = tmp_path / "session.db"

        log, world, scene = open_session(db)
        world.add_zone("inn")
        world.add_zone("alley")
        world.connect("inn", "alley")
        world.add_entity(Entity(id="player", kind="pc", name="Player"))
        world.place("player", "inn")
        log.close()

        # Second session: world state is identical
        log2, world2, scene2 = open_session(db)
        assert world2.zone_of("player") == "inn"
        assert world2.are_connected("inn", "alley")
        log2.close()

    def test_multiple_beats_accumulate_canon_consistently(self, tmp_path):
        """Multiple beats across two sessions leave a consistent, growing canon ledger."""
        db = tmp_path / "session.db"

        # Session 1: one fact
        log, world, scene = open_session(db)
        world.add_entity(Entity(id="player", kind="pc", name="Player"))
        runner, pipeline = _minimal_runner(
            log, world,
            adjudicator=_mock_adjudicator(
                declared_facts=[{"subject": "cult", "predicate": "location",
                                 "value": "temple", "revealed": True}],
            ),
        )
        runner.run("player", "discovers the cult location")
        log.close()

        # Session 2: another fact added
        log2, world2, scene2 = open_session(db)
        world2.add_entity(Entity(id="vale", kind="npc", name="Vale"))
        runner2, pipeline2 = _minimal_runner(
            log2, world2,
            extra_sheets={"vale": CharacterSheet(entity_id="vale", concept="npc")},
            adjudicator=_mock_adjudicator(
                declared_facts=[{"subject": "duke", "predicate": "role",
                                 "value": "funder", "revealed": True}],
            ),
        )
        runner2.run("vale", "exposes the duke")
        facts = pipeline2.canon_ledger()
        assert ("cult", "location") in facts   # fact from session 1 still present
        assert ("duke", "role") in facts        # fact from session 2 added
        log2.close()
