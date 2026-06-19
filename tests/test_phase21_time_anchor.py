"""Phase 21 deliverable 8: D-030 time anchor and scene transition.

Backend-owned minimal time anchor: scene_id, beat_index, scene_phase,
prose_time_label, elapsed_category. scene_transition structural event emitted
on scene boundary; client reads from event stream, never declares transitions.
"""
from __future__ import annotations

import json
import tempfile
import os

import pytest

from fable_table_engine import ELAPSED_CATEGORIES, WorldState
from fable_table_engine.event_log import EventLog
from fable_table_engine.gm import WorldSimulator
from fable_table_engine.persistence import SQLiteWorldState, open_session
from fable_table_engine.world_state import ELAPSED_CATEGORIES as _EC


# --------------------------------------------------------------------------- #
# ELAPSED_CATEGORIES constant                                                    #
# --------------------------------------------------------------------------- #

class TestElapsedCategories:

    def test_contains_beat(self):
        assert "beat" in ELAPSED_CATEGORIES

    def test_contains_exchange(self):
        assert "exchange" in ELAPSED_CATEGORIES

    def test_contains_scene(self):
        assert "scene" in ELAPSED_CATEGORIES

    def test_contains_travel(self):
        assert "travel" in ELAPSED_CATEGORIES

    def test_contains_breather(self):
        assert "breather" in ELAPSED_CATEGORIES

    def test_contains_downtime(self):
        assert "downtime" in ELAPSED_CATEGORIES

    def test_is_frozenset(self):
        assert isinstance(ELAPSED_CATEGORIES, frozenset)

    def test_has_six_members(self):
        assert len(ELAPSED_CATEGORIES) == 6


# --------------------------------------------------------------------------- #
# WorldState time anchor defaults                                                #
# --------------------------------------------------------------------------- #

class TestWorldStateTimeAnchorDefaults:

    def test_scene_id_is_string(self):
        w = WorldState()
        assert isinstance(w.scene_id, str)
        assert len(w.scene_id) == 36  # UUID4 canonical form

    def test_beat_index_starts_at_zero(self):
        assert WorldState().beat_index == 0

    def test_scene_phase_defaults_to_quiet(self):
        assert WorldState().scene_phase == "quiet"

    def test_prose_time_label_defaults_to_none(self):
        assert WorldState().prose_time_label is None

    def test_elapsed_category_defaults_to_beat(self):
        assert WorldState().elapsed_category == "beat"

    def test_two_instances_get_different_scene_ids(self):
        a, b = WorldState(), WorldState()
        assert a.scene_id != b.scene_id


# --------------------------------------------------------------------------- #
# WorldState.advance_beat()                                                      #
# --------------------------------------------------------------------------- #

class TestAdvanceBeat:

    def test_increments_beat_index(self):
        w = WorldState()
        w.advance_beat()
        assert w.beat_index == 1

    def test_multiple_increments_accumulate(self):
        w = WorldState()
        for _ in range(5):
            w.advance_beat()
        assert w.beat_index == 5

    def test_records_elapsed_category(self):
        w = WorldState()
        w.advance_beat("exchange")
        assert w.elapsed_category == "exchange"

    def test_default_elapsed_category_is_beat(self):
        w = WorldState()
        w.advance_beat()
        assert w.elapsed_category == "beat"

    def test_invalid_elapsed_category_raises(self):
        with pytest.raises(ValueError, match="elapsed_category"):
            WorldState().advance_beat("century")

    def test_all_valid_categories_accepted(self):
        for cat in ELAPSED_CATEGORIES:
            w = WorldState()
            w.advance_beat(cat)
            assert w.elapsed_category == cat


# --------------------------------------------------------------------------- #
# WorldState.begin_scene_transition()                                            #
# --------------------------------------------------------------------------- #

class TestBeginSceneTransition:

    def test_returns_new_scene_id(self):
        w = WorldState()
        old = w.scene_id
        new_id = w.begin_scene_transition("dialogue")
        assert new_id != old
        assert new_id == w.scene_id

    def test_resets_beat_index(self):
        w = WorldState()
        w.advance_beat()
        w.advance_beat()
        w.begin_scene_transition("combat")
        assert w.beat_index == 0

    def test_updates_scene_phase(self):
        w = WorldState()
        w.begin_scene_transition("combat")
        assert w.scene_phase == "combat"

    def test_updates_elapsed_category(self):
        w = WorldState()
        w.begin_scene_transition("quiet", elapsed_category="breather")
        assert w.elapsed_category == "breather"

    def test_default_elapsed_category_is_scene(self):
        w = WorldState()
        w.begin_scene_transition("quiet")
        assert w.elapsed_category == "scene"

    def test_updates_prose_time_label(self):
        w = WorldState()
        w.begin_scene_transition("quiet", prose_time_label="morning of the third day")
        assert w.prose_time_label == "morning of the third day"

    def test_prose_time_label_none_by_default(self):
        w = WorldState()
        w.begin_scene_transition("quiet")
        assert w.prose_time_label is None

    def test_invalid_elapsed_category_raises(self):
        with pytest.raises(ValueError, match="elapsed_category"):
            WorldState().begin_scene_transition("quiet", elapsed_category="nanosecond")

    def test_successive_transitions_each_produce_unique_scene_ids(self):
        w = WorldState()
        ids = {w.begin_scene_transition("quiet") for _ in range(5)}
        assert len(ids) == 5


# --------------------------------------------------------------------------- #
# WorldSimulator.declare_scene_transition()                                      #
# --------------------------------------------------------------------------- #

class TestDeclareSceneTransition:

    def _setup(self):
        log = EventLog()
        world = WorldState()
        sim = WorldSimulator(log, world, gm_entity="gm")
        return log, world, sim

    def test_emits_scene_transition_event(self):
        log, world, sim = self._setup()
        sim.declare_scene_transition("combat")
        events = log.all()
        assert any(e.type == "scene_transition" for e in events)

    def test_event_content_contains_scene_id(self):
        log, world, sim = self._setup()
        new_id = sim.declare_scene_transition("combat")
        ev = next(e for e in log.all() if e.type == "scene_transition")
        payload = json.loads(ev.content)
        assert payload["scene_id"] == new_id

    def test_event_content_contains_scene_phase(self):
        log, world, sim = self._setup()
        sim.declare_scene_transition("tactical")
        ev = next(e for e in log.all() if e.type == "scene_transition")
        assert json.loads(ev.content)["scene_phase"] == "tactical"

    def test_event_content_contains_elapsed_category(self):
        log, world, sim = self._setup()
        sim.declare_scene_transition("quiet", elapsed_category="breather")
        ev = next(e for e in log.all() if e.type == "scene_transition")
        assert json.loads(ev.content)["elapsed_category"] == "breather"

    def test_prose_time_label_included_when_set(self):
        log, world, sim = self._setup()
        sim.declare_scene_transition("quiet", prose_time_label="dawn, second day")
        ev = next(e for e in log.all() if e.type == "scene_transition")
        assert json.loads(ev.content).get("prose_time_label") == "dawn, second day"

    def test_prose_time_label_absent_when_not_set(self):
        log, world, sim = self._setup()
        sim.declare_scene_transition("quiet")
        ev = next(e for e in log.all() if e.type == "scene_transition")
        assert "prose_time_label" not in json.loads(ev.content)

    def test_event_author_is_gm(self):
        log, world, sim = self._setup()
        sim.declare_scene_transition("quiet")
        ev = next(e for e in log.all() if e.type == "scene_transition")
        assert ev.author == "gm"

    def test_event_channel_is_system(self):
        log, world, sim = self._setup()
        sim.declare_scene_transition("quiet")
        ev = next(e for e in log.all() if e.type == "scene_transition")
        assert ev.channel == "system"

    def test_event_audience_is_gm_only(self):
        log, world, sim = self._setup()
        sim.declare_scene_transition("quiet")
        ev = next(e for e in log.all() if e.type == "scene_transition")
        assert ev.audience == ("gm",)

    def test_world_scene_id_updated(self):
        log, world, sim = self._setup()
        old_id = world.scene_id
        sim.declare_scene_transition("dialogue")
        assert world.scene_id != old_id

    def test_world_beat_index_reset(self):
        log, world, sim = self._setup()
        world.advance_beat()
        world.advance_beat()
        sim.declare_scene_transition("quiet")
        assert world.beat_index == 0

    def test_returns_new_scene_id_matching_world(self):
        log, world, sim = self._setup()
        returned_id = sim.declare_scene_transition("combat")
        assert returned_id == world.scene_id

    def test_player_does_not_see_scene_transition_event(self):
        """scene_transition is GM-audience only — player projection is empty."""
        log, world, sim = self._setup()
        sim.declare_scene_transition("quiet")
        player_proj = log.project_for("hero")
        assert all(e.type != "scene_transition" for e in player_proj)


# --------------------------------------------------------------------------- #
# SQLiteWorldState persistence                                                   #
# --------------------------------------------------------------------------- #

class TestSQLiteTimeAnchorPersistence:

    def _db_path(self, tmp):
        return os.path.join(tmp, "session.db")

    def test_scene_id_persists_across_session_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._db_path(tmp)
            log, world, scene = open_session(path)
            first_scene_id = world.scene_id
            # Re-open the same DB
            log2, world2, scene2 = open_session(path)
            assert world2.scene_id == first_scene_id

    def test_beat_index_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._db_path(tmp)
            log, world, scene = open_session(path)
            world.advance_beat()
            world.advance_beat()
            log2, world2, _ = open_session(path)
            assert world2.beat_index == 2

    def test_scene_phase_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._db_path(tmp)
            log, world, scene = open_session(path)
            world.begin_scene_transition("combat")
            log2, world2, _ = open_session(path)
            assert world2.scene_phase == "combat"

    def test_prose_time_label_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._db_path(tmp)
            log, world, scene = open_session(path)
            world.begin_scene_transition("quiet", prose_time_label="midnight")
            log2, world2, _ = open_session(path)
            assert world2.prose_time_label == "midnight"

    def test_elapsed_category_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._db_path(tmp)
            log, world, scene = open_session(path)
            world.advance_beat("exchange")
            log2, world2, _ = open_session(path)
            assert world2.elapsed_category == "exchange"
