"""Phase 21 deliverable 7: D-028 knowledge transfer enforcement.

Knowledge transferred via share_briefing or object_shown enters the receiver's
belief store as epistemic_type="claim", never "fact". The engine enforces this
at the event level; the client never transfers facts between views.
"""
from __future__ import annotations

import pytest

from fable_table_engine import (
    TRANSFER_TYPES,
    EventLog,
)
from fable_table_engine.context import ContextAssembler
from fable_table_engine.events import Commitment, Event, ProjectedEvent


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _claim(subject: str = "guard", predicate: str = "left", value: str = "back_door") -> Commitment:
    return Commitment(subject=subject, predicate=predicate, value=value, epistemic_type="claim")


def _fact(subject: str = "door", predicate: str = "colour", value: str = "red") -> Commitment:
    return Commitment(subject=subject, predicate=predicate, value=value, epistemic_type="fact")


# --------------------------------------------------------------------------- #
# TRANSFER_TYPES constant                                                        #
# --------------------------------------------------------------------------- #

class TestTransferTypes:

    def test_contains_share_briefing(self):
        assert "share_briefing" in TRANSFER_TYPES

    def test_contains_object_shown(self):
        assert "object_shown" in TRANSFER_TYPES

    def test_is_frozenset(self):
        assert isinstance(TRANSFER_TYPES, frozenset)

    def test_has_exactly_two_members(self):
        assert len(TRANSFER_TYPES) == 2


# --------------------------------------------------------------------------- #
# Event validation — no "fact" commitments on transfer events                   #
# --------------------------------------------------------------------------- #

class TestTransferEventValidation:

    def _base_kwargs(self, type_: str, commitments: tuple[Commitment, ...] = ()) -> dict:
        return dict(
            sequence=0, id="e1", timestamp="2026-06-19T00:00:00",
            author="mira", channel="public",
            audience=("hero", "mira", "gm"),
            visibility="content",
            type=type_,
            content="Mira tells the group what she saw.",
            commitments=commitments,
        )

    def test_share_briefing_with_claim_accepted(self):
        e = Event(**self._base_kwargs("share_briefing", (_claim(),)))
        assert e.type == "share_briefing"

    def test_object_shown_with_claim_accepted(self):
        e = Event(**self._base_kwargs("object_shown", (_claim(),)))
        assert e.type == "object_shown"

    def test_share_briefing_with_no_commitments_accepted(self):
        e = Event(**self._base_kwargs("share_briefing"))
        assert e.commitments == ()

    def test_object_shown_with_no_commitments_accepted(self):
        e = Event(**self._base_kwargs("object_shown"))
        assert e.commitments == ()

    def test_share_briefing_with_fact_raises(self):
        with pytest.raises(ValueError, match="D-028"):
            Event(**self._base_kwargs("share_briefing", (_fact(),)))

    def test_object_shown_with_fact_raises(self):
        with pytest.raises(ValueError, match="D-028"):
            Event(**self._base_kwargs("object_shown", (_fact(),)))

    def test_share_briefing_with_theory_accepted(self):
        c = Commitment(subject="captain", predicate="motive", value="greed", epistemic_type="theory")
        e = Event(**self._base_kwargs("share_briefing", (c,)))
        assert e.commitments[0].epistemic_type == "theory"

    def test_share_briefing_with_observation_accepted(self):
        c = Commitment(
            subject="guard", predicate="exit_direction", value="back",
            epistemic_type="observation",
        )
        e = Event(**self._base_kwargs("share_briefing", (c,)))
        assert e.commitments[0].epistemic_type == "observation"

    def test_fact_commitment_on_non_transfer_type_still_accepted(self):
        """Narration events can carry fact commitments without restriction."""
        e = Event(
            sequence=0, id="e2", timestamp="2026-06-19T00:00:00",
            author="gm", channel="public",
            audience=("hero", "gm"),
            visibility="content",
            type="narration",
            content="The door is red.",
            commitments=(_fact(),),
        )
        assert e.commitments[0].epistemic_type == "fact"

    def test_error_message_names_the_type(self):
        with pytest.raises(ValueError, match="share_briefing"):
            Event(**self._base_kwargs("share_briefing", (_fact(),)))

    def test_mixed_fact_and_claim_raises(self):
        """Even one fact commitment in a batch is enough to reject the event."""
        with pytest.raises(ValueError, match="D-028"):
            Event(**self._base_kwargs("share_briefing", (_fact(), _claim())))


# --------------------------------------------------------------------------- #
# EventLog round-trip                                                           #
# --------------------------------------------------------------------------- #

class TestTransferEventLog:

    def test_share_briefing_appended_to_log(self):
        log = EventLog()
        e = log.append(
            author="mira", channel="public", type="share_briefing",
            content="I saw the guard leave through the back.",
            audience=("hero", "mira", "gm"),
            commitments=(_claim(),),
        )
        assert e.type == "share_briefing"
        assert e.commitments[0].epistemic_type == "claim"

    def test_object_shown_appended_to_log(self):
        log = EventLog()
        e = log.append(
            author="hero", channel="public", type="object_shown",
            content="Hero shows the coded letter.",
            audience=("mira", "hero", "gm"),
            commitments=(_claim("letter", "sender", "unknown_faction"),),
        )
        assert e.type == "object_shown"

    def test_share_briefing_with_fact_rejected_at_append(self):
        log = EventLog()
        with pytest.raises(ValueError, match="D-028"):
            log.append(
                author="mira", channel="public", type="share_briefing",
                content="The door is red.",
                audience=("hero", "mira", "gm"),
                commitments=(_fact(),),
            )


# --------------------------------------------------------------------------- #
# Belief store — transferred knowledge enters as claims, not facts              #
# --------------------------------------------------------------------------- #

class TestKnowledgeTransferBeliefStore:

    def _setup_log(self) -> EventLog:
        log = EventLog()
        log.append(
            author="mira", channel="public", type="share_briefing",
            content="I saw the guard leave through the back door.",
            audience=("hero", "mira", "gm"),
            commitments=(
                Commitment(
                    subject="guard", predicate="exit_direction", value="back",
                    epistemic_type="claim",
                    asserting_entity="mira",
                ),
            ),
        )
        return log

    def test_hero_sees_transfer_event(self):
        log = self._setup_log()
        proj = log.project_for("hero")
        assert len(proj) == 1
        assert proj[0].type == "share_briefing"

    def test_transferred_claim_in_belief_store_claims(self):
        log = self._setup_log()
        assembler = ContextAssembler(log)
        store = assembler.belief_store("hero")
        assert len(store.claims) == 1
        assert store.claims[0].subject == "guard"
        assert store.claims[0].predicate == "exit_direction"

    def test_transferred_claim_not_in_beliefs(self):
        """Transferred knowledge never enters the facts dict."""
        log = self._setup_log()
        assembler = ContextAssembler(log)
        store = assembler.belief_store("hero")
        assert not store.believes("guard", "exit_direction")

    def test_transferred_claim_value_of_returns_none(self):
        """value_of() operates on facts only — claims are not facts."""
        log = self._setup_log()
        assembler = ContextAssembler(log)
        store = assembler.belief_store("hero")
        assert store.value_of("guard", "exit_direction") is None

    def test_gm_also_sees_transfer(self):
        log = self._setup_log()
        proj = log.project_for("gm")
        assert any(e.type == "share_briefing" for e in proj)

    def test_non_audience_entity_excluded(self):
        """An entity not in the audience sees nothing."""
        log = self._setup_log()
        proj = log.project_for("outsider")
        assert proj == ()

    def test_mira_sees_her_own_briefing(self):
        log = self._setup_log()
        proj = log.project_for("mira")
        assert any(e.type == "share_briefing" for e in proj)

    def test_fact_plus_share_briefing_doesnt_merge(self):
        """An engine-confirmed fact and a share_briefing about the same key
        coexist. The fact stays in beliefs; the briefing's claim stays in claims.
        The client never auto-promotes the claim to fact based on the briefing."""
        log = EventLog()
        log.append(
            author="gm", channel="public", type="narration",
            content="The door is confirmed red.",
            audience=("hero", "gm"),
            commitments=(
                Commitment(subject="door", predicate="colour", value="red", epistemic_type="fact"),
            ),
        )
        log.append(
            author="mira", channel="public", type="share_briefing",
            content="Mira also confirms the door colour.",
            audience=("hero", "mira", "gm"),
            commitments=(
                Commitment(subject="door", predicate="colour", value="red", epistemic_type="claim"),
            ),
        )
        assembler = ContextAssembler(log)
        store = assembler.belief_store("hero")
        assert store.believes("door", "colour")          # fact from narration
        assert len(store.claims) == 1                    # claim from briefing — separate
        assert store.claims_about("door", "colour")[0].epistemic_type == "claim"
