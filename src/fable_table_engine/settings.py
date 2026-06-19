"""Settings system for FABLE Table Engine.

Layered configuration: code defaults (SettingsRegistry) →
settings/models.json (user-level) → settings/campaigns/{campaign_id}.json
(per-campaign). API keys are stored in the environment only — never in
settings files. See D-041 for the full spec.
"""
from __future__ import annotations

import json
from pathlib import Path


class SettingsRegistry:
    """Code-level defaults for all essential settings.

    The system is always in a valid state with zero user configuration.
    """

    DEFAULTS: dict[str, str] = {
        # Model assignments
        "gm_adjudicator_model": "claude-opus-4-8",
        "gm_narrator_model": "claude-opus-4-8",
        "gm_world_simulator_model": "claude-opus-4-8",
        "auditor_model": "claude-haiku-4-5-20251001",
        "social_interpreter_model": "claude-sonnet-4-6",
        "character_agent_default_model": "claude-opus-4-8",
        # Lorebook injection window (D-043)
        "lorebook_injection_window": "5",
        # Per-role context budget policies (D-042)
        "gm_adjudicator_max_tokens": "40000",
        "gm_adjudicator_event_window": "20",
        "gm_narrator_max_tokens": "20000",
        "gm_narrator_event_window": "8",
        "character_agent_max_tokens": "12000",
        "character_agent_event_window": "12",
        "social_interpreter_max_tokens": "8000",
        "social_interpreter_event_window": "6",
        "auditor_max_tokens": "16000",
        "auditor_event_window": "10",
        "plot_manager_max_tokens": "24000",
        "plot_manager_event_window": "15",
    }

    ESSENTIAL_KEYS: frozenset[str] = frozenset(DEFAULTS.keys())


class SettingsManager:
    """Resolves settings by walking the three-layer hierarchy.

    Priority (lowest → highest):
    1. SettingsRegistry code defaults
    2. settings/models.json  (user-level)
    3. settings/campaigns/{campaign_id}.json  (per-campaign)

    ``scope`` parameters accept ``"user"`` or any campaign_id string.
    """

    def __init__(self, settings_dir: str | Path = "settings") -> None:
        self._dir = Path(settings_dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _user_path(self) -> Path:
        return self._dir / "models.json"

    def _campaign_path(self, campaign_id: str) -> Path:
        return self._dir / "campaigns" / f"{campaign_id}.json"

    def _read(self, path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def _write(self, path: Path, data: dict[str, str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")

    def _scope_path(self, scope: str) -> Path:
        return self._user_path if scope == "user" else self._campaign_path(scope)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_settings(self, campaign_id: str | None = None) -> dict[str, str]:
        """Return merged settings dict (code defaults → user → campaign)."""
        merged: dict[str, str] = dict(SettingsRegistry.DEFAULTS)
        merged.update(self._read(self._user_path))
        if campaign_id is not None:
            merged.update(self._read(self._campaign_path(campaign_id)))
        return merged

    def get(self, key: str, campaign_id: str | None = None) -> str:
        """Return effective value for *key* from the merged settings."""
        return self.load_settings(campaign_id).get(key, "")

    def set(self, key: str, value: str, scope: str = "user") -> None:
        """Write an override.

        ``scope`` is ``"user"`` (writes to ``settings/models.json``) or a
        campaign_id string (writes to the per-campaign file, creating it
        on first use).
        """
        path = self._scope_path(scope)
        data = self._read(path)
        data[key] = value
        self._write(path, data)

    def reset_setting(self, key: str, scope: str = "user") -> None:
        """Remove an override, reverting to the next layer down.

        If *scope* is ``"user"``, removes the user-level override and
        reverts to the code default. If *scope* is a campaign_id, removes
        the per-campaign override and reverts to the user level (or code
        default if no user override exists). Deletes the file if it
        becomes empty after removal.
        """
        path = self._scope_path(scope)
        data = self._read(path)
        data.pop(key, None)
        if data:
            self._write(path, data)
        elif path.exists():
            path.unlink()

    def character_model(self, entity_id: str, campaign_id: str | None = None) -> str:
        """Return the model configured for a specific character agent.

        Falls through to ``character_agent_default_model`` when no
        per-entity slot is set.
        """
        settings = self.load_settings(campaign_id)
        slot_key = f"character_agent_{entity_id}_model"
        return settings.get(slot_key, settings["character_agent_default_model"])

    def character_slots(
        self, roster: list[str], campaign_id: str | None = None
    ) -> dict[str, str]:
        """Return ``{entity_id: model}`` for every entity in *roster*."""
        return {eid: self.character_model(eid, campaign_id) for eid in roster}

    def user_settings_path(self) -> Path:
        """Return the full path to the user-level settings file."""
        return self._user_path.resolve()

    def campaign_settings_path(self, campaign_id: str) -> Path:
        """Return the full path to the per-campaign settings file."""
        return self._campaign_path(campaign_id).resolve()


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def load_settings(
    settings_dir: str | Path = "settings",
    campaign_id: str | None = None,
) -> dict[str, str]:
    """Return merged settings for *settings_dir* without keeping a manager object."""
    return SettingsManager(settings_dir).load_settings(campaign_id)


def reset_setting(
    key: str,
    scope: str = "user",
    settings_dir: str | Path = "settings",
) -> None:
    """Remove an override in *settings_dir*. See ``SettingsManager.reset_setting``."""
    SettingsManager(settings_dir).reset_setting(key, scope)
