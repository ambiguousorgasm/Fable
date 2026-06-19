"""Phase 8 tests — Auditor (D-018, D-019, CORE §3).

All Anthropic client calls are mocked; no API key required.

What is verified:
  - AuditTier, AuditFlag, AuditResult basic behaviour.
  - Auditor.check_commitments: deterministic canon-contradiction detection.
  - Override passthrough bypasses all checks (D-008).
  - Auditor.check_narration: structural (empty prose) and semantic checks.
  - Semantic escalation rule (D-019): high-confidence + revealed canon → CRITICAL;
    low-confidence or hidden fact → ADVISORY.
  - NON_CRITICAL model failure: retry exhaustion degrades gracefully.
  - BeatRunner integration: pre-commit and post-narration hooks.
  - Beat abort on CRITICAL; advisory/warning flags do not abort.
  - Audit events carry gm-only audience — never in player belief stores.
  - BeatResult.audit_flags and BeatResult.beat_aborted are accurate.
"""

from __future__ import annotations

import random
from unittest.mock import MagicMock

import pytest

from fable_table_engine import (
    AdjudicatorGM,
    AuditFlag,
    AuditResult,
    AuditTier,
    Auditor,
    BeatResult,
    BeatRunner,
    CharacterSheet,
    CommitPipeline,
    Commitment,
    ContextAssembler,
    DiceService,
    Entity,
    EventLog,
    Fact,
    ModelGateway,
    NarratorGM,
    RulesEngine,
    WorldState,
)


# --------------------------------------------------------------------------- #
# Shared mock builders                                                          #
# --------------------------------------------------------------------------- #

def _make_tools_response(tool_input: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "adjudicate_action"
    block.input = tool_input
    response = MagicMock()
    response.content = [block]
    return response


def _make_text_response(text: str):
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _make_consistency_response(contradictions: list[dict]):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "report_consistency"
    block.input = {"contradictions": contradictions}
    response = MagicMock()
    response.content = [block]
    return response


def _make_fact(subject, predicate, value, *, revealed=True, via_override=False) -> Fact:
    return Fact(
        subject=subject, predicate=predicate, value=value,
        revealed=revealed, event_id="e-test", via_override=via_override,
    )


# --------------------------------------------------------------------------- #
# Shared BeatRunner setup                                                       #
# --------------------------------------------------------------------------- #

def _make_runner(adj_input: dict, narrator_text: str, auditor: Auditor | None = None):
    """Return (runner, log, pipeline, assembler)."""
    log = EventLog()
    world = WorldState()
    world.add_zone("tavern")
    world.add_entity(Entity(id="rook", kind="pc", name="Rook"))
    world.place("rook", "tavern")

    pipeline = CommitPipeline(log)
    dice = DiceService(log, rng=random.Random(42))
    rules = RulesEngine(log, dice)
    assembler = ContextAssembler(log)

    sheet = CharacterSheet(entity_id="rook", concept="Blade", skills={"fighting": 3})

    adj_client = MagicMock()
    adj_client.messages.create.return_value = _make_tools_response(adj_input)

    narrator_client = MagicMock()
    narrator_client.messages.create.return_value = _make_text_response(narrator_text)

    runner = BeatRunner(
        log=log, world=world, pipeline=pipeline,
        rules=rules, assembler=assembler,
        adjudicator=AdjudicatorGM(ModelGateway(adj_client)),
        narrator=NarratorGM(ModelGateway(narrator_client)),
        sheets={"rook": sheet},
        gm_entity="gm",
        auditor=auditor,
    )
    return runner, log, pipeline, assembler


# --------------------------------------------------------------------------- #
# AuditFlag and AuditResult                                                     #
# --------------------------------------------------------------------------- #

class TestAuditFlagAndResult:

    def test_audit_flag_stores_fields(self):
        flag = AuditFlag(tier=AuditTier.CRITICAL, category="canon_contradiction", description="x != y")
        assert flag.tier == AuditTier.CRITICAL
        assert flag.category == "canon_contradiction"
        assert flag.description == "x != y"

    def test_audit_result_any_blocking_true_on_critical(self):
        result = AuditResult(
            passed=False,
            flags=[AuditFlag(AuditTier.CRITICAL, "structural", "empty narration")],
        )
        assert result.any_blocking is True

    def test_audit_result_any_blocking_false_without_critical(self):
        result = AuditResult(
            passed=True,
            flags=[
                AuditFlag(AuditTier.ADVISORY, "semantic", "low confidence"),
                AuditFlag(AuditTier.NON_CRITICAL, "model_failure", "API error"),
            ],
        )
        assert result.any_blocking is False

    def test_audit_result_passed_reflects_no_flags(self):
        result = AuditResult(passed=True)
        assert result.any_blocking is False
        assert result.flags == []


# --------------------------------------------------------------------------- #
# Auditor.check_commitments — deterministic                                     #
# --------------------------------------------------------------------------- #

class TestAuditorCheckCommitments:

    def _auditor(self) -> Auditor:
        return Auditor(semantic=False)

    def _commitment(self, subject, predicate, value, *, revealed=True) -> Commitment:
        return Commitment(subject=subject, predicate=predicate, value=value, revealed=revealed)

    def test_empty_commitments_pass(self):
        result = self._auditor().check_commitments([], {})
        assert result.passed is True
        assert result.flags == []

    def test_clean_commitment_passes(self):
        canon = {("gate", "state"): _make_fact("gate", "state", "barred")}
        c = self._commitment("gate", "state", "barred")  # same value → no conflict
        result = self._auditor().check_commitments([c], canon)
        assert result.passed is True
        assert result.flags == []

    def test_new_subject_predicate_passes(self):
        canon = {("gate", "state"): _make_fact("gate", "state", "barred")}
        c = self._commitment("door", "state", "open")  # different key
        result = self._auditor().check_commitments([c], canon)
        assert result.passed is True

    def test_contradicting_revealed_fact_is_critical(self):
        canon = {("gate", "state"): _make_fact("gate", "state", "barred", revealed=True)}
        c = self._commitment("gate", "state", "open", revealed=True)
        result = self._auditor().check_commitments([c], canon)
        assert result.any_blocking is True
        assert result.flags[0].tier == AuditTier.CRITICAL
        assert result.flags[0].category == "canon_contradiction"

    def test_hidden_fact_contradiction_is_not_flagged(self):
        canon = {("gate", "state"): _make_fact("gate", "state", "barred", revealed=True)}
        # Commitment is hidden (revealed=False) — not yet canon boundary.
        c = self._commitment("gate", "state", "open", revealed=False)
        result = self._auditor().check_commitments([c], canon)
        assert result.passed is True
        assert result.flags == []

    def test_override_passthrough_bypasses_all_checks(self):
        canon = {("gate", "state"): _make_fact("gate", "state", "barred", revealed=True)}
        c = self._commitment("gate", "state", "open", revealed=True)
        result = self._auditor().check_commitments([c], canon, is_override=True)
        assert result.passed is True
        assert result.flags == []


# --------------------------------------------------------------------------- #
# Auditor.check_narration — structural                                          #
# --------------------------------------------------------------------------- #

class TestAuditorCheckNarrationStructural:

    def _auditor(self) -> Auditor:
        return Auditor(semantic=False)

    def test_non_empty_narration_passes(self):
        result = self._auditor().check_narration("You look around.", "rook", "I look around.", {})
        assert result.passed is True
        assert result.flags == []

    def test_empty_string_is_critical(self):
        result = self._auditor().check_narration("", "rook", "I look.", {})
        assert result.any_blocking is True
        assert result.flags[0].tier == AuditTier.CRITICAL
        assert result.flags[0].category == "structural"

    def test_whitespace_only_is_critical(self):
        result = self._auditor().check_narration("   \n\t  ", "rook", "I look.", {})
        assert result.any_blocking is True

    def test_no_model_call_when_semantic_false(self):
        client = MagicMock()
        auditor = Auditor(gateway=ModelGateway(client), semantic=False)
        canon = {("gate", "state"): _make_fact("gate", "state", "barred")}
        auditor.check_narration("The gate is open.", "rook", "I push the gate.", canon)
        client.messages.create.assert_not_called()

    def test_no_model_call_without_client(self):
        # semantic=True but no client → semantic disabled silently.
        auditor = Auditor(gateway=None, semantic=True)
        canon = {("gate", "state"): _make_fact("gate", "state", "barred")}
        result = auditor.check_narration("The gate is open.", "rook", "I push the gate.", canon)
        assert result.passed is True
        assert result.flags == []

    def test_no_semantic_call_on_empty_canon(self):
        client = MagicMock()
        auditor = Auditor(gateway=ModelGateway(client), semantic=True)
        # Empty canon → skip semantic check even if client present.
        result = auditor.check_narration("You step forward.", "rook", "I step.", {})
        client.messages.create.assert_not_called()
        assert result.passed is True


# --------------------------------------------------------------------------- #
# Auditor — semantic check                                                      #
# --------------------------------------------------------------------------- #

class TestAuditorSemantic:

    def test_high_confidence_revealed_contradiction_is_critical(self):
        client = MagicMock()
        client.messages.create.return_value = _make_consistency_response([{
            "subject": "gate", "predicate": "state",
            "committed_value": "barred", "narrated_value": "open",
            "confidence": 0.95,
        }])
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=0)
        canon = {("gate", "state"): _make_fact("gate", "state", "barred", revealed=True)}

        result = auditor.check_narration("The gate swings open.", "rook", "I push the gate.", canon)

        assert result.any_blocking is True
        critical = [f for f in result.flags if f.tier == AuditTier.CRITICAL]
        assert len(critical) == 1
        assert critical[0].category == "semantic"

    def test_low_confidence_contradiction_is_advisory(self):
        client = MagicMock()
        client.messages.create.return_value = _make_consistency_response([{
            "subject": "gate", "predicate": "state",
            "committed_value": "barred", "narrated_value": "open",
            "confidence": 0.6,
        }])
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=0)
        canon = {("gate", "state"): _make_fact("gate", "state", "barred", revealed=True)}

        result = auditor.check_narration("The gate swings open.", "rook", "I push the gate.", canon)

        assert result.any_blocking is False
        advisory = [f for f in result.flags if f.tier == AuditTier.ADVISORY]
        assert len(advisory) == 1

    def test_high_confidence_hidden_fact_is_advisory(self):
        client = MagicMock()
        client.messages.create.return_value = _make_consistency_response([{
            "subject": "gate", "predicate": "state",
            "committed_value": "barred", "narrated_value": "open",
            "confidence": 0.95,
        }])
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=0)
        # revealed=False → not yet canon boundary → stays ADVISORY even at high confidence.
        canon = {("gate", "state"): _make_fact("gate", "state", "barred", revealed=False)}

        result = auditor.check_narration("The gate swings open.", "rook", "I push the gate.", canon)

        assert result.any_blocking is False
        assert all(f.tier == AuditTier.ADVISORY for f in result.flags)

    def test_high_confidence_via_override_fact_is_advisory(self):
        client = MagicMock()
        client.messages.create.return_value = _make_consistency_response([{
            "subject": "gate", "predicate": "state",
            "committed_value": "barred", "narrated_value": "open",
            "confidence": 0.95,
        }])
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=0)
        # via_override=True means an override event already logged this transition (D-019).
        canon = {("gate", "state"): _make_fact("gate", "state", "barred", revealed=True, via_override=True)}

        result = auditor.check_narration("The gate swings open.", "rook", "I push the gate.", canon)

        assert result.any_blocking is False

    def test_no_contradictions_returns_no_flags(self):
        client = MagicMock()
        client.messages.create.return_value = _make_consistency_response([])
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=0)
        canon = {("gate", "state"): _make_fact("gate", "state", "barred")}

        result = auditor.check_narration("The barred gate holds firm.", "rook", "I push.", canon)

        assert result.passed is True
        assert result.flags == []

    def test_model_failure_returns_non_critical(self):
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("connection refused")
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=0)
        canon = {("gate", "state"): _make_fact("gate", "state", "barred")}

        result = auditor.check_narration("The gate swings open.", "rook", "I push.", canon)

        assert result.any_blocking is False
        non_critical = [f for f in result.flags if f.tier == AuditTier.NON_CRITICAL]
        assert len(non_critical) == 1
        assert "model_failure" == non_critical[0].category

    def test_model_failure_retries_configured_times(self):
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("flaky API")
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=2)
        canon = {("gate", "state"): _make_fact("gate", "state", "barred")}

        auditor.check_narration("The gate swings open.", "rook", "I push.", canon)

        # 1 initial attempt + 2 retries = 3 total calls.
        assert client.messages.create.call_count == 3

    def test_model_failure_does_not_block_beat(self):
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("API error")
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=0)
        canon = {("gate", "state"): _make_fact("gate", "state", "barred")}

        result = auditor.check_narration("The gate swings open.", "rook", "I push.", canon)

        # NON_CRITICAL does not block.
        assert result.passed is True
        assert result.any_blocking is False


# --------------------------------------------------------------------------- #
# BeatRunner integration                                                        #
# --------------------------------------------------------------------------- #

class TestBeatRunnerAudit:

    _NO_STAKES = {"has_stakes": False, "reasoning": "Trivial.", "declared_facts": []}

    def test_no_auditor_clean_beat(self):
        runner, log, pipeline, _ = _make_runner(
            self._NO_STAKES, "You glance around.",
        )
        result = runner.run("rook", "I look around.")
        assert result.beat_aborted is False
        assert result.narration_event_id != ""
        assert result.audit_flags == []

    def test_auditor_clean_beat_passes(self):
        runner, log, pipeline, _ = _make_runner(
            self._NO_STAKES, "You glance around.",
            auditor=Auditor(semantic=False),
        )
        result = runner.run("rook", "I look around.")
        assert result.beat_aborted is False
        assert result.narration_event_id != ""
        assert "narration" in {e.type for e in log.all()}

    def test_pre_commit_canon_contradiction_aborts_beat(self):
        runner, log, pipeline, _ = _make_runner(
            {
                "has_stakes": False,
                "reasoning": "Observes the gate.",
                "declared_facts": [
                    {"subject": "gate", "predicate": "state", "value": "open", "revealed": True}
                ],
            },
            "The gate stands open.",
            auditor=Auditor(semantic=False),
        )
        # Pre-seed canon with the contradicting value.
        pipeline.commit(
            author="gm", channel="system", content="gate is barred",
            audience=("rook", "gm"), visibility="content",
            commitments=[Commitment(subject="gate", predicate="state", value="barred", revealed=True)],
        )

        result = runner.run("rook", "I look at the gate.")

        assert result.beat_aborted is True
        assert result.narration_event_id == ""
        assert result.committed_fact_count == 0
        assert any(f.category == "canon_contradiction" for f in result.audit_flags)

    def test_aborted_beat_has_no_narration_event(self):
        runner, log, pipeline, _ = _make_runner(
            {
                "has_stakes": False,
                "reasoning": "...",
                "declared_facts": [
                    {"subject": "chest", "predicate": "locked", "value": False, "revealed": True}
                ],
            },
            "The chest clicks open.",
            auditor=Auditor(semantic=False),
        )
        pipeline.commit(
            author="gm", channel="system", content="chest is locked",
            audience=("rook", "gm"), visibility="content",
            commitments=[Commitment(subject="chest", predicate="locked", value=True, revealed=True)],
        )

        result = runner.run("rook", "I pick the lock.")

        event_types = [e.type for e in log.all()]
        assert "narration" not in event_types

    def test_audit_block_event_logged_to_gm_only(self):
        runner, log, pipeline, _ = _make_runner(
            {
                "has_stakes": False,
                "reasoning": "...",
                "declared_facts": [
                    {"subject": "gate", "predicate": "state", "value": "open", "revealed": True}
                ],
            },
            "The gate stands open.",
            auditor=Auditor(semantic=False),
        )
        pipeline.commit(
            author="gm", channel="system", content="gate is barred",
            audience=("rook", "gm"), visibility="content",
            commitments=[Commitment(subject="gate", predicate="state", value="barred", revealed=True)],
        )

        runner.run("rook", "I check the gate.")

        block_events = [e for e in log.all() if e.type == "audit_block"]
        assert len(block_events) == 1
        assert block_events[0].audience == ("gm",)

    def test_beat_aborted_false_on_clean_beat(self):
        runner, log, pipeline, _ = _make_runner(
            self._NO_STAKES, "Nothing happens.",
            auditor=Auditor(semantic=False),
        )
        result = runner.run("rook", "I wait.")
        assert result.beat_aborted is False

    def test_beat_result_carries_audit_flags(self):
        client = MagicMock()
        client.messages.create.return_value = _make_consistency_response([{
            "subject": "sword", "predicate": "sheathed",
            "committed_value": "true", "narrated_value": "false",
            "confidence": 0.5,
        }])
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=0)

        canon_commitment = Commitment(
            subject="sword", predicate="sheathed", value=True, revealed=True
        )
        runner, log, pipeline, _ = _make_runner(
            self._NO_STAKES, "You draw your blade.",
            auditor=auditor,
        )
        pipeline.commit(
            author="gm", channel="system", content="sword is sheathed",
            audience=("rook", "gm"), visibility="content",
            commitments=[canon_commitment],
        )

        result = runner.run("rook", "I watch the guard.")

        # Low-confidence semantic flag → advisory, beat not aborted.
        assert result.beat_aborted is False
        assert any(f.category == "semantic" for f in result.audit_flags)

    def test_advisory_flag_does_not_abort_beat(self):
        client = MagicMock()
        client.messages.create.return_value = _make_consistency_response([{
            "subject": "room", "predicate": "bright",
            "committed_value": "true", "narrated_value": "false",
            "confidence": 0.4,
        }])
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=0)

        runner, log, pipeline, _ = _make_runner(
            self._NO_STAKES, "The dim room presses around you.",
            auditor=auditor,
        )
        pipeline.commit(
            author="gm", channel="system", content="room is bright",
            audience=("rook", "gm"), visibility="content",
            commitments=[Commitment(subject="room", predicate="bright", value=True, revealed=True)],
        )

        result = runner.run("rook", "I look around.")

        assert result.beat_aborted is False
        assert result.narration_event_id != ""
        advisory_events = [e for e in log.all() if e.type == "audit_advisory"]
        assert len(advisory_events) == 1
        assert advisory_events[0].audience == ("gm",)

    def test_audit_events_never_in_player_belief_store(self):
        client = MagicMock()
        client.messages.create.return_value = _make_consistency_response([{
            "subject": "room", "predicate": "bright",
            "committed_value": "true", "narrated_value": "false",
            "confidence": 0.4,
        }])
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=0)

        runner, log, pipeline, assembler = _make_runner(
            self._NO_STAKES, "Shadows surround you.",
            auditor=auditor,
        )
        pipeline.commit(
            author="gm", channel="system", content="room is bright",
            audience=("rook", "gm"), visibility="content",
            commitments=[Commitment(subject="room", predicate="bright", value=True, revealed=True)],
        )
        runner.run("rook", "I look around.")

        player_store = assembler.belief_store("rook")
        player_types = {e.type for e in player_store.events}
        assert "audit_block" not in player_types
        assert "audit_advisory" not in player_types
        assert "audit_warning" not in player_types

    def test_post_narration_empty_prose_aborts_beat(self):
        runner, log, pipeline, _ = _make_runner(
            self._NO_STAKES, "",  # narrator returns empty string
            auditor=Auditor(semantic=False),
        )
        result = runner.run("rook", "I look around.")

        assert result.beat_aborted is True
        assert result.narration_event_id == ""
        assert "narration" not in {e.type for e in log.all()}
        assert any(f.category == "structural" for f in result.audit_flags)

    def test_non_critical_model_failure_does_not_abort_beat(self):
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("API flaky")
        auditor = Auditor(gateway=ModelGateway(client), semantic=True, max_retries=1)

        runner, log, pipeline, _ = _make_runner(
            self._NO_STAKES, "You look around the room.",
            auditor=auditor,
        )
        # Need some canon so the semantic check is actually attempted.
        pipeline.commit(
            author="gm", channel="system", content="torch lit",
            audience=("rook", "gm"), visibility="content",
            commitments=[Commitment(subject="torch", predicate="lit", value=True, revealed=True)],
        )

        result = runner.run("rook", "I look at the torch.")

        assert result.beat_aborted is False
        assert result.narration_event_id != ""
        warning_events = [e for e in log.all() if e.type == "audit_warning"]
        assert len(warning_events) == 1
        assert warning_events[0].audience == ("gm",)
        assert any(f.tier == AuditTier.NON_CRITICAL for f in result.audit_flags)
