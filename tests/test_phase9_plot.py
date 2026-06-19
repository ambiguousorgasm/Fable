"""Phase 9 acceptance tests — plot graph, plot manager, D-023/D-026 integration.

Acceptance contracts:
  1.  PlotGraph loads with function nodes, hooks, fronts, and factions.
  2.  PlotManager detects a fixture entity marked destroyed in the canon ledger.
  3.  PlotManager proposes a re-binding to an unblocked alternative fixture.
  4.  propose_rebinding emits a plot_revision event with the correct audience.
  5.  plot_revision events never appear in a player's belief store.
  6.  accept_rebinding updates the hook's binding (D-016 two-step write).
  7.  When no alternative is available, a plot_advisory event is emitted instead.
  8.  handle_clock_fired logs a front_consequence event for the owning front.
  9.  Interest signals accumulate from beat events.
  10. top_subjects ranks by total weight.
  11. promotion_candidates returns subjects above the threshold.
  12. gm_context_summary includes active hooks and fronts (never empty-world).
  13. WorldSimulator.advance respects trigger_types (D-026).
  14. WorldSimulator.advance skips inactive clocks (D-026).
  15. Clocks without trigger_types default to {"beat"} (D-026 backward compat).
  16. SQLiteEventLog.transaction commits atomically on success (D-023).
  17. SQLiteEventLog.transaction rolls back in-memory + DB on exception (D-023).
  18. Nested transaction calls are no-ops (outer manages the commit).
  19. BeatRunner wires interest_accumulator: signal emitted for actor each beat.
  20. BeatRunner wires plot_manager: gm_context_summary included in world summary.
  21. post_beat calls handle_clock_fired for each fired clock.
  22. post_beat auto-accepts re-bindings and updates the graph.
  23. Fixture check uses both "condition" and "available" canon predicates.
  24. PlotGraph.front_for_clock returns None for unknown clock names.
  25. InterestSignalAccumulator.signals_for returns only the target subject.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fable_table_engine import (
    CommitPipeline,
    Commitment,
    EventLog,
    Faction,
    FixtureBinding,
    FixtureIssue,
    Front,
    FunctionNode,
    Hook,
    InterestSignal,
    InterestSignalAccumulator,
    PlotGraph,
    PlotManager,
    SQLiteEventLog,
    SQLiteWorldState,
    WorldState,
    open_session,
)
from fable_table_engine.gm import WorldSimulator
from fable_table_engine.access import Fact


# --------------------------------------------------------------------------- #
# Fixtures / helpers                                                            #
# --------------------------------------------------------------------------- #

def _make_graph() -> PlotGraph:
    graph = PlotGraph()
    fn = FunctionNode(id="fn_contact", description="Party learns of the conspiracy")
    graph.add_function(fn)

    binding = FixtureBinding(
        function_id="fn_contact",
        fixture_entity_id="informant_marco",
        description="Marco delivers the tip in the tavern",
    )
    hook = Hook(function_id="fn_contact", binding=binding)
    graph.add_hook(hook)

    alt = FixtureBinding(
        function_id="fn_contact",
        fixture_entity_id="informant_yara",
        description="Yara delivers the tip via letter",
    )
    graph.set_alternatives("fn_contact", [alt])

    front = Front(
        id="f_cult",
        name="Cult advance",
        threat="The cult completes its ritual",
        clock_name="ritual_clock",
        consequence_truth="cult_ritual_complete",
    )
    graph.add_front(front)

    faction = Faction(id="cult", name="The Crimson Pact", goals=["complete ritual"])
    graph.add_faction(faction)

    return graph


def _make_log_and_pipeline():
    log = EventLog()
    pipeline = CommitPipeline(log)
    return log, pipeline


def _commit_condition(pipeline, entity_id: str, condition: str) -> None:
    pipeline.commit(
        author="gm",
        channel="system",
        content=f"[test] {entity_id} condition = {condition}",
        audience=("gm",),
        visibility="content",
        commitments=[
            Commitment(
                subject=entity_id,
                predicate="condition",
                value=condition,
                revealed=True,
            )
        ],
    )


def _commit_available(pipeline, entity_id: str, available: bool) -> None:
    pipeline.commit(
        author="gm",
        channel="system",
        content=f"[test] {entity_id} available = {available}",
        audience=("gm",),
        visibility="content",
        commitments=[
            Commitment(
                subject=entity_id,
                predicate="available",
                value=available,
                revealed=True,
            )
        ],
    )


# --------------------------------------------------------------------------- #
# 1: PlotGraph structure                                                        #
# --------------------------------------------------------------------------- #

class TestPlotGraph:
    def test_loads_with_all_node_types(self):
        graph = _make_graph()
        assert "fn_contact" in graph.function_nodes
        assert len(graph.hooks) == 1
        assert len(graph.fronts) == 1
        assert len(graph.factions) == 1

    def test_function_node_fields(self):
        graph = _make_graph()
        fn = graph.function_nodes["fn_contact"]
        assert fn.id == "fn_contact"
        assert fn.required is True

    def test_hook_binding_fields(self):
        graph = _make_graph()
        hook = graph.hooks[0]
        assert hook.function_id == "fn_contact"
        assert hook.binding.fixture_entity_id == "informant_marco"
        assert hook.active is True

    def test_alternatives_stored(self):
        graph = _make_graph()
        alts = graph.alternative_fixtures.get("fn_contact", [])
        assert len(alts) == 1
        assert alts[0].fixture_entity_id == "informant_yara"

    def test_front_fields(self):
        graph = _make_graph()
        front = graph.fronts[0]
        assert front.clock_name == "ritual_clock"
        assert front.consequence_truth == "cult_ritual_complete"

    def test_front_for_clock_found(self):
        graph = _make_graph()
        front = graph.front_for_clock("ritual_clock")
        assert front is not None
        assert front.id == "f_cult"

    def test_front_for_clock_not_found(self, ):  # acceptance 24
        graph = _make_graph()
        assert graph.front_for_clock("nonexistent") is None

    def test_faction_fields(self):
        graph = _make_graph()
        faction = graph.factions[0]
        assert faction.id == "cult"
        assert "complete ritual" in faction.goals

    def test_hidden_nodes_empty_by_default(self):
        graph = PlotGraph()
        assert graph.hidden_nodes == []

    def test_add_function_overwrites_same_id(self):
        graph = PlotGraph()
        graph.add_function(FunctionNode(id="f1", description="first"))
        graph.add_function(FunctionNode(id="f1", description="second"))
        assert graph.function_nodes["f1"].description == "second"


# --------------------------------------------------------------------------- #
# 2–3: Fixture health detection                                                 #
# --------------------------------------------------------------------------- #

class TestFixtureHealth:
    def test_healthy_fixture_no_issues(self):  # acceptance 2
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        pm = PlotManager(graph, pipeline, log)
        assert pm.check_fixture_health() == []

    def test_detects_destroyed_fixture(self):  # acceptance 2
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        _commit_condition(pipeline, "informant_marco", "destroyed")
        pm = PlotManager(graph, pipeline, log)
        issues = pm.check_fixture_health()
        assert len(issues) == 1
        assert issues[0].hook.binding.fixture_entity_id == "informant_marco"
        assert issues[0].reason == "fixture_blocked"

    def test_detects_other_blocking_conditions(self):  # acceptance 23
        for cond in ("dead", "captured", "unavailable", "eliminated"):
            graph = _make_graph()
            log, pipeline = _make_log_and_pipeline()
            _commit_condition(pipeline, "informant_marco", cond)
            pm = PlotManager(graph, pipeline, log)
            issues = pm.check_fixture_health()
            assert len(issues) == 1, f"expected issue for condition={cond!r}"

    def test_detects_unavailable_false_predicate(self):  # acceptance 23
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        _commit_available(pipeline, "informant_marco", False)
        pm = PlotManager(graph, pipeline, log)
        issues = pm.check_fixture_health()
        assert len(issues) == 1

    def test_available_true_not_blocking(self):
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        _commit_available(pipeline, "informant_marco", True)
        pm = PlotManager(graph, pipeline, log)
        assert pm.check_fixture_health() == []

    def test_non_blocking_condition_ignored(self):
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        _commit_condition(pipeline, "informant_marco", "injured")
        pm = PlotManager(graph, pipeline, log)
        assert pm.check_fixture_health() == []

    def test_inactive_hook_not_checked(self):
        graph = _make_graph()
        graph.hooks[0].active = False
        log, pipeline = _make_log_and_pipeline()
        _commit_condition(pipeline, "informant_marco", "destroyed")
        pm = PlotManager(graph, pipeline, log)
        assert pm.check_fixture_health() == []


# --------------------------------------------------------------------------- #
# 3–6: Re-binding proposals                                                    #
# --------------------------------------------------------------------------- #

class TestRebinding:
    def test_propose_rebinding_returns_binding(self):  # acceptance 3
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        _commit_condition(pipeline, "informant_marco", "destroyed")
        pm = PlotManager(graph, pipeline, log)
        issues = pm.check_fixture_health()
        proposed = pm.propose_rebinding(issues[0])
        assert proposed is not None
        assert proposed.fixture_entity_id == "informant_yara"

    def test_propose_rebinding_emits_plot_revision_event(self):  # acceptance 4
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        _commit_condition(pipeline, "informant_marco", "destroyed")
        pm = PlotManager(graph, pipeline, log)
        issues = pm.check_fixture_health()
        pm.propose_rebinding(issues[0])

        revision_events = [e for e in log.all() if e.type == "plot_revision"]
        assert len(revision_events) == 1
        ev = revision_events[0]
        assert "fn_contact" in ev.content
        assert "informant_marco" in ev.content
        assert "informant_yara" in ev.content

    def test_plot_revision_audience_is_gm_and_pm_only(self):  # acceptance 4
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        _commit_condition(pipeline, "informant_marco", "destroyed")
        pm = PlotManager(graph, pipeline, log)
        issues = pm.check_fixture_health()
        pm.propose_rebinding(issues[0])

        ev = next(e for e in log.all() if e.type == "plot_revision")
        assert set(ev.audience) == {"gm", "plot_manager"}

    def test_plot_revision_not_in_player_belief_store(self):  # acceptance 5
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        from fable_table_engine import ContextAssembler
        _commit_condition(pipeline, "informant_marco", "destroyed")
        pm = PlotManager(graph, pipeline, log)
        issues = pm.check_fixture_health()
        pm.propose_rebinding(issues[0])

        assembler = ContextAssembler(log)
        player_store = assembler.belief_store("player_kai")
        revision_events = [e for e in player_store.events if e.type == "plot_revision"]
        assert revision_events == []

    def test_accept_rebinding_updates_hook(self):  # acceptance 6
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        _commit_condition(pipeline, "informant_marco", "destroyed")
        pm = PlotManager(graph, pipeline, log)
        issues = pm.check_fixture_health()
        proposed = pm.propose_rebinding(issues[0])
        assert proposed is not None
        pm.accept_rebinding(issues[0].hook, proposed)

        assert graph.hooks[0].binding.fixture_entity_id == "informant_yara"

    def test_no_alternative_emits_advisory(self):  # acceptance 7
        graph = PlotGraph()
        fn = FunctionNode(id="fn_x", description="something")
        graph.add_function(fn)
        binding = FixtureBinding("fn_x", "entity_a", "via A")
        graph.add_hook(Hook(function_id="fn_x", binding=binding))
        # no alternatives registered

        log, pipeline = _make_log_and_pipeline()
        _commit_condition(pipeline, "entity_a", "destroyed")
        pm = PlotManager(graph, pipeline, log)
        issues = pm.check_fixture_health()
        result = pm.propose_rebinding(issues[0])

        assert result is None
        advisory_events = [e for e in log.all() if e.type == "plot_advisory"]
        assert len(advisory_events) == 1
        assert "fn_x" in advisory_events[0].content

    def test_alternative_also_blocked_skipped(self):
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        _commit_condition(pipeline, "informant_marco", "destroyed")
        _commit_condition(pipeline, "informant_yara", "captured")
        pm = PlotManager(graph, pipeline, log)
        issues = pm.check_fixture_health()
        result = pm.propose_rebinding(issues[0])
        assert result is None

    def test_alternative_skips_current_fixture_even_if_same(self):
        graph = PlotGraph()
        fn = FunctionNode(id="fn_x", description="x")
        graph.add_function(fn)
        binding = FixtureBinding("fn_x", "entity_a", "via A")
        graph.add_hook(Hook(function_id="fn_x", binding=binding))
        # Alternative list accidentally includes the current fixture first
        graph.set_alternatives("fn_x", [
            FixtureBinding("fn_x", "entity_a", "still entity_a"),
            FixtureBinding("fn_x", "entity_b", "via B"),
        ])
        log, pipeline = _make_log_and_pipeline()
        _commit_condition(pipeline, "entity_a", "destroyed")
        pm = PlotManager(graph, pipeline, log)
        issues = pm.check_fixture_health()
        result = pm.propose_rebinding(issues[0])
        assert result is not None
        assert result.fixture_entity_id == "entity_b"


# --------------------------------------------------------------------------- #
# 8: Front / clock handling                                                     #
# --------------------------------------------------------------------------- #

class TestFrontHandling:
    def test_handle_clock_fired_emits_consequence_event(self):  # acceptance 8
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        pm = PlotManager(graph, pipeline, log)
        front = pm.handle_clock_fired("ritual_clock")
        assert front is not None
        assert front.id == "f_cult"
        consequence_events = [e for e in log.all() if e.type == "front_consequence"]
        assert len(consequence_events) == 1
        ev = consequence_events[0]
        assert "cult_ritual_complete" in ev.content
        assert set(ev.audience) == {"gm", "plot_manager"}

    def test_handle_clock_fired_unknown_clock_returns_none(self):
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        pm = PlotManager(graph, pipeline, log)
        result = pm.handle_clock_fired("nonexistent_clock")
        assert result is None

    def test_handle_clock_fired_no_front_no_event(self):
        graph = PlotGraph()  # no fronts
        log, pipeline = _make_log_and_pipeline()
        pm = PlotManager(graph, pipeline, log)
        pm.handle_clock_fired("any_clock")
        assert not any(e.type == "front_consequence" for e in log.all())


# --------------------------------------------------------------------------- #
# 9–11: InterestSignalAccumulator                                               #
# --------------------------------------------------------------------------- #

class TestInterestSignalAccumulator:
    def test_emit_and_total_weight(self):  # acceptance 9
        acc = InterestSignalAccumulator()
        acc.emit("npc_marco", "query", 1.0)
        acc.emit("npc_marco", "attention", 0.5)
        assert acc.total_weight("npc_marco") == pytest.approx(1.5)

    def test_total_weight_zero_for_unknown(self):
        acc = InterestSignalAccumulator()
        assert acc.total_weight("nobody") == 0.0

    def test_top_subjects_ordered(self):  # acceptance 10
        acc = InterestSignalAccumulator()
        acc.emit("a", "q", 3.0)
        acc.emit("b", "q", 5.0)
        acc.emit("a", "q", 1.0)
        top = acc.top_subjects(n=2)
        assert top[0] == ("b", 5.0)
        assert top[1] == ("a", 4.0)

    def test_top_subjects_n_limits(self):
        acc = InterestSignalAccumulator()
        for i in range(10):
            acc.emit(f"sub{i}", "q", float(i))
        top = acc.top_subjects(n=3)
        assert len(top) == 3

    def test_promotion_candidates_above_threshold(self):  # acceptance 11
        acc = InterestSignalAccumulator()
        acc.PROMOTION_THRESHOLD  # confirm attribute exists
        for _ in range(12):
            acc.emit("hot_topic", "query", 0.5)  # total = 6.0 > 5.0 threshold
        acc.emit("cool_topic", "query", 0.5)     # total = 0.5
        candidates = acc.promotion_candidates()
        assert "hot_topic" in candidates
        assert "cool_topic" not in candidates

    def test_signals_for_returns_only_target(self):  # acceptance 25
        acc = InterestSignalAccumulator()
        acc.emit("a", "q", 1.0, "evt1")
        acc.emit("b", "q", 2.0, "evt2")
        acc.emit("a", "q", 0.5, "evt3")
        sigs = acc.signals_for("a")
        assert len(sigs) == 2
        assert all(s.subject == "a" for s in sigs)

    def test_all_signals_property(self):
        acc = InterestSignalAccumulator()
        acc.emit("x", "action", 1.0)
        acc.emit("y", "beat", 0.5)
        assert len(acc.all_signals) == 2

    def test_causal_event_id_stored(self):
        acc = InterestSignalAccumulator()
        acc.emit("x", "action", 1.0, causal_event_id="evt-abc")
        assert acc.all_signals[0].causal_event_id == "evt-abc"


# --------------------------------------------------------------------------- #
# 12: GM context summary                                                        #
# --------------------------------------------------------------------------- #

class TestGmContextSummary:
    def test_includes_active_hooks(self):  # acceptance 12
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        pm = PlotManager(graph, pipeline, log)
        summary = pm.gm_context_summary()
        assert "fn_contact" in summary
        assert "informant_marco" in summary

    def test_includes_fronts(self):
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        pm = PlotManager(graph, pipeline, log)
        summary = pm.gm_context_summary()
        assert "Cult advance" in summary
        assert "ritual_clock" in summary

    def test_empty_graph_returns_placeholder(self):
        graph = PlotGraph()
        log, pipeline = _make_log_and_pipeline()
        pm = PlotManager(graph, pipeline, log)
        assert pm.gm_context_summary() == "(no active hooks or fronts)"

    def test_inactive_hooks_excluded(self):
        graph = _make_graph()
        graph.hooks[0].active = False
        log, pipeline = _make_log_and_pipeline()
        pm = PlotManager(graph, pipeline, log, gm_entity="gm")
        summary = pm.gm_context_summary()
        # fronts still appear; only hooks are excluded
        assert "Cult advance" in summary
        assert "informant_marco" not in summary


# --------------------------------------------------------------------------- #
# 13–15: WorldSimulator D-026 trigger_types and active                         #
# --------------------------------------------------------------------------- #

class TestWorldSimulatorD026:
    def _make_sim(self, clock_data: dict):
        log = EventLog()
        world = WorldState()
        world.set_clock("test_clock", clock_data)
        sim = WorldSimulator(log, world)
        return sim, world, log

    def test_advance_beat_trigger_advances_default_clock(self):  # acceptance 15
        sim, world, log = self._make_sim({"current": 0, "max": 3, "step": 1})
        sim.advance("beat")
        assert world.clocks["test_clock"]["current"] == 1

    def test_advance_scene_trigger_skips_beat_clock(self):  # acceptance 13
        sim, world, log = self._make_sim({
            "current": 0, "max": 3, "step": 1,
            "trigger_types": ["scene"],
        })
        sim.advance("beat")
        assert world.clocks["test_clock"]["current"] == 0

    def test_advance_scene_trigger_advances_scene_clock(self):
        sim, world, log = self._make_sim({
            "current": 0, "max": 3, "step": 1,
            "trigger_types": ["scene"],
        })
        sim.advance("scene")
        assert world.clocks["test_clock"]["current"] == 1

    def test_clock_with_multiple_trigger_types(self):
        sim, world, log = self._make_sim({
            "current": 0, "max": 6, "step": 1,
            "trigger_types": ["beat", "scene"],
        })
        sim.advance("scene")
        sim.advance("beat")
        assert world.clocks["test_clock"]["current"] == 2

    def test_inactive_clock_skipped(self):  # acceptance 14
        sim, world, log = self._make_sim({
            "current": 0, "max": 3, "step": 1,
            "active": False,
        })
        sim.advance("beat")
        assert world.clocks["test_clock"]["current"] == 0

    def test_active_true_clock_still_advances(self):
        sim, world, log = self._make_sim({
            "current": 0, "max": 3, "step": 1,
            "active": True,
        })
        sim.advance("beat")
        assert world.clocks["test_clock"]["current"] == 1

    def test_no_trigger_types_defaults_to_beat(self):  # acceptance 15
        # trigger_types field absent — old clock schema
        sim, world, log = self._make_sim({"current": 0, "max": 3, "step": 1})
        fired = sim.advance("beat")
        assert world.clocks["test_clock"]["current"] == 1

    def test_trigger_types_empty_list_defaults_to_beat(self):
        sim, world, log = self._make_sim({
            "current": 0, "max": 3, "step": 1,
            "trigger_types": [],
        })
        fired = sim.advance("beat")
        assert world.clocks["test_clock"]["current"] == 1

    def test_clock_fires_on_trigger_match(self):
        sim, world, log = self._make_sim({
            "current": 2, "max": 3, "step": 1,
            "trigger_types": ["beat"],
        })
        fired = sim.advance("beat")
        assert "test_clock" in fired

    def test_clock_not_fired_on_trigger_mismatch(self):
        sim, world, log = self._make_sim({
            "current": 2, "max": 3, "step": 1,
            "trigger_types": ["scene"],
        })
        fired = sim.advance("beat")
        assert fired == []


# --------------------------------------------------------------------------- #
# 16–18: D-023 SQLiteEventLog.transaction                                       #
# --------------------------------------------------------------------------- #

class TestSQLiteTransaction:
    def test_transaction_commits_all_events_atomically(self):  # acceptance 16
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "sess.db"
            log, world, _scene = open_session(db)
            with log.transaction():
                log.append(
                    author="gm", channel="system", type="narration",
                    content="event A", audience=("gm",), visibility="content",
                )
                log.append(
                    author="gm", channel="system", type="narration",
                    content="event B", audience=("gm",), visibility="content",
                )
            log.close()

            # Reopen and verify both events persisted
            log2, _world2, _scene2 = open_session(db)
            events = [e for e in log2.all() if e.type == "narration"]
            assert len(events) == 2
            log2.close()

    def test_transaction_rollback_on_exception(self):  # acceptance 17
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "sess.db"
            log, world, _scene = open_session(db)
            try:
                with log.transaction():
                    log.append(
                        author="gm", channel="system", type="narration",
                        content="should be rolled back", audience=("gm",),
                        visibility="content",
                    )
                    raise ValueError("simulated failure")
            except ValueError:
                pass

            # In-memory state is restored
            narr_events = [e for e in log.all() if e.type == "narration"]
            assert narr_events == []

            log.close()

            # DB also rolled back
            log2, _world2, _scene2 = open_session(db)
            narr_events2 = [e for e in log2.all() if e.type == "narration"]
            assert narr_events2 == []
            log2.close()

    def test_nested_transaction_is_noop(self):  # acceptance 18
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "sess.db"
            log, world, _scene = open_session(db)
            with log.transaction():
                with log.transaction():  # inner: no-op
                    log.append(
                        author="gm", channel="system", type="narration",
                        content="inside nested", audience=("gm",),
                        visibility="content",
                    )
            log.close()

            log2, _world2, _scene2 = open_session(db)
            narr = [e for e in log2.all() if e.type == "narration"]
            assert len(narr) == 1
            log2.close()

    def test_without_transaction_each_append_auto_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "sess.db"
            log, world, _scene = open_session(db)
            log.append(
                author="gm", channel="system", type="narration",
                content="standalone", audience=("gm",), visibility="content",
            )
            log.close()

            log2, _world2, _scene2 = open_session(db)
            narr = [e for e in log2.all() if e.type == "narration"]
            assert len(narr) == 1
            log2.close()


# --------------------------------------------------------------------------- #
# 19–22: BeatRunner integration                                                 #
# --------------------------------------------------------------------------- #

class TestBeatRunnerIntegration:
    """Validates that BeatRunner correctly wires the interest accumulator and
    plot manager without requiring a live model call (mocked GM and narrator)."""

    def _make_runner(self, accumulator=None, plot_manager=None):
        from fable_table_engine import (
            BeatRunner,
            CharacterSheet,
            CommitPipeline,
            ContextAssembler,
            DiceService,
            EventLog,
            RulesEngine,
            WorldState,
        )
        from fable_table_engine.gm import AdjudicatorGM, NarratorGM, StakesDecision

        log = EventLog()
        world = WorldState()
        pipeline = CommitPipeline(log)
        dice = DiceService(log)
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)

        adj = MagicMock(spec=AdjudicatorGM)
        adj.evaluate.return_value = StakesDecision(
            has_stakes=False, reasoning="no stakes", declared_facts=[]
        )
        narr = MagicMock(spec=NarratorGM)
        narr.narrate.return_value = "The dust settles."

        sheets = {"hero": CharacterSheet(entity_id="hero", concept="adventurer")}

        runner = BeatRunner(
            log=log,
            world=world,
            pipeline=pipeline,
            rules=rules,
            assembler=assembler,
            adjudicator=adj,
            narrator=narr,
            sheets=sheets,
            gm_entity="gm",
            interest_accumulator=accumulator,
            plot_manager=plot_manager,
        )
        return runner, log, pipeline, world

    def test_interest_signal_emitted_for_actor(self):  # acceptance 19
        acc = InterestSignalAccumulator()
        runner, log, pipeline, world = self._make_runner(accumulator=acc)
        runner.run("hero", "I look around cautiously.")
        assert acc.total_weight("hero") > 0.0
        sigs = acc.signals_for("hero")
        assert len(sigs) == 1
        assert sigs[0].category == "action"

    def test_multiple_beats_accumulate(self):
        acc = InterestSignalAccumulator()
        runner, log, pipeline, world = self._make_runner(accumulator=acc)
        runner.run("hero", "First action.")
        runner.run("hero", "Second action.")
        assert acc.total_weight("hero") == pytest.approx(1.0)  # 0.5 * 2

    def test_plot_manager_gm_context_in_world_summary(self):  # acceptance 20
        from fable_table_engine.gm import AdjudicatorGM, StakesDecision
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        pm = PlotManager(graph, pipeline, log)

        from fable_table_engine import (
            BeatRunner, CharacterSheet, ContextAssembler,
            DiceService, EventLog, RulesEngine, WorldState,
        )
        from fable_table_engine.gm import NarratorGM

        adj = MagicMock(spec=AdjudicatorGM)
        captured_summary: list[str] = []

        def capture_evaluate(**kwargs):
            captured_summary.append(kwargs.get("world_summary", ""))
            return StakesDecision(has_stakes=False, reasoning="", declared_facts=[])

        adj.evaluate.side_effect = capture_evaluate
        narr = MagicMock(spec=NarratorGM)
        narr.narrate.return_value = "Done."

        dice = DiceService(log)
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        sheets = {"hero": CharacterSheet(entity_id="hero", concept="adventurer")}

        runner = BeatRunner(
            log=log, world=WorldState(), pipeline=pipeline,
            rules=rules, assembler=assembler,
            adjudicator=adj, narrator=narr, sheets=sheets,
            gm_entity="gm", plot_manager=pm,
        )
        runner.run("hero", "I search the area.")

        assert len(captured_summary) == 1
        assert "fn_contact" in captured_summary[0]  # hook summary present

    def test_plot_manager_post_beat_called_for_fired_clocks(self):  # acceptance 21
        from fable_table_engine.gm import WorldSimulator
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        pm = PlotManager(graph, pipeline, log)

        from fable_table_engine import (
            BeatRunner, CharacterSheet, ContextAssembler,
            DiceService, WorldState, RulesEngine,
        )
        from fable_table_engine.gm import AdjudicatorGM, NarratorGM, StakesDecision

        world = WorldState()
        world.set_clock("ritual_clock", {"current": 2, "max": 3, "step": 1})

        adj = MagicMock(spec=AdjudicatorGM)
        adj.evaluate.return_value = StakesDecision(
            has_stakes=False, reasoning="", declared_facts=[]
        )
        narr = MagicMock(spec=NarratorGM)
        narr.narrate.return_value = "Time passes."

        dice = DiceService(log)
        rules = RulesEngine(log, dice)
        assembler = ContextAssembler(log)
        sheets = {"hero": CharacterSheet(entity_id="hero", concept="adventurer")}
        sim = WorldSimulator(log, world)

        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=rules, assembler=assembler,
            adjudicator=adj, narrator=narr, sheets=sheets,
            gm_entity="gm", simulator=sim, plot_manager=pm,
        )
        runner.run("hero", "I act.")

        # Clock fired → PlotManager logged a front_consequence
        consequence_events = [e for e in log.all() if e.type == "front_consequence"]
        assert len(consequence_events) == 1
        assert "cult_ritual_complete" in consequence_events[0].content

    def test_post_beat_auto_accepts_rebinding(self):  # acceptance 22
        from fable_table_engine.gm import WorldSimulator
        graph = _make_graph()
        log, pipeline = _make_log_and_pipeline()
        _commit_condition(pipeline, "informant_marco", "destroyed")
        pm = PlotManager(graph, pipeline, log)

        issues = pm.check_fixture_health()
        assert len(issues) == 1

        accepted = pm.post_beat([])
        assert len(accepted) == 1
        assert accepted[0].fixture_entity_id == "informant_yara"
        # graph updated
        assert graph.hooks[0].binding.fixture_entity_id == "informant_yara"
