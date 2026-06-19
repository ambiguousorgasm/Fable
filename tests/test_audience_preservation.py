"""Audience preservation — end-to-end delivery scope tests (Task 1, e.md).

Invariants under test:
1. channel + target survive proposal creation → queue transit → run() →
   narration event audience. Nothing reconstructs them from prose.
2. Whisper narration reaches only actor + named target + GM.
3. Public narration reaches all present entities + GM.
4. OOC bypasses all fictional mechanics (no adjudicator, narrator, commit,
   or clock calls).
5. Narrator context for public beats contains only public-channel events;
   actor-private events (whispers received) are excluded.
6. Queue/orchestrator transit preserves whisper channel and target unchanged.
7. Invalid or absent whisper target fails deterministically before any
   adjudication or narration occurs.
8. No downstream component can produce a narration event whose audience
   conflicts with the resolved delivery scope.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from fable_table_engine import (
    ActionQueue,
    BeatResult,
    BeatRunner,
    CharacterAgent,
    CharacterSheet,
    CommitPipeline,
    ContextAssembler,
    DeliveryScope,
    Entity,
    EventLog,
    Orchestrator,
    PersonaSpec,
    Proposal,
    WorldState,
)
from fable_table_engine.beat import _resolve_delivery
from fable_table_engine.gm import AdjudicatorGM, NarratorGM, StakesDecision
from fable_table_engine.rules import RulesEngine


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

GM = "gm"


def _world_with(*entity_ids: str) -> WorldState:
    world = WorldState()
    for eid in entity_ids:
        world.add_entity(Entity(id=eid, kind="character", name=eid.capitalize()))
    return world


def _log() -> EventLog:
    return EventLog()


def _no_stakes_adjudicator() -> AdjudicatorGM:
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


def _narrator(text: str = "Nothing notable happens.") -> NarratorGM:
    nar = MagicMock(spec=NarratorGM)
    nar.narrate.return_value = text
    return nar


def _runner(
    log: EventLog,
    world: WorldState,
    entity_ids: list[str],
    adjudicator: AdjudicatorGM | None = None,
    narrator: NarratorGM | None = None,
) -> BeatRunner:
    pipeline = CommitPipeline(log)
    assembler = ContextAssembler(log)
    rules = RulesEngine(log, MagicMock())
    sheets = {eid: CharacterSheet(entity_id=eid, concept="test character") for eid in entity_ids}
    return BeatRunner(
        log=log,
        world=world,
        pipeline=pipeline,
        rules=rules,
        assembler=assembler,
        adjudicator=adjudicator or _no_stakes_adjudicator(),
        narrator=narrator or _narrator(),
        sheets=sheets,
        gm_entity=GM,
    )


# --------------------------------------------------------------------------- #
# _resolve_delivery unit tests                                                  #
# --------------------------------------------------------------------------- #

def test_resolve_public_includes_all_entities_and_gm():
    world = _world_with("player", "vale", "rook")
    scope = _resolve_delivery("public", "player", None, world, GM)
    assert scope.channel == "public"
    assert set(scope.audience) == {"player", "vale", "rook", GM}
    assert scope.target is None


def test_resolve_whisper_restricts_to_actor_target_gm():
    world = _world_with("player", "vale", "rook")
    scope = _resolve_delivery("whisper", "player", "vale", world, GM)
    assert scope.channel == "whisper"
    assert set(scope.audience) == {"player", "vale", GM}
    assert scope.target == "vale"


def test_resolve_whisper_excludes_third_party():
    world = _world_with("player", "vale", "rook")
    scope = _resolve_delivery("whisper", "player", "vale", world, GM)
    assert "rook" not in scope.audience


def test_resolve_ooc_includes_all_entities_and_gm():
    world = _world_with("player", "vale")
    scope = _resolve_delivery("ooc", "player", None, world, GM)
    assert scope.channel == "ooc"
    assert set(scope.audience) == {"player", "vale", GM}


def test_resolve_whisper_unknown_target_raises():
    world = _world_with("player", "vale")
    with pytest.raises(ValueError, match="not a known entity"):
        _resolve_delivery("whisper", "player", "ghost", world, GM)


def test_resolve_whisper_self_target_raises():
    world = _world_with("player", "vale")
    with pytest.raises(ValueError, match="cannot whisper to yourself"):
        _resolve_delivery("whisper", "player", "player", world, GM)


def test_resolve_whisper_missing_target_raises():
    world = _world_with("player", "vale")
    with pytest.raises(ValueError, match="requires a non-empty target"):
        _resolve_delivery("whisper", "player", None, world, GM)


def test_resolve_unknown_channel_raises():
    world = _world_with("player")
    with pytest.raises(ValueError, match="unknown proposal channel"):
        _resolve_delivery("secret", "player", None, world, GM)


def test_resolve_no_duplicate_audience_when_gm_in_entities():
    """If GM is also a world entity, audience must still be unique."""
    world = _world_with("player", GM)
    scope = _resolve_delivery("public", "player", None, world, GM)
    assert len(scope.audience) == len(set(scope.audience))


# --------------------------------------------------------------------------- #
# Proposal channel/target preservation through the queue                       #
# --------------------------------------------------------------------------- #

def test_queue_transit_preserves_whisper_channel_and_target():
    """Invariant 6: enqueue+drain must not alter channel or target."""
    q = ActionQueue()
    p = Proposal(agent="player", intent="I lean in close", channel="whisper", target="vale")
    q.enqueue(p)
    drained = q.drain()
    assert len(drained) == 1
    assert drained[0].channel == "whisper"
    assert drained[0].target == "vale"


def test_queue_transit_preserves_ooc_channel():
    q = ActionQueue()
    p = Proposal(agent="player", intent="Can we pause?", channel="ooc")
    q.enqueue(p)
    drained = q.drain()
    assert drained[0].channel == "ooc"
    assert drained[0].target is None


# --------------------------------------------------------------------------- #
# Whisper: narration event audience                                             #
# --------------------------------------------------------------------------- #

def test_whisper_narration_event_excludes_rook(tmp_path):
    """Invariant 2: a whisper from player to vale must not appear in rook's projection."""
    log = _log()
    world = _world_with("player", "vale", "rook")
    runner = _runner(log, world, ["player", "vale", "rook"])

    result = runner.run("player", "I slip vale a note", channel="whisper", target="vale")

    # Find the narration event in the log
    narration_events = [e for e in log._events if e.type == "narration"]
    assert len(narration_events) == 1
    ev = narration_events[0]

    assert "rook" not in ev.audience
    assert "player" in ev.audience
    assert "vale" in ev.audience
    assert GM in ev.audience
    assert ev.channel == "whisper"


def test_whisper_result_channel_is_whisper():
    log = _log()
    world = _world_with("player", "vale")
    runner = _runner(log, world, ["player", "vale"])
    result = runner.run("player", "a quiet word", channel="whisper", target="vale")
    assert result.channel == "whisper"


def test_whisper_absent_from_rook_belief_store():
    """The non-audience entity's belief store must not contain the whisper."""
    log = _log()
    world = _world_with("player", "vale", "rook")
    runner = _runner(log, world, ["player", "vale", "rook"])
    runner.run("player", "I whisper to vale", channel="whisper", target="vale")

    from fable_table_engine import ContextAssembler
    assembler = ContextAssembler(log)
    rook_store = assembler.belief_store("rook")
    narration_ids = {e.id for e in rook_store.events if e.type == "narration"}
    assert len(narration_ids) == 0, "rook should see no narration events from a whisper they weren't party to"


# --------------------------------------------------------------------------- #
# Public: narration reaches all present                                         #
# --------------------------------------------------------------------------- #

def test_public_narration_reaches_all_present():
    """Invariant 3: public narration audience includes every world entity + GM."""
    log = _log()
    world = _world_with("player", "vale", "rook")
    runner = _runner(log, world, ["player", "vale", "rook"])
    runner.run("player", "I look around", channel="public")

    narration_events = [e for e in log._events if e.type == "narration"]
    assert len(narration_events) == 1
    assert set(narration_events[0].audience) == {"player", "vale", "rook", GM}
    assert narration_events[0].channel == "public"


def test_public_result_channel_is_public():
    log = _log()
    world = _world_with("player")
    runner = _runner(log, world, ["player"])
    result = runner.run("player", "I stand watch")
    assert result.channel == "public"


# --------------------------------------------------------------------------- #
# OOC: bypasses all fiction                                                     #
# --------------------------------------------------------------------------- #

def test_ooc_does_not_call_adjudicator_or_narrator():
    """Invariant 4: OOC must not trigger adjudication, narration, or clocks."""
    log = _log()
    world = _world_with("player", "vale")
    adj = _no_stakes_adjudicator()
    nar = _narrator()
    runner = _runner(log, world, ["player", "vale"], adjudicator=adj, narrator=nar)

    result = runner.run("player", "I need a bathroom break", channel="ooc")

    adj.evaluate.assert_not_called()
    nar.narrate.assert_not_called()
    assert result.channel == "ooc"
    assert result.had_stakes is False
    assert result.committed_fact_count == 0
    assert result.narration == ""


def test_ooc_emits_ooc_channel_event():
    log = _log()
    world = _world_with("player", "vale")
    runner = _runner(log, world, ["player", "vale"])

    runner.run("player", "Can we retcon that?", channel="ooc")

    ooc_events = [e for e in log._events if e.channel == "ooc"]
    assert len(ooc_events) == 1
    assert ooc_events[0].type == "ooc"
    assert ooc_events[0].content == "Can we retcon that?"


def test_ooc_does_not_emit_narration_event():
    log = _log()
    world = _world_with("player")
    runner = _runner(log, world, ["player"])
    runner.run("player", "OOC comment", channel="ooc")
    narration_events = [e for e in log._events if e.type == "narration"]
    assert len(narration_events) == 0


def test_ooc_does_not_tick_clocks():
    from unittest.mock import MagicMock
    from fable_table_engine.gm import WorldSimulator

    log = _log()
    world = _world_with("player")
    adj = _no_stakes_adjudicator()
    nar = _narrator()
    sim = MagicMock(spec=WorldSimulator)

    pipeline = CommitPipeline(log)
    assembler = ContextAssembler(log)
    rules = RulesEngine(log, MagicMock())
    runner = BeatRunner(
        log=log, world=world, pipeline=pipeline, rules=rules,
        assembler=assembler, adjudicator=adj, narrator=nar,
        sheets={"player": CharacterSheet(entity_id="player", concept="test")},
        gm_entity=GM, simulator=sim,
    )
    runner.run("player", "pause?", channel="ooc")
    sim.advance.assert_not_called()


# --------------------------------------------------------------------------- #
# Narrator context filtering (invariant 5)                                     #
# --------------------------------------------------------------------------- #

def test_public_narrator_context_excludes_prior_whisper():
    """Invariant 5: narrator context for a public beat must not include
    whisper events the actor received — those are private and not safe for
    all public recipients to read through the narration."""
    log = _log()
    world = _world_with("player", "vale", "rook")

    # First: emit a whisper to player that rook must not see
    log.append(
        author="vale",
        channel="whisper",
        type="dialogue",
        content="The vault code is 7-7-3.",
        audience=("player", "vale", GM),
        visibility="content",
    )

    # Capture what narrator receives as player_context
    captured_contexts: list[str] = []
    nar = MagicMock(spec=NarratorGM)
    def capture_narrate(**kwargs):
        captured_contexts.append(kwargs.get("player_context", ""))
        return "Nothing happens."
    nar.narrate.side_effect = capture_narrate

    runner = _runner(log, world, ["player", "vale", "rook"], narrator=nar)
    runner.run("player", "I look around", channel="public")

    assert len(captured_contexts) == 1
    assert "7-7-3" not in captured_contexts[0], (
        "vault code from a private whisper must not appear in narrator context "
        "for a public beat"
    )


def test_whisper_narrator_context_includes_actor_private_events():
    """For a whisper beat, the narrator may use the actor's full context
    since output goes only to actor + target + GM."""
    log = _log()
    world = _world_with("player", "vale", "rook")

    log.append(
        author="vale",
        channel="whisper",
        type="dialogue",
        content="Meet me at midnight.",
        audience=("player", "vale", GM),
        visibility="content",
    )

    captured_contexts: list[str] = []
    nar = MagicMock(spec=NarratorGM)
    def capture_narrate(**kwargs):
        captured_contexts.append(kwargs.get("player_context", ""))
        return "Player responds quietly."
    nar.narrate.side_effect = capture_narrate

    runner = _runner(log, world, ["player", "vale", "rook"], narrator=nar)
    runner.run("player", "I nod and whisper back", channel="whisper", target="vale")

    assert len(captured_contexts) == 1
    assert "midnight" in captured_contexts[0], (
        "narrator for a whisper beat should see the actor's prior private event"
    )


# --------------------------------------------------------------------------- #
# Invalid whisper target                                                        #
# --------------------------------------------------------------------------- #

def test_invalid_whisper_target_raises_before_adjudication():
    """Invariant 7: unknown target fails deterministically before any model call."""
    log = _log()
    world = _world_with("player", "vale")
    adj = _no_stakes_adjudicator()
    runner = _runner(log, world, ["player", "vale"], adjudicator=adj)

    with pytest.raises(ValueError, match="not a known entity"):
        runner.run("player", "I whisper to nobody", channel="whisper", target="ghost")

    adj.evaluate.assert_not_called()


def test_missing_whisper_target_raises():
    log = _log()
    world = _world_with("player", "vale")
    runner = _runner(log, world, ["player", "vale"])

    with pytest.raises(ValueError, match="requires a non-empty target"):
        runner.run("player", "I mutter something", channel="whisper", target=None)


# --------------------------------------------------------------------------- #
# run_with_agent: channel + target preserved from Proposal                      #
# --------------------------------------------------------------------------- #

def test_run_with_agent_whisper_preserves_scope():
    """Channel and target from the agent's Proposal must reach the narration event."""
    log = _log()
    world = _world_with("player", "vale", "rook")

    agent = MagicMock(spec=CharacterAgent)
    agent.entity_id = "vale"
    agent.propose.return_value = Proposal(
        agent="vale", intent="I slip player a note", channel="whisper", target="player"
    )

    runner = _runner(log, world, ["player", "vale", "rook"])
    result = runner.run_with_agent(agent)

    narration_events = [e for e in log._events if e.type == "narration"]
    assert len(narration_events) == 1
    ev = narration_events[0]
    assert ev.channel == "whisper"
    assert set(ev.audience) == {"vale", "player", GM}
    assert "rook" not in ev.audience
    assert result.channel == "whisper"


def test_run_with_agent_whisper_survives_queue_transit():
    """Channel and target survive ActionQueue enqueue→drain inside run_with_agent."""
    log = _log()
    world = _world_with("player", "vale", "rook")
    q = ActionQueue()

    agent = MagicMock(spec=CharacterAgent)
    agent.entity_id = "vale"
    agent.propose.return_value = Proposal(
        agent="vale", intent="I warn player quietly", channel="whisper", target="player"
    )

    runner = _runner(log, world, ["player", "vale", "rook"])
    result = runner.run_with_agent(agent, queue=q)

    narration_events = [e for e in log._events if e.type == "narration"]
    assert narration_events[0].channel == "whisper"
    assert "rook" not in narration_events[0].audience


# --------------------------------------------------------------------------- #
# run_round: player Proposal with whisper channel                               #
# --------------------------------------------------------------------------- #

def test_run_round_player_proposal_str_is_public():
    """A bare string in player_proposals is treated as a public action."""
    log = _log()
    world = _world_with("player", "vale")
    runner = _runner(log, world, ["player", "vale"])
    orch = Orchestrator(["player"])

    results = runner.run_round(
        orch, agents={},
        player_proposals={"player": "I look around"},
        present=["player"],
    )

    assert results[0].channel == "public"


def test_run_round_player_proposal_object_whisper():
    """A Proposal object in player_proposals preserves its channel and target."""
    log = _log()
    world = _world_with("player", "vale", "rook")
    runner = _runner(log, world, ["player", "vale", "rook"])
    orch = Orchestrator(["player"])

    whisper = Proposal(agent="player", intent="I pull vale aside", channel="whisper", target="vale")
    results = runner.run_round(
        orch, agents={},
        player_proposals={"player": whisper},
        present=["player"],
    )

    assert results[0].channel == "whisper"
    narration_events = [e for e in log._events if e.type == "narration"]
    assert "rook" not in narration_events[0].audience
