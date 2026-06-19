"""Phase 16 tests — scene cadence + companion activation (D-021).

Key invariants:

  1. SceneMode: six deterministic modes with correct companion limits.
  2. SceneCadence.select_companions: always-active companions always included;
     conditional companions fill remaining slots sorted by spotlight_order
     (least-recently-acted first).
  3. is_full_activation: True for TACTICAL/COMBAT/HIGH_DRAMA only.
  4. Orchestrator.sorted_by_spotlight: sorts candidates least-recently-acted first;
     never-acted candidates sort before all others.
  5. run_round with scene_cadence: gated companions removed from rotation and
     receive zero model calls; human seats never gated; backward-compatible
     when scene_cadence is None.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fable_table_engine import (
    ActionQueue,
    BeatRunner,
    CharacterAgent,
    CharacterSheet,
    CommitPipeline,
    ContextAssembler,
    Entity,
    EventLog,
    ModelGateway,
    Orchestrator,
    PersonaSpec,
    Proposal,
    WorldState,
)
from fable_table_engine.gm import AdjudicatorGM, NarratorGM, StakesDecision
from fable_table_engine.orchestrator import SceneCadence, SceneMode
from fable_table_engine.rules import RulesEngine


# --------------------------------------------------------------------------- #
# Fixtures / helpers                                                            #
# --------------------------------------------------------------------------- #

def _noop_adjudicator() -> AdjudicatorGM:
    adj = MagicMock(spec=AdjudicatorGM)
    adj.evaluate.return_value = StakesDecision(
        has_stakes=False,
        reasoning="no stakes",
        skill=None,
        skill_rating=None,
        tn=None,
        declared_facts=[],
    )
    return adj


def _noop_narrator() -> NarratorGM:
    nar = MagicMock(spec=NarratorGM)
    nar.narrate.return_value = "Nothing notable happens."
    return nar


def _make_world(*entity_ids: str) -> WorldState:
    w = WorldState()
    w.add_zone("room")
    for eid in entity_ids:
        w.add_entity(Entity(id=eid, name=eid.capitalize(), kind="character"))
        w.place(eid, "room")
    return w


def _make_agent(entity_id: str, intent: str = "I stand ready.") -> tuple[CharacterAgent, MagicMock]:
    persona = PersonaSpec(entity_id=entity_id, name=entity_id.capitalize(), concept="teammate", voice="Direct.")
    sheet = CharacterSheet(entity_id=entity_id, concept="c")
    client = MagicMock()
    block = MagicMock()
    block.type = "tool_use"
    block.name = "propose_action"
    block.input = {"intent": intent, "channel": "public", "reasoning": "test"}
    resp = MagicMock()
    resp.content = [block]
    # ModelGateway reads usage; provide a minimal mock so it doesn't error
    resp.usage = MagicMock(
        input_tokens=5, output_tokens=3,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
    )
    client.messages.create.return_value = resp
    gateway = ModelGateway(client)
    return CharacterAgent(persona, sheet, gateway), client


def _make_runner(world: WorldState, sheets: dict[str, CharacterSheet]) -> BeatRunner:
    log = EventLog()
    pipeline = CommitPipeline(log)
    assembler = ContextAssembler(log)
    rules = RulesEngine(log, MagicMock())
    return BeatRunner(
        log=log,
        world=world,
        pipeline=pipeline,
        rules=rules,
        assembler=assembler,
        adjudicator=_noop_adjudicator(),
        narrator=_noop_narrator(),
        sheets=sheets,
        gm_entity="gm",
    )


# --------------------------------------------------------------------------- #
# SceneMode                                                                     #
# --------------------------------------------------------------------------- #

class TestSceneMode:

    def test_all_six_values_exist(self):
        modes = {m.value for m in SceneMode}
        assert modes == {"quiet", "dialogue", "tactical", "combat", "downtime", "high_drama"}

    def test_is_str_subclass(self):
        assert SceneMode.QUIET == "quiet"
        assert SceneMode.COMBAT == "combat"

    def test_roundtrip_from_string(self):
        assert SceneMode("dialogue") is SceneMode.DIALOGUE


# --------------------------------------------------------------------------- #
# SceneCadence — properties                                                     #
# --------------------------------------------------------------------------- #

class TestSceneCadenceProperties:

    def test_default_mode_is_tactical(self):
        sc = SceneCadence()
        assert sc.mode is SceneMode.TACTICAL

    def test_set_mode_changes_mode(self):
        sc = SceneCadence()
        sc.set_mode(SceneMode.COMBAT)
        assert sc.mode is SceneMode.COMBAT

    def test_companion_limit_quiet(self):
        sc = SceneCadence(SceneMode.QUIET)
        assert sc.companion_limit == 1

    def test_companion_limit_dialogue(self):
        sc = SceneCadence(SceneMode.DIALOGUE)
        assert sc.companion_limit == 2

    def test_companion_limit_downtime(self):
        sc = SceneCadence(SceneMode.DOWNTIME)
        assert sc.companion_limit == 1

    def test_companion_limit_unlimited_modes(self):
        for mode in (SceneMode.TACTICAL, SceneMode.COMBAT, SceneMode.HIGH_DRAMA):
            sc = SceneCadence(mode)
            assert sc.companion_limit >= 2 ** 16, f"{mode} should be unlimited"

    def test_is_full_activation_true_for_tactical_combat_drama(self):
        for mode in (SceneMode.TACTICAL, SceneMode.COMBAT, SceneMode.HIGH_DRAMA):
            assert SceneCadence(mode).is_full_activation

    def test_is_full_activation_false_for_limited_modes(self):
        for mode in (SceneMode.QUIET, SceneMode.DIALOGUE, SceneMode.DOWNTIME):
            assert not SceneCadence(mode).is_full_activation

    def test_always_active_starts_empty(self):
        sc = SceneCadence()
        assert sc.always_active == frozenset()

    def test_set_and_clear_always_active(self):
        sc = SceneCadence()
        sc.set_always_active("ally")
        assert "ally" in sc.always_active
        sc.clear_always_active("ally")
        assert "ally" not in sc.always_active

    def test_clear_nonexistent_always_active_is_noop(self):
        sc = SceneCadence()
        sc.clear_always_active("nobody")  # should not raise


# --------------------------------------------------------------------------- #
# SceneCadence.select_companions                                                #
# --------------------------------------------------------------------------- #

class TestSelectCompanions:

    def test_combat_returns_all_candidates(self):
        sc = SceneCadence(SceneMode.COMBAT)
        result = sc.select_companions(["ally1", "ally2", "ally3"])
        assert result == ["ally1", "ally2", "ally3"]

    def test_tactical_returns_all_candidates(self):
        sc = SceneCadence(SceneMode.TACTICAL)
        result = sc.select_companions(["a", "b"])
        assert result == ["a", "b"]

    def test_high_drama_returns_all_candidates(self):
        sc = SceneCadence(SceneMode.HIGH_DRAMA)
        result = sc.select_companions(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_quiet_returns_at_most_one(self):
        sc = SceneCadence(SceneMode.QUIET)
        result = sc.select_companions(["ally1", "ally2", "ally3"])
        assert len(result) == 1

    def test_dialogue_returns_at_most_two(self):
        sc = SceneCadence(SceneMode.DIALOGUE)
        result = sc.select_companions(["ally1", "ally2", "ally3"])
        assert len(result) == 2

    def test_downtime_returns_at_most_one(self):
        sc = SceneCadence(SceneMode.DOWNTIME)
        result = sc.select_companions(["ally1", "ally2"])
        assert len(result) == 1

    def test_empty_candidates_returns_empty(self):
        sc = SceneCadence(SceneMode.QUIET)
        assert sc.select_companions([]) == []

    def test_fewer_candidates_than_limit_returns_all(self):
        sc = SceneCadence(SceneMode.DIALOGUE)
        result = sc.select_companions(["only_one"])
        assert result == ["only_one"]

    def test_always_active_always_included_in_quiet(self):
        sc = SceneCadence(SceneMode.QUIET)
        sc.set_always_active("vital")
        result = sc.select_companions(["vital", "ally2"])
        assert "vital" in result

    def test_always_active_fills_the_one_quiet_slot(self):
        sc = SceneCadence(SceneMode.QUIET)
        sc.set_always_active("vital")
        result = sc.select_companions(["vital", "ally2"])
        # vital uses the 1 slot; no room for ally2
        assert result == ["vital"]
        assert "ally2" not in result

    def test_always_active_beyond_limit_still_all_included(self):
        sc = SceneCadence(SceneMode.QUIET)
        sc.set_always_active("vital1")
        sc.set_always_active("vital2")
        result = sc.select_companions(["vital1", "vital2", "ally3"])
        # both always_active included even though limit=1
        assert "vital1" in result
        assert "vital2" in result
        # no room for conditional ally3 (0 remaining slots)
        assert "ally3" not in result

    def test_spotlight_order_picks_least_recently_acted(self):
        sc = SceneCadence(SceneMode.QUIET)
        # spotlight_order: ally2 acted less recently than ally1
        result = sc.select_companions(
            ["ally1", "ally2"],
            spotlight_order=["ally2", "ally1"],
        )
        assert result == ["ally2"]

    def test_without_spotlight_order_preserves_candidate_order(self):
        sc = SceneCadence(SceneMode.QUIET)
        result = sc.select_companions(["ally1", "ally2"])
        assert result == ["ally1"]

    def test_spotlight_order_with_dialogue_limit(self):
        sc = SceneCadence(SceneMode.DIALOGUE)
        # ally3 most idle, ally1 least idle
        result = sc.select_companions(
            ["ally1", "ally2", "ally3"],
            spotlight_order=["ally3", "ally2", "ally1"],
        )
        assert result == ["ally3", "ally2"]

    def test_candidates_not_in_spotlight_order_sort_last(self):
        sc = SceneCadence(SceneMode.DIALOGUE)
        result = sc.select_companions(
            ["ally1", "ally2", "ally3"],
            spotlight_order=["ally1"],  # ally2, ally3 not in order → low priority
        )
        assert result == ["ally1", "ally2"]  # ally1 first (in order), then candidates order


# --------------------------------------------------------------------------- #
# Orchestrator.sorted_by_spotlight                                              #
# --------------------------------------------------------------------------- #

class TestOrchestratorSortedBySpotlight:

    def test_never_acted_sorts_first(self):
        orch = Orchestrator(["a", "b", "c"])
        orch.record_acted("b")
        orch.record_acted("a")
        result = orch.sorted_by_spotlight(["a", "b", "c"])
        # c never acted (-1) → first
        assert result[0] == "c"

    def test_least_recently_acted_sorts_before_more_recent(self):
        orch = Orchestrator(["a", "b"])
        orch.record_acted("a")
        orch.record_acted("b")
        result = orch.sorted_by_spotlight(["a", "b"])
        # a acted at index 0, b at index 1 → a less recent → a first
        assert result == ["a", "b"]

    def test_empty_history_preserves_candidate_order(self):
        orch = Orchestrator(["x", "y", "z"])
        result = orch.sorted_by_spotlight(["x", "y", "z"])
        # all have index -1; sorted stable on equal key → original order preserved
        assert result == ["x", "y", "z"]

    def test_multiple_candidates_sorted_correctly(self):
        orch = Orchestrator(["a", "b", "c", "d"])
        for who in ["c", "a", "b"]:
            orch.record_acted(who)
        # history: [c, a, b]; last_acted_index: d=-1, c=0, a=1, b=2
        result = orch.sorted_by_spotlight(["a", "b", "c", "d"])
        assert result == ["d", "c", "a", "b"]

    def test_single_candidate_returns_single_element_list(self):
        orch = Orchestrator(["a"])
        orch.record_acted("a")
        assert orch.sorted_by_spotlight(["a"]) == ["a"]

    def test_empty_candidates_returns_empty(self):
        orch = Orchestrator(["a"])
        assert orch.sorted_by_spotlight([]) == []


# --------------------------------------------------------------------------- #
# run_round with scene_cadence                                                  #
# --------------------------------------------------------------------------- #

class TestRunRoundWithSceneCadence:
    """Integration: scene_cadence gates AI companions in run_round."""

    def _setup(self, *ai_entity_ids: str) -> tuple[BeatRunner, Orchestrator, dict[str, CharacterAgent], dict[str, MagicMock]]:
        world = _make_world(*ai_entity_ids)
        sheets = {eid: CharacterSheet(entity_id=eid, concept="c") for eid in ai_entity_ids}
        runner = _make_runner(world, sheets)
        orch = Orchestrator(list(ai_entity_ids))
        agents: dict[str, CharacterAgent] = {}
        clients: dict[str, MagicMock] = {}
        for eid in ai_entity_ids:
            agent, client = _make_agent(eid)
            agents[eid] = agent
            clients[eid] = client
        return runner, orch, agents, clients

    def test_no_cadence_all_agents_get_beat(self):
        runner, orch, agents, clients = self._setup("ally1", "ally2")
        results = runner.run_round(orch, agents)
        assert len(results) == 2
        assert clients["ally1"].messages.create.call_count == 1
        assert clients["ally2"].messages.create.call_count == 1

    def test_combat_cadence_all_agents_get_beat(self):
        runner, orch, agents, clients = self._setup("ally1", "ally2", "ally3")
        sc = SceneCadence(SceneMode.COMBAT)
        results = runner.run_round(orch, agents, scene_cadence=sc)
        assert len(results) == 3
        for eid in ("ally1", "ally2", "ally3"):
            assert clients[eid].messages.create.call_count == 1

    def test_tactical_cadence_all_agents_get_beat(self):
        runner, orch, agents, clients = self._setup("ally1", "ally2")
        sc = SceneCadence(SceneMode.TACTICAL)
        results = runner.run_round(orch, agents, scene_cadence=sc)
        assert len(results) == 2

    def test_quiet_cadence_only_one_agent_gets_beat(self):
        runner, orch, agents, clients = self._setup("ally1", "ally2", "ally3")
        sc = SceneCadence(SceneMode.QUIET)
        results = runner.run_round(orch, agents, scene_cadence=sc)
        assert len(results) == 1

    def test_quiet_gated_agents_receive_zero_model_calls(self):
        runner, orch, agents, clients = self._setup("ally1", "ally2")
        sc = SceneCadence(SceneMode.QUIET)
        runner.run_round(orch, agents, scene_cadence=sc)
        total_calls = sum(c.messages.create.call_count for c in clients.values())
        # adjudicator/narrator are MagicMock stubs — only CharacterAgent.propose()
        # calls messages.create (1 call per activated companion); gated → 0 calls
        assert total_calls == 1  # only the 1 activated companion

    def test_dialogue_cadence_at_most_two_agents(self):
        runner, orch, agents, clients = self._setup("ally1", "ally2", "ally3")
        sc = SceneCadence(SceneMode.DIALOGUE)
        results = runner.run_round(orch, agents, scene_cadence=sc)
        assert len(results) == 2

    def test_human_seat_never_gated_in_quiet_mode(self):
        world = _make_world("hero", "ally1")
        sheets = {
            "hero": CharacterSheet(entity_id="hero", concept="player"),
            "ally1": CharacterSheet(entity_id="ally1", concept="c"),
        }
        runner = _make_runner(world, sheets)
        orch = Orchestrator(["hero", "ally1"])

        ally1_agent, ally1_client = _make_agent("ally1")
        agents = {"ally1": ally1_agent}
        player_proposals = {"hero": "I look around carefully."}

        sc = SceneCadence(SceneMode.QUIET)
        results = runner.run_round(
            orch, agents,
            player_proposals=player_proposals,
            scene_cadence=sc,
        )
        # hero (human) always gets a beat; plus the 1 companion
        assert len(results) == 2
        actors = {r.actor for r in results}
        assert "hero" in actors

    def test_always_active_gets_beat_in_quiet_mode(self):
        runner, orch, agents, clients = self._setup("ally1", "ally2", "ally3")
        sc = SceneCadence(SceneMode.QUIET)
        sc.set_always_active("ally3")
        results = runner.run_round(orch, agents, scene_cadence=sc)
        actors = {r.actor for r in results}
        assert "ally3" in actors

    def test_always_active_uses_the_single_quiet_slot(self):
        runner, orch, agents, clients = self._setup("ally1", "ally2")
        sc = SceneCadence(SceneMode.QUIET)
        sc.set_always_active("ally2")
        results = runner.run_round(orch, agents, scene_cadence=sc)
        # ally2 is always_active and uses the 1 slot; ally1 is gated
        assert len(results) == 1
        assert results[0].actor == "ally2"
        assert clients["ally1"].messages.create.call_count == 0

    def test_scene_mode_transition_takes_effect_next_round(self):
        runner, orch, agents, clients = self._setup("ally1", "ally2")
        sc = SceneCadence(SceneMode.QUIET)
        results_round1 = runner.run_round(orch, agents, scene_cadence=sc)
        assert len(results_round1) == 1

        sc.set_mode(SceneMode.COMBAT)
        results_round2 = runner.run_round(orch, agents, scene_cadence=sc)
        assert len(results_round2) == 2

    def test_spotlight_order_used_to_pick_activated_companion(self):
        """With QUIET mode, the least-recently-acted companion gets priority."""
        runner, orch, agents, clients = self._setup("ally1", "ally2")
        # ally1 acted first (more recently in the next round's perspective)
        orch.record_acted("ally1")

        sc = SceneCadence(SceneMode.QUIET)
        results = runner.run_round(orch, agents, scene_cadence=sc)
        # ally2 less recently acted → should be selected
        assert len(results) == 1
        assert results[0].actor == "ally2"
        assert clients["ally1"].messages.create.call_count == 0
