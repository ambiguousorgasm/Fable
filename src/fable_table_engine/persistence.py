"""SQLite-backed persistence for EventLog, WorldState, Scene, PlotGraph, DispositionGraph, and session management (CORE §8; phases 1, 10, 17, 19, 21).

All classes are drop-in subclasses of their in-memory counterparts — same
interface, same guarantees, same capability enforcement. The in-memory originals
remain the default for tests; use `open_session` to opt into durability.

`open_session` is the recommended entry point: it opens one shared SQLite
connection so the event log, world state, and scene live in one file and share
one transaction boundary. For campaign-aware sessions, follow with
`attach_campaign(log, campaign)` to add the persistent plot graph.

Phase 21 additions:
  * ENGINE_SCHEMA_VERSION — bump this string when a DB migration is needed.
  * SchemaVersionError — raised by open_session and SessionManager.resume on
    mismatch (fail-closed; Phase 22 adds migration).
  * SessionManifest — frozen metadata record for one saved session.
  * SessionManager — creates, lists, and resumes sessions; enforces the schema
    version guard on resume.

Persistence scope:
  * EventLog  — every appended event survives restart.
  * WorldState — every mutation survives restart.
  * Scene — dark_zones and closed_connections survive restart (Phase 10).
    Secrecy-relevant scene state (lighting, open/closed connections) must not
    default to permissive on restart — invariant 5 requires fail-closed.
  * PlotGraph — all mutations via SQLitePlotGraph methods survive restart (Phase 17).
    Plot graph state is GM-private and never read by project_for or CommitPipeline.
  * DispositionGraph — all deltas via SQLiteDispositionGraph.apply_delta survive
    restart (Phase 19). Engine-private; never read by project_for or CommitPipeline.
  * NOT persisted: belief stores and canon ledger (read-time projections;
    rebuild on read).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_SCHEMA_VERSION = "22.0"


class SchemaVersionError(RuntimeError):
    """Raised when a session DB has no migration path to ENGINE_SCHEMA_VERSION.

    Fail-closed: callers must not proceed with the session. open_session()
    applies migrations automatically when a path exists in _MIGRATION_REGISTRY.
    Raise only when the registry has no entry for the stored version.
    """

from .event_log import EventLog
from .events import Commitment, Event, Visibility
from .perception import Scene
from .disposition import DispositionDelta, DispositionGraph
from .plot_graph import Faction, FixtureBinding, Front, FunctionNode, Hook, PlotGraph
from .world_state import Entity, WorldState


# --------------------------------------------------------------------------- #
# Migration registry                                                            #
# --------------------------------------------------------------------------- #
#
# Each entry maps from_version -> (to_version, description, [sql_statements]).
# open_session() walks this dict from the stored version to ENGINE_SCHEMA_VERSION.
# Add an entry here whenever a DDL change is made:
#   - ALTER TABLE events ADD COLUMN ...
#   - CREATE TABLE ...
#   - Any other schema-altering statement
# A pure code change with no DDL change needs only a version bump and an empty
# sql_statements list (like the 21.3 → 22.0 bootstrap entry below).

_MIGRATION_REGISTRY: dict[str, tuple[str, str, list[str]]] = {
    # from_version: (to_version, description, sql_statements)
    "21.3": (
        "22.0",
        "Phase 22.0: migration registry bootstrap; no DDL changes",
        [],
    ),
}


def _apply_migrations(conn: "sqlite3.Connection", stored: str) -> None:
    """Walk _MIGRATION_REGISTRY from stored to ENGINE_SCHEMA_VERSION.

    Applies each migration's SQL statements in order and commits after each
    step. Raises SchemaVersionError when no path exists — caller must close
    the connection before propagating.
    """
    current = stored
    while current != ENGINE_SCHEMA_VERSION:
        step = _MIGRATION_REGISTRY.get(current)
        if step is None:
            raise SchemaVersionError(
                f"No migration path from schema version {current!r} to "
                f"{ENGINE_SCHEMA_VERSION!r}. Restore the session from a backup "
                f"or create a new session with the current engine."
            )
        target, _description, sql_statements = step
        for stmt in sql_statements:
            conn.execute(stmt)
        conn.execute("UPDATE schema_version SET version = ?", (target,))
        conn.commit()
        current = target


# --------------------------------------------------------------------------- #
# Schema version DDL                                                            #
# --------------------------------------------------------------------------- #

_CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT NOT NULL
)
"""


# --------------------------------------------------------------------------- #
# Internal helpers                                                              #
# --------------------------------------------------------------------------- #

def _commitment_from_dict(d: dict[str, Any]) -> Commitment:
    return Commitment(
        subject=d["subject"],
        predicate=d["predicate"],
        value=d["value"],
        confidence=d.get("confidence"),
        revealed=d.get("revealed", False),
        epistemic_type=d.get("epistemic_type", "fact"),
        asserting_entity=d.get("asserting_entity"),
        observing_entity=d.get("observing_entity"),
    )


def _event_from_row(row: tuple) -> Event:
    seq, id_, ts, author, channel, aud_json, vis_json, type_, content, cmts_json, der_json, roll_vis, auth_json = row
    return Event(
        sequence=seq,
        id=id_,
        timestamp=ts,
        author=author,
        channel=channel,
        audience=tuple(json.loads(aud_json)),
        visibility=json.loads(vis_json),
        type=type_,
        content=content,
        commitments=tuple(_commitment_from_dict(c) for c in json.loads(cmts_json)),
        derived_from=tuple(json.loads(der_json)),
        roll_visibility=roll_vis,
        authorized_by=tuple(json.loads(auth_json)),
    )


# --------------------------------------------------------------------------- #
# SQLiteEventLog                                                                #
# --------------------------------------------------------------------------- #

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    sequence         INTEGER PRIMARY KEY,
    id               TEXT NOT NULL UNIQUE,
    timestamp        TEXT NOT NULL,
    author           TEXT NOT NULL,
    channel          TEXT NOT NULL,
    audience         TEXT NOT NULL,
    visibility       TEXT NOT NULL,
    type             TEXT NOT NULL,
    content          TEXT NOT NULL,
    commitments      TEXT NOT NULL,
    derived_from     TEXT NOT NULL,
    roll_visibility  TEXT,
    authorized_by    TEXT NOT NULL DEFAULT '[]'
)
"""

_INSERT_EVENT = """
INSERT INTO events
    (sequence, id, timestamp, author, channel, audience, visibility,
     type, content, commitments, derived_from, roll_visibility, authorized_by)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class SQLiteEventLog(EventLog):
    """Append-only event log with SQLite backing.

    On init, any existing events are loaded from the DB into the in-memory
    list so all reads stay fast (the in-memory list is the read cache; SQLite
    is the durable source that survives restarts). Every append writes to both.
    The determinism-boundary capability check is inherited unchanged from
    EventLog.append — no mechanical event can be forged regardless of backend.

    Pass the connection from `open_session`; do not share connections across
    threads without external locking.

    D-023: Use `transaction()` to batch all writes in one beat atomically. The
    shared `_tx_active` flag (a one-element list) is also held by the companion
    SQLiteWorldState so neither auto-commits while a transaction is open.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        _tx_active: list[bool] | None = None,
    ) -> None:
        super().__init__()
        self._conn = conn
        self._tx_active: list[bool] = _tx_active if _tx_active is not None else [False]
        self._world_state_ref: SQLiteWorldState | None = None
        self._scene_ref: SQLiteScene | None = None
        self._plot_graph_ref: "SQLitePlotGraph | None" = None
        self._disposition_ref: "SQLiteDispositionGraph | None" = None
        self._conn.execute(_CREATE_EVENTS)
        self._conn.commit()
        self._load()

    def _load(self) -> None:
        rows = self._conn.execute(
            "SELECT sequence, id, timestamp, author, channel, audience, visibility, "
            "type, content, commitments, derived_from, roll_visibility, authorized_by "
            "FROM events ORDER BY sequence"
        ).fetchall()
        for row in rows:
            event = _event_from_row(row)
            self._events.append(event)
            self._by_id[event.id] = event

    @contextmanager
    def transaction(self):
        """Atomic beat transaction (D-023).

        All event-log appends and world-state writes inside this block are
        committed in a single SQLite COMMIT on success. On exception the
        connection is rolled back and the in-memory event list is restored to
        its pre-transaction snapshot. The companion SQLiteWorldState is
        reloaded from the rolled-back DB if a back-reference is wired via
        `open_session`.

        Nested calls are no-ops (the outer transaction manages the commit).
        """
        if self._tx_active[0]:
            yield
            return

        snapshot_events = list(self._events)
        snapshot_by_id = dict(self._by_id)
        self._tx_active[0] = True
        try:
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            self._events = snapshot_events
            self._by_id = snapshot_by_id
            if self._world_state_ref is not None:
                self._world_state_ref._load()
            if self._scene_ref is not None:
                self._scene_ref._load()
            if self._plot_graph_ref is not None:
                self._plot_graph_ref._load()
            if self._disposition_ref is not None:
                self._disposition_ref._load()
            raise
        finally:
            self._tx_active[0] = False

    def append(
        self,
        *,
        author: str,
        channel: str,
        type: str,
        content: str,
        audience=(),
        visibility: Visibility = "content",
        commitments=(),
        derived_from=(),
        roll_visibility: str | None = None,
        authorized_by=(),
        _capability=None,
    ) -> Event:
        # Capability check + in-memory append via parent; raises on boundary violation.
        event = super().append(
            author=author,
            channel=channel,
            type=type,
            content=content,
            audience=audience,
            visibility=visibility,
            commitments=commitments,
            derived_from=derived_from,
            roll_visibility=roll_visibility,
            authorized_by=authorized_by,
            _capability=_capability,
        )
        vis = event.visibility if isinstance(event.visibility, str) else dict(event.visibility)
        self._conn.execute(
            _INSERT_EVENT,
            (
                event.sequence,
                event.id,
                event.timestamp,
                event.author,
                event.channel,
                json.dumps(list(event.audience)),
                json.dumps(vis),
                event.type,
                event.content,
                json.dumps([c.to_dict() for c in event.commitments]),
                json.dumps(list(event.derived_from)),
                event.roll_visibility,
                json.dumps(list(event.authorized_by)),
            ),
        )
        if not self._tx_active[0]:
            self._conn.commit()
        return event

    def close(self) -> None:
        """Close the underlying database connection (closes the whole session)."""
        self._conn.close()


# --------------------------------------------------------------------------- #
# SQLiteWorldState                                                              #
# --------------------------------------------------------------------------- #

_CREATE_WORLD_STATE = """
CREATE TABLE IF NOT EXISTS world_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_WORLD_KEY = "state"


class SQLiteWorldState(WorldState):
    """WorldState with SQLite backing.

    Loads existing state on init; writes the full state as a JSON document on
    each mutation. Stored as a single row because world state is always read
    and written as a whole object — there is no benefit to splitting into
    relational tables at this scale.

    Pass the same connection as SQLiteEventLog so the whole session shares one
    file. The connection lifetime is owned by SQLiteEventLog (call log.close()
    to end the session).

    D-023: shares the same `_tx_active` flag as the event log. When inside a
    transaction, world-state writes are queued in SQLite but not committed until
    the event log's `transaction()` context manager exits. On rollback, `_load()`
    re-reads the rolled-back DB to restore in-memory state.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        _tx_active: list[bool] | None = None,
    ) -> None:
        super().__init__()
        self._conn = conn
        self._tx_active: list[bool] = _tx_active if _tx_active is not None else [False]
        self._conn.execute(_CREATE_WORLD_STATE)
        self._conn.commit()
        self._load()

    def _load(self) -> None:
        row = self._conn.execute(
            "SELECT value FROM world_state WHERE key = ?", (_WORLD_KEY,)
        ).fetchone()
        if row is None:
            # No persisted row — reset all mutable state to empty defaults.
            # This path is reached on rollback to before the first _save(), e.g. when
            # the first world mutation in a transaction is rolled back and the DB never
            # had a row to begin with.
            self.zones = set()
            self.connections = set()
            self.closeness = set()
            self.scenes = {}
            self.clocks = {}
            self.fronts = {}
            self.maintained_truths = {}
            self.entities = {}
            # Time anchor resets to fresh defaults (D-030).
            import uuid as _uuid
            self.scene_id = str(_uuid.uuid4())
            self.beat_index = 0
            self.scene_phase = "quiet"
            self.prose_time_label = None
            self.elapsed_category = "beat"
            # Persist defaults immediately so a subsequent open sees the same
            # scene_id rather than generating a new UUID.
            self._save()
            return
        s = json.loads(row[0])
        self.zones = set(s.get("zones", []))
        self.connections = {frozenset(pair) for pair in s.get("connections", [])}
        self.closeness = {frozenset(pair) for pair in s.get("closeness", [])}
        self.scenes = s.get("scenes", {})
        self.clocks = s.get("clocks", {})
        self.fronts = s.get("fronts", {})
        self.maintained_truths = s.get("maintained_truths", {})
        # Clear before repopulating so entities removed by a rollback don't linger.
        self.entities = {}
        for e in s.get("entities", {}).values():
            entity = Entity(
                id=e["id"],
                kind=e["kind"],
                name=e["name"],
                position=e.get("position"),
                conditions=tuple(e.get("conditions", [])),
                resources=e.get("resources", {}),
            )
            self.entities[entity.id] = entity
        # Time anchor fields (D-030); default-safe for DBs created before 21.3.
        import uuid as _uuid
        self.scene_id = s.get("scene_id") or str(_uuid.uuid4())
        self.beat_index = int(s.get("beat_index", 0))
        self.scene_phase = s.get("scene_phase", "quiet")
        self.prose_time_label = s.get("prose_time_label")
        self.elapsed_category = s.get("elapsed_category", "beat")

    def _save(self) -> None:
        doc: dict[str, Any] = {
            "zones": list(self.zones),
            "connections": [sorted(pair) for pair in self.connections],
            "closeness": [sorted(pair) for pair in self.closeness],
            "scenes": self.scenes,
            "clocks": self.clocks,
            "fronts": self.fronts,
            "maintained_truths": self.maintained_truths,
            "entities": {
                eid: {
                    "id": e.id,
                    "kind": e.kind,
                    "name": e.name,
                    "position": e.position,
                    "conditions": list(e.conditions),
                    "resources": e.resources,
                }
                for eid, e in self.entities.items()
            },
            # Time anchor fields (D-030).
            "scene_id": self.scene_id,
            "beat_index": self.beat_index,
            "scene_phase": self.scene_phase,
            "prose_time_label": self.prose_time_label,
            "elapsed_category": self.elapsed_category,
        }
        self._conn.execute(
            "INSERT OR REPLACE INTO world_state (key, value) VALUES (?, ?)",
            (_WORLD_KEY, json.dumps(doc)),
        )
        if not self._tx_active[0]:
            self._conn.commit()

    # Override every mutation method to persist after the in-memory change.

    def add_entity(self, entity: Entity) -> None:
        super().add_entity(entity)
        self._save()

    def update_entity(self, entity: Entity) -> None:
        super().update_entity(entity)
        self._save()

    def add_zone(self, zone: str) -> None:
        super().add_zone(zone)
        self._save()

    def connect(self, a: str, b: str) -> None:
        super().connect(a, b)
        self._save()

    def place(self, entity_id: str, zone: str) -> None:
        super().place(entity_id, zone)
        self._save()

    def set_close(self, a: str, b: str) -> None:
        super().set_close(a, b)
        self._save()

    def set_clock(self, name: str, data: dict) -> None:
        super().set_clock(name, data)
        self._save()

    def set_front(self, name: str, data: dict) -> None:
        super().set_front(name, data)
        self._save()

    def set_maintained_truth(self, key: str, data: dict) -> None:
        super().set_maintained_truth(key, data)
        self._save()

    def expire_maintained_truth(self, key: str) -> None:
        super().expire_maintained_truth(key)
        self._save()

    def advance_beat(self, elapsed_category: str = "beat") -> None:
        super().advance_beat(elapsed_category)
        self._save()

    def begin_scene_transition(
        self,
        scene_phase: str,
        elapsed_category: str = "scene",
        prose_time_label: str | None = None,
    ) -> str:
        new_scene_id = super().begin_scene_transition(scene_phase, elapsed_category, prose_time_label)
        self._save()
        return new_scene_id


# --------------------------------------------------------------------------- #
# SQLiteScene                                                                   #
# --------------------------------------------------------------------------- #

_CREATE_SCENE_STATE = """
CREATE TABLE IF NOT EXISTS scene_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_SCENE_KEY = "state"


class SQLiteScene(Scene):
    """Scene with SQLite backing (Phase 10 — secrecy-relevant state must not default permissive).

    Persists ``dark_zones`` and ``closed_connections`` in the shared DB so that
    lighting and door-state survive session restart. Shares the ``_tx_active``
    flag with SQLiteEventLog and SQLiteWorldState — all three are committed or
    rolled back together.

    On rollback, ``_load()`` restores the in-memory sets to the pre-transaction
    DB state. This is wired via ``SQLiteEventLog._scene_ref`` (set by
    ``open_session``).

    Default posture on a fresh DB (no prior state) is the inherited Scene
    default: all zones lit, all connections open. A `darken` or `close` call
    immediately writes to DB so the next session sees the restricted state.
    """

    def __init__(
        self,
        world: WorldState,
        conn: sqlite3.Connection,
        _tx_active: list[bool] | None = None,
    ) -> None:
        super().__init__(world)
        self._conn = conn
        self._tx_active: list[bool] = _tx_active if _tx_active is not None else [False]
        self._conn.execute(_CREATE_SCENE_STATE)
        self._conn.commit()
        self._load()

    def _load(self) -> None:
        row = self._conn.execute(
            "SELECT value FROM scene_state WHERE key = ?", (_SCENE_KEY,)
        ).fetchone()
        if row is None:
            return
        s = json.loads(row[0])
        self.dark_zones = set(s.get("dark_zones", []))
        self.closed_connections = {frozenset(pair) for pair in s.get("closed_connections", [])}

    def _save(self) -> None:
        doc: dict[str, Any] = {
            "dark_zones": sorted(self.dark_zones),
            "closed_connections": [sorted(pair) for pair in self.closed_connections],
        }
        self._conn.execute(
            "INSERT OR REPLACE INTO scene_state (key, value) VALUES (?, ?)",
            (_SCENE_KEY, json.dumps(doc)),
        )
        if not self._tx_active[0]:
            self._conn.commit()

    def darken(self, zone: str) -> None:
        super().darken(zone)
        self._save()

    def illuminate(self, zone: str) -> None:
        """Restore a darkened zone to lit and persist the change."""
        self.dark_zones.discard(zone)
        self._save()

    def close(self, a: str, b: str) -> None:
        super().close(a, b)
        self._save()

    def open_connection(self, a: str, b: str) -> None:
        """Reopen a closed connection and persist the change."""
        self.closed_connections.discard(frozenset({a, b}))
        self._save()


# --------------------------------------------------------------------------- #
# SQLitePlotGraph                                                               #
# --------------------------------------------------------------------------- #

_CREATE_PLOT_GRAPH = """
CREATE TABLE IF NOT EXISTS plot_graph (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_PLOT_GRAPH_KEY = "graph"


class SQLitePlotGraph(PlotGraph):
    """PlotGraph with SQLite backing (Phase 17 — GM-private persistent hidden state).

    Every mutation method calls `_save()` so the graph survives session restart
    within the D-023 transaction model. The companion `SQLiteEventLog` rolls
    this back via `_plot_graph_ref._load()` on transaction failure.

    Use `attach_campaign(log, campaign)` rather than constructing directly.
    Plot graph state is never read by `project_for`, `CommitPipeline`, or any
    player-facing projection — the access control is structural (no code path
    from the graph to belief stores exists).
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        _tx_active: list[bool] | None = None,
    ) -> None:
        super().__init__()
        self._conn = conn
        self._tx_active: list[bool] = _tx_active if _tx_active is not None else [False]
        self._conn.execute(_CREATE_PLOT_GRAPH)
        if not self._tx_active[0]:
            self._conn.commit()
        self._load()

    def _load(self) -> None:
        """Clear and repopulate from DB; called on init and on rollback."""
        self.function_nodes.clear()
        self.hooks.clear()
        self.fronts.clear()
        self.factions.clear()
        self.hidden_nodes.clear()
        self.alternative_fixtures.clear()
        row = self._conn.execute(
            "SELECT value FROM plot_graph WHERE key = ?", (_PLOT_GRAPH_KEY,)
        ).fetchone()
        if row is None:
            return
        loaded = PlotGraph.from_dict(json.loads(row[0]))
        self.function_nodes.update(loaded.function_nodes)
        self.hooks.extend(loaded.hooks)
        self.fronts.extend(loaded.fronts)
        self.factions.extend(loaded.factions)
        self.hidden_nodes.extend(loaded.hidden_nodes)
        self.alternative_fixtures.update(loaded.alternative_fixtures)

    def _save(self) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO plot_graph (key, value) VALUES (?, ?)",
            (_PLOT_GRAPH_KEY, json.dumps(self.to_dict())),
        )
        if not self._tx_active[0]:
            self._conn.commit()

    def add_function(self, node: FunctionNode) -> None:
        super().add_function(node)
        self._save()

    def add_hook(self, hook: Hook) -> None:
        super().add_hook(hook)
        self._save()

    def add_front(self, front: Front) -> None:
        super().add_front(front)
        self._save()

    def add_faction(self, faction: Faction) -> None:
        super().add_faction(faction)
        self._save()

    def add_hidden_node(self, node: FunctionNode) -> None:
        super().add_hidden_node(node)
        self._save()

    def set_alternatives(
        self, function_id: str, alternatives: list[FixtureBinding]
    ) -> None:
        super().set_alternatives(function_id, alternatives)
        self._save()

    def update_hook_binding(
        self, function_id: str, new_binding: FixtureBinding
    ) -> None:
        super().update_hook_binding(function_id, new_binding)
        self._save()


# --------------------------------------------------------------------------- #
# SQLiteDispositionGraph                                                        #
# --------------------------------------------------------------------------- #

_CREATE_DISPOSITION = """
CREATE TABLE IF NOT EXISTS disposition (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

_DISPOSITION_KEY = "graph"


class SQLiteDispositionGraph(DispositionGraph):
    """DispositionGraph with SQLite backing (Phase 19).

    Every `apply_delta` call persists the full graph so disposition state
    survives session restart within the D-023 transaction model. The companion
    `SQLiteEventLog` rolls this back via `_disposition_ref._load()` on failure.

    Relationship state is engine-private and never read by `project_for`,
    `CommitPipeline`, or any player-facing projection — structural isolation.
    Use `attach_disposition(log)` rather than constructing directly.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        _tx_active: list[bool] | None = None,
    ) -> None:
        super().__init__()
        self._conn = conn
        self._tx_active: list[bool] = _tx_active if _tx_active is not None else [False]
        self._conn.execute(_CREATE_DISPOSITION)
        if not self._tx_active[0]:
            self._conn.commit()
        self._load()

    def _load(self) -> None:
        """Clear and repopulate from DB; called on init and on rollback."""
        self._edges.clear()
        self._history.clear()
        self._by_event.clear()
        row = self._conn.execute(
            "SELECT value FROM disposition WHERE key = ?", (_DISPOSITION_KEY,)
        ).fetchone()
        if row is None:
            return
        loaded = DispositionGraph.from_dict(json.loads(row[0]))
        self._edges.update(loaded._edges)
        self._history.extend(loaded._history)
        for eid, deltas in loaded._by_event.items():
            self._by_event.setdefault(eid, []).extend(deltas)

    def _save(self) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO disposition (key, value) VALUES (?, ?)",
            (_DISPOSITION_KEY, json.dumps(self.to_dict())),
        )
        if not self._tx_active[0]:
            self._conn.commit()

    def apply_delta(self, delta: DispositionDelta) -> None:
        super().apply_delta(delta)
        self._save()


def attach_disposition(log: SQLiteEventLog) -> SQLiteDispositionGraph:
    """Create or load the persistent disposition graph for this session.

    Wires the graph into `log.transaction()` rollback via `_disposition_ref`.
    Call after `open_session`::

        log, world, scene = open_session(path)
        disp = attach_disposition(log)
        engine = DispositionEngine(disp)
    """
    graph = SQLiteDispositionGraph(log._conn, _tx_active=log._tx_active)
    log._disposition_ref = graph
    return graph


# --------------------------------------------------------------------------- #
# Campaign attachment                                                           #
# --------------------------------------------------------------------------- #

def attach_campaign(
    log: SQLiteEventLog,
    campaign: "Any | None" = None,
) -> SQLitePlotGraph:
    """Create or load the persistent plot graph for this session.

    If the session DB already has a saved plot graph, loads it (a resumed
    session). If not, and a `CampaignPackage` is supplied, seeds from it.
    Wires the graph into `log.transaction()` rollback via `_plot_graph_ref`.

    Call after `open_session`::

        log, world, scene = open_session(path)
        graph = attach_campaign(log, campaign)
        campaign.seed_world(world)    # seed clocks separately

    The campaign package seeds only an empty graph — a resumed session's graph
    is never overwritten, even if a campaign is passed.
    """
    graph = SQLitePlotGraph(log._conn, _tx_active=log._tx_active)
    log._plot_graph_ref = graph

    is_empty = (
        not graph.function_nodes
        and not graph.hooks
        and not graph.fronts
        and not graph.factions
        and not graph.hidden_nodes
    )
    if campaign is not None and is_empty:
        seeded = campaign.to_plot_graph()
        graph.function_nodes.update(seeded.function_nodes)
        graph.hooks.extend(seeded.hooks)
        graph.fronts.extend(seeded.fronts)
        graph.factions.extend(seeded.factions)
        graph.hidden_nodes.extend(seeded.hidden_nodes)
        graph.alternative_fixtures.update(seeded.alternative_fixtures)
        graph._save()

    return graph


# --------------------------------------------------------------------------- #
# Session factory                                                               #
# --------------------------------------------------------------------------- #

def open_session(
    db_path: str | Path,
) -> tuple[SQLiteEventLog, SQLiteWorldState, SQLiteScene]:
    """Open (or resume) a persisted session from a SQLite file.

    Returns ``(log, world, scene)`` sharing one connection and one ``_tx_active``
    flag (D-023). Scene state (lighting, closed connections) is restored from the
    DB so secrecy-relevant posture survives restarts (Phase 10 invariant 5). Pass
    ``log`` and ``world`` to CommitPipeline, DiceService, RulesEngine, etc.
    exactly as you would the in-memory variants. Call ``log.close()`` when the
    session ends.

    Phase 22 — schema version guard + auto-migration: on a fresh DB
    ENGINE_SCHEMA_VERSION is written. On a resumed DB the engine walks
    _MIGRATION_REGISTRY from the stored version to the current one, applying
    any DDL statements along the way. Raises SchemaVersionError only when no
    migration path exists (e.g. version from future engine, or pre-registry DB
    with an unknown version string).

    BeatRunner wraps each beat in ``log.transaction()`` automatically. Manual use::

        log, world, scene = open_session("session.db")
        with log.transaction():
            runner.run(actor, action)  # all writes committed atomically
        log.close()
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # Schema version guard + auto-migration (Phase 22).
    conn.execute(_CREATE_SCHEMA_VERSION)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (ENGINE_SCHEMA_VERSION,))
        conn.commit()
    elif row[0] != ENGINE_SCHEMA_VERSION:
        stored = row[0]
        try:
            _apply_migrations(conn, stored)
        except SchemaVersionError:
            conn.close()
            raise

    tx_active: list[bool] = [False]
    log = SQLiteEventLog(conn, _tx_active=tx_active)
    world = SQLiteWorldState(conn, _tx_active=tx_active)
    scene = SQLiteScene(world, conn, _tx_active=tx_active)
    log._world_state_ref = world
    log._scene_ref = scene
    return log, world, scene


# --------------------------------------------------------------------------- #
# Session manifest and manager (Phase 21)                                       #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SessionManifest:
    """Immutable metadata record for one saved session.

    Stored in the session index (sessions_dir/index.json) separate from the
    session DB itself, so the home screen can list sessions without opening
    each DB. Fields are strings throughout for simple JSON round-trip.
    """

    session_id: str
    campaign_id: str
    title: str
    created_at: str       # ISO-8601
    updated_at: str       # ISO-8601
    last_scene_summary: str
    player_summary: str
    db_path: str
    schema_version: str
    engine_version: str

    def to_dict(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "campaign_id": self.campaign_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_scene_summary": self.last_scene_summary,
            "player_summary": self.player_summary,
            "db_path": self.db_path,
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionManifest":
        return cls(
            session_id=d["session_id"],
            campaign_id=d["campaign_id"],
            title=d["title"],
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            last_scene_summary=d.get("last_scene_summary", ""),
            player_summary=d.get("player_summary", ""),
            db_path=d["db_path"],
            schema_version=d["schema_version"],
            engine_version=d["engine_version"],
        )


class SessionManager:
    """Creates, lists, and resumes sessions. Enforces the schema version guard.

    All session DBs are stored in ``sessions_dir`` as ``{session_id}.db``.
    The manifest index lives at ``sessions_dir/index.json`` and is the only
    file that must be read to populate the home-screen session list.

    Usage::

        mgr = SessionManager("sessions/")
        manifest, log, world, scene = mgr.create("my_campaign", "First Session")
        # ... play beats ...
        mgr.update_manifest(manifest.session_id, last_scene_summary="Arrived at the keep.")
        log.close()

        # Later:
        manifest, log, world, scene = mgr.resume(manifest.session_id)
    """

    def __init__(self, sessions_dir: str | Path) -> None:
        self._dir = Path(sessions_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.json"

    def _load_index(self) -> dict[str, dict]:
        if not self._index_path.exists():
            return {}
        return json.loads(self._index_path.read_text())

    def _save_index(self, index: dict[str, dict]) -> None:
        self._index_path.write_text(json.dumps(index, indent=2))

    def list_sessions(self) -> list[SessionManifest]:
        """Return all known sessions, ordered by most-recently-updated first."""
        index = self._load_index()
        manifests = [SessionManifest.from_dict(d) for d in index.values()]
        return sorted(manifests, key=lambda m: m.updated_at, reverse=True)

    def create(
        self,
        campaign_id: str,
        title: str,
        player_summary: str = "",
    ) -> tuple[SessionManifest, SQLiteEventLog, SQLiteWorldState, SQLiteScene]:
        """Create a new session and return (manifest, log, world, scene).

        The session DB is created and the schema version is written by
        open_session. Callers seed world state from their CampaignPackage and
        optionally call attach_campaign for the plot graph.
        """
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db_path = str(self._dir / f"{session_id}.db")

        log, world, scene = open_session(db_path)

        manifest = SessionManifest(
            session_id=session_id,
            campaign_id=campaign_id,
            title=title,
            created_at=now,
            updated_at=now,
            last_scene_summary="",
            player_summary=player_summary,
            db_path=db_path,
            schema_version=ENGINE_SCHEMA_VERSION,
            engine_version=ENGINE_SCHEMA_VERSION,
        )

        index = self._load_index()
        index[session_id] = manifest.to_dict()
        self._save_index(index)

        return manifest, log, world, scene

    def resume(
        self,
        session_id: str,
    ) -> tuple[SessionManifest, SQLiteEventLog, SQLiteWorldState, SQLiteScene]:
        """Resume a saved session. Returns (manifest, log, world, scene).

        Raises KeyError if session_id is not in the index.
        Raises SchemaVersionError (via open_session) if the DB version mismatches.
        """
        index = self._load_index()
        if session_id not in index:
            raise KeyError(f"Session {session_id!r} not found")
        manifest = SessionManifest.from_dict(index[session_id])
        log, world, scene = open_session(manifest.db_path)
        return manifest, log, world, scene

    def update_manifest(
        self,
        session_id: str,
        *,
        title: str | None = None,
        last_scene_summary: str | None = None,
        player_summary: str | None = None,
    ) -> SessionManifest:
        """Update mutable manifest fields; persist and return the updated manifest.

        Call at session checkpoint or close to keep the index current.
        Raises KeyError if session_id is not in the index.
        """
        index = self._load_index()
        if session_id not in index:
            raise KeyError(f"Session {session_id!r} not found")
        d = dict(index[session_id])
        d["updated_at"] = datetime.now(timezone.utc).isoformat()
        if title is not None:
            d["title"] = title
        if last_scene_summary is not None:
            d["last_scene_summary"] = last_scene_summary
        if player_summary is not None:
            d["player_summary"] = player_summary
        index[session_id] = d
        self._save_index(index)
        return SessionManifest.from_dict(d)
