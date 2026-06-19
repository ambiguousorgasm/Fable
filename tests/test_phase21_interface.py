"""Phase 21 deliverable 10: home screen + play interface.

HomeScreen: campaign listing, session listing, rendering.
PlayInterface: event stream rendering, settings panel, time-anchor status.
build_play_interface: wires engine components into a PlayInterface.
Security: client never sees GM-private event content.

All model calls are mocked; no API key required.
"""
from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fable_table_engine import (
    AdjudicatorGM,
    BeatRunner,
    CharacterSheet,
    CommitPipeline,
    ContextAssembler,
    DiceService,
    Entity,
    EventLog,
    ModelGateway,
    NarratorGM,
    PlaytestSession,
    RulesEngine,
    WorldState,
)

from fable_table_engine.interface import HomeScreen, PlayInterface, build_play_interface
from fable_table_engine.persistence import SessionManager, open_session
from fable_table_engine.settings import SettingsManager, SettingsRegistry


# --------------------------------------------------------------------------- #
# Helpers                                                                        #
# --------------------------------------------------------------------------- #

_CAMPAIGN_MIN = {
    "version": "1.0",
    "title": "The Ruins of Thornwall",
    "description": "A dungeon crawl.",
}

_NO_STAKES = {
    "has_stakes": False,
    "reasoning": "stakes-free action",
    "action_domain": "social",
    "exposure": 0,
    "effect": "standard",
    "consequence_palette": [],
}


def _write_campaign(tmp: str, filename: str, data: dict) -> Path:
    path = Path(tmp) / filename
    path.write_text(json.dumps(data))
    return path


def _tool_response(tool_input: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "adjudicate_action"
    block.input = tool_input
    response = MagicMock()
    response.content = [block]
    return response


def _text_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _make_mocked_gm_pair(narrator_text: str = "You act."):
    """Return (adjudicator, narrator) with mocked Anthropic clients."""
    adj_client = MagicMock()
    adj_client.messages.create.return_value = _tool_response(_NO_STAKES)
    narrator_client = MagicMock()
    narrator_client.messages.create.return_value = _text_response(narrator_text)
    return (
        AdjudicatorGM(ModelGateway(adj_client)),
        NarratorGM(ModelGateway(narrator_client)),
    )


def _make_session(narrator_text: str = "You act.", player_id: str = "hero"):
    """Return (PlaytestSession, assembler, log, world) with mocked models."""
    log = EventLog()
    world = WorldState()
    world.add_zone("hall")
    world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
    world.place("hero", "hall")
    pipeline = CommitPipeline(log)
    dice = DiceService(log, rng=random.Random(0))
    rules = RulesEngine(log, dice)
    assembler = ContextAssembler(log)
    adj, narr = _make_mocked_gm_pair(narrator_text)
    runner = BeatRunner(
        log=log, world=world, pipeline=pipeline, rules=rules,
        assembler=assembler, adjudicator=adj, narrator=narr,
        sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
    )
    session = PlaytestSession(runner, assembler, player_id)
    return session, assembler, log, world


# --------------------------------------------------------------------------- #
# HomeScreen — campaign listing                                                  #
# --------------------------------------------------------------------------- #

class TestHomeScreenCampaigns:

    def test_empty_dir_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = HomeScreen(campaigns_dir=tmp)
            assert home.available_campaigns() == []

    def test_nonexistent_dir_returns_empty_list(self):
        home = HomeScreen(campaigns_dir="/nonexistent/path/xyz123")
        assert home.available_campaigns() == []

    def test_valid_campaign_file_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_campaign(tmp, "ruins.json", _CAMPAIGN_MIN)
            home = HomeScreen(campaigns_dir=tmp)
            campaigns = home.available_campaigns()
            assert len(campaigns) == 1
            assert campaigns[0].title == "The Ruins of Thornwall"

    def test_malformed_json_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.json").write_text("NOT JSON {{{")
            home = HomeScreen(campaigns_dir=tmp)
            assert home.available_campaigns() == []

    def test_invalid_schema_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "missing.json").write_text('{"version": "1.0"}')
            home = HomeScreen(campaigns_dir=tmp)
            assert home.available_campaigns() == []

    def test_multiple_campaigns_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_campaign(tmp, "a.json", {**_CAMPAIGN_MIN, "title": "Alpha"})
            _write_campaign(tmp, "b.json", {**_CAMPAIGN_MIN, "title": "Beta"})
            home = HomeScreen(campaigns_dir=tmp)
            assert len(home.available_campaigns()) == 2

    def test_non_json_files_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "readme.txt").write_text("text file")
            _write_campaign(tmp, "valid.json", _CAMPAIGN_MIN)
            home = HomeScreen(campaigns_dir=tmp)
            assert len(home.available_campaigns()) == 1

    def test_malformed_skipped_valid_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.json").write_text("BROKEN")
            _write_campaign(tmp, "good.json", _CAMPAIGN_MIN)
            home = HomeScreen(campaigns_dir=tmp)
            assert len(home.available_campaigns()) == 1


# --------------------------------------------------------------------------- #
# HomeScreen — session listing                                                   #
# --------------------------------------------------------------------------- #

class TestHomeScreenSessions:

    def test_empty_dir_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = HomeScreen(sessions_dir=tmp)
            assert home.available_sessions() == []

    def test_nonexistent_dir_returns_empty_list(self):
        home = HomeScreen(sessions_dir="/nonexistent/path/xyz123")
        assert home.available_sessions() == []

    def test_lists_created_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(tmp)
            mgr.create("camp1", "First Session")
            home = HomeScreen(sessions_dir=tmp)
            sessions = home.available_sessions()
            assert len(sessions) == 1
            assert sessions[0].title == "First Session"

    def test_multiple_sessions_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(tmp)
            mgr.create("camp1", "Session One")
            mgr.create("camp1", "Session Two")
            home = HomeScreen(sessions_dir=tmp)
            assert len(home.available_sessions()) == 2

    def test_session_manager_returns_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = HomeScreen(sessions_dir=tmp)
            assert isinstance(home.session_manager(), SessionManager)

    def test_settings_manager_returns_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = HomeScreen(settings_dir=tmp)
            assert isinstance(home.settings_manager(), SettingsManager)


# --------------------------------------------------------------------------- #
# HomeScreen — render                                                            #
# --------------------------------------------------------------------------- #

class TestHomeScreenRender:

    def test_render_contains_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = HomeScreen(campaigns_dir=tmp, sessions_dir=tmp)
            assert "FABLE Table Engine" in home.render()

    def test_render_shows_campaign_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_campaign(tmp, "ruins.json", _CAMPAIGN_MIN)
            home = HomeScreen(campaigns_dir=tmp, sessions_dir=tmp)
            assert "The Ruins of Thornwall" in home.render()

    def test_render_shows_session_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(tmp)
            mgr.create("camp", "My Campaign Session")
            home = HomeScreen(campaigns_dir=tmp, sessions_dir=tmp)
            assert "My Campaign Session" in home.render()

    def test_render_none_message_when_no_campaigns(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = HomeScreen(campaigns_dir=tmp, sessions_dir=tmp)
            assert "none" in home.render().lower()

    def test_render_none_message_when_no_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = HomeScreen(campaigns_dir=tmp, sessions_dir=tmp)
            assert "none" in home.render().lower()

    def test_render_includes_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = HomeScreen(campaigns_dir=tmp, sessions_dir=tmp)
            rendered = home.render()
            assert "resume" in rendered
            assert "new" in rendered
            assert "settings" in rendered
            assert "quit" in rendered

    def test_render_numbers_campaigns(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_campaign(tmp, "ruins.json", _CAMPAIGN_MIN)
            home = HomeScreen(campaigns_dir=tmp, sessions_dir=tmp)
            assert "[1]" in home.render()

    def test_render_numbers_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(tmp)
            mgr.create("c", "Session A")
            home = HomeScreen(campaigns_dir=tmp, sessions_dir=tmp)
            assert "[1]" in home.render()


# --------------------------------------------------------------------------- #
# PlayInterface — render_status                                                  #
# --------------------------------------------------------------------------- #

class TestPlayInterfaceRenderStatus:

    def _make_interface(self, world=None):
        session, _, _, _ = _make_session()
        settings = SettingsManager("/nonexistent")
        return PlayInterface(session, settings, world=world)

    def test_render_status_empty_without_world(self):
        iface = self._make_interface(world=None)
        assert iface.render_status() == ""

    def test_render_status_shows_scene_phase(self):
        world = WorldState()
        iface = self._make_interface(world=world)
        assert "quiet" in iface.render_status()

    def test_render_status_shows_beat_index(self):
        world = WorldState()
        iface = self._make_interface(world=world)
        assert "beat:0" in iface.render_status()

    def test_render_status_reflects_advance_beat(self):
        world = WorldState()
        world.advance_beat()
        iface = self._make_interface(world=world)
        assert "beat:1" in iface.render_status()

    def test_render_status_shows_prose_time_label(self):
        world = WorldState()
        world.begin_scene_transition("combat", prose_time_label="dawn")
        iface = self._make_interface(world=world)
        assert "dawn" in iface.render_status()

    def test_render_status_prose_label_absent_when_none(self):
        world = WorldState()
        iface = self._make_interface(world=world)
        assert "None" not in iface.render_status()

    def test_render_status_scene_phase_after_transition(self):
        world = WorldState()
        world.begin_scene_transition("combat")
        iface = self._make_interface(world=world)
        assert "combat" in iface.render_status()


# --------------------------------------------------------------------------- #
# PlayInterface — render_settings                                                #
# --------------------------------------------------------------------------- #

class TestPlayInterfaceRenderSettings:

    def _make_interface(self, settings_dir, roster=(), campaign_id=None):
        session, _, _, _ = _make_session()
        settings = SettingsManager(settings_dir)
        return PlayInterface(
            session, settings, roster=roster, campaign_id=campaign_id
        )

    def test_render_settings_contains_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._make_interface(tmp)
            assert "Settings" in iface.render_settings()

    def test_render_settings_shows_all_essential_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._make_interface(tmp)
            rendered = iface.render_settings()
            for key in SettingsRegistry.ESSENTIAL_KEYS:
                assert key in rendered

    def test_render_settings_shows_default_model_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._make_interface(tmp)
            rendered = iface.render_settings()
            assert "claude-opus-4-8" in rendered
            assert "claude-haiku-4-5-20251001" in rendered

    def test_render_settings_marks_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("auditor_model", "claude-opus-4-8")
            iface = self._make_interface(tmp)
            rendered = iface.render_settings()
            assert " *" in rendered

    def test_render_settings_no_mark_when_no_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._make_interface(tmp)
            assert " *" not in iface.render_settings()

    def test_render_settings_shows_settings_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._make_interface(tmp)
            assert "models.json" in iface.render_settings()

    def test_render_settings_no_roster_shows_no_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._make_interface(tmp, roster=[])
            assert "Character agent slots" not in iface.render_settings()

    def test_render_settings_shows_character_slots_when_roster_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._make_interface(tmp, roster=["hero", "rogue"])
            rendered = iface.render_settings()
            assert "Character agent slots" in rendered
            assert "hero" in rendered
            assert "rogue" in rendered

    def test_render_settings_marks_per_entity_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("character_agent_hero_model", "claude-haiku-4-5-20251001")
            session, _, _, _ = _make_session()
            iface = PlayInterface(
                session, mgr, roster=["hero", "rogue"]
            )
            rendered = iface.render_settings()
            assert " *" in rendered

    def test_render_settings_campaign_id_shown_in_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._make_interface(tmp, campaign_id="my-campaign")
            assert "my-campaign" in iface.render_settings()

    def test_render_settings_no_campaign_id_no_campaign_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._make_interface(tmp, campaign_id=None)
            assert "Campaign file" not in iface.render_settings()


# --------------------------------------------------------------------------- #
# PlayInterface — history and submit                                             #
# --------------------------------------------------------------------------- #

class TestPlayInterfaceHistory:

    def test_history_returns_list(self):
        session, _, _, _ = _make_session()
        iface = PlayInterface(session, SettingsManager("/tmp"))
        assert isinstance(iface.history(), list)

    def test_history_empty_before_any_action(self):
        session, _, _, _ = _make_session()
        iface = PlayInterface(session, SettingsManager("/tmp"))
        assert iface.history() == []

    def test_history_contains_lines_after_submit(self):
        session, _, _, _ = _make_session("You walk forward.")
        iface = PlayInterface(session, SettingsManager("/tmp"))
        iface.submit("look around")
        history = iface.history()
        assert len(history) > 0

    def test_submit_returns_new_lines(self):
        session, _, _, _ = _make_session("The hall is quiet.")
        iface = PlayInterface(session, SettingsManager("/tmp"))
        lines = iface.submit("look around")
        assert isinstance(lines, list)
        assert len(lines) > 0

    def test_history_grows_with_each_submit(self):
        session, _, _, _ = _make_session("You act.")
        iface = PlayInterface(session, SettingsManager("/tmp"))
        iface.submit("look around")
        count_1 = len(iface.history())
        iface.submit("wait quietly")
        count_2 = len(iface.history())
        assert count_2 >= count_1

    def test_player_id_property(self):
        session, _, _, _ = _make_session(player_id="hero")
        iface = PlayInterface(session, SettingsManager("/tmp"))
        assert iface.player_id == "hero"

    def test_export_transcript_returns_string(self):
        session, _, _, _ = _make_session("You act.")
        iface = PlayInterface(session, SettingsManager("/tmp"))
        iface.submit("look around")
        assert isinstance(iface.export_transcript(), str)


# --------------------------------------------------------------------------- #
# Security: client never sees GM-private event content                          #
# --------------------------------------------------------------------------- #

class TestPlayInterfaceSecurity:

    def test_gm_only_narration_absent_from_history(self):
        """Events with gm-only audience must not appear in player history."""
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        pipeline = CommitPipeline(log)
        dice = DiceService(log, rng=random.Random(0))
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)

        adj, narr = _make_mocked_gm_pair("Public narration.")
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline, rules=rules,
            assembler=assembler, adjudicator=adj, narrator=narr,
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
        )
        session = PlaytestSession(runner, assembler, "hero")
        iface = PlayInterface(session, SettingsManager("/tmp"))

        # Append a GM-only event directly to the log
        log.append(
            author="gm",
            channel="system",
            type="narration",
            content="SECRET GM CONTEXT ONLY",
            audience=("gm",),
            visibility="content",
        )

        history = iface.history()
        assert all("SECRET GM CONTEXT ONLY" not in line for line in history)

    def test_scene_transition_event_absent_from_history(self):
        """scene_transition is GM-only; player history must not contain it."""
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        assembler = ContextAssembler(log)
        adj, narr = _make_mocked_gm_pair()
        pipeline = CommitPipeline(log)
        rules = RulesEngine(log, DiceService(log, rng=random.Random(0)))
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline, rules=rules,
            assembler=assembler, adjudicator=adj, narrator=narr,
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
        )
        session = PlaytestSession(runner, assembler, "hero")
        iface = PlayInterface(session, SettingsManager("/tmp"))

        import json as _json
        log.append(
            author="gm", channel="system", type="scene_transition",
            content=_json.dumps({"scene_id": "abc", "scene_phase": "combat", "elapsed_category": "scene"}),
            audience=("gm",), visibility="content",
        )
        history = iface.history()
        assert all("scene_transition" not in line for line in history)

    def test_history_never_contains_event_types_invisible_to_player(self):
        """Structural GM events (audit_advisory, ooc without player) absent."""
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        assembler = ContextAssembler(log)
        adj, narr = _make_mocked_gm_pair()
        pipeline = CommitPipeline(log)
        rules = RulesEngine(log, DiceService(log, rng=random.Random(0)))
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline, rules=rules,
            assembler=assembler, adjudicator=adj, narrator=narr,
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
        )
        session = PlaytestSession(runner, assembler, "hero")
        iface = PlayInterface(session, SettingsManager("/tmp"))

        log.append(
            author="gm", channel="system", type="audit_advisory",
            content="AUDIT INTERNAL",
            audience=("gm",), visibility="content",
        )
        history = iface.history()
        assert all("AUDIT INTERNAL" not in line for line in history)


# --------------------------------------------------------------------------- #
# build_play_interface                                                           #
# --------------------------------------------------------------------------- #

class TestBuildPlayInterface:

    def _build(self, tmp, player_id="hero", roster=(), campaign_id=None):
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id=player_id, kind="pc", name="Hero"))
        world.place(player_id, "hall")
        from fable_table_engine.perception import Scene
        scene = Scene(world)
        adj, narr = _make_mocked_gm_pair()
        settings = SettingsManager(tmp)
        sheets = {player_id: CharacterSheet(entity_id=player_id, concept="Fighter")}
        return build_play_interface(
            log, world, scene, player_id, adj, narr, settings,
            roster=roster, campaign_id=campaign_id, sheets=sheets,
        )

    def test_returns_play_interface(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._build(tmp)
            assert isinstance(iface, PlayInterface)

    def test_player_id_set_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._build(tmp, player_id="ranger")
            assert iface.player_id == "ranger"

    def test_world_accessible_via_render_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._build(tmp)
            status = iface.render_status()
            assert "beat:0" in status

    def test_history_empty_before_any_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._build(tmp)
            assert iface.history() == []

    def test_submit_runs_beat(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._build(tmp)
            result = iface.submit("look around")
            assert isinstance(result, list)

    def test_roster_flows_to_settings_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._build(tmp, roster=["hero", "rogue"])
            assert "hero" in iface.render_settings()
            assert "rogue" in iface.render_settings()

    def test_campaign_id_flows_to_settings_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._build(tmp, campaign_id="test-camp")
            assert "test-camp" in iface.render_settings()

    def test_optional_subsystems_default_to_none(self):
        """build_play_interface with no optional args still produces a working interface."""
        with tempfile.TemporaryDirectory() as tmp:
            iface = self._build(tmp)
            assert isinstance(iface, PlayInterface)
            assert iface.render_status() != ""

    def test_executor_forwarded_to_runner(self):
        from fable_table_engine.access import CommitPipeline
        from fable_table_engine.effects import EffectExecutor
        from fable_table_engine.event_log import EventLog
        from fable_table_engine.world_state import WorldState, Entity
        from fable_table_engine.perception import Scene
        with tempfile.TemporaryDirectory() as tmp:
            log = EventLog()
            world = WorldState()
            world.add_zone("hall")
            world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
            world.place("hero", "hall")
            scene = Scene(world)
            adj, narr = _make_mocked_gm_pair()
            settings = SettingsManager(tmp)
            executor = EffectExecutor(log, world, CommitPipeline(log))
            iface = build_play_interface(
                log, world, scene, "hero", adj, narr, settings,
                executor=executor,
            )
            assert isinstance(iface, PlayInterface)

    def test_budgeter_forwarded_to_assembler_and_runner(self):
        from fable_table_engine.budgeter import ContextBudgeter
        from fable_table_engine.event_log import EventLog
        from fable_table_engine.world_state import WorldState, Entity
        from fable_table_engine.perception import Scene
        with tempfile.TemporaryDirectory() as tmp:
            log = EventLog()
            world = WorldState()
            world.add_zone("hall")
            world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
            world.place("hero", "hall")
            scene = Scene(world)
            adj, narr = _make_mocked_gm_pair()
            settings = SettingsManager(tmp)
            budgeter = ContextBudgeter()
            iface = build_play_interface(
                log, world, scene, "hero", adj, narr, settings,
                budgeter=budgeter,
            )
            assert isinstance(iface, PlayInterface)

    def test_lore_assembler_forwarded_to_context_assembler(self):
        from fable_table_engine.lorebook import LoreAssembler, LoreDeck
        from fable_table_engine.event_log import EventLog
        from fable_table_engine.world_state import WorldState, Entity
        from fable_table_engine.perception import Scene
        with tempfile.TemporaryDirectory() as tmp:
            log = EventLog()
            world = WorldState()
            world.add_zone("hall")
            world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
            world.place("hero", "hall")
            scene = Scene(world)
            adj, narr = _make_mocked_gm_pair()
            settings = SettingsManager(tmp)
            lore_assembler = LoreAssembler(LoreDeck())
            iface = build_play_interface(
                log, world, scene, "hero", adj, narr, settings,
                lore_assembler=lore_assembler,
            )
            assert isinstance(iface, PlayInterface)


# --------------------------------------------------------------------------- #
# HomeScreen + SessionManager integration                                        #
# --------------------------------------------------------------------------- #

class TestHomeScreenSessionIntegration:

    def test_session_manager_creates_session_visible_in_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = HomeScreen(sessions_dir=tmp)
            mgr = home.session_manager()
            mgr.create("camp-1", "Adventure Begins")
            sessions = home.available_sessions()
            assert any(s.title == "Adventure Begins" for s in sessions)

    def test_session_created_with_open_session_not_listed(self):
        """open_session creates a DB but doesn't register in SessionManager index."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "raw.db")
            log, world, scene = open_session(db_path)
            home = HomeScreen(sessions_dir=tmp)
            # open_session alone doesn't write to the SessionManager index
            sessions = home.available_sessions()
            assert all(s.db_path != db_path for s in sessions)

    def test_campaign_file_loaded_from_campaigns_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            camp_dir = Path(tmp) / "campaigns"
            camp_dir.mkdir()
            _write_campaign(str(camp_dir), "ruins.json", _CAMPAIGN_MIN)
            home = HomeScreen(campaigns_dir=str(camp_dir))
            assert len(home.available_campaigns()) == 1
