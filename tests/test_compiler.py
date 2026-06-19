"""E-1: CampaignCompiler and CampaignCompilerGateway tests.

Contracts:
  1.  CampaignCompiler.compile() extracts the create_campaign tool input from response.
  2.  CampaignCompiler.compile() raises CompilerError when no tool_use block is returned.
  3.  CampaignCompilerGateway.generate() returns a CampaignPackage on first-attempt success.
  4.  CampaignCompilerGateway.generate() calls repair() when validation fails.
  5.  CampaignCompilerGateway.generate() raises CompilerError after max_attempts.
  6.  CampaignCompilerGateway.generate() raises ValueError on empty user_input.
  7.  load_campaign_dict round-trips new D-040 fields (player_intro, gm_context, etc.).
  8.  Minimal campaign (no D-040 fields) still loads cleanly.
  9.  npcs with duplicate ids are rejected.
  10. initial_visible_truths non-string entry is rejected.
  11. tone_boundaries non-dict is rejected.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from fable_table_engine.campaign import CampaignPackage, load_campaign_dict
from fable_table_engine.compiler import (
    CampaignCompiler,
    CampaignCompilerGateway,
    CompilerError,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                      #
# --------------------------------------------------------------------------- #

def _minimal_pkg_dict() -> dict:
    return {"version": "1.0", "title": "Test Campaign"}


def _full_compiled_dict() -> dict:
    """Minimal but cross-reference-valid dict as a compiler would produce."""
    return {
        "version": "1.0",
        "title": "The Saltmere Conspiracy",
        "description": "A mystery in a rain-soaked port city.",
        "player_intro": "You are a debt collector who just found a body.",
        "gm_context": "The harbormaster is the murderer.",
        "starting_scene": "Rain hammers the docks as you arrive.",
        "starting_location": "Saltmere Docks",
        "initial_visible_truths": ["The city guard is corrupt.", "Trade routes have collapsed."],
        "initial_hidden_truths": ["The harbormaster is Faction Crimson's inside man."],
        "world_clocks": [
            {"name": "escalation", "current": 0, "max": 6,
             "landing_truth": "The city falls under martial law.", "front_owner": "front-001"},
        ],
        "fronts": [
            {
                "id": "front-001",
                "name": "The Crimson Tide",
                "threat": "A smuggling syndicate poised to seize the port",
                "clock_name": "escalation",
                "consequence_truth": "Faction Crimson controls all commerce.",
            }
        ],
        "npcs": [
            {"id": "npc-001", "name": "Harbormaster Vel", "description": "Corrupt official",
             "disposition": "hostile"},
        ],
        "tone_boundaries": {
            "content_rating": "PG-13",
            "forbidden_themes": ["graphic torture"],
            "advisory_themes": ["organized crime"],
        },
        "function_nodes": [],
        "hooks": [],
        "factions": [],
        "hidden_nodes": [],
        "lore_entries": [],
    }


def _make_mock_response(tool_input: dict) -> MagicMock:
    block = SimpleNamespace(type="tool_use", name="create_campaign", input=tool_input)
    resp = MagicMock()
    resp.content = [block]
    return resp


def _make_gateway(return_dict: dict) -> MagicMock:
    gw = MagicMock()
    gw.call.return_value = _make_mock_response(return_dict)
    return gw


# --------------------------------------------------------------------------- #
# CampaignCompiler                                                              #
# --------------------------------------------------------------------------- #

def test_compiler_extracts_tool_input():
    gw = _make_gateway(_full_compiled_dict())
    compiler = CampaignCompiler(gw)
    result = compiler.compile("A port city mystery.")
    assert result["title"] == "The Saltmere Conspiracy"
    gw.call.assert_called_once()
    call_kwargs = gw.call.call_args
    assert call_kwargs[0][0] == "campaign_compiler"


def test_compiler_raises_on_missing_tool_call():
    gw = MagicMock()
    resp = MagicMock()
    resp.content = []
    gw.call.return_value = resp
    compiler = CampaignCompiler(gw)
    with pytest.raises(CompilerError, match="create_campaign"):
        compiler.compile("A campaign.")


def test_compiler_repair_includes_errors_in_prompt():
    gw = _make_gateway(_full_compiled_dict())
    compiler = CampaignCompiler(gw)
    compiler.repair("original input", {"title": "X"}, ["missing version", "missing fronts"])
    prompt_sent = gw.call.call_args[1]["messages"][0]["content"]
    assert "missing version" in prompt_sent
    assert "missing fronts" in prompt_sent


# --------------------------------------------------------------------------- #
# CampaignCompilerGateway                                                       #
# --------------------------------------------------------------------------- #

def test_gateway_returns_package_on_first_success():
    gw = _make_gateway(_full_compiled_dict())
    compiler = CampaignCompiler(gw)
    gateway = CampaignCompilerGateway(compiler, max_attempts=3)
    pkg = gateway.generate("A port city mystery.")
    assert isinstance(pkg, CampaignPackage)
    assert pkg.title == "The Saltmere Conspiracy"
    assert pkg.player_intro == "You are a debt collector who just found a body."
    assert pkg.gm_context == "The harbormaster is the murderer."
    assert len(pkg.initial_visible_truths) == 2
    assert len(pkg.initial_hidden_truths) == 1
    assert len(pkg.npcs) == 1
    assert pkg.tone_boundaries["content_rating"] == "PG-13"
    assert gw.call.call_count == 1


def test_gateway_calls_repair_on_validation_failure():
    bad_dict = {"version": "1.0"}  # missing title → validation fails
    good_dict = _full_compiled_dict()

    gw = MagicMock()
    gw.call.side_effect = [
        _make_mock_response(bad_dict),
        _make_mock_response(good_dict),
    ]
    compiler = CampaignCompiler(gw)
    gateway = CampaignCompilerGateway(compiler, max_attempts=3)
    pkg = gateway.generate("A campaign.")
    assert pkg.title == "The Saltmere Conspiracy"
    assert gw.call.call_count == 2


def test_gateway_raises_after_max_attempts():
    bad_dict = {"version": "1.0"}  # always fails — missing title

    gw = MagicMock()
    gw.call.return_value = _make_mock_response(bad_dict)

    compiler = CampaignCompiler(gw)
    gateway = CampaignCompilerGateway(compiler, max_attempts=2)
    with pytest.raises(CompilerError, match="2 attempt"):
        gateway.generate("A campaign.")
    assert gw.call.call_count == 2


def test_gateway_raises_on_empty_input():
    gw = MagicMock()
    compiler = CampaignCompiler(gw)
    gateway = CampaignCompilerGateway(compiler)
    with pytest.raises(ValueError, match="empty"):
        gateway.generate("   ")
    gw.call.assert_not_called()


# --------------------------------------------------------------------------- #
# load_campaign_dict — D-040 field round-trip and validation                   #
# --------------------------------------------------------------------------- #

def test_load_campaign_dict_d040_fields():
    data = _full_compiled_dict()
    pkg = load_campaign_dict(data)
    assert pkg.player_intro == "You are a debt collector who just found a body."
    assert pkg.gm_context == "The harbormaster is the murderer."
    assert pkg.starting_scene == "Rain hammers the docks as you arrive."
    assert pkg.starting_location == "Saltmere Docks"
    assert pkg.initial_visible_truths == ["The city guard is corrupt.", "Trade routes have collapsed."]
    assert pkg.initial_hidden_truths == ["The harbormaster is Faction Crimson's inside man."]
    assert len(pkg.npcs) == 1
    assert pkg.npcs[0]["name"] == "Harbormaster Vel"
    assert pkg.tone_boundaries["content_rating"] == "PG-13"
    assert pkg.tone_boundaries["forbidden_themes"] == ["graphic torture"]


def test_minimal_campaign_loads_with_empty_d040_defaults():
    pkg = load_campaign_dict(_minimal_pkg_dict())
    assert pkg.player_intro == ""
    assert pkg.gm_context == ""
    assert pkg.initial_visible_truths == []
    assert pkg.initial_hidden_truths == []
    assert pkg.npcs == []
    assert pkg.tone_boundaries == {}


def test_duplicate_npc_ids_rejected():
    data = _minimal_pkg_dict()
    data["npcs"] = [
        {"id": "npc-001", "name": "Alice"},
        {"id": "npc-001", "name": "Bob"},
    ]
    with pytest.raises(ValueError, match="Duplicate npc id"):
        load_campaign_dict(data)


def test_npc_missing_id_rejected():
    data = _minimal_pkg_dict()
    data["npcs"] = [{"name": "Alice"}]
    with pytest.raises(ValueError, match="npcs\\[0\\].id"):
        load_campaign_dict(data)


def test_npc_missing_name_rejected():
    data = _minimal_pkg_dict()
    data["npcs"] = [{"id": "npc-001"}]
    with pytest.raises(ValueError, match="npcs\\[0\\].name"):
        load_campaign_dict(data)


def test_initial_visible_truths_non_string_rejected():
    data = _minimal_pkg_dict()
    data["initial_visible_truths"] = ["valid truth", 42]
    with pytest.raises(ValueError, match="initial_visible_truths\\[1\\]"):
        load_campaign_dict(data)


def test_initial_hidden_truths_non_string_rejected():
    data = _minimal_pkg_dict()
    data["initial_hidden_truths"] = [{"not": "a string"}]
    with pytest.raises(ValueError, match="initial_hidden_truths\\[0\\]"):
        load_campaign_dict(data)


def test_tone_boundaries_non_dict_rejected():
    data = _minimal_pkg_dict()
    data["tone_boundaries"] = ["not", "a", "dict"]
    with pytest.raises(ValueError, match="tone_boundaries must be an object"):
        load_campaign_dict(data)
