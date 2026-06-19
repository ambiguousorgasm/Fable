"""Phase 6 tests — character agents (CORE §4.1; D-015 groundwork).

All tests mock the Anthropic client. Key invariants verified:

  1. CharacterAgent reads ONLY its own filtered belief store.
  2. hidden_agenda appears in the system prompt only — never in the user
     message that could leak to other agents.
  3. Two agents with different audience memberships receive different contexts
     (differential knowledge).
  4. Proposal is correctly structured; channel/target validation holds.
  5. Whisper proposals carry a target.
  6. Proposal is seat-agnostic: constructed directly without an agent.
  7. PersonaSpec and Proposal validation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fable_table_engine import (
    CharacterAgent,
    CharacterSheet,
    Commitment,
    ContextAssembler,
    Entity,
    EventLog,
    ModelGateway,
    PersonaSpec,
    Proposal,
    WorldState,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _tool_response(tool_input: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "propose_action"
    block.input = tool_input
    resp = MagicMock()
    resp.content = [block]
    return resp


def _make_agent(persona: PersonaSpec, tool_input: dict) -> tuple[CharacterAgent, MagicMock]:
    sheet = CharacterSheet(entity_id=persona.entity_id, concept=persona.concept,
                           skills={"fighting": 2})
    client = MagicMock()
    client.messages.create.return_value = _tool_response(tool_input)
    return CharacterAgent(persona, sheet, ModelGateway(client)), client


def _basic_persona(entity_id: str = "vale", name: str = "Vale") -> PersonaSpec:
    return PersonaSpec(
        entity_id=entity_id,
        name=name,
        concept="Field surgeon, reluctant soldier",
        voice="Precise, clipped. Uses medical jargon when stressed.",
        values=["preserve life", "keep promises"],
        public_goals=["get the party out alive"],
        hidden_agenda="Secretly working to expose the commander as a war criminal.",
        relationships={"rook": "Trusts her blades more than her judgment."},
    )


def _basic_log_with_shared_and_private() -> tuple[EventLog, str, str]:
    """Return (log, shared_event_id, private_event_id).

    shared: audience=[vale, rook, gm]   — both agents see it
    private: audience=[vale, gm]        — only vale sees it
    """
    log = EventLog()
    shared = log.append(
        author="gm", channel="public", type="narration",
        content="The innkeeper slides a mug across the bar.",
        audience=("vale", "rook", "gm"), visibility="content",
    )
    private = log.append(
        author="gm", channel="whisper", type="narration",
        content="The innkeeper slips Vale a folded note.",
        audience=("vale", "gm"), visibility="content",
    )
    return log, shared.id, private.id


# --------------------------------------------------------------------------- #
# PersonaSpec                                                                   #
# --------------------------------------------------------------------------- #

class TestPersonaSpec:

    def test_basic_construction(self):
        p = _basic_persona()
        assert p.entity_id == "vale"
        assert p.hidden_agenda != ""

    def test_empty_entity_id_rejected(self):
        with pytest.raises(ValueError):
            PersonaSpec(entity_id="", name="Vale", concept="x", voice="x")

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            PersonaSpec(entity_id="vale", name="", concept="x", voice="x")

    def test_optional_fields_default(self):
        p = PersonaSpec(entity_id="x", name="X", concept="c", voice="v")
        assert p.values == []
        assert p.public_goals == []
        assert p.hidden_agenda == ""
        assert p.relationships == {}


# --------------------------------------------------------------------------- #
# Proposal                                                                      #
# --------------------------------------------------------------------------- #

class TestProposal:

    def test_public_proposal(self):
        p = Proposal(agent="vale", intent="I check the patient's wound.", channel="public")
        assert p.target is None

    def test_whisper_requires_target(self):
        with pytest.raises(ValueError, match="target"):
            Proposal(agent="vale", intent="whisper something", channel="whisper")

    def test_whisper_with_target(self):
        p = Proposal(agent="vale", intent="I signal rook.", channel="whisper", target="rook")
        assert p.target == "rook"

    def test_empty_intent_rejected(self):
        with pytest.raises(ValueError):
            Proposal(agent="vale", intent="", channel="public")

    def test_unknown_channel_rejected(self):
        with pytest.raises(ValueError):
            Proposal(agent="vale", intent="do thing", channel="magic")

    def test_seat_agnostic_construction(self):
        # Proposal can be built without any agent — it is just data.
        p = Proposal(agent="human-player", intent="I climb the wall.", channel="public")
        assert p.agent == "human-player"


# --------------------------------------------------------------------------- #
# CharacterAgent construction                                                   #
# --------------------------------------------------------------------------- #

class TestCharacterAgentConstruction:

    def test_entity_id_mismatch_rejected(self):
        persona = _basic_persona("vale")
        sheet = CharacterSheet(entity_id="rook", concept="x")
        client = MagicMock()
        with pytest.raises(ValueError, match="entity_id"):
            CharacterAgent(persona, sheet, ModelGateway(client))

    def test_entity_id_property(self):
        agent, _ = _make_agent(_basic_persona(), {"intent": "x", "channel": "public", "reasoning": "r"})
        assert agent.entity_id == "vale"

    def test_persona_and_sheet_properties(self):
        persona = _basic_persona()
        agent, _ = _make_agent(persona, {"intent": "x", "channel": "public", "reasoning": "r"})
        assert agent.persona is persona
        assert agent.sheet.entity_id == "vale"


# --------------------------------------------------------------------------- #
# CharacterAgent.propose — basic behaviour                                     #
# --------------------------------------------------------------------------- #

class TestCharacterAgentPropose:

    def test_returns_proposal(self):
        agent, _ = _make_agent(
            _basic_persona(),
            {"intent": "I tend to the wounded guard.", "channel": "public", "reasoning": "duty"},
        )
        log = EventLog()
        assembler = ContextAssembler(log)
        result = agent.propose(assembler)
        assert isinstance(result, Proposal)
        assert result.agent == "vale"
        assert result.intent == "I tend to the wounded guard."

    def test_whisper_proposal(self):
        agent, _ = _make_agent(
            _basic_persona(),
            {"intent": "signal rook", "dialogue": "Get ready.", "channel": "whisper",
             "target": "rook", "reasoning": "keep it quiet"},
        )
        log = EventLog()
        assembler = ContextAssembler(log)
        result = agent.propose(assembler)
        assert result.channel == "whisper"
        assert result.target == "rook"
        assert result.dialogue == "Get ready."

    def test_missing_tool_call_raises(self):
        persona = _basic_persona()
        sheet = CharacterSheet(entity_id="vale", concept="c")
        client = MagicMock()
        resp = MagicMock()
        resp.content = []
        client.messages.create.return_value = resp
        agent = CharacterAgent(persona, sheet, ModelGateway(client))
        with pytest.raises(RuntimeError, match="propose_action"):
            agent.propose(ContextAssembler(EventLog()))


# --------------------------------------------------------------------------- #
# Information boundary — hidden agenda                                          #
# --------------------------------------------------------------------------- #

class TestHiddenAgendaBoundary:

    def test_hidden_agenda_in_system_prompt_only(self):
        """hidden_agenda must appear in the system prompt, never in user content."""
        agent, client = _make_agent(
            _basic_persona(),
            {"intent": "Watch the exits.", "channel": "public", "reasoning": "r"},
        )
        agent.propose(ContextAssembler(EventLog()))
        call = client.messages.create.call_args
        kwargs = call[1] if call[1] else {}

        system_prompt: str = kwargs.get("system", "")
        messages: list = kwargs.get("messages", [])
        user_content = next((m["content"] for m in messages if m["role"] == "user"), "")

        assert "war criminal" in system_prompt
        assert "war criminal" not in user_content

    def test_relationships_in_user_message(self):
        """Relationships (non-secret) should appear in the user message context."""
        agent, client = _make_agent(
            _basic_persona(),
            {"intent": "act", "channel": "public", "reasoning": "r"},
        )
        agent.propose(ContextAssembler(EventLog()))
        call = client.messages.create.call_args
        kwargs = call[1] if call[1] else {}
        messages = kwargs.get("messages", [])
        user_content = next((m["content"] for m in messages if m["role"] == "user"), "")
        assert "rook" in user_content


# --------------------------------------------------------------------------- #
# Differential knowledge                                                        #
# --------------------------------------------------------------------------- #

class TestDifferentialKnowledge:

    def test_two_agents_see_different_events(self):
        """Vale sees the private note; Rook does not."""
        log, shared_id, private_id = _basic_log_with_shared_and_private()
        assembler = ContextAssembler(log)

        vale_store = assembler.belief_store("vale")
        rook_store = assembler.belief_store("rook")

        vale_ids = {e.id for e in vale_store.events}
        rook_ids = {e.id for e in rook_store.events}

        assert shared_id in vale_ids
        assert shared_id in rook_ids       # both see the shared event
        assert private_id in vale_ids      # vale sees the private note
        assert private_id not in rook_ids  # rook does not

    def test_agent_propose_context_reflects_private_knowledge(self):
        """Vale's user message contains the private note content; Rook's does not."""
        log, _, private_id = _basic_log_with_shared_and_private()

        def _run_propose(entity_id: str, name: str) -> str:
            persona = PersonaSpec(entity_id=entity_id, name=name, concept="c", voice="v")
            sheet = CharacterSheet(entity_id=entity_id, concept="c")
            client = MagicMock()
            client.messages.create.return_value = _tool_response(
                {"intent": "act", "channel": "public", "reasoning": "r"}
            )
            agent = CharacterAgent(persona, sheet, ModelGateway(client))
            agent.propose(ContextAssembler(log))
            call = client.messages.create.call_args
            kwargs = call[1] if call[1] else {}
            messages = kwargs.get("messages", [])
            return next((m["content"] for m in messages if m["role"] == "user"), "")

        vale_context = _run_propose("vale", "Vale")
        rook_context = _run_propose("rook", "Rook")

        assert "folded note" in vale_context   # private event content present for vale
        assert "folded note" not in rook_context  # absent from rook's view

    def test_committed_facts_visible_only_to_audience(self):
        """A revealed fact committed on an event only vale witnessed is in vale's beliefs."""
        log = EventLog()
        from fable_table_engine import CommitPipeline, Commitment
        pipeline = CommitPipeline(log)
        pipeline.commit(
            author="gm", channel="whisper",
            content="The note identifies the spy.",
            audience=("vale", "gm"),
            visibility="content",
            commitments=[Commitment(subject="spy", predicate="identity",
                                    value="commander-harwick", revealed=True)],
        )
        assembler = ContextAssembler(log)
        vale_store = assembler.belief_store("vale")
        rook_store = assembler.belief_store("rook")

        assert ("spy", "identity") in vale_store.beliefs
        assert ("spy", "identity") not in rook_store.beliefs
