"""Phase 21 deliverable 9: D-041 settings system.

Layered JSON settings: code defaults → user-level (settings/models.json) →
per-campaign (settings/campaigns/{campaign_id}.json). API keys in env only.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from fable_table_engine.settings import (
    SettingsRegistry,
    SettingsManager,
    load_settings,
    reset_setting,
)


# --------------------------------------------------------------------------- #
# SettingsRegistry                                                               #
# --------------------------------------------------------------------------- #

class TestSettingsRegistry:

    def test_has_gm_adjudicator_model(self):
        assert "gm_adjudicator_model" in SettingsRegistry.DEFAULTS

    def test_has_gm_narrator_model(self):
        assert "gm_narrator_model" in SettingsRegistry.DEFAULTS

    def test_has_gm_world_simulator_model(self):
        assert "gm_world_simulator_model" in SettingsRegistry.DEFAULTS

    def test_has_auditor_model(self):
        assert "auditor_model" in SettingsRegistry.DEFAULTS

    def test_has_social_interpreter_model(self):
        assert "social_interpreter_model" in SettingsRegistry.DEFAULTS

    def test_has_character_agent_default_model(self):
        assert "character_agent_default_model" in SettingsRegistry.DEFAULTS

    def test_gm_adjudicator_default_is_opus(self):
        assert SettingsRegistry.DEFAULTS["gm_adjudicator_model"] == "claude-opus-4-8"

    def test_gm_narrator_default_is_opus(self):
        assert SettingsRegistry.DEFAULTS["gm_narrator_model"] == "claude-opus-4-8"

    def test_gm_world_simulator_default_is_opus(self):
        assert SettingsRegistry.DEFAULTS["gm_world_simulator_model"] == "claude-opus-4-8"

    def test_auditor_default_is_haiku(self):
        assert SettingsRegistry.DEFAULTS["auditor_model"] == "claude-haiku-4-5-20251001"

    def test_social_interpreter_default_is_sonnet(self):
        assert SettingsRegistry.DEFAULTS["social_interpreter_model"] == "claude-sonnet-4-6"

    def test_character_agent_default_is_opus(self):
        assert SettingsRegistry.DEFAULTS["character_agent_default_model"] == "claude-opus-4-8"

    def test_essential_keys_is_frozenset(self):
        assert isinstance(SettingsRegistry.ESSENTIAL_KEYS, frozenset)

    def test_essential_keys_matches_defaults(self):
        assert SettingsRegistry.ESSENTIAL_KEYS == frozenset(SettingsRegistry.DEFAULTS.keys())

    def test_has_model_and_budget_settings(self):
        # 7 model slots + 12 per-role budget entries + 1 lorebook window
        assert len(SettingsRegistry.DEFAULTS) == 20


# --------------------------------------------------------------------------- #
# SettingsManager — zero-config valid state                                      #
# --------------------------------------------------------------------------- #

class TestSettingsManagerDefaults:

    def _mgr(self, tmp: str) -> SettingsManager:
        return SettingsManager(tmp)

    def test_valid_with_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self._mgr(tmp)
            result = mgr.load_settings()
            assert result["gm_adjudicator_model"] == "claude-opus-4-8"

    def test_all_essential_keys_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self._mgr(tmp)
            settings = mgr.load_settings()
            for key in SettingsRegistry.ESSENTIAL_KEYS:
                assert key in settings

    def test_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert isinstance(self._mgr(tmp).load_settings(), dict)

    def test_get_returns_default_when_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = self._mgr(tmp)
            assert mgr.get("auditor_model") == "claude-haiku-4-5-20251001"

    def test_get_unknown_key_returns_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert self._mgr(tmp).get("nonexistent_key") == ""


# --------------------------------------------------------------------------- #
# SettingsManager — user-level overrides                                         #
# --------------------------------------------------------------------------- #

class TestUserLevelOverrides:

    def test_set_user_writes_models_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-sonnet-4-6")
            path = Path(tmp) / "models.json"
            assert path.exists()

    def test_set_user_value_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-sonnet-4-6")
            assert mgr.get("gm_narrator_model") == "claude-sonnet-4-6"

    def test_user_override_does_not_affect_other_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-sonnet-4-6")
            assert mgr.get("auditor_model") == "claude-haiku-4-5-20251001"

    def test_user_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-sonnet-4-6")
            with open(Path(tmp) / "models.json") as f:
                data = json.load(f)
            assert data["gm_narrator_model"] == "claude-sonnet-4-6"

    def test_multiple_user_overrides_accumulate(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-sonnet-4-6")
            mgr.set("auditor_model", "claude-sonnet-4-6")
            assert mgr.get("gm_narrator_model") == "claude-sonnet-4-6"
            assert mgr.get("auditor_model") == "claude-sonnet-4-6"

    def test_user_settings_path_includes_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            assert mgr.user_settings_path().name == "models.json"


# --------------------------------------------------------------------------- #
# SettingsManager — per-campaign overrides                                       #
# --------------------------------------------------------------------------- #

class TestCampaignLevelOverrides:

    def test_campaign_file_created_on_first_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-haiku-4-5-20251001", scope="campaign-abc")
            path = Path(tmp) / "campaigns" / "campaign-abc.json"
            assert path.exists()

    def test_campaign_override_visible_with_campaign_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-haiku-4-5-20251001", scope="camp1")
            assert mgr.get("gm_narrator_model", campaign_id="camp1") == "claude-haiku-4-5-20251001"

    def test_campaign_override_not_visible_without_campaign_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-haiku-4-5-20251001", scope="camp1")
            # Without campaign_id, should fall back to code default
            assert mgr.get("gm_narrator_model") == "claude-opus-4-8"

    def test_campaign_overrides_user_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-sonnet-4-6", scope="user")
            mgr.set("gm_narrator_model", "claude-haiku-4-5-20251001", scope="camp1")
            assert mgr.get("gm_narrator_model", campaign_id="camp1") == "claude-haiku-4-5-20251001"

    def test_campaign_absent_falls_through_to_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-sonnet-4-6", scope="user")
            # Different campaign: no campaign file → falls through to user
            assert mgr.get("gm_narrator_model", campaign_id="other") == "claude-sonnet-4-6"

    def test_campaign_settings_path_contains_campaign_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            path = mgr.campaign_settings_path("mycamp")
            assert "mycamp.json" in str(path)

    def test_two_campaigns_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-sonnet-4-6", scope="camp-a")
            mgr.set("gm_narrator_model", "claude-haiku-4-5-20251001", scope="camp-b")
            assert mgr.get("gm_narrator_model", campaign_id="camp-a") == "claude-sonnet-4-6"
            assert mgr.get("gm_narrator_model", campaign_id="camp-b") == "claude-haiku-4-5-20251001"


# --------------------------------------------------------------------------- #
# SettingsManager — reset_setting                                                #
# --------------------------------------------------------------------------- #

class TestResetSetting:

    def test_reset_user_override_reverts_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("auditor_model", "claude-opus-4-8")
            mgr.reset_setting("auditor_model")
            assert mgr.get("auditor_model") == "claude-haiku-4-5-20251001"

    def test_reset_nonexistent_key_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.reset_setting("nonexistent_key")  # must not raise

    def test_reset_last_user_key_removes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("auditor_model", "claude-opus-4-8")
            mgr.reset_setting("auditor_model")
            assert not (Path(tmp) / "models.json").exists()

    def test_reset_one_of_two_user_keys_keeps_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("auditor_model", "claude-opus-4-8")
            mgr.set("social_interpreter_model", "claude-haiku-4-5-20251001")
            mgr.reset_setting("auditor_model")
            assert (Path(tmp) / "models.json").exists()
            assert mgr.get("social_interpreter_model") == "claude-haiku-4-5-20251001"

    def test_reset_campaign_override_reverts_to_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-sonnet-4-6", scope="user")
            mgr.set("gm_narrator_model", "claude-haiku-4-5-20251001", scope="camp1")
            mgr.reset_setting("gm_narrator_model", scope="camp1")
            assert mgr.get("gm_narrator_model", campaign_id="camp1") == "claude-sonnet-4-6"

    def test_reset_last_campaign_key_removes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-haiku-4-5-20251001", scope="camp1")
            mgr.reset_setting("gm_narrator_model", scope="camp1")
            assert not (Path(tmp) / "campaigns" / "camp1.json").exists()


# --------------------------------------------------------------------------- #
# SettingsManager — character agent slots                                        #
# --------------------------------------------------------------------------- #

class TestCharacterSlots:

    def test_character_model_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            assert mgr.character_model("hero") == "claude-opus-4-8"

    def test_character_model_per_entity_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("character_agent_hero_model", "claude-sonnet-4-6")
            assert mgr.character_model("hero") == "claude-sonnet-4-6"

    def test_character_model_campaign_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("character_agent_ranger_model", "claude-haiku-4-5-20251001", scope="camp1")
            assert mgr.character_model("ranger", campaign_id="camp1") == "claude-haiku-4-5-20251001"

    def test_character_model_other_entity_unaffected(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("character_agent_hero_model", "claude-sonnet-4-6")
            assert mgr.character_model("rogue") == "claude-opus-4-8"

    def test_character_slots_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            slots = mgr.character_slots(["hero", "rogue"])
            assert isinstance(slots, dict)
            assert set(slots.keys()) == {"hero", "rogue"}

    def test_character_slots_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            slots = mgr.character_slots(["hero", "rogue", "bard"])
            assert all(v == "claude-opus-4-8" for v in slots.values())

    def test_character_slots_per_entity_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("character_agent_rogue_model", "claude-haiku-4-5-20251001")
            slots = mgr.character_slots(["hero", "rogue"])
            assert slots["hero"] == "claude-opus-4-8"
            assert slots["rogue"] == "claude-haiku-4-5-20251001"

    def test_character_slots_empty_roster(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert SettingsManager(tmp).character_slots([]) == {}

    def test_character_default_model_override_affects_all_unspecified(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("character_agent_default_model", "claude-sonnet-4-6")
            slots = mgr.character_slots(["hero", "rogue"])
            assert slots["hero"] == "claude-sonnet-4-6"
            assert slots["rogue"] == "claude-sonnet-4-6"


# --------------------------------------------------------------------------- #
# API key policy                                                                 #
# --------------------------------------------------------------------------- #

class TestApiKeyPolicy:

    def test_can_store_env_var_name_not_value(self):
        """Settings files store env-var names; the GUI reads the actual key from env."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("voice_api_key_env", "ELEVENLABS_API_KEY")
            assert mgr.get("voice_api_key_env") == "ELEVENLABS_API_KEY"

    def test_settings_file_does_not_contain_raw_api_key(self):
        """Verify the file only contains env-var names, not actual key values."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("voice_api_key_env", "ELEVENLABS_API_KEY")
            with open(Path(tmp) / "models.json") as f:
                content = f.read()
            # The file should contain the env-var name
            assert "ELEVENLABS_API_KEY" in content
            # It should NOT contain a plausible real key (starts with sk-)
            assert "sk-" not in content


# --------------------------------------------------------------------------- #
# Module-level convenience functions                                             #
# --------------------------------------------------------------------------- #

class TestModuleLevelFunctions:

    def test_load_settings_returns_defaults_with_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = load_settings(settings_dir=tmp)
            assert result["gm_adjudicator_model"] == "claude-opus-4-8"

    def test_load_settings_with_campaign_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("auditor_model", "claude-sonnet-4-6", scope="camp1")
            result = load_settings(settings_dir=tmp, campaign_id="camp1")
            assert result["auditor_model"] == "claude-sonnet-4-6"

    def test_reset_setting_removes_user_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("auditor_model", "claude-opus-4-8")
            reset_setting("auditor_model", settings_dir=tmp)
            result = load_settings(settings_dir=tmp)
            assert result["auditor_model"] == "claude-haiku-4-5-20251001"

    def test_reset_setting_campaign_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("auditor_model", "claude-opus-4-8", scope="c1")
            reset_setting("auditor_model", scope="c1", settings_dir=tmp)
            result = load_settings(settings_dir=tmp, campaign_id="c1")
            assert result["auditor_model"] == "claude-haiku-4-5-20251001"


# --------------------------------------------------------------------------- #
# load_settings layer merge order                                                #
# --------------------------------------------------------------------------- #

class TestLayerMergeOrder:

    def test_campaign_beats_user_beats_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            # Code default: claude-opus-4-8
            mgr.set("auditor_model", "claude-sonnet-4-6", scope="user")     # user layer
            mgr.set("auditor_model", "claude-haiku-4-5-20251001", scope="camp1")  # campaign layer
            assert mgr.get("auditor_model", campaign_id="camp1") == "claude-haiku-4-5-20251001"

    def test_user_beats_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("auditor_model", "claude-sonnet-4-6", scope="user")
            assert mgr.get("auditor_model") == "claude-sonnet-4-6"

    def test_default_used_when_no_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert SettingsManager(tmp).get("auditor_model") == "claude-haiku-4-5-20251001"

    def test_load_settings_no_campaign_excludes_campaign_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SettingsManager(tmp)
            mgr.set("gm_narrator_model", "claude-haiku-4-5-20251001", scope="camp1")
            # Without campaign_id, campaign overrides must not leak through
            result = mgr.load_settings()
            assert result["gm_narrator_model"] == "claude-opus-4-8"
