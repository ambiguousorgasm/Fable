"""Persistence tests — SQLiteEventLog and SQLiteWorldState (roadmap phase 1 step 6).

Every test that touches the DB uses pytest's tmp_path fixture so nothing
leaks across runs. The core invariants verified:

  1. Events survive a close/reopen cycle with all fields intact.
  2. WorldState survives a close/reopen cycle with all topology/entity state intact.
  3. The determinism boundary (mechanical capability) is still enforced after
     the SQLite subclass is introduced.
  4. open_session produces a working (log, world) pair sharing one DB file.
  5. CommitPipeline, DiceService, and RulesEngine all work with the SQLite backend.
  6. SQLiteWorldState._load() clears in-memory state before repopulating so a
     rolled-back entity does not survive in memory (regression for the missing
     self.entities.clear() bug).
"""

import pytest

from fable_table_engine import (
    Commitment,
    CommitPipeline,
    DiceService,
    DeterminismBoundaryError,
    Entity,
    RulesEngine,
    SQLiteEventLog,
    SQLiteScene,
    SQLiteWorldState,
    open_session,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _make_log(tmp_path):
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    return SQLiteEventLog(conn)


def _make_world(tmp_path):
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "world.db"))
    return SQLiteWorldState(conn)


# --------------------------------------------------------------------------- #
# SQLiteEventLog                                                                #
# --------------------------------------------------------------------------- #

class TestSQLiteEventLog:

    def test_append_and_read(self, tmp_path):
        log = _make_log(tmp_path)
        e = log.append(
            author="gm",
            channel="public",
            type="declaration",
            content="The gate is barred.",
            audience=("alice", "bob"),
            visibility="content",
        )
        assert len(log) == 1
        assert log.get(e.id) is e
        assert log.get_by_sequence(0) is e
        assert log.all() == (e,)
        log.close()

    def test_survives_restart(self, tmp_path):
        db = tmp_path / "session.db"
        import sqlite3

        # First session: write one event.
        conn1 = sqlite3.connect(str(db))
        log1 = SQLiteEventLog(conn1)
        e = log1.append(
            author="gm",
            channel="public",
            type="declaration",
            content="The tower is 100 feet tall.",
            audience=("alice",),
            visibility="content",
            commitments=[Commitment(subject="tower", predicate="height", value="100ft", revealed=True)],
        )
        original_id = e.id
        log1.close()

        # Second session: reload and verify.
        conn2 = sqlite3.connect(str(db))
        log2 = SQLiteEventLog(conn2)
        assert len(log2) == 1
        reloaded = log2.get(original_id)
        assert reloaded.id == original_id
        assert reloaded.author == "gm"
        assert reloaded.content == "The tower is 100 feet tall."
        assert reloaded.audience == ("alice",)
        assert len(reloaded.commitments) == 1
        assert reloaded.commitments[0].subject == "tower"
        assert reloaded.commitments[0].value == "100ft"
        assert reloaded.commitments[0].revealed is True
        log2.close()

    def test_sequence_preserved_across_restart(self, tmp_path):
        db = tmp_path / "session.db"
        import sqlite3

        conn1 = sqlite3.connect(str(db))
        log1 = SQLiteEventLog(conn1)
        for i in range(3):
            log1.append(author="gm", channel="public", type="declaration",
                        content=f"Event {i}", audience=("alice",))
        log1.close()

        conn2 = sqlite3.connect(str(db))
        log2 = SQLiteEventLog(conn2)
        assert len(log2) == 3
        for seq, event in enumerate(log2.all()):
            assert event.sequence == seq
            assert event.content == f"Event {seq}"
        # Next append gets sequence 3, not 0.
        e = log2.append(author="gm", channel="public", type="declaration",
                        content="Event 3", audience=("alice",))
        assert e.sequence == 3
        log2.close()

    def test_per_member_visibility_survives_restart(self, tmp_path):
        db = tmp_path / "session.db"
        import sqlite3

        conn1 = sqlite3.connect(str(db))
        log1 = SQLiteEventLog(conn1)
        log1.append(
            author="gm",
            channel="whisper",
            type="declaration",
            content="Secret message.",
            audience=("alice", "bob"),
            visibility={"alice": "content", "bob": "metadata"},
        )
        log1.close()

        conn2 = sqlite3.connect(str(db))
        log2 = SQLiteEventLog(conn2)
        e = log2.all()[0]
        assert e.visibility_for("alice") == "content"
        assert e.visibility_for("bob") == "metadata"
        log2.close()

    def test_mechanical_boundary_enforced(self, tmp_path):
        log = _make_log(tmp_path)
        with pytest.raises(DeterminismBoundaryError):
            log.append(author="gm", channel="dice", type="dice_roll",
                       content="fake roll", audience=("alice",))
        log.close()

    def test_project_for_works(self, tmp_path):
        log = _make_log(tmp_path)
        log.append(author="gm", channel="public", type="declaration",
                   content="Public.", audience=("alice", "bob"))
        log.append(author="gm", channel="whisper", type="declaration",
                   content="Secret.", audience=("alice",))
        alice_view = log.project_for("alice")
        bob_view = log.project_for("bob")
        assert len(alice_view) == 2
        assert len(bob_view) == 1
        # Per-POV contiguous index (D-013).
        assert alice_view[0].sequence == 0
        assert alice_view[1].sequence == 1
        assert bob_view[0].sequence == 0
        log.close()


# --------------------------------------------------------------------------- #
# SQLiteWorldState                                                              #
# --------------------------------------------------------------------------- #

class TestSQLiteWorldState:

    def test_zones_and_connections_survive_restart(self, tmp_path):
        db = tmp_path / "world.db"
        import sqlite3

        conn1 = sqlite3.connect(str(db))
        ws1 = SQLiteWorldState(conn1)
        ws1.add_zone("tavern")
        ws1.add_zone("street")
        ws1.connect("tavern", "street")
        conn1.close()

        conn2 = sqlite3.connect(str(db))
        ws2 = SQLiteWorldState(conn2)
        assert "tavern" in ws2.zones
        assert "street" in ws2.zones
        assert ws2.are_connected("tavern", "street")
        conn2.close()

    def test_entities_survive_restart(self, tmp_path):
        db = tmp_path / "world.db"
        import sqlite3

        conn1 = sqlite3.connect(str(db))
        ws1 = SQLiteWorldState(conn1)
        ws1.add_zone("tavern")
        ws1.add_entity(Entity(id="alice", kind="pc", name="Alice"))
        ws1.place("alice", "tavern")
        conn1.close()

        conn2 = sqlite3.connect(str(db))
        ws2 = SQLiteWorldState(conn2)
        assert "alice" in ws2.entities
        assert ws2.zone_of("alice") == "tavern"
        conn2.close()

    def test_closeness_survives_restart(self, tmp_path):
        db = tmp_path / "world.db"
        import sqlite3

        conn1 = sqlite3.connect(str(db))
        ws1 = SQLiteWorldState(conn1)
        ws1.add_entity(Entity(id="alice", kind="pc", name="Alice"))
        ws1.add_entity(Entity(id="bob", kind="npc", name="Bob"))
        ws1.set_close("alice", "bob")
        conn1.close()

        conn2 = sqlite3.connect(str(db))
        ws2 = SQLiteWorldState(conn2)
        assert ws2.are_close("alice", "bob")
        conn2.close()

    def test_validation_still_enforced(self, tmp_path):
        ws = _make_world(tmp_path)
        with pytest.raises(ValueError):
            ws.connect("nonexistent-a", "nonexistent-b")
        with pytest.raises(ValueError):
            ws.add_entity(Entity(id="alice", kind="pc", name="Alice"))
            ws.add_entity(Entity(id="alice", kind="pc", name="Alice"))  # duplicate


# --------------------------------------------------------------------------- #
# open_session factory                                                          #
# --------------------------------------------------------------------------- #

class TestOpenSession:

    def test_shared_file(self, tmp_path):
        db = tmp_path / "session.db"
        log, world, _ = open_session(db)
        log.append(author="gm", channel="public", type="declaration",
                   content="Session start.", audience=("alice",))
        world.add_zone("tavern")
        log.close()

        # Reopen and verify both stores are present in the same file.
        log2, world2, _ = open_session(db)
        assert len(log2) == 1
        assert "tavern" in world2.zones
        log2.close()

    def test_commit_pipeline_works(self, tmp_path):
        log, _world, _scene = open_session(tmp_path / "session.db")
        pipeline = CommitPipeline(log)
        pipeline.commit(
            author="gm",
            channel="public",
            content="The gate is barred.",
            audience=("alice",),
            commitments=[Commitment(subject="gate", predicate="state",
                                    value="barred", revealed=True)],
        )
        ledger = pipeline.canon_ledger()
        assert ("gate", "state") in ledger
        log.close()

    def test_dice_service_works(self, tmp_path):
        import random
        log, _world, _scene = open_session(tmp_path / "session.db")
        dice = DiceService(log, rng=random.Random(42))
        result = dice.roll(3, 6, author="alice", audience=("alice",))
        assert result.total >= 3
        assert len(log) == 1
        log.close()

    def test_rules_engine_works(self, tmp_path):
        import random
        log, _world, _scene = open_session(tmp_path / "session.db")
        dice = DiceService(log, rng=random.Random(42))
        rules = RulesEngine(log, dice)
        result = rules.resolve_check(actor="alice", skill=2, tn=10,
                                     audience=("alice",))
        assert result.band is not None
        assert len(log) == 2  # dice_roll + resolution
        log.close()

    def test_full_session_roundtrip(self, tmp_path):
        """Write a session with events and world state; reload and verify integrity."""
        db = tmp_path / "session.db"

        # --- session 1 ---
        log, world, _ = open_session(db)
        world.add_zone("inn")
        world.add_zone("alley")
        world.connect("inn", "alley")
        world.add_entity(Entity(id="player", kind="pc", name="Rook"))
        world.place("player", "inn")

        pipeline = CommitPipeline(log)
        pipeline.commit(
            author="gm",
            channel="public",
            content="The innkeeper nods at Rook.",
            audience=("player",),
            commitments=[
                Commitment(subject="innkeeper", predicate="attitude",
                           value="neutral", revealed=True),
            ],
        )
        first_event_id = log.all()[0].id
        log.close()

        # --- session 2 ---
        log2, world2, _ = open_session(db)
        assert len(log2) == 1
        assert log2.get(first_event_id).content == "The innkeeper nods at Rook."
        assert world2.zone_of("player") == "inn"
        assert world2.are_connected("inn", "alley")

        pipeline2 = CommitPipeline(log2)
        ledger = pipeline2.canon_ledger()
        assert ledger[("innkeeper", "attitude")].value == "neutral"
        log2.close()

    def test_sqlite_scene_is_returned(self, tmp_path):
        log, world, scene = open_session(tmp_path / "session.db")
        assert isinstance(scene, SQLiteScene)
        assert scene.world is world
        log.close()


# --------------------------------------------------------------------------- #
# SQLiteWorldState rollback correctness (bug: _load did not clear entities)    #
# --------------------------------------------------------------------------- #

class TestWorldStateRollback:
    """Regression suite for the missing self.entities.clear() in _load().

    Before the fix, _load() appended to the existing entities dict rather than
    replacing it. A rolled-back entity would remain in memory even though SQLite
    no longer had it.
    """

    def test_entity_added_inside_failed_transaction_is_gone_from_memory(self, tmp_path):
        """An entity added inside a transaction that raises must not appear after rollback."""
        log, world, scene = open_session(tmp_path / "session.db")
        world.add_zone("dungeon")
        world.add_entity(Entity(id="player", kind="pc", name="Player"))
        log.close()

        log2, world2, _ = open_session(tmp_path / "session.db")
        try:
            with log2.transaction():
                world2.add_entity(Entity(id="phantom", kind="npc", name="Phantom"))
                assert "phantom" in world2.entities  # present inside tx
                raise RuntimeError("forced rollback")
        except RuntimeError:
            pass

        # After rollback: phantom must not be in memory
        assert "phantom" not in world2.entities
        # Pre-existing entity must still be there
        assert "player" in world2.entities
        log2.close()

    def test_entity_added_inside_failed_transaction_absent_after_reopen(self, tmp_path):
        """After rollback and reopen the phantom entity is absent from the DB too."""
        log, world, _ = open_session(tmp_path / "session.db")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        log.close()

        log2, world2, _ = open_session(tmp_path / "session.db")
        try:
            with log2.transaction():
                world2.add_entity(Entity(id="ghost", kind="npc", name="Ghost"))
                raise RuntimeError("forced rollback")
        except RuntimeError:
            pass
        log2.close()

        # Reopen — ghost must not appear
        log3, world3, _ = open_session(tmp_path / "session.db")
        assert "ghost" not in world3.entities
        assert "hero" in world3.entities
        log3.close()

    def test_rollback_to_empty_db_clears_in_memory_entities(self, tmp_path):
        """Rollback when no world row yet existed resets all in-memory state.

        Uses open_session to ensure the shared _tx_active flag prevents
        SQLiteWorldState._save() from auto-committing inside the transaction.
        """
        log, world, _ = open_session(tmp_path / "session.db")

        # No entity saved yet — first world mutation inside a tx that rolls back
        try:
            with log.transaction():
                world.add_entity(Entity(id="wraith", kind="npc", name="Wraith"))
                assert "wraith" in world.entities
                raise RuntimeError("forced rollback")
        except RuntimeError:
            pass

        # After rollback to empty: wraith must be gone
        assert "wraith" not in world.entities
        log.close()
