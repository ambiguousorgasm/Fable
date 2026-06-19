"""Phase 21 — schema version guard, SessionManifest, and SessionManager.

Adversarial acceptance tests (Phase 21 deliverable 1):

Schema version guard:
  1. Fresh DB → ENGINE_SCHEMA_VERSION written.
  2. Resume with matching version → succeeds.
  3. Resume with wrong version → SchemaVersionError (fail-closed).
  4. SchemaVersionError closes the connection before raising.

SessionManifest:
  5. Frozen dataclass — mutation raises FrozenInstanceError.
  6. to_dict / from_dict round-trip preserves all fields.
  7. from_dict tolerates missing optional fields (last_scene_summary, player_summary).

SessionManager:
  8. list_sessions on a fresh dir returns an empty list.
  9. create returns valid (manifest, log, world, scene).
 10. Created session appears in list_sessions.
 11. Multiple creates produce independent sessions.
 12. resume restores the same manifest.
 13. Events appended before close are visible after resume.
 14. resume with unknown session_id raises KeyError.
 15. resume on a DB whose schema version was manually downgraded raises SchemaVersionError.
 16. update_manifest updates supplied fields and persists; updated_at changes.
 17. update_manifest with unknown session_id raises KeyError.
 18. update_manifest with no kwargs only bumps updated_at.
 19. list_sessions orders by updated_at descending.
"""

import sqlite3
import time

import pytest

from fable_table_engine import (
    ENGINE_SCHEMA_VERSION,
    Entity,
    SchemaVersionError,
    SessionManifest,
    SessionManager,
    open_session,
)
from fable_table_engine.persistence import _MIGRATION_REGISTRY, _apply_migrations


# --------------------------------------------------------------------------- #
# Schema version guard                                                          #
# --------------------------------------------------------------------------- #

class TestSchemaVersionGuard:
    def test_fresh_db_writes_version(self, tmp_path):
        db = tmp_path / "s.db"
        log, world, scene = open_session(db)
        log.close()
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == ENGINE_SCHEMA_VERSION

    def test_resume_matching_version_succeeds(self, tmp_path):
        db = tmp_path / "s.db"
        log, world, scene = open_session(db)
        log.close()
        # Second open should not raise.
        log2, world2, scene2 = open_session(db)
        log2.close()

    def test_resume_wrong_version_raises(self, tmp_path):
        db = tmp_path / "s.db"
        log, world, scene = open_session(db)
        log.close()
        # Overwrite stored version with a fake older version.
        conn = sqlite3.connect(str(db))
        conn.execute("UPDATE schema_version SET version = '99'")
        conn.commit()
        conn.close()
        with pytest.raises(SchemaVersionError):
            open_session(db)

    def test_schema_version_error_message_contains_versions(self, tmp_path):
        db = tmp_path / "s.db"
        log, _, _ = open_session(db)
        log.close()
        conn = sqlite3.connect(str(db))
        conn.execute("UPDATE schema_version SET version = '0'")
        conn.commit()
        conn.close()
        with pytest.raises(SchemaVersionError, match="'0'"):
            open_session(db)


# --------------------------------------------------------------------------- #
# Migration registry (Phase 22)                                                 #
# --------------------------------------------------------------------------- #

class TestMigrationRegistry:

    def test_registry_is_not_empty(self):
        assert len(_MIGRATION_REGISTRY) >= 1

    def test_all_targets_reachable_from_origin(self):
        """Every registry entry's to_version is ENGINE_SCHEMA_VERSION or another from_version."""
        all_from = set(_MIGRATION_REGISTRY.keys())
        all_to = {v[0] for v in _MIGRATION_REGISTRY.values()}
        # Every to_version except ENGINE_SCHEMA_VERSION must be a from_version
        orphans = all_to - {ENGINE_SCHEMA_VERSION} - all_from
        assert orphans == set(), f"Orphaned to_versions (not in registry): {orphans}"

    def test_walking_to_current_terminates(self):
        """Walking the registry from any known start version reaches ENGINE_SCHEMA_VERSION."""
        for start in _MIGRATION_REGISTRY:
            current = start
            seen: set[str] = set()
            while current != ENGINE_SCHEMA_VERSION:
                assert current not in seen, f"Cycle detected at {current!r}"
                seen.add(current)
                step = _MIGRATION_REGISTRY.get(current)
                assert step is not None, f"No path from {current!r}"
                current = step[0]

    def test_21_3_migrates_to_current(self, tmp_path):
        """A DB stamped 21.3 is auto-migrated to ENGINE_SCHEMA_VERSION by open_session."""
        db = tmp_path / "old.db"
        # Create a valid DB at current version, then rewind to 21.3.
        log, _, _ = open_session(db)
        log.close()
        conn = sqlite3.connect(str(db))
        conn.execute("UPDATE schema_version SET version = '21.3'")
        conn.commit()
        conn.close()
        # open_session should migrate, not raise.
        log2, _, _ = open_session(db)
        log2.close()
        # Confirm the stored version is now current.
        conn2 = sqlite3.connect(str(db))
        row = conn2.execute("SELECT version FROM schema_version").fetchone()
        conn2.close()
        assert row[0] == ENGINE_SCHEMA_VERSION

    def test_unknown_version_still_raises_schema_version_error(self, tmp_path):
        db = tmp_path / "future.db"
        log, _, _ = open_session(db)
        log.close()
        conn = sqlite3.connect(str(db))
        conn.execute("UPDATE schema_version SET version = '999.0'")
        conn.commit()
        conn.close()
        with pytest.raises(SchemaVersionError, match="999.0"):
            open_session(db)

    def test_apply_migrations_noop_on_current_version(self, tmp_path):
        """_apply_migrations is a no-op when stored == ENGINE_SCHEMA_VERSION."""
        db = tmp_path / "current.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE schema_version (version TEXT NOT NULL)")
        conn.execute("INSERT INTO schema_version VALUES (?)", (ENGINE_SCHEMA_VERSION,))
        conn.commit()
        # Should not raise (while loop exits immediately).
        _apply_migrations(conn, ENGINE_SCHEMA_VERSION)
        conn.close()

    def test_apply_migrations_raises_on_no_path(self, tmp_path):
        db = tmp_path / "nope.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE schema_version (version TEXT NOT NULL)")
        conn.execute("INSERT INTO schema_version VALUES ('999.0')")
        conn.commit()
        with pytest.raises(SchemaVersionError):
            _apply_migrations(conn, "999.0")
        conn.close()

    def test_migration_sql_applied_in_order(self):
        """A synthetic migration with DDL is applied before the version is bumped."""
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE schema_version (version TEXT NOT NULL)")
        conn.execute("INSERT INTO schema_version VALUES ('test.0')")
        conn.commit()

        # Synthetic migration: test.0 → ENGINE_SCHEMA_VERSION (terminates the walk).
        _MIGRATION_REGISTRY["test.0"] = (
            ENGINE_SCHEMA_VERSION,
            "synthetic test migration",
            ["CREATE TABLE _migration_marker (id INTEGER)"],
        )
        try:
            _apply_migrations(conn, "test.0")
            # DDL ran.
            row = conn.execute("SELECT name FROM sqlite_master WHERE name='_migration_marker'").fetchone()
            assert row is not None
            # Version bumped to current.
            ver = conn.execute("SELECT version FROM schema_version").fetchone()[0]
            assert ver == ENGINE_SCHEMA_VERSION
        finally:
            del _MIGRATION_REGISTRY["test.0"]
        conn.close()


# --------------------------------------------------------------------------- #
# SessionManifest                                                               #
# --------------------------------------------------------------------------- #

class TestSessionManifest:
    def _make(self, **overrides) -> SessionManifest:
        defaults = dict(
            session_id="sid-1",
            campaign_id="camp-1",
            title="Test Session",
            created_at="2026-06-19T00:00:00+00:00",
            updated_at="2026-06-19T00:01:00+00:00",
            last_scene_summary="Arrived at the keep.",
            player_summary="Kael, Sable",
            db_path="/tmp/sid-1.db",
            schema_version=ENGINE_SCHEMA_VERSION,
            engine_version=ENGINE_SCHEMA_VERSION,
        )
        defaults.update(overrides)
        return SessionManifest(**defaults)

    def test_frozen(self):
        m = self._make()
        with pytest.raises(Exception):  # FrozenInstanceError is a subclass of AttributeError
            m.title = "changed"  # type: ignore[misc]

    def test_to_dict_from_dict_round_trip(self):
        m = self._make()
        assert SessionManifest.from_dict(m.to_dict()) == m

    def test_from_dict_optional_defaults(self):
        d = {
            "session_id": "s",
            "campaign_id": "c",
            "title": "T",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "db_path": "/tmp/s.db",
            "schema_version": ENGINE_SCHEMA_VERSION,
            "engine_version": ENGINE_SCHEMA_VERSION,
        }
        m = SessionManifest.from_dict(d)
        assert m.last_scene_summary == ""
        assert m.player_summary == ""

    def test_all_fields_in_to_dict(self):
        m = self._make()
        d = m.to_dict()
        for field in (
            "session_id", "campaign_id", "title", "created_at", "updated_at",
            "last_scene_summary", "player_summary", "db_path",
            "schema_version", "engine_version",
        ):
            assert field in d


# --------------------------------------------------------------------------- #
# SessionManager                                                                #
# --------------------------------------------------------------------------- #

class TestSessionManager:
    def test_list_sessions_empty_initially(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        assert mgr.list_sessions() == []

    def test_create_returns_valid_components(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        manifest, log, world, scene = mgr.create("camp-1", "Session One")
        try:
            assert manifest.campaign_id == "camp-1"
            assert manifest.title == "Session One"
            assert manifest.schema_version == ENGINE_SCHEMA_VERSION
            assert manifest.session_id != ""
            # log, world, scene should be functional
            world.add_zone("zone_a")
            assert "zone_a" in world.zones
        finally:
            log.close()

    def test_created_session_appears_in_list(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        manifest, log, _, _ = mgr.create("camp-1", "My Session")
        log.close()
        sessions = mgr.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].session_id == manifest.session_id
        assert sessions[0].title == "My Session"

    def test_multiple_creates_independent(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        m1, log1, _, _ = mgr.create("camp-1", "First")
        log1.close()
        m2, log2, _, _ = mgr.create("camp-1", "Second")
        log2.close()
        assert m1.session_id != m2.session_id
        assert len(mgr.list_sessions()) == 2

    def test_schema_version_written_in_db(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        manifest, log, _, _ = mgr.create("camp-1", "Session")
        log.close()
        conn = sqlite3.connect(manifest.db_path)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        conn.close()
        assert row[0] == ENGINE_SCHEMA_VERSION

    def test_resume_returns_correct_manifest(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        m1, log, _, _ = mgr.create("camp-1", "Resumed Session", player_summary="Kael")
        log.close()
        m2, log2, _, _ = mgr.resume(m1.session_id)
        log2.close()
        assert m2.session_id == m1.session_id
        assert m2.title == "Resumed Session"
        assert m2.player_summary == "Kael"

    def test_events_survive_resume(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        manifest, log, world, scene = mgr.create("camp-1", "Durable")
        world.add_zone("arena")
        world.add_entity(Entity(id="hero", kind="character", name="Hero"))
        log.close()

        _, log2, world2, _ = mgr.resume(manifest.session_id)
        try:
            assert "arena" in world2.zones
            assert "hero" in world2.entities
        finally:
            log2.close()

    def test_resume_unknown_id_raises(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        with pytest.raises(KeyError):
            mgr.resume("does-not-exist")

    def test_resume_wrong_schema_raises(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        manifest, log, _, _ = mgr.create("camp-1", "Old Session")
        log.close()
        # Manually downgrade the DB version.
        conn = sqlite3.connect(manifest.db_path)
        conn.execute("UPDATE schema_version SET version = '0'")
        conn.commit()
        conn.close()
        with pytest.raises(SchemaVersionError):
            mgr.resume(manifest.session_id)

    def test_update_manifest_updates_fields(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        m, log, _, _ = mgr.create("camp-1", "Session")
        log.close()
        updated = mgr.update_manifest(
            m.session_id,
            title="Renamed",
            last_scene_summary="Reached the tower.",
            player_summary="Kael, Sable, Wren",
        )
        assert updated.title == "Renamed"
        assert updated.last_scene_summary == "Reached the tower."
        assert updated.player_summary == "Kael, Sable, Wren"

    def test_update_manifest_persists(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        m, log, _, _ = mgr.create("camp-1", "Session")
        log.close()
        mgr.update_manifest(m.session_id, last_scene_summary="Done.")
        # Reload the index by creating a new manager instance.
        mgr2 = SessionManager(tmp_path / "sessions")
        sessions = mgr2.list_sessions()
        assert sessions[0].last_scene_summary == "Done."

    def test_update_manifest_bumps_updated_at(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        m, log, _, _ = mgr.create("camp-1", "Session")
        log.close()
        original_ts = m.updated_at
        time.sleep(0.01)
        updated = mgr.update_manifest(m.session_id)
        assert updated.updated_at > original_ts

    def test_update_manifest_unknown_id_raises(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        with pytest.raises(KeyError):
            mgr.update_manifest("no-such-id")

    def test_list_sessions_ordered_by_updated_at_desc(self, tmp_path):
        mgr = SessionManager(tmp_path / "sessions")
        m1, log1, _, _ = mgr.create("camp-1", "First")
        log1.close()
        time.sleep(0.01)
        m2, log2, _, _ = mgr.create("camp-1", "Second")
        log2.close()
        sessions = mgr.list_sessions()
        assert sessions[0].session_id == m2.session_id
        assert sessions[1].session_id == m1.session_id
