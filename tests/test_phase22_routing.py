"""Phase 22 tests — D-017 multi-model routing.

Covers: ProviderAdapter ABC, AnthropicAdapter, ToolOutputError,
per-role model resolution from SettingsManager, structured-output
normalization retry in AdjudicatorGM, BeatRunner handling of ToolOutputError.
"""
from __future__ import annotations

import json
import tempfile
from abc import ABC
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fable_table_engine import (
    AdjudicatorGM,
    AnthropicAdapter,
    BeatRunner,
    CharacterSheet,
    CommitPipeline,
    ContextAssembler,
    DiceService,
    Entity,
    EventLog,
    ModelGateway,
    ProviderAdapter,
    RulesEngine,
    SettingsManager,
    TelemetrySink,
    ToolOutputError,
    WorldState,
)
from fable_table_engine.perception import Scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_client(return_value=None, side_effect=None):
    client = MagicMock()
    if side_effect is not None:
        client.messages.create = MagicMock(side_effect=side_effect)
    else:
        client.messages.create = MagicMock(return_value=return_value or MagicMock(content=[]))
    return client


def _fake_tool_response(name: str, input_dict: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_dict
    resp = MagicMock()
    resp.content = [block]
    return resp


def _adjudicator_response(has_stakes: bool = False) -> MagicMock:
    return _fake_tool_response("adjudicate_action", {
        "has_stakes": has_stakes,
        "reasoning": "test reasoning",
        "skill": None,
        "tn": None,
        "declared_facts": [],
        "action_domain": "beat",
        "exposure": None,
        "effect": None,
        "trade_options": [],
        "trade_default": "Balanced",
        "consequence_palette": {},
        "triumph_effects": [],
        "edge_label": None,
        "seam": False,
        "narrative_hint": "ok",
    })


def _settings_dir_with(data: dict, campaign_id: str | None = None) -> str:
    tmp = tempfile.mkdtemp()
    p = Path(tmp)
    (p / "campaigns").mkdir()
    if campaign_id:
        (p / "campaigns" / f"{campaign_id}.json").write_text(json.dumps(data))
    else:
        (p / "models.json").write_text(json.dumps(data))
    return tmp


# ---------------------------------------------------------------------------
# ProviderAdapter ABC
# ---------------------------------------------------------------------------

class TestProviderAdapterABC:
    def test_is_abstract(self):
        assert issubclass(ProviderAdapter, ABC)

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            ProviderAdapter()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_name_and_call(self):
        class Incomplete(ProviderAdapter):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass_works(self):
        class DummyAdapter(ProviderAdapter):
            @property
            def name(self) -> str:
                return "dummy"

            def call(self, role: str, model: str, **kwargs):
                return {"role": role, "model": model, **kwargs}

        adapter = DummyAdapter()
        result = adapter.call("test", "model-x", messages=[])
        assert result["role"] == "test"
        assert result["model"] == "model-x"


# ---------------------------------------------------------------------------
# AnthropicAdapter
# ---------------------------------------------------------------------------

class TestAnthropicAdapter:
    def test_name(self):
        client = _raw_client()
        adapter = AnthropicAdapter(client)
        assert adapter.name == "anthropic"

    def test_call_delegates_to_client(self):
        expected = MagicMock()
        client = _raw_client(return_value=expected)
        adapter = AnthropicAdapter(client)
        result = adapter.call("adjudicator", "claude-opus-4-8", messages=[], max_tokens=10)
        assert result is expected
        client.messages.create.assert_called_once_with(
            model="claude-opus-4-8", messages=[], max_tokens=10
        )

    def test_model_passed_as_keyword(self):
        client = _raw_client()
        adapter = AnthropicAdapter(client)
        adapter.call("narrator", "claude-haiku-4-5-20251001", messages=[])
        _, kwargs = client.messages.create.call_args
        assert kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_role_not_forwarded_to_client(self):
        client = _raw_client()
        adapter = AnthropicAdapter(client)
        adapter.call("adjudicator", "claude-opus-4-8", messages=[])
        _, kwargs = client.messages.create.call_args
        assert "role" not in kwargs

    def test_is_provider_adapter_subclass(self):
        client = _raw_client()
        assert isinstance(AnthropicAdapter(client), ProviderAdapter)


# ---------------------------------------------------------------------------
# ModelGateway — per-role model resolution
# ---------------------------------------------------------------------------

class TestModelGatewayResolution:
    def test_raw_client_auto_wrapped(self):
        client = _raw_client()
        gw = ModelGateway(client)
        assert gw._client is client
        assert isinstance(gw._adapter, AnthropicAdapter)

    def test_adapter_passed_directly(self):
        client = _raw_client()
        adapter = AnthropicAdapter(client)
        gw = ModelGateway(adapter)
        assert gw._adapter is adapter

    def test_kwarg_model_used_when_no_settings(self):
        client = _raw_client()
        gw = ModelGateway(client, timeout_secs=None)
        gw.call("adjudicator", model="claude-haiku-4-5", messages=[], max_tokens=5)
        _, kwargs = client.messages.create.call_args
        assert kwargs["model"] == "claude-haiku-4-5"

    def test_model_not_double_passed_in_kwargs(self):
        client = _raw_client()
        gw = ModelGateway(client, timeout_secs=None)
        gw.call("adjudicator", model="claude-opus-4-8", messages=[], max_tokens=5)
        _, kwargs = client.messages.create.call_args
        # model appears exactly once — as a keyword arg, not duplicated
        assert kwargs["model"] == "claude-opus-4-8"
        assert list(kwargs.keys()).count("model") == 1

    def test_settings_override_takes_priority_over_kwarg(self):
        settings_dir = _settings_dir_with({"gm_adjudicator_model": "claude-haiku-4-5-20251001"})
        sm = SettingsManager(settings_dir)
        client = _raw_client()
        gw = ModelGateway(client, settings=sm, timeout_secs=None)
        gw.call("adjudicator", model="claude-opus-4-8", messages=[], max_tokens=5)
        _, kwargs = client.messages.create.call_args
        assert kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_registry_default_used_when_no_kwarg_no_settings(self):
        client = _raw_client()
        gw = ModelGateway(client, timeout_secs=None)
        gw.call("adjudicator", messages=[], max_tokens=5)
        _, kwargs = client.messages.create.call_args
        assert kwargs["model"] == "claude-opus-4-8"

    def test_narrator_role_resolved_from_settings(self):
        settings_dir = _settings_dir_with({"gm_narrator_model": "claude-haiku-4-5-20251001"})
        sm = SettingsManager(settings_dir)
        client = _raw_client()
        gw = ModelGateway(client, settings=sm, timeout_secs=None)
        gw.call("narrator", messages=[], max_tokens=5)
        _, kwargs = client.messages.create.call_args
        assert kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_character_agent_role_resolved_from_settings(self):
        settings_dir = _settings_dir_with({"character_agent_default_model": "claude-haiku-4-5-20251001"})
        sm = SettingsManager(settings_dir)
        client = _raw_client()
        gw = ModelGateway(client, settings=sm, timeout_secs=None)
        gw.call("character_agent", messages=[], max_tokens=5)
        _, kwargs = client.messages.create.call_args
        assert kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_unknown_role_falls_back_to_registry(self):
        client = _raw_client()
        gw = ModelGateway(client, timeout_secs=None)
        gw.call("mystery_role", messages=[], max_tokens=5)
        _, kwargs = client.messages.create.call_args
        # no registry entry → _FALLBACK_MODEL
        assert kwargs["model"] == "claude-opus-4-8"

    def test_settings_campaign_scope_resolves_correctly(self):
        # SettingsManager.get() with campaign_id reads campaign-scoped JSON.
        # The gateway resolves via settings.get(key) without campaign_id, so
        # campaign-level overrides are wired up by the caller — not the gateway.
        settings_dir = _settings_dir_with(
            {"gm_adjudicator_model": "claude-haiku-4-5-20251001"},
            campaign_id="camp1",
        )
        sm = SettingsManager(settings_dir)
        # Verify SettingsManager itself resolves correctly when given campaign_id
        assert sm.get("gm_adjudicator_model", campaign_id="camp1") == "claude-haiku-4-5-20251001"
        # User-level (no campaign_id) falls through to registry default
        assert sm.get("gm_adjudicator_model") == "claude-opus-4-8"

    def test_telemetry_records_resolved_model(self):
        client = _raw_client()
        sink = TelemetrySink()
        gw = ModelGateway(client, sink=sink, timeout_secs=None)
        gw.call("narrator", model="claude-haiku-4-5-20251001", messages=[], max_tokens=5)
        assert sink.records[0].model == "claude-haiku-4-5-20251001"
        assert sink.records[0].role == "narrator"


# ---------------------------------------------------------------------------
# ToolOutputError
# ---------------------------------------------------------------------------

class TestToolOutputError:
    def test_message_format(self):
        err = ToolOutputError("adjudicator", 2, "no tool call found")
        assert "adjudicator" in str(err)
        assert "2" in str(err)
        assert "no tool call found" in str(err)

    def test_attributes(self):
        err = ToolOutputError("narrator", 1, "bad schema")
        assert err.role == "narrator"
        assert err.attempts == 1
        assert err.reason == "bad schema"

    def test_is_exception(self):
        assert isinstance(ToolOutputError("x", 1, "y"), Exception)

    def test_not_model_call_error(self):
        from fable_table_engine import ModelCallError
        assert not issubclass(ToolOutputError, ModelCallError)


# ---------------------------------------------------------------------------
# AdjudicatorGM — structured-output normalization (retry)
# ---------------------------------------------------------------------------

class TestAdjudicatorNormalization:
    def _sheet(self) -> CharacterSheet:
        return CharacterSheet(entity_id="hero", concept="Sword")

    def test_good_response_returns_plan(self):
        resp = _adjudicator_response(has_stakes=False)
        client = _raw_client(return_value=resp)
        adj = AdjudicatorGM(ModelGateway(client))
        plan = adj.evaluate("stab", self._sheet(), "", "")
        assert plan is not None
        assert plan.has_stakes is False

    def test_first_fail_then_success_returns_plan(self):
        bad = MagicMock()
        bad.content = []  # no tool block → parse fails
        good = _adjudicator_response(has_stakes=False)
        client = _raw_client(side_effect=[bad, good])
        adj = AdjudicatorGM(ModelGateway(client))
        plan = adj.evaluate("stab", self._sheet(), "", "")
        assert plan is not None
        assert client.messages.create.call_count == 2

    def test_two_failures_raises_tool_output_error(self):
        bad = MagicMock()
        bad.content = []
        client = _raw_client(side_effect=[bad, bad])
        adj = AdjudicatorGM(ModelGateway(client))
        with pytest.raises(ToolOutputError) as exc_info:
            adj.evaluate("stab", self._sheet(), "", "")
        assert exc_info.value.role == "adjudicator"
        assert exc_info.value.attempts == 2
        assert client.messages.create.call_count == 2

    def test_error_message_names_missing_tool(self):
        bad = MagicMock()
        bad.content = []
        client = _raw_client(side_effect=[bad, bad])
        adj = AdjudicatorGM(ModelGateway(client))
        with pytest.raises(ToolOutputError, match="adjudicate_action"):
            adj.evaluate("stab", self._sheet(), "", "")


# ---------------------------------------------------------------------------
# BeatRunner — ToolOutputError abort path
# ---------------------------------------------------------------------------

class TestBeatRunnerToolOutputErrorHandling:
    def _build(self):
        log = EventLog()
        world = WorldState()
        world.add_entity(Entity(id="hero", name="Hero", kind="character"))
        pipeline = CommitPipeline(log)
        dice = DiceService(log)
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        sheet = CharacterSheet(entity_id="hero", concept="Blade")
        return log, world, pipeline, rules, assembler, sheet

    def test_tool_output_error_produces_aborted_beat(self):
        log, world, pipeline, rules, assembler, sheet = self._build()
        bad = MagicMock()
        bad.content = []
        client = _raw_client(side_effect=[bad, bad, bad, bad])
        gw = ModelGateway(client, timeout_secs=None)
        adj = AdjudicatorGM(gw)
        narrator = MagicMock()
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=rules, assembler=assembler, adjudicator=adj, narrator=narrator,
            sheets={"hero": sheet},
        )
        result = runner.run("hero", "attack the guard")
        assert result.beat_aborted is True

    def test_aborted_beat_has_no_resolution(self):
        log, world, pipeline, rules, assembler, sheet = self._build()
        bad = MagicMock()
        bad.content = []
        client = _raw_client(side_effect=[bad, bad, bad, bad])
        gw = ModelGateway(client, timeout_secs=None)
        adj = AdjudicatorGM(gw)
        narrator = MagicMock()
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=rules, assembler=assembler, adjudicator=adj, narrator=narrator,
            sheets={"hero": sheet},
        )
        result = runner.run("hero", "attack the guard")
        assert result.resolution is None
        assert result.narration == ""
