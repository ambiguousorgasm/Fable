"""Phase 22 tests — D-042 context budget management.

Covers: ContextBudgetPolicy, BudgetCheckResult, TokenEstimator,
ContextBudgeter (defaults, custom policies, trim_events, check_sections,
check_budget, from_settings), CostCeilingStatus / TelemetrySink ceiling,
ContextAssembler budgeter collaborator, BeatRunner event-window wiring,
CharacterAgent propose budgeter pass-through.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fable_table_engine import (
    BudgetCheckResult,
    CharacterSheet,
    CommitPipeline,
    ContextAssembler,
    ContextBudgetPolicy,
    ContextBudgeter,
    CostCeilingStatus,
    EventLog,
    ModelGateway,
    SettingsManager,
    TelemetrySink,
    TokenEstimator,
)
from fable_table_engine.budgeter import _DEFAULT_POLICIES


# ---------------------------------------------------------------------------
# ContextBudgetPolicy
# ---------------------------------------------------------------------------

class TestContextBudgetPolicy:
    def test_required_fields(self):
        pol = ContextBudgetPolicy(max_tokens=10_000, event_window=5)
        assert pol.max_tokens == 10_000
        assert pol.event_window == 5

    def test_defaults(self):
        pol = ContextBudgetPolicy(max_tokens=1, event_window=1)
        assert pol.required_sections == ()
        assert pol.summarize_older is False

    def test_custom_required_sections(self):
        pol = ContextBudgetPolicy(max_tokens=1, event_window=1, required_sections=("world", "canon"))
        assert "world" in pol.required_sections
        assert "canon" in pol.required_sections

    def test_frozen(self):
        pol = ContextBudgetPolicy(max_tokens=1, event_window=1)
        with pytest.raises((AttributeError, TypeError)):
            pol.max_tokens = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BudgetCheckResult
# ---------------------------------------------------------------------------

class TestBudgetCheckResult:
    def test_fits_true(self):
        r = BudgetCheckResult(role="narrator", token_estimate=100, cap=1000, fits=True)
        assert r.fits is True
        assert r.over_by == 0

    def test_fits_false_over_by(self):
        r = BudgetCheckResult(role="adjudicator", token_estimate=1200, cap=1000, fits=False)
        assert r.fits is False
        assert r.over_by == 200

    def test_over_by_zero_when_fits(self):
        r = BudgetCheckResult(role="x", token_estimate=999, cap=1000, fits=True)
        assert r.over_by == 0

    def test_frozen(self):
        r = BudgetCheckResult(role="x", token_estimate=1, cap=10, fits=True)
        with pytest.raises((AttributeError, TypeError)):
            r.fits = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TokenEstimator
# ---------------------------------------------------------------------------

class TestTokenEstimator:
    def test_estimate_proxy(self):
        est = TokenEstimator()
        # 400 chars / 4 = 100 tokens
        assert est.estimate("x" * 400) == 100

    def test_estimate_minimum_one(self):
        est = TokenEstimator()
        assert est.estimate("") == 1
        assert est.estimate("ab") == 1  # 2 // 4 = 0 → min 1

    def test_count_no_client_returns_proxy(self):
        est = TokenEstimator(client=None)
        result = est.count("x" * 400, "claude-opus-4-8", cap=40_000)
        assert result == 100  # proxy path

    def test_count_far_from_cap_no_api_call(self):
        client = MagicMock()
        est = TokenEstimator(client=client)
        # 100 tokens proxy, cap=10_000 → 100 < 8000 (80%) → no API call
        est.count("x" * 400, "claude-opus-4-8", cap=10_000)
        client.messages.count_tokens.assert_not_called()

    def test_count_near_cap_calls_api(self):
        client = MagicMock()
        mock_result = MagicMock()
        mock_result.input_tokens = 9_500
        client.messages.count_tokens.return_value = mock_result
        est = TokenEstimator(client=client)
        # proxy=9000 (36000 chars / 4), cap=10000 → 9000 >= 8000 → API call
        result = est.count("x" * 36_000, "claude-opus-4-8", cap=10_000)
        assert result == 9_500
        client.messages.count_tokens.assert_called_once()

    def test_count_api_exception_falls_back_to_proxy(self):
        client = MagicMock()
        client.messages.count_tokens.side_effect = RuntimeError("API down")
        est = TokenEstimator(client=client)
        result = est.count("x" * 36_000, "claude-opus-4-8", cap=10_000)
        assert result == 9_000  # proxy fallback

    def test_preflight_threshold_constant(self):
        assert TokenEstimator.PREFLIGHT_THRESHOLD == 0.80


# ---------------------------------------------------------------------------
# ContextBudgeter — defaults
# ---------------------------------------------------------------------------

class TestContextBudgeterDefaults:
    def test_default_policies_present(self):
        budgeter = ContextBudgeter()
        for role in ("gm_adjudicator", "gm_narrator", "character_agent",
                     "social_interpreter", "auditor", "plot_manager"):
            pol = budgeter.policy(role)
            assert pol.max_tokens > 0
            assert pol.event_window > 0

    def test_adjudicator_defaults(self):
        budgeter = ContextBudgeter()
        pol = budgeter.policy("gm_adjudicator")
        assert pol.max_tokens == 40_000
        assert pol.event_window == 20

    def test_narrator_defaults(self):
        budgeter = ContextBudgeter()
        pol = budgeter.policy("gm_narrator")
        assert pol.max_tokens == 20_000
        assert pol.event_window == 8

    def test_character_agent_defaults(self):
        budgeter = ContextBudgeter()
        assert budgeter.event_window("character_agent") == 12

    def test_social_interpreter_defaults(self):
        budgeter = ContextBudgeter()
        assert budgeter.event_window("social_interpreter") == 6

    def test_auditor_defaults(self):
        budgeter = ContextBudgeter()
        assert budgeter.event_window("auditor") == 10

    def test_plot_manager_defaults(self):
        budgeter = ContextBudgeter()
        assert budgeter.event_window("plot_manager") == 15

    def test_unknown_role_falls_back_to_adjudicator_policy(self):
        budgeter = ContextBudgeter()
        pol = budgeter.policy("some_unknown_role")
        assert pol == _DEFAULT_POLICIES["gm_adjudicator"]


# ---------------------------------------------------------------------------
# ContextBudgeter — custom policies
# ---------------------------------------------------------------------------

class TestContextBudgeterCustomPolicies:
    def test_custom_policy_overrides_default(self):
        custom = {"gm_adjudicator": ContextBudgetPolicy(max_tokens=5_000, event_window=3)}
        budgeter = ContextBudgeter(policies=custom)
        assert budgeter.event_window("gm_adjudicator") == 3
        assert budgeter.policy("gm_adjudicator").max_tokens == 5_000

    def test_other_roles_keep_defaults_when_only_one_overridden(self):
        custom = {"gm_adjudicator": ContextBudgetPolicy(max_tokens=5_000, event_window=3)}
        budgeter = ContextBudgeter(policies=custom)
        assert budgeter.event_window("gm_narrator") == 8  # still default

    def test_partial_policy_dict_merges_with_defaults(self):
        custom = {
            "gm_narrator": ContextBudgetPolicy(max_tokens=9_999, event_window=4),
        }
        budgeter = ContextBudgeter(policies=custom)
        assert budgeter.policy("gm_narrator").max_tokens == 9_999
        assert budgeter.policy("gm_adjudicator").max_tokens == 40_000


# ---------------------------------------------------------------------------
# ContextBudgeter — trim_events
# ---------------------------------------------------------------------------

class TestContextBudgeterTrimEvents:
    def test_trim_within_window_unchanged(self):
        budgeter = ContextBudgeter()
        events = list(range(5))
        result = budgeter.trim_events(events, "gm_narrator")  # window=8
        assert result == events

    def test_trim_over_window_keeps_most_recent(self):
        budgeter = ContextBudgeter()
        events = list(range(20))  # 0..19
        result = budgeter.trim_events(events, "gm_narrator")  # window=8
        assert result == list(range(12, 20))

    def test_trim_exact_window_unchanged(self):
        budgeter = ContextBudgeter()
        events = list(range(8))
        result = budgeter.trim_events(events, "gm_narrator")
        assert result == events

    def test_trim_empty_list(self):
        budgeter = ContextBudgeter()
        assert budgeter.trim_events([], "gm_adjudicator") == []

    def test_trim_returns_copy_not_same_object(self):
        budgeter = ContextBudgeter()
        events = [1, 2, 3]
        result = budgeter.trim_events(events, "auditor")
        result.append(99)
        assert events == [1, 2, 3]


# ---------------------------------------------------------------------------
# ContextBudgeter — check_sections
# ---------------------------------------------------------------------------

class TestContextBudgeterCheckSections:
    def test_no_required_sections_always_passes(self):
        budgeter = ContextBudgeter()
        # default policies have empty required_sections
        missing = budgeter.check_sections({}, "gm_adjudicator")
        assert missing == []

    def test_required_section_present(self):
        custom = {
            "gm_adjudicator": ContextBudgetPolicy(
                max_tokens=40_000, event_window=20,
                required_sections=("world", "canon"),
            )
        }
        budgeter = ContextBudgeter(policies=custom)
        missing = budgeter.check_sections({"world": "text", "canon": "text"}, "gm_adjudicator")
        assert missing == []

    def test_required_section_empty_reported(self):
        custom = {
            "gm_adjudicator": ContextBudgetPolicy(
                max_tokens=40_000, event_window=20,
                required_sections=("world", "canon"),
            )
        }
        budgeter = ContextBudgeter(policies=custom)
        missing = budgeter.check_sections({"world": "text", "canon": ""}, "gm_adjudicator")
        assert "canon" in missing
        assert "world" not in missing

    def test_required_section_missing_entirely_reported(self):
        custom = {
            "gm_adjudicator": ContextBudgetPolicy(
                max_tokens=40_000, event_window=20,
                required_sections=("world",),
            )
        }
        budgeter = ContextBudgeter(policies=custom)
        missing = budgeter.check_sections({}, "gm_adjudicator")
        assert "world" in missing


# ---------------------------------------------------------------------------
# ContextBudgeter — check_budget
# ---------------------------------------------------------------------------

class TestContextBudgeterCheckBudget:
    def test_small_text_fits(self):
        budgeter = ContextBudgeter()
        result = budgeter.check_budget("hello", "gm_narrator")  # cap=20000
        assert result.fits is True
        assert result.cap == 20_000
        assert result.role == "gm_narrator"

    def test_large_text_does_not_fit(self):
        budgeter = ContextBudgeter(
            policies={"gm_adjudicator": ContextBudgetPolicy(max_tokens=10, event_window=5)}
        )
        result = budgeter.check_budget("x" * 200, "gm_adjudicator")  # 200//4=50 > 10
        assert result.fits is False
        assert result.over_by > 0

    def test_uses_custom_estimator(self):
        est = MagicMock()
        est.count.return_value = 999
        budgeter = ContextBudgeter(estimator=est)
        result = budgeter.check_budget("text", "gm_narrator", model="claude-opus-4-8")
        assert result.token_estimate == 999
        est.count.assert_called_once_with("text", "claude-opus-4-8", 20_000)


# ---------------------------------------------------------------------------
# ContextBudgeter — from_settings
# ---------------------------------------------------------------------------

class TestContextBudgeterFromSettings:
    def _settings_dir_with(self, data: dict) -> str:
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "models.json").write_text(json.dumps(data))
        return tmp

    def test_default_settings_produce_default_policies(self):
        sm = SettingsManager(tempfile.mkdtemp())
        budgeter = ContextBudgeter.from_settings(sm)
        # SettingsRegistry defaults match ContextBudgeter defaults
        assert budgeter.event_window("gm_adjudicator") == 20
        assert budgeter.event_window("gm_narrator") == 8

    def test_user_override_applied(self):
        settings_dir = self._settings_dir_with({
            "gm_narrator_event_window": "3",
            "gm_narrator_max_tokens": "5000",
        })
        sm = SettingsManager(settings_dir)
        budgeter = ContextBudgeter.from_settings(sm)
        assert budgeter.event_window("gm_narrator") == 3
        assert budgeter.policy("gm_narrator").max_tokens == 5_000

    def test_partial_override_keeps_other_role_defaults(self):
        settings_dir = self._settings_dir_with({"gm_narrator_event_window": "3"})
        sm = SettingsManager(settings_dir)
        budgeter = ContextBudgeter.from_settings(sm)
        # adjudicator not overridden → default
        assert budgeter.event_window("gm_adjudicator") == 20

    def test_invalid_value_falls_back_to_default(self):
        settings_dir = self._settings_dir_with({"gm_narrator_event_window": "not_a_number"})
        sm = SettingsManager(settings_dir)
        budgeter = ContextBudgeter.from_settings(sm)
        assert budgeter.event_window("gm_narrator") == 8  # default

    def test_custom_estimator_passed_through(self):
        sm = SettingsManager(tempfile.mkdtemp())
        est = TokenEstimator()
        budgeter = ContextBudgeter.from_settings(sm, estimator=est)
        assert budgeter._estimator is est


# ---------------------------------------------------------------------------
# CostCeilingStatus / TelemetrySink
# ---------------------------------------------------------------------------

class TestCostCeilingStatus:
    def _sink_with_cost(self, cost: float, ceiling: float | None) -> TelemetrySink:
        from fable_table_engine import CallRecord
        sink = TelemetrySink(cost_ceiling_usd=ceiling)
        if cost > 0:
            sink.record(CallRecord(
                role="test", model="m", input_tokens=0, output_tokens=0,
                cache_read_tokens=0, cache_write_tokens=0,
                cost_usd=cost, latency_ms=10.0,
            ))
        return sink

    def test_no_ceiling_always_ok(self):
        sink = self._sink_with_cost(999.0, ceiling=None)
        assert sink.ceiling_status() == CostCeilingStatus.OK

    def test_below_warning_threshold(self):
        sink = self._sink_with_cost(0.05, ceiling=1.00)  # 5%
        assert sink.ceiling_status() == CostCeilingStatus.OK

    def test_at_warning_threshold(self):
        sink = self._sink_with_cost(0.80, ceiling=1.00)  # 80%
        assert sink.ceiling_status() == CostCeilingStatus.WARNING

    def test_above_warning_below_ceiling(self):
        sink = self._sink_with_cost(0.90, ceiling=1.00)  # 90%
        assert sink.ceiling_status() == CostCeilingStatus.WARNING

    def test_at_ceiling_exceeded(self):
        sink = self._sink_with_cost(1.00, ceiling=1.00)  # 100%
        assert sink.ceiling_status() == CostCeilingStatus.EXCEEDED

    def test_over_ceiling_exceeded(self):
        sink = self._sink_with_cost(1.50, ceiling=1.00)
        assert sink.ceiling_status() == CostCeilingStatus.EXCEEDED

    def test_zero_cost_no_ceiling(self):
        sink = TelemetrySink()
        assert sink.ceiling_status() == CostCeilingStatus.OK

    def test_total_cost_usd(self):
        from fable_table_engine import CallRecord
        sink = TelemetrySink()
        sink.record(CallRecord(role="a", model="m", input_tokens=0, output_tokens=0,
                               cache_read_tokens=0, cache_write_tokens=0,
                               cost_usd=0.30, latency_ms=10.0))
        sink.record(CallRecord(role="b", model="m", input_tokens=0, output_tokens=0,
                               cache_read_tokens=0, cache_write_tokens=0,
                               cost_usd=0.20, latency_ms=10.0))
        assert abs(sink.total_cost_usd() - 0.50) < 1e-9

    def test_ceiling_status_is_string_enum(self):
        assert CostCeilingStatus.OK == "ok"
        assert CostCeilingStatus.WARNING == "warning"
        assert CostCeilingStatus.EXCEEDED == "exceeded"


# ---------------------------------------------------------------------------
# ContextAssembler — budgeter collaborator
# ---------------------------------------------------------------------------

class TestContextAssemblerBudgeter:
    def test_default_no_budgeter(self):
        log = EventLog()
        assembler = ContextAssembler(log)
        assert assembler.budgeter is None

    def test_budgeter_stored_and_accessible(self):
        log = EventLog()
        budgeter = ContextBudgeter()
        assembler = ContextAssembler(log, budgeter=budgeter)
        assert assembler.budgeter is budgeter

    def test_belief_store_unaffected_by_budgeter(self):
        log = EventLog()
        for i in range(30):
            log.append(author="gm", channel="public", type="narration",
                       content=f"event {i}", audience=("gm", "player"))
        budgeter = ContextBudgeter(
            policies={"gm_adjudicator": ContextBudgetPolicy(max_tokens=40_000, event_window=3)}
        )
        assembler = ContextAssembler(log, budgeter=budgeter)
        store = assembler.belief_store("gm")
        # Belief store must contain all events — budgeter does not filter canon
        assert len(store.events) == 30


# ---------------------------------------------------------------------------
# BeatRunner — event-window wiring
# ---------------------------------------------------------------------------

class TestBeatRunnerBudgeterWiring:
    def _raw_client(self, response=None):
        client = MagicMock()
        client.messages.create = MagicMock(return_value=response or MagicMock(content=[]))
        return client

    def test_budgeter_accepted_in_init(self):
        from fable_table_engine import BeatRunner, DiceService, RulesEngine, Entity, WorldState
        log = EventLog()
        world = WorldState()
        world.add_entity(Entity(id="hero", name="Hero", kind="character"))
        pipeline = CommitPipeline(log)
        dice = DiceService(log)
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        budgeter = ContextBudgeter()
        client = self._raw_client()
        gw = ModelGateway(client, timeout_secs=None)
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline, rules=rules,
            assembler=assembler, adjudicator=MagicMock(), narrator=MagicMock(),
            sheets={"hero": CharacterSheet(entity_id="hero", concept="x")},
            budgeter=budgeter,
        )
        assert runner._budgeter is budgeter

    def test_no_budgeter_uses_legacy_window(self):
        from fable_table_engine import BeatRunner, DiceService, RulesEngine, Entity, WorldState
        from fable_table_engine.beat import CONTEXT_EVENT_WINDOW
        log = EventLog()
        world = WorldState()
        world.add_entity(Entity(id="hero", name="Hero", kind="character"))
        pipeline = CommitPipeline(log)
        dice = DiceService(log)
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline, rules=rules,
            assembler=assembler, adjudicator=MagicMock(), narrator=MagicMock(),
            sheets={"hero": CharacterSheet(entity_id="hero", concept="x")},
        )
        assert runner._budgeter is None
        assert CONTEXT_EVENT_WINDOW == 12  # legacy fallback unchanged
