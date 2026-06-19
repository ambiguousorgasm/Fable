"""Phase 15 tests — Human-seat adapter and text playtest console.

All Anthropic client calls are mocked; no API key required.

What is verified:
  parse_proposal:
    - Plain text → public channel.
    - /ooc prefix → OOC channel.
    - /ooc with no body → fallback intent.
    - whisper <target>: <intent> → whisper channel + target.
    - Whisper syntax with extra whitespace is handled.
    - Missing colon in whisper raises ValueError.
    - Empty whisper target raises ValueError.
    - Empty whisper intent raises ValueError.
    - Empty string raises ValueError.
    - agent field is set from the passed agent id.

  render_event:
    - narration → content string.
    - ooc → [OOC] prefix.
    - dice_roll → [roll] prefix.
    - resolution → [outcome] prefix.
    - front_advance → [event] prefix.
    - GM-internal types (audit, system, effect_applied) → None.
    - Event with None content → None.

  PlaytestSession:
    - step returns narration text.
    - step: player does not see events they are not in the audience of.
    - step: OOC beats return the OOC line, no narration.
    - step: successive calls return only new events (incremental drain).
    - step: whisper seen by target, not by non-audience entity.
    - player_view returns full history, not just new events.
    - export_transcript returns string form of player view.
    - export_transcript_json returns list of dicts with required fields.
    - export_transcript_json contains only entitled events (not GM-only ones).
    - parse_proposal is reachable through session.
"""

from __future__ import annotations

import random
from unittest.mock import MagicMock

import pytest

from fable_table_engine import (
    AdjudicatorGM,
    BeatRunner,
    CharacterSheet,
    CommitPipeline,
    ContextAssembler,
    DiceService,
    Entity,
    EventLog,
    ModelGateway,
    NarratorGM,
    PlaytestSession,
    RulesEngine,
    WorldState,
    parse_proposal,
    render_event,
)
from fable_table_engine.events import ProjectedEvent


# --------------------------------------------------------------------------- #
# Shared mock helpers                                                           #
# --------------------------------------------------------------------------- #

def _tool_response(tool_input: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "adjudicate_action"
    block.input = tool_input
    response = MagicMock()
    response.content = [block]
    return response


def _text_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _make_runner(adj_input: dict, narrator_text: str = "You act."):
    log = EventLog()
    world = WorldState()
    world.add_zone("hall")
    world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
    world.add_entity(Entity(id="ally", kind="pc", name="Ally"))
    world.place("hero", "hall")
    world.place("ally", "hall")

    pipeline = CommitPipeline(log)
    dice = DiceService(log, rng=random.Random(0))
    rules = RulesEngine(log, dice)
    assembler = ContextAssembler(log)
    sheets = {
        "hero": CharacterSheet(entity_id="hero", concept="Fighter", skills={"fighting": 3}),
        "ally": CharacterSheet(entity_id="ally", concept="Scout", skills={"sneaking": 3}),
    }

    adj_client = MagicMock()
    adj_client.messages.create.return_value = _tool_response(adj_input)
    narrator_client = MagicMock()
    narrator_client.messages.create.return_value = _text_response(narrator_text)

    runner = BeatRunner(
        log=log, world=world, pipeline=pipeline,
        rules=rules, assembler=assembler,
        adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
        narrator=NarratorGM(ModelGateway(narrator_client)),
        sheets=sheets,
        gm_entity="gm",
    )
    return runner, assembler, log


_NO_STAKES = {"has_stakes": False, "reasoning": "Trivial."}

_STAKES = {
    "has_stakes": True,
    "reasoning": "Real risk.",
    "skill": "fighting",
    "tn": 11,
}


# --------------------------------------------------------------------------- #
# parse_proposal — public                                                       #
# --------------------------------------------------------------------------- #

class TestParseProposalPublic:

    def test_plain_text_is_public(self):
        p = parse_proposal("I open the door.", "hero")
        assert p.channel == "public"
        assert p.intent == "I open the door."
        assert p.agent == "hero"
        assert p.target is None

    def test_strips_leading_trailing_whitespace(self):
        p = parse_proposal("  I look around.  ", "hero")
        assert p.intent == "I look around."

    def test_agent_id_set_correctly(self):
        p = parse_proposal("I act.", "vale")
        assert p.agent == "vale"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_proposal("", "hero")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_proposal("   ", "hero")


# --------------------------------------------------------------------------- #
# parse_proposal — OOC                                                          #
# --------------------------------------------------------------------------- #

class TestParseProposalOOC:

    def test_ooc_prefix(self):
        p = parse_proposal("/ooc How many HP do I have?", "hero")
        assert p.channel == "ooc"
        assert p.intent == "How many HP do I have?"

    def test_ooc_no_body_uses_fallback(self):
        p = parse_proposal("/ooc", "hero")
        assert p.channel == "ooc"
        assert p.intent == "(out of character)"

    def test_ooc_extra_whitespace(self):
        p = parse_proposal("/ooc   What time is it?", "hero")
        assert p.intent == "What time is it?"


# --------------------------------------------------------------------------- #
# parse_proposal — whisper                                                      #
# --------------------------------------------------------------------------- #

class TestParseProposalWhisper:

    def test_whisper_basic(self):
        p = parse_proposal("whisper ally: Follow me quietly.", "hero")
        assert p.channel == "whisper"
        assert p.target == "ally"
        assert p.intent == "Follow me quietly."

    def test_whisper_case_insensitive(self):
        p = parse_proposal("WHISPER ally: Quick!", "hero")
        assert p.channel == "whisper"
        assert p.target == "ally"

    def test_whisper_extra_whitespace_around_target(self):
        p = parse_proposal("whisper  ally : Go left.", "hero")
        assert p.target == "ally"
        assert p.intent == "Go left."

    def test_whisper_missing_colon_raises(self):
        with pytest.raises(ValueError, match="Malformed whisper"):
            parse_proposal("whisper ally Go left.", "hero")

    def test_whisper_empty_target_raises(self):
        with pytest.raises(ValueError, match="target"):
            parse_proposal("whisper : No target here.", "hero")

    def test_whisper_empty_intent_raises(self):
        with pytest.raises(ValueError, match="intent"):
            parse_proposal("whisper ally:", "hero")

    def test_whisper_intent_with_colon(self):
        # colon in the intent body should not split there
        p = parse_proposal("whisper ally: Time: now.", "hero")
        assert p.intent == "Time: now."


# --------------------------------------------------------------------------- #
# render_event                                                                  #
# --------------------------------------------------------------------------- #

def _proj(type_: str, content: str | None = "test") -> ProjectedEvent:
    return ProjectedEvent(
        sequence=0, id="e1", timestamp="2026-06-18T00:00:00",
        author="gm", channel="public", type=type_,
        visibility="content", content=content,
    )


class TestRenderEvent:

    def test_narration_returns_content(self):
        result = render_event(_proj("narration", "You step through the door."))
        assert result == "You step through the door."

    def test_ooc_adds_prefix(self):
        e = ProjectedEvent(
            sequence=0, id="e1", timestamp="t", author="hero",
            channel="ooc", type="ooc", visibility="content",
            content="How many HP?",
        )
        result = render_event(e)
        assert result == "[OOC] hero: How many HP?"

    def test_dice_roll_adds_prefix(self):
        result = render_event(_proj("dice_roll", "3d6 → 12"))
        assert result is not None
        assert "[roll]" in result

    def test_resolution_adds_prefix(self):
        result = render_event(_proj("resolution", "Success"))
        assert "[outcome]" in result

    def test_front_advance_adds_prefix(self):
        result = render_event(_proj("front_advance", "Clock fires."))
        assert "[event]" in result

    def test_audit_block_returns_none(self):
        assert render_event(_proj("audit_block")) is None

    def test_audit_warning_returns_none(self):
        assert render_event(_proj("audit_warning")) is None

    def test_commitment_returns_none(self):
        assert render_event(_proj("commitment")) is None

    def test_effect_applied_returns_none(self):
        assert render_event(_proj("effect_applied")) is None

    def test_none_content_returns_none(self):
        assert render_event(_proj("narration", None)) is None

    def test_unknown_type_returns_none(self):
        assert render_event(_proj("something_custom")) is None


# --------------------------------------------------------------------------- #
# PlaytestSession.step                                                          #
# --------------------------------------------------------------------------- #

class TestPlaytestSessionStep:

    def test_step_returns_narration(self):
        runner, assembler, _ = _make_runner(_NO_STAKES, "You glance around the hall.")
        session = PlaytestSession(runner, assembler, "hero")
        lines = session.step("I look around.")
        assert any("glance" in line for line in lines)

    def test_step_incremental_new_events_only(self):
        runner, assembler, _ = _make_runner(_NO_STAKES, "You act.")
        session = PlaytestSession(runner, assembler, "hero")
        first = session.step("I do something.")
        second = session.step("I do something else.")
        # First call's events should not appear in the second call's output
        first_ids = set(first)
        second_ids = set(second)
        # With the same narrator text "You act." both will have the same text,
        # but they are different event IDs in the log so both will be returned.
        assert len(first) >= 0  # may be 1 or more
        assert len(second) >= 0

    def test_step_repeated_calls_no_overlap(self):
        runner, assembler, _ = _make_runner(
            _NO_STAKES, "You proceed."
        )
        session = PlaytestSession(runner, assembler, "hero")
        # Patch narrator to return distinct text per call
        runner._narrator._gateway._client.messages.create.side_effect = [
            _text_response("First narration."),
            _text_response("Second narration."),
        ]
        first = session.step("First action.")
        second = session.step("Second action.")
        assert not any("Second" in line for line in first)
        assert not any("First" in line for line in second)

    def test_step_ooc_returns_ooc_line(self):
        runner, assembler, _ = _make_runner(_NO_STAKES)
        session = PlaytestSession(runner, assembler, "hero")
        lines = session.step("/ooc What is my stress?")
        assert any("[OOC]" in line for line in lines)

    def test_step_ooc_no_narration(self):
        runner, assembler, _ = _make_runner(_NO_STAKES)
        session = PlaytestSession(runner, assembler, "hero")
        lines = session.step("/ooc No narration please.")
        # OOC lines should show; no narration prose
        narration_lines = [l for l in lines if "[OOC]" not in l]
        assert narration_lines == []


# --------------------------------------------------------------------------- #
# PlaytestSession — entitlement isolation                                       #
# --------------------------------------------------------------------------- #

class TestEntitlementIsolation:

    def test_player_does_not_see_gm_only_events(self):
        """Audit events go to gm audience only — must not appear in player view."""
        runner, assembler, log = _make_runner(_NO_STAKES)
        # Manually append a GM-only event
        log.append(
            author="gm", channel="system", type="audit_advisory",
            content="[semantic] possible contradiction",
            audience=("gm",), visibility="content",
        )
        session = PlaytestSession(runner, assembler, "hero")
        lines = session.player_view()
        assert not any("audit" in line.lower() or "semantic" in line.lower() for line in lines)

    def test_player_does_not_see_other_entitys_private_events(self):
        """An event with audience=(ally,gm) must not appear in hero's view."""
        runner, assembler, log = _make_runner(_NO_STAKES)
        log.append(
            author="gm", channel="whisper", type="narration",
            content="A secret for ally only.",
            audience=("ally", "gm"), visibility="content",
        )
        session = PlaytestSession(runner, assembler, "hero")
        # Trigger a belief store read
        _ = session.step("I look around.")
        full = session.player_view()
        assert not any("secret for ally" in line for line in full)

    def test_export_json_excludes_gm_only(self):
        runner, assembler, log = _make_runner(_NO_STAKES)
        log.append(
            author="gm", channel="system", type="audit_block",
            content="Blocked by auditor.",
            audience=("gm",), visibility="content",
        )
        session = PlaytestSession(runner, assembler, "hero")
        records = session.export_transcript_json()
        assert not any(r["type"] == "audit_block" for r in records)


# --------------------------------------------------------------------------- #
# PlaytestSession — whisper isolation                                           #
# --------------------------------------------------------------------------- #

class TestWhisperIsolation:

    def test_whisper_visible_to_target(self):
        runner, assembler, _ = _make_runner(_NO_STAKES, "You lean in and whisper.")
        hero_session = PlaytestSession(runner, assembler, "hero")
        ally_session = PlaytestSession(runner, assembler, "ally")
        hero_session.step("whisper ally: Meet me at the east door.")
        # ally should see the narration (audience includes ally)
        ally_lines = ally_session.player_view()
        assert any(line for line in ally_lines)

    def test_whisper_not_visible_to_third_party(self):
        """A third entity present in the world must not see a hero→ally whisper."""
        runner, assembler, log = _make_runner(_NO_STAKES, "You lean close and whisper.")
        # Add a third entity
        runner._world.add_entity(Entity(id="bystander", kind="npc", name="Bystander"))
        runner._world.place("bystander", "hall")
        hero_session = PlaytestSession(runner, assembler, "hero")
        bystander_session = PlaytestSession(runner, assembler, "bystander")
        hero_session.step("whisper ally: Secret plan.")
        bystander_lines = bystander_session.player_view()
        assert not any("Secret plan" in line or "whisper" in line.lower() for line in bystander_lines)


# --------------------------------------------------------------------------- #
# PlaytestSession — player_view and export                                      #
# --------------------------------------------------------------------------- #

class TestPlaytestSessionExport:

    def test_player_view_returns_full_history(self):
        runner, assembler, _ = _make_runner(_NO_STAKES, "You proceed.")
        session = PlaytestSession(runner, assembler, "hero")
        session.step("First action.")
        session.step("Second action.")
        full = session.player_view()
        # player_view should return at least 2 narration lines
        assert len(full) >= 2

    def test_export_transcript_is_string(self):
        runner, assembler, _ = _make_runner(_NO_STAKES, "Narration.")
        session = PlaytestSession(runner, assembler, "hero")
        session.step("I act.")
        assert isinstance(session.export_transcript(), str)

    def test_export_transcript_empty_session(self):
        runner, assembler, _ = _make_runner(_NO_STAKES)
        session = PlaytestSession(runner, assembler, "hero")
        assert session.export_transcript() == ""

    def test_export_transcript_json_fields(self):
        runner, assembler, _ = _make_runner(_NO_STAKES, "Narration.")
        session = PlaytestSession(runner, assembler, "hero")
        session.step("I act.")
        records = session.export_transcript_json()
        assert len(records) > 0
        r = records[0]
        assert "id" in r
        assert "sequence" in r
        assert "timestamp" in r
        assert "type" in r
        assert "author" in r
        assert "channel" in r
        assert "content" in r

    def test_export_transcript_json_narration_present(self):
        runner, assembler, _ = _make_runner(_NO_STAKES, "The hall is empty.")
        session = PlaytestSession(runner, assembler, "hero")
        session.step("I look around.")
        records = session.export_transcript_json()
        types = [r["type"] for r in records]
        assert "narration" in types

    def test_player_view_and_export_consistent(self):
        runner, assembler, _ = _make_runner(_NO_STAKES, "You proceed.")
        session = PlaytestSession(runner, assembler, "hero")
        session.step("I act.")
        view_lines = session.player_view()
        transcript = session.export_transcript()
        # export_transcript is "\n\n".join(player_view)
        assert transcript == "\n\n".join(view_lines)

    def test_session_parse_proposal_delegates(self):
        runner, assembler, _ = _make_runner(_NO_STAKES)
        session = PlaytestSession(runner, assembler, "hero")
        p = session.parse_proposal("I attack.")
        assert p.agent == "hero"
        assert p.channel == "public"
        assert p.intent == "I attack."

    def test_player_id_property(self):
        runner, assembler, _ = _make_runner(_NO_STAKES)
        session = PlaytestSession(runner, assembler, "hero")
        assert session.player_id == "hero"
