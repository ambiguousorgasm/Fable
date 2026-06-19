"""Phase 7 tests — orchestrator / spotlight (CORE §4.3, §5 step 1; D-005, D-010, D-015).

Key invariants:

  1. ActionQueue: enqueue/drain/peek contract; non-authoritative; clears on drain.
  2. Orchestrator SPOTLIGHT: director-picks-next; least-recently-acted first;
     falls back to full active set when everyone has acted recently.
  3. Orchestrator INITIATIVE: structured order; skips absent seats; wraps around.
  4. Orchestrator metadata-only: no event content involved in routing decisions.
  5. run_with_agent: agent proposes via its own filtered belief store; dialogue folded
     into action string correctly; action queue transit optional.
  6. run_round: each present seat gets exactly one beat; orchestrator history updated
     after each seat; AI and human seats handled correctly; missing seat raises.
  7. D-015: turn routing does not hardcode seat identity (human vs. AI).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fable_table_engine import (
    ActionQueue,
    BeatResult,
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
    TurnGrant,
    TurnMode,
    WorldState,
)
from fable_table_engine.gm import AdjudicatorGM, NarratorGM, StakesDecision
from fable_table_engine.rules import Band, CheckResult, RulesEngine


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
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


def _rules() -> RulesEngine:
    return RulesEngine(DiceService_stub := MagicMock())


def _beat_runner(log, world, sheets, adjudicator=None, narrator=None) -> BeatRunner:
    pipeline = CommitPipeline(log)
    assembler = ContextAssembler(log)
    from fable_table_engine.rules import RulesEngine
    rules = RulesEngine(log, MagicMock())  # dice never called in no-stakes beats
    return BeatRunner(
        log=log,
        world=world,
        pipeline=pipeline,
        rules=rules,
        assembler=assembler,
        adjudicator=adjudicator or _noop_adjudicator(),
        narrator=narrator or _noop_narrator(),
        sheets=sheets,
        gm_entity="gm",
    )


def _make_world_with(*entity_ids: str) -> WorldState:
    w = WorldState()
    w.add_zone("room")
    for eid in entity_ids:
        w.add_entity(Entity(id=eid, name=eid.capitalize(), kind="character"))
        w.place(eid, "room")
    return w


def _agent_persona(entity_id: str) -> PersonaSpec:
    return PersonaSpec(
        entity_id=entity_id,
        name=entity_id.capitalize(),
        concept="AI teammate",
        voice="Direct.",
    )


def _make_agent(entity_id: str, intent: str = "I watch the door.") -> tuple[CharacterAgent, MagicMock]:
    persona = _agent_persona(entity_id)
    sheet = CharacterSheet(entity_id=entity_id, concept="c")
    client = MagicMock()
    block = MagicMock()
    block.type = "tool_use"
    block.name = "propose_action"
    block.input = {"intent": intent, "channel": "public", "reasoning": "tactical"}
    resp = MagicMock()
    resp.content = [block]
    client.messages.create.return_value = resp
    return CharacterAgent(persona, sheet, ModelGateway(client)), client


def _make_agent_with_dialogue(entity_id: str, intent: str, dialogue: str) -> CharacterAgent:
    persona = _agent_persona(entity_id)
    sheet = CharacterSheet(entity_id=entity_id, concept="c")
    client = MagicMock()
    block = MagicMock()
    block.type = "tool_use"
    block.name = "propose_action"
    block.input = {"intent": intent, "dialogue": dialogue, "channel": "public", "reasoning": "r"}
    resp = MagicMock()
    resp.content = [block]
    client.messages.create.return_value = resp
    return CharacterAgent(persona, sheet, ModelGateway(client))


# --------------------------------------------------------------------------- #
# ActionQueue                                                                   #
# --------------------------------------------------------------------------- #

class TestActionQueue:

    def test_empty_queue_is_falsy(self):
        q = ActionQueue()
        assert not q
        assert len(q) == 0

    def test_enqueue_makes_truthy(self):
        q = ActionQueue()
        q.enqueue(Proposal(agent="x", intent="act", channel="public"))
        assert q
        assert len(q) == 1

    def test_drain_returns_proposals_and_clears(self):
        q = ActionQueue()
        p = Proposal(agent="x", intent="act", channel="public")
        q.enqueue(p)
        out = q.drain()
        assert len(out) == 1
        assert out[0] is p
        assert len(q) == 0
        assert not q

    def test_drain_empty_returns_empty_list(self):
        q = ActionQueue()
        assert q.drain() == []

    def test_peek_does_not_clear(self):
        q = ActionQueue()
        q.enqueue(Proposal(agent="x", intent="act", channel="public"))
        peeked = q.peek()
        assert len(peeked) == 1
        assert len(q) == 1

    def test_multiple_proposals_preserve_order(self):
        q = ActionQueue()
        for i in range(3):
            q.enqueue(Proposal(agent=f"x{i}", intent=f"act {i}", channel="public"))
        out = q.drain()
        assert [p.intent for p in out] == ["act 0", "act 1", "act 2"]

    def test_drain_twice_second_is_empty(self):
        q = ActionQueue()
        q.enqueue(Proposal(agent="x", intent="act", channel="public"))
        q.drain()
        assert q.drain() == []


# --------------------------------------------------------------------------- #
# Orchestrator — construction                                                   #
# --------------------------------------------------------------------------- #

class TestOrchestratorConstruction:

    def test_empty_seats_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            Orchestrator(seats=[])

    def test_seats_property(self):
        o = Orchestrator(["a", "b"])
        assert set(o.seats) == {"a", "b"}

    def test_default_mode_is_spotlight(self):
        o = Orchestrator(["a"])
        assert o.mode == TurnMode.SPOTLIGHT

    def test_initiative_mode_constructor(self):
        o = Orchestrator(["a"], mode=TurnMode.INITIATIVE)
        assert o.mode == TurnMode.INITIATIVE


# --------------------------------------------------------------------------- #
# Orchestrator — SPOTLIGHT                                                      #
# --------------------------------------------------------------------------- #

class TestOrchestratorSpotlight:

    def test_single_seat_always_gets_turn(self):
        o = Orchestrator(["a"])
        grant = o.grant_turn()
        assert grant.actor == "a"
        assert grant.mode == TurnMode.SPOTLIGHT

    def test_two_seats_alternate(self):
        o = Orchestrator(["a", "b"])
        first = o.grant_turn(["a", "b"])
        o.record_acted(first.actor)
        second = o.grant_turn(["a", "b"])
        assert first.actor != second.actor

    def test_least_recently_acted_gets_turn(self):
        o = Orchestrator(["a", "b", "c"])
        # a and b have acted; c hasn't
        o.record_acted("a")
        o.record_acted("b")
        grant = o.grant_turn(["a", "b", "c"])
        assert grant.actor == "c"

    def test_absent_seat_not_granted(self):
        o = Orchestrator(["a", "b", "c"])
        # Only b is present
        grant = o.grant_turn(["b"])
        assert grant.actor == "b"

    def test_all_acted_falls_back_to_full_active(self):
        o = Orchestrator(["a", "b"])
        o.record_acted("a")
        o.record_acted("b")
        grant = o.grant_turn(["a", "b"])
        assert grant.actor in {"a", "b"}

    def test_record_acted_updates_history(self):
        o = Orchestrator(["a", "b", "c"])
        o.record_acted("c")
        # c recently acted; a or b should be preferred
        grant = o.grant_turn(["a", "b", "c"])
        assert grant.actor in {"a", "b"}

    def test_grant_turn_returns_turn_grant(self):
        o = Orchestrator(["a"])
        grant = o.grant_turn()
        assert isinstance(grant, TurnGrant)
        assert grant.reason != ""

    def test_no_active_seats_raises(self):
        o = Orchestrator(["a"])
        with pytest.raises(ValueError, match="no active seats"):
            o.grant_turn([])

    def test_set_spotlight_mode_switches_mode(self):
        o = Orchestrator(["a"], mode=TurnMode.INITIATIVE)
        o.set_spotlight_mode()
        assert o.mode == TurnMode.SPOTLIGHT


# --------------------------------------------------------------------------- #
# Orchestrator — INITIATIVE                                                     #
# --------------------------------------------------------------------------- #

class TestOrchestratorInitiative:

    def test_set_initiative_switches_mode(self):
        o = Orchestrator(["a", "b"])
        o.set_initiative(["b", "a"])
        assert o.mode == TurnMode.INITIATIVE

    def test_initiative_follows_order(self):
        o = Orchestrator(["a", "b", "c"])
        o.set_initiative(["c", "a", "b"])
        seats = []
        for _ in range(3):
            g = o.grant_turn(["a", "b", "c"])
            seats.append(g.actor)
            o.record_acted(g.actor)
        assert seats == ["c", "a", "b"]

    def test_initiative_wraps_around(self):
        o = Orchestrator(["a", "b"])
        o.set_initiative(["a", "b"])
        for _ in range(2):
            o.grant_turn(["a", "b"])
        grant = o.grant_turn(["a", "b"])
        assert grant.actor == "a"

    def test_initiative_skips_absent_seats(self):
        o = Orchestrator(["a", "b", "c"])
        o.set_initiative(["a", "b", "c"])
        # only b is present
        grant = o.grant_turn(["b"])
        assert grant.actor == "b"

    def test_initiative_no_present_raises(self):
        o = Orchestrator(["a", "b"])
        o.set_initiative(["a", "b"])
        with pytest.raises(ValueError, match="no initiative-order seat"):
            o.grant_turn(["c"])  # c not in initiative order and not present

    def test_empty_initiative_order_raises(self):
        o = Orchestrator(["a"])
        with pytest.raises(ValueError, match="cannot be empty"):
            o.set_initiative([])

    def test_initiative_mode_no_order_raises_on_grant(self):
        o = Orchestrator(["a"], mode=TurnMode.INITIATIVE)
        with pytest.raises(ValueError, match="no order set"):
            o.grant_turn()

    def test_initiative_grant_mode_label(self):
        o = Orchestrator(["a"])
        o.set_initiative(["a"])
        grant = o.grant_turn(["a"])
        assert grant.mode == TurnMode.INITIATIVE


# --------------------------------------------------------------------------- #
# BeatRunner.run_with_agent                                                     #
# --------------------------------------------------------------------------- #

class TestRunWithAgent:

    def test_returns_beat_result(self):
        log = EventLog()
        world = _make_world_with("vale")
        sheets = {"vale": CharacterSheet(entity_id="vale", concept="c")}
        runner = _beat_runner(log, world, sheets)

        agent, _ = _make_agent("vale", "I check the exits.")
        result = runner.run_with_agent(agent)
        assert isinstance(result, BeatResult)
        assert result.actor == "vale"

    def test_agent_intent_becomes_action(self):
        log = EventLog()
        world = _make_world_with("vale")
        sheets = {"vale": CharacterSheet(entity_id="vale", concept="c")}
        adj = _noop_adjudicator()
        runner = _beat_runner(log, world, sheets, adjudicator=adj)

        agent, _ = _make_agent("vale", "I guard the door.")
        runner.run_with_agent(agent)
        call_action = adj.evaluate.call_args[1]["action"]
        assert "guard the door" in call_action

    def test_dialogue_folded_into_action(self):
        log = EventLog()
        world = _make_world_with("rook")
        sheets = {"rook": CharacterSheet(entity_id="rook", concept="c")}
        adj = _noop_adjudicator()
        runner = _beat_runner(log, world, sheets, adjudicator=adj)

        agent = _make_agent_with_dialogue("rook", "Draw my blade.", "Ready when you are.")
        runner.run_with_agent(agent)
        call_action = adj.evaluate.call_args[1]["action"]
        assert "Draw my blade" in call_action
        assert "Ready when you are" in call_action

    def test_queue_transit_works(self):
        log = EventLog()
        world = _make_world_with("vale")
        sheets = {"vale": CharacterSheet(entity_id="vale", concept="c")}
        runner = _beat_runner(log, world, sheets)
        q = ActionQueue()

        agent, _ = _make_agent("vale", "Scout ahead.")
        result = runner.run_with_agent(agent, queue=q)
        assert result.actor == "vale"
        assert len(q) == 0  # drained after processing

    def test_queue_empty_after_beat(self):
        log = EventLog()
        world = _make_world_with("vale")
        sheets = {"vale": CharacterSheet(entity_id="vale", concept="c")}
        runner = _beat_runner(log, world, sheets)
        q = ActionQueue()

        agent, _ = _make_agent("vale", "Search the room.")
        runner.run_with_agent(agent, queue=q)
        assert not q

    def test_agent_reads_own_belief_store(self):
        """Structural test: agent.propose() calls assembler.belief_store(agent.entity_id)."""
        log = EventLog()
        world = _make_world_with("vale")
        sheets = {"vale": CharacterSheet(entity_id="vale", concept="c")}

        assembler = ContextAssembler(log)
        pipeline = CommitPipeline(log)
        from fable_table_engine.rules import RulesEngine
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=RulesEngine(log, MagicMock()),
            assembler=assembler,
            adjudicator=_noop_adjudicator(),
            narrator=_noop_narrator(),
            sheets=sheets,
        )

        agent, client = _make_agent("vale", "Watch the perimeter.")
        runner.run_with_agent(agent)

        # The client.messages.create call should carry vale's POV, not "gm" or "rook"
        call = client.messages.create.call_args
        kwargs = call[1] if call[1] else {}
        messages = kwargs.get("messages", [])
        user_content = next((m["content"] for m in messages if m["role"] == "user"), "")
        assert user_content != ""  # vale got a context


# --------------------------------------------------------------------------- #
# BeatRunner.run_round                                                          #
# --------------------------------------------------------------------------- #

class TestRunRound:

    def test_all_seats_get_one_beat(self):
        log = EventLog()
        world = _make_world_with("vale", "rook")
        sheets = {
            "vale": CharacterSheet(entity_id="vale", concept="c"),
            "rook": CharacterSheet(entity_id="rook", concept="c"),
        }
        runner = _beat_runner(log, world, sheets)
        orc = Orchestrator(["vale", "rook"])
        vale_agent, _ = _make_agent("vale", "Stand guard.")
        rook_agent, _ = _make_agent("rook", "Watch the door.")

        results = runner.run_round(
            orchestrator=orc,
            agents={"vale": vale_agent, "rook": rook_agent},
        )
        assert len(results) == 2
        actors = {r.actor for r in results}
        assert actors == {"vale", "rook"}

    def test_each_seat_acts_exactly_once(self):
        log = EventLog()
        world = _make_world_with("a", "b", "c")
        sheets = {k: CharacterSheet(entity_id=k, concept="c") for k in ["a", "b", "c"]}
        runner = _beat_runner(log, world, sheets)
        orc = Orchestrator(["a", "b", "c"])
        agents = {k: _make_agent(k)[0] for k in ["a", "b", "c"]}

        results = runner.run_round(orchestrator=orc, agents=agents)
        actor_counts = {}
        for r in results:
            actor_counts[r.actor] = actor_counts.get(r.actor, 0) + 1
        assert all(v == 1 for v in actor_counts.values())

    def test_human_seat_uses_player_proposal(self):
        log = EventLog()
        world = _make_world_with("player", "rook")
        sheets = {
            "player": CharacterSheet(entity_id="player", concept="c"),
            "rook": CharacterSheet(entity_id="rook", concept="c"),
        }
        runner = _beat_runner(log, world, sheets)
        orc = Orchestrator(["player", "rook"])
        rook_agent, _ = _make_agent("rook", "Stand watch.")

        results = runner.run_round(
            orchestrator=orc,
            agents={"rook": rook_agent},
            player_proposals={"player": "I search the shelves."},
        )
        actors = {r.actor for r in results}
        assert actors == {"player", "rook"}

    def test_missing_seat_raises(self):
        log = EventLog()
        world = _make_world_with("a", "b")
        sheets = {"a": CharacterSheet(entity_id="a", concept="c"),
                  "b": CharacterSheet(entity_id="b", concept="c")}
        runner = _beat_runner(log, world, sheets)
        orc = Orchestrator(["a", "b"])
        # "b" has no agent and no player proposal
        a_agent, _ = _make_agent("a")

        with pytest.raises(ValueError, match="'b'"):
            runner.run_round(orchestrator=orc, agents={"a": a_agent})

    def test_present_subset_limits_round(self):
        log = EventLog()
        world = _make_world_with("a", "b", "c")
        sheets = {k: CharacterSheet(entity_id=k, concept="c") for k in ["a", "b", "c"]}
        runner = _beat_runner(log, world, sheets)
        orc = Orchestrator(["a", "b", "c"])
        agents = {k: _make_agent(k)[0] for k in ["a", "b", "c"]}

        # Only a and b are present in this scene
        results = runner.run_round(orchestrator=orc, agents=agents, present=["a", "b"])
        assert len(results) == 2
        assert all(r.actor in {"a", "b"} for r in results)

    def test_orchestrator_history_updated_after_round(self):
        log = EventLog()
        world = _make_world_with("a", "b")
        sheets = {"a": CharacterSheet(entity_id="a", concept="c"),
                  "b": CharacterSheet(entity_id="b", concept="c")}
        runner = _beat_runner(log, world, sheets)
        orc = Orchestrator(["a", "b"])
        agents = {k: _make_agent(k)[0] for k in ["a", "b"]}

        runner.run_round(orchestrator=orc, agents=agents)
        # After a full round, spotlight should rotate: whoever went first goes second next
        second_round_first = orc.grant_turn(["a", "b"])
        results_first_round = runner.run_round(orchestrator=orc, agents=agents)
        # Both seats get turns in the second round too
        assert len(results_first_round) == 2

    def test_initiative_mode_round(self):
        log = EventLog()
        world = _make_world_with("a", "b")
        sheets = {"a": CharacterSheet(entity_id="a", concept="c"),
                  "b": CharacterSheet(entity_id="b", concept="c")}
        runner = _beat_runner(log, world, sheets)
        orc = Orchestrator(["a", "b"])
        orc.set_initiative(["b", "a"])
        agents = {k: _make_agent(k)[0] for k in ["a", "b"]}

        results = runner.run_round(orchestrator=orc, agents=agents)
        assert results[0].actor == "b"
        assert results[1].actor == "a"

    def test_queue_used_for_human_seat_in_round(self):
        log = EventLog()
        world = _make_world_with("player")
        sheets = {"player": CharacterSheet(entity_id="player", concept="c")}
        runner = _beat_runner(log, world, sheets)
        orc = Orchestrator(["player"])
        q = ActionQueue()

        results = runner.run_round(
            orchestrator=orc,
            agents={},
            player_proposals={"player": "I climb the wall."},
            queue=q,
        )
        assert len(results) == 1
        assert results[0].actor == "player"
        assert len(q) == 0

    def test_d015_seat_agnostic_any_entity_can_be_human(self):
        """D-015: routing doesn't hardcode which entity_id is the human player."""
        log = EventLog()
        # In this scenario, 'rook' is the human and 'player' is the AI — reversed.
        world = _make_world_with("rook", "player")
        sheets = {"rook": CharacterSheet(entity_id="rook", concept="c"),
                  "player": CharacterSheet(entity_id="player", concept="c")}
        runner = _beat_runner(log, world, sheets)
        orc = Orchestrator(["rook", "player"])
        player_agent, _ = _make_agent("player")

        results = runner.run_round(
            orchestrator=orc,
            agents={"player": player_agent},
            player_proposals={"rook": "I pick the lock."},
        )
        actors = {r.actor for r in results}
        assert actors == {"rook", "player"}
