from __future__ import annotations

import os

import pytest

from fable_table_engine.persistence import SessionManager
from fable_table_engine.web import WebAppState


def test_web_home_payload_contains_public_metadata_only(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    manager = SessionManager(tmp_path / "sessions")
    manifest, log, _world, _scene = manager.create("blank", "Public Test")
    log.close()

    payload = WebAppState(root=tmp_path).api_home()

    assert payload["key_configured"] is False
    assert payload["sessions"][0]["session_id"] == manifest.session_id
    assert payload["sessions"][0]["title"] == "Public Test"
    assert "db_path" not in payload["sessions"][0]
    assert "events" not in payload["sessions"][0]


def test_web_home_detects_env_key_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=test-key\n", encoding="utf-8")

    payload = WebAppState(root=tmp_path).api_home()

    assert payload["key_configured"] is True
    assert os.environ["ANTHROPIC_API_KEY"] == "test-key"


def test_web_new_session_requires_anthropic_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    state = WebAppState(root=tmp_path)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        state.new_session({"title": "No Key"})


def test_web_settings_requires_open_session(tmp_path):
    state = WebAppState(root=tmp_path)

    with pytest.raises(KeyError, match="Session is not open"):
        state.settings_text("missing")
