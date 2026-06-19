"""Phase 21 deliverable 6: D-032 epistemic certainty labels."""
from __future__ import annotations

import pytest

from fable_table_engine import epistemic_label
from fable_table_engine.console import EPISTEMIC_LABELS, _commitment_labels, render_event
from fable_table_engine.context import BeliefStore, ContextAssembler
from fable_table_engine.event_log import EventLog
from fable_table_engine.events import EPISTEMIC_TYPES, Commitment, ProjectedEvent


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _proj(
    type_: str = "narration",
    content: str = "text",
    *,
    commitments: tuple[Commitment, ...] = (),
    superseded_by: str | None = None,
) -> ProjectedEvent:
    return ProjectedEvent(
        sequence=0, id="e1", timestamp="2026-06-19T00:00:00",
        author="gm", channel="public", type=type_,
        visibility="content", content=content,
        commitments=commitments,
        superseded_by=superseded_by,
    )


def _commitment(epistemic_type: str = "fact") -> Commitment:
    return Commitment(
        subject="door", predicate="colour", value="red",
        epistemic_type=epistemic_type,
    )


# --------------------------------------------------------------------------- #
# EPISTEMIC_LABELS dict                                                         #
# --------------------------------------------------------------------------- #

class TestEpistemicLabelsDict:

    def test_fact_maps_to_confirmed(self):
        assert EPISTEMIC_LABELS["fact"] == "Confirmed"

    def test_claim_maps_to_claimed(self):
        assert EPISTEMIC_LABELS["claim"] == "Claimed"

    def test_observation_maps_to_observed(self):
        assert EPISTEMIC_LABELS["observation"] == "Observed"

    def test_theory_maps_to_suspected(self):
        assert EPISTEMIC_LABELS["theory"] == "Suspected"

    def test_has_exactly_four_entries(self):
        assert len(EPISTEMIC_LABELS) == 4


# --------------------------------------------------------------------------- #
# epistemic_label()                                                             #
# --------------------------------------------------------------------------- #

class TestEpistemicLabelFunction:

    def test_fact_returns_confirmed(self):
        assert epistemic_label("fact") == "Confirmed"

    def test_claim_returns_claimed(self):
        assert epistemic_label("claim") == "Claimed"

    def test_observation_returns_observed(self):
        assert epistemic_label("observation") == "Observed"

    def test_theory_returns_suspected(self):
        assert epistemic_label("theory") == "Suspected"

    def test_unknown_type_returns_unknown(self):
        assert epistemic_label("something_else") == "Unknown"

    def test_none_returns_unknown(self):
        assert epistemic_label(None) == "Unknown"

    def test_empty_string_returns_unknown(self):
        assert epistemic_label("") == "Unknown"

    def test_superseded_overrides_any_type(self):
        for t in ("fact", "claim", "observation", "theory", "something"):
            assert epistemic_label(t, superseded=True) == "Corrected/Superseded"

    def test_superseded_none_type_also_corrected(self):
        assert epistemic_label(None, superseded=True) == "Corrected/Superseded"


# --------------------------------------------------------------------------- #
# _commitment_labels()                                                          #
# --------------------------------------------------------------------------- #

class TestCommitmentLabels:

    def test_no_commitments_returns_empty_string(self):
        e = _proj()
        assert _commitment_labels(e) == ""

    def test_single_fact_commitment(self):
        c = _commitment("fact")
        e = _proj(commitments=(c,))
        result = _commitment_labels(e)
        assert result == " [Confirmed: door.colour=red]"

    def test_single_claim_commitment(self):
        c = _commitment("claim")
        e = _proj(commitments=(c,))
        result = _commitment_labels(e)
        assert result == " [Claimed: door.colour=red]"

    def test_single_observation_commitment(self):
        c = _commitment("observation")
        e = _proj(commitments=(c,))
        result = _commitment_labels(e)
        assert result == " [Observed: door.colour=red]"

    def test_single_theory_commitment(self):
        c = _commitment("theory")
        e = _proj(commitments=(c,))
        result = _commitment_labels(e)
        assert result == " [Suspected: door.colour=red]"

    def test_multiple_commitments_space_separated(self):
        c1 = Commitment(subject="door", predicate="colour", value="red", epistemic_type="fact")
        c2 = Commitment(subject="npc", predicate="hostile", value=True, epistemic_type="claim")
        e = _proj(commitments=(c1, c2))
        result = _commitment_labels(e)
        assert "[Confirmed: door.colour=red]" in result
        assert "[Claimed: npc.hostile=True]" in result
        assert result.startswith(" ")

    def test_superseded_event_labels_all_as_corrected(self):
        c = _commitment("fact")
        e = _proj(commitments=(c,), superseded_by="corr-01")
        result = _commitment_labels(e)
        assert "[Corrected/Superseded: door.colour=red]" in result

    def test_superseded_claim_also_corrected(self):
        c = _commitment("claim")
        e = _proj(commitments=(c,), superseded_by="corr-01")
        result = _commitment_labels(e)
        assert "[Corrected/Superseded: door.colour=red]" in result


# --------------------------------------------------------------------------- #
# render_event() — commitment labels appended                                   #
# --------------------------------------------------------------------------- #

class TestRenderEventWithCommitmentLabels:

    def test_narration_without_commitments_unchanged(self):
        e = _proj("narration", "The door opened.")
        assert render_event(e) == "The door opened."

    def test_narration_with_fact_commitment_appends_label(self):
        c = _commitment("fact")
        e = _proj("narration", "The door was red.", commitments=(c,))
        result = render_event(e)
        assert result is not None
        assert result.startswith("The door was red.")
        assert "[Confirmed: door.colour=red]" in result

    def test_narration_with_theory_commitment(self):
        c = _commitment("theory")
        e = _proj("narration", "You suspect the lock is old.", commitments=(c,))
        result = render_event(e)
        assert result is not None
        assert "[Suspected: door.colour=red]" in result

    def test_correction_with_commitment_appends_label(self):
        c = _commitment("fact")
        e = _proj("correction", "The door was red.", commitments=(c,))
        result = render_event(e)
        assert result is not None
        assert result.startswith("[correction] The door was red.")
        assert "[Confirmed: door.colour=red]" in result

    def test_superseded_narration_with_commitment(self):
        c = _commitment("fact")
        e = _proj("narration", "The door was blue.", commitments=(c,), superseded_by="corr-01")
        result = render_event(e)
        assert result is not None
        assert result.startswith("[superseded] The door was blue.")
        assert "[Corrected/Superseded: door.colour=red]" in result


# --------------------------------------------------------------------------- #
# "theory" in EPISTEMIC_TYPES                                                   #
# --------------------------------------------------------------------------- #

class TestTheoryInEpistemicTypes:

    def test_theory_is_valid_epistemic_type(self):
        assert "theory" in EPISTEMIC_TYPES

    def test_theory_commitment_accepted(self):
        c = Commitment(subject="villain", predicate="motive", value="greed", epistemic_type="theory")
        assert c.epistemic_type == "theory"

    def test_theory_commitment_invalid_type_raises(self):
        with pytest.raises(ValueError, match="epistemic_type"):
            Commitment(subject="a", predicate="b", value="c", epistemic_type="guess")


# --------------------------------------------------------------------------- #
# _fold_epistemic() handles "theory" — BeliefStore.theories                    #
# --------------------------------------------------------------------------- #

class TestBeliefStoreTheories:

    def _store(self) -> BeliefStore:
        log = EventLog()
        log.append(
            author="gm", channel="public", type="narration",
            content="You suspect the innkeeper is hiding something.",
            audience=("hero", "gm"),
            commitments=(
                Commitment(
                    subject="innkeeper", predicate="hiding_something", value=True,
                    epistemic_type="theory",
                ),
            ),
        )
        assembler = ContextAssembler(log)
        return assembler.belief_store("hero")

    def test_theories_populated(self):
        store = self._store()
        assert len(store.theories) == 1

    def test_theory_not_in_beliefs(self):
        store = self._store()
        assert not store.believes("innkeeper", "hiding_something")

    def test_theory_belief_has_correct_type(self):
        store = self._store()
        assert store.theories[0].epistemic_type == "theory"

    def test_theory_belief_subject_predicate_value(self):
        store = self._store()
        t = store.theories[0]
        assert t.subject == "innkeeper"
        assert t.predicate == "hiding_something"
        assert t.value is True

    def test_fact_does_not_enter_theories(self):
        log = EventLog()
        log.append(
            author="gm", channel="public", type="narration",
            content="The door is red.",
            audience=("hero", "gm"),
            commitments=(
                Commitment(subject="door", predicate="colour", value="red", epistemic_type="fact"),
            ),
        )
        assembler = ContextAssembler(log)
        store = assembler.belief_store("hero")
        assert store.theories == ()
        assert store.believes("door", "colour")

    def test_multiple_theories_in_pov_order(self):
        log = EventLog()
        log.append(
            author="gm", channel="public", type="narration",
            content="first suspicion",
            audience=("hero", "gm"),
            commitments=(
                Commitment(subject="a", predicate="x", value=1, epistemic_type="theory"),
            ),
        )
        log.append(
            author="gm", channel="public", type="narration",
            content="second suspicion",
            audience=("hero", "gm"),
            commitments=(
                Commitment(subject="b", predicate="y", value=2, epistemic_type="theory"),
            ),
        )
        assembler = ContextAssembler(log)
        store = assembler.belief_store("hero")
        assert len(store.theories) == 2
        assert store.theories[0].subject == "a"
        assert store.theories[1].subject == "b"
