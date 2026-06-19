"""Phase 14 tests — Provider gateway and isolated telemetry (D-017, D-022).

What is verified:
  - ModelGateway.call() delegates to client.messages.create.
  - Role tag is recorded in CallRecord.
  - Token and cost fields are populated from response.usage.
  - Telemetry is stored in TelemetrySink.records, never in fictional state.
  - TelemetrySink.summary() returns correct totals and per-role breakdown.
  - Missing usage fields default to zero (mock without usage attribute).
  - Known models produce non-zero cost estimates.
  - Unknown models fall back to sonnet pricing rather than crashing.
  - Latency is recorded as a positive float.
  - Multiple calls accumulate independently in the sink.
  - Shared sink: two gateways writing to the same sink accumulate correctly.
  - Auditor, AdjudicatorGM, NarratorGM, CharacterAgent accept ModelGateway.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fable_table_engine import (
    AdjudicatorGM,
    Auditor,
    CallRecord,
    CharacterAgent,
    CharacterSheet,
    ModelGateway,
    NarratorGM,
    PersonaSpec,
    TelemetrySink,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _mock_client(input_tokens: int = 10, output_tokens: int = 5,
                 cache_read: int = 0, cache_write: int = 0) -> MagicMock:
    """Return a mock anthropic client whose messages.create returns a response with usage."""
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = cache_read
    usage.cache_creation_input_tokens = cache_write

    response = MagicMock()
    response.usage = usage
    response.content = []

    client = MagicMock()
    client.messages.create.return_value = response
    return client


def _make_gateway(input_tokens: int = 10, output_tokens: int = 5) -> tuple[ModelGateway, MagicMock]:
    client = _mock_client(input_tokens, output_tokens)
    return ModelGateway(client), client


# --------------------------------------------------------------------------- #
# ModelGateway delegation                                                       #
# --------------------------------------------------------------------------- #

class TestModelGatewayDelegation:

    def test_delegates_to_client_messages_create(self):
        gw, client = _make_gateway()
        gw.call("adjudicator", model="claude-sonnet-4-6", max_tokens=10,
                messages=[{"role": "user", "content": "hi"}])
        client.messages.create.assert_called_once()
        kw = client.messages.create.call_args[1]
        assert kw["model"] == "claude-sonnet-4-6"
        assert kw["max_tokens"] == 10
        assert kw["messages"] == [{"role": "user", "content": "hi"}]

    def test_returns_response_object(self):
        gw, client = _make_gateway()
        resp = gw.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                       messages=[{"role": "user", "content": "x"}])
        assert resp is client.messages.create.return_value

    def test_role_tag_recorded(self):
        gw, _ = _make_gateway()
        gw.call("auditor", model="claude-haiku-4-5-20251001", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        assert gw.sink.records[0].role == "auditor"

    def test_model_recorded(self):
        gw, _ = _make_gateway()
        gw.call("adjudicator", model="claude-sonnet-4-6", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        assert gw.sink.records[0].model == "claude-sonnet-4-6"


# --------------------------------------------------------------------------- #
# Token recording                                                               #
# --------------------------------------------------------------------------- #

class TestTokenRecording:

    def test_input_output_tokens_recorded(self):
        gw, _ = _make_gateway(input_tokens=100, output_tokens=50)
        gw.call("narrator", model="claude-sonnet-4-6", max_tokens=50,
                messages=[{"role": "user", "content": "x"}])
        r = gw.sink.records[0]
        assert r.input_tokens == 100
        assert r.output_tokens == 50

    def test_cache_tokens_recorded(self):
        client = _mock_client(input_tokens=20, output_tokens=10, cache_read=5, cache_write=3)
        gw = ModelGateway(client)
        gw.call("adjudicator", model="claude-sonnet-4-6", max_tokens=50,
                messages=[{"role": "user", "content": "x"}])
        r = gw.sink.records[0]
        assert r.cache_read_tokens == 5
        assert r.cache_write_tokens == 3

    def test_no_usage_attribute_defaults_to_zero(self):
        """Mocks that don't have a usage attribute should not crash."""
        client = MagicMock()
        response = MagicMock(spec=[])  # no usage attribute
        client.messages.create.return_value = response
        gw = ModelGateway(client)
        gw.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        r = gw.sink.records[0]
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.cost_usd == 0.0

    def test_none_usage_fields_default_to_zero(self):
        """usage attributes that are None should not crash the cost calculation."""
        usage = MagicMock()
        usage.input_tokens = None
        usage.output_tokens = None
        usage.cache_read_input_tokens = None
        usage.cache_creation_input_tokens = None
        response = MagicMock()
        response.usage = usage
        client = MagicMock()
        client.messages.create.return_value = response
        gw = ModelGateway(client)
        gw.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        r = gw.sink.records[0]
        assert r.input_tokens == 0
        assert r.cost_usd == 0.0


# --------------------------------------------------------------------------- #
# Cost calculation                                                              #
# --------------------------------------------------------------------------- #

class TestCostCalculation:

    def test_sonnet_cost_nonzero(self):
        gw, _ = _make_gateway(input_tokens=1000, output_tokens=500)
        gw.call("narrator", model="claude-sonnet-4-6", max_tokens=500,
                messages=[{"role": "user", "content": "x"}])
        assert gw.sink.records[0].cost_usd > 0.0

    def test_haiku_cheaper_than_sonnet_same_tokens(self):
        gw_sonnet, _ = _make_gateway(input_tokens=1000, output_tokens=500)
        gw_haiku, _ = _make_gateway(input_tokens=1000, output_tokens=500)
        gw_sonnet.call("auditor", model="claude-sonnet-4-6", max_tokens=500,
                       messages=[{"role": "user", "content": "x"}])
        gw_haiku.call("auditor", model="claude-haiku-4-5-20251001", max_tokens=500,
                      messages=[{"role": "user", "content": "x"}])
        assert gw_haiku.sink.records[0].cost_usd < gw_sonnet.sink.records[0].cost_usd

    def test_unknown_model_does_not_crash(self):
        gw, _ = _make_gateway(input_tokens=100, output_tokens=50)
        gw.call("narrator", model="claude-future-99", max_tokens=50,
                messages=[{"role": "user", "content": "x"}])
        assert gw.sink.records[0].cost_usd > 0.0  # falls back to sonnet pricing

    def test_cache_read_lowers_cost_vs_full_input(self):
        """Cache read tokens are ~0.1× input price — cheaper than regular input."""
        # 1000 input tokens at sonnet price vs 1000 cache-read tokens
        client_normal = _mock_client(input_tokens=1000, output_tokens=0)
        client_cached = _mock_client(input_tokens=0, output_tokens=0, cache_read=1000)
        gw_normal = ModelGateway(client_normal)
        gw_cached = ModelGateway(client_cached)
        gw_normal.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                       messages=[{"role": "user", "content": "x"}])
        gw_cached.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                       messages=[{"role": "user", "content": "x"}])
        assert gw_cached.sink.records[0].cost_usd < gw_normal.sink.records[0].cost_usd


# --------------------------------------------------------------------------- #
# Latency recording                                                             #
# --------------------------------------------------------------------------- #

class TestLatencyRecording:

    def test_latency_is_positive(self):
        gw, _ = _make_gateway()
        gw.call("adjudicator", model="claude-sonnet-4-6", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        assert gw.sink.records[0].latency_ms >= 0.0

    def test_latency_is_float(self):
        gw, _ = _make_gateway()
        gw.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        assert isinstance(gw.sink.records[0].latency_ms, float)


# --------------------------------------------------------------------------- #
# TelemetrySink accumulation                                                    #
# --------------------------------------------------------------------------- #

class TestTelemetrySink:

    def test_records_accumulate_across_calls(self):
        gw, _ = _make_gateway()
        gw.call("adjudicator", model="claude-sonnet-4-6", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        gw.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                messages=[{"role": "user", "content": "y"}])
        assert len(gw.sink.records) == 2

    def test_summary_empty_sink(self):
        sink = TelemetrySink()
        s = sink.summary()
        assert s["total_calls"] == 0
        assert s["total_cost_usd"] == 0.0
        assert s["by_role"] == {}

    def test_summary_total_calls(self):
        gw, _ = _make_gateway()
        for _ in range(3):
            gw.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                    messages=[{"role": "user", "content": "x"}])
        assert gw.sink.summary()["total_calls"] == 3

    def test_summary_by_role(self):
        gw, _ = _make_gateway(input_tokens=10, output_tokens=5)
        gw.call("adjudicator", model="claude-sonnet-4-6", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        gw.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        s = gw.sink.summary()
        assert "adjudicator" in s["by_role"]
        assert "narrator" in s["by_role"]
        assert s["by_role"]["adjudicator"]["calls"] == 1
        assert s["by_role"]["narrator"]["calls"] == 1

    def test_summary_cost_is_sum(self):
        gw, _ = _make_gateway(input_tokens=1000, output_tokens=500)
        gw.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        gw.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                messages=[{"role": "user", "content": "x"}])
        s = gw.sink.summary()
        assert abs(s["total_cost_usd"] - sum(r.cost_usd for r in gw.sink.records)) < 1e-10

    def test_shared_sink_across_two_gateways(self):
        """Two gateways sharing a sink both write to it."""
        shared_sink = TelemetrySink()
        gw1 = ModelGateway(_mock_client(), sink=shared_sink)
        gw2 = ModelGateway(_mock_client(), sink=shared_sink)
        gw1.call("adjudicator", model="claude-sonnet-4-6", max_tokens=5,
                 messages=[{"role": "user", "content": "x"}])
        gw2.call("narrator", model="claude-sonnet-4-6", max_tokens=5,
                 messages=[{"role": "user", "content": "x"}])
        assert len(shared_sink.records) == 2
        assert shared_sink.summary()["total_calls"] == 2

    def test_sink_not_connected_to_event_log(self):
        """TelemetrySink has no reference to EventLog — enforces D-022."""
        from fable_table_engine import EventLog
        sink = TelemetrySink()
        assert not hasattr(sink, "_log")
        assert not hasattr(sink, "event_log")
        assert not any(
            isinstance(v, EventLog) for v in vars(sink).values()
        )


# --------------------------------------------------------------------------- #
# CallRecord                                                                    #
# --------------------------------------------------------------------------- #

class TestCallRecord:

    def test_call_record_fields(self):
        r = CallRecord(
            role="adjudicator",
            model="claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=10,
            cache_write_tokens=0,
            cost_usd=0.001,
            latency_ms=123.4,
        )
        assert r.role == "adjudicator"
        assert r.model == "claude-sonnet-4-6"
        assert r.input_tokens == 100
        assert r.latency_ms == 123.4


# --------------------------------------------------------------------------- #
# Caller integration — gateway accepted by all four callers                     #
# --------------------------------------------------------------------------- #

class TestCallerIntegration:
    """Smoke tests that each caller accepts a ModelGateway and records telemetry."""

    def _tool_block(self, name: str, data: dict) -> MagicMock:
        block = MagicMock()
        block.type = "tool_use"
        block.name = name
        block.input = data
        return block

    def _text_block(self, text: str) -> MagicMock:
        block = MagicMock()
        block.type = "text"
        block.text = text
        return block

    def test_adjudicator_gm_uses_gateway(self):
        client = _mock_client()
        client.messages.create.return_value.content = [
            self._tool_block("adjudicate_action", {
                "has_stakes": False,
                "reasoning": "trivial",
            })
        ]
        gw = ModelGateway(client)
        adj = AdjudicatorGM(gw)
        from fable_table_engine import CharacterSheet
        sheet = CharacterSheet(entity_id="hero", concept="Fighter")
        adj.evaluate("I look around.", sheet, "...", "...")
        assert len(gw.sink.records) == 1
        assert gw.sink.records[0].role == "adjudicator"

    def test_narrator_gm_uses_gateway(self):
        client = _mock_client()
        client.messages.create.return_value.content = [self._text_block("You step forward.")]
        gw = ModelGateway(client)
        narrator = NarratorGM(gw)
        narrator.narrate("I step.", None, None, "(context)")
        assert len(gw.sink.records) == 1
        assert gw.sink.records[0].role == "narrator"

    def test_auditor_uses_gateway(self):
        client = _mock_client()
        block = self._tool_block("report_consistency", {"contradictions": []})
        client.messages.create.return_value.content = [block]
        gw = ModelGateway(client)
        auditor = Auditor(gateway=gw, semantic=True)
        from fable_table_engine import Fact
        canon = {("gate", "state"): Fact(subject="gate", predicate="state",
                                         value="barred", revealed=True,
                                         event_id="e1", via_override=False)}
        auditor.check_narration("The gate holds.", "hero", "I try the gate.", canon)
        assert len(gw.sink.records) == 1
        assert gw.sink.records[0].role == "auditor"

    def test_character_agent_uses_gateway(self):
        client = _mock_client()
        client.messages.create.return_value.content = [
            self._tool_block("propose_action", {
                "intent": "Watch the door.",
                "channel": "public",
                "reasoning": "tactical",
            })
        ]
        gw = ModelGateway(client)
        persona = PersonaSpec(
            entity_id="vale", name="Vale", concept="Surgeon", voice="Clipped.",
            values=["preserve life"], public_goals=["survive"],
        )
        sheet = CharacterSheet(entity_id="vale", concept="Surgeon")
        agent = CharacterAgent(persona, sheet, gw)
        from fable_table_engine import ContextAssembler, EventLog
        agent.propose(ContextAssembler(EventLog()))
        assert len(gw.sink.records) == 1
        assert gw.sink.records[0].role == "character_agent"
