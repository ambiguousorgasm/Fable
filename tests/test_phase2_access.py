"""Phase 2 — access model + commit boundary (CORE §6; IMPLEMENTATION_PLAN phase 2).

Two headline acceptance areas from the plan: whisper secrecy and canonical
contradiction detection. The rest pin the declaration -> commit -> canon
lifecycle and the override escape hatch.
"""

import pytest

from fable_table_engine import (
    CanonConflictError,
    CommitPipeline,
    Commitment,
    EventLog,
    OVERRIDE_TYPE,
    canon_ledger,
    committed_facts,
)


def _commitment(subject, predicate, value, *, revealed=True):
    return Commitment(subject=subject, predicate=predicate, value=value, revealed=revealed)


# --- whisper secrecy (commitment-level) -----------------------------------


def test_whispered_commitment_never_enters_nonaudience_projection():
    """A fact shared on a whisper never appears in a non-audience projection."""
    log = EventLog()
    pipe = CommitPipeline(log)
    pipe.commit(
        author="p1",
        channel="whisper",
        content="the seneschal is the traitor",
        audience=("p1", "tm1", "gm"),
        visibility={"p1": "content", "tm1": "content", "gm": "metadata"},
        commitments=(_commitment("seneschal", "loyalty", "traitor", revealed=False),),
    )

    # The whisper target sees the content (and its commitment).
    tm1 = log.project_for("tm1")
    assert len(tm1) == 1 and tm1[0].content == "the seneschal is the traitor"
    assert tm1[0].commitments[0].subject == "seneschal"

    # The GM knows it happened but not what was said — and gets no commitment.
    gm = log.project_for("gm")
    assert gm[0].visibility == "metadata"
    assert gm[0].content is None
    assert gm[0].commitments == ()

    # A teammate outside the audience sees nothing at all.
    assert log.project_for("tm2") == ()


def test_hidden_commitment_is_not_canon():
    """A committed-but-unrevealed fact binds state but stays out of the canon ledger."""
    log = EventLog()
    pipe = CommitPipeline(log)
    pipe.commit(
        author="gm",
        channel="system",
        content="(prep) the vault is trapped",
        audience=("gm",),
        commitments=(_commitment("vault", "trapped", True, revealed=False),),
    )
    assert ("vault", "trapped") in pipe.committed_facts()
    assert ("vault", "trapped") not in pipe.canon_ledger()


# --- canonical contradiction detection ------------------------------------


def test_revealed_fact_enters_canon_ledger():
    log = EventLog()
    pipe = CommitPipeline(log)
    pipe.commit(
        author="gm",
        channel="public",
        content="The tower looms a hundred feet off.",
        audience=("p1", "tm1"),
        commitments=(_commitment("tower", "distance", "~100ft"),),
    )
    canon = pipe.canon_ledger()
    assert canon[("tower", "distance")].value == "~100ft"


def test_contradicting_canon_is_blocked_and_not_appended():
    """Silently contradicting a revealed fact is the forbidden move (CORE §6.2)."""
    log = EventLog()
    pipe = CommitPipeline(log)
    pipe.commit(
        author="gm",
        channel="public",
        content="The tower looms a hundred feet off.",
        audience=("p1",),
        commitments=(_commitment("tower", "distance", "~100ft"),),
    )

    with pytest.raises(CanonConflictError) as exc:
        pipe.commit(
            author="gm",
            channel="public",
            content="The tower is right beside you.",
            audience=("p1",),
            commitments=(_commitment("tower", "distance", "10ft"),),
        )
    assert exc.value.conflicts[0].existing.value == "~100ft"
    # Nothing was canonized on conflict: only the first declaration is on the log.
    assert len(log) == 1
    assert pipe.canon_ledger()[("tower", "distance")].value == "~100ft"


def test_restating_the_same_fact_is_idempotent():
    log = EventLog()
    pipe = CommitPipeline(log)
    for _ in range(2):
        pipe.commit(
            author="gm",
            channel="public",
            content="A hundred feet to the tower.",
            audience=("p1",),
            commitments=(_commitment("tower", "distance", "~100ft"),),
        )
    assert len(log) == 2  # both appended; no conflict
    assert pipe.canon_ledger()[("tower", "distance")].value == "~100ft"


def test_hidden_facts_may_be_freely_revised():
    """The hidden future is fluid: a hidden fact may be superseded (CORE §7.4)."""
    log = EventLog()
    pipe = CommitPipeline(log)
    pipe.commit(
        author="gm",
        channel="system",
        content="(prep) the guard is loyal",
        audience=("gm",),
        commitments=(_commitment("guard", "loyalty", "loyal", revealed=False),),
    )
    # No raise: revising a hidden commitment is allowed.
    pipe.commit(
        author="gm",
        channel="system",
        content="(prep) actually, the guard is bought",
        audience=("gm",),
        commitments=(_commitment("guard", "loyalty", "bought", revealed=False),),
    )
    assert pipe.committed_facts()[("guard", "loyalty")].value == "bought"
    assert ("guard", "loyalty") not in pipe.canon_ledger()


def test_revealed_commitment_may_supersede_a_hidden_one():
    """Revealing supersedes prep: a hidden fact does not freeze the boundary."""
    log = EventLog()
    pipe = CommitPipeline(log)
    pipe.commit(
        author="gm",
        channel="system",
        content="(prep) gate barred",
        audience=("gm",),
        commitments=(_commitment("gate", "state", "barred", revealed=False),),
    )
    # The players arrive and the GM reveals a different state — allowed, since
    # the hidden value was never canon.
    pipe.commit(
        author="gm",
        channel="public",
        content="The gate hangs open.",
        audience=("p1",),
        commitments=(_commitment("gate", "state", "open"),),
    )
    assert pipe.canon_ledger()[("gate", "state")].value == "open"


# --- override escape hatch (D-008) ----------------------------------------


def test_override_supersedes_canon_and_is_logged_as_intentional():
    log = EventLog()
    pipe = CommitPipeline(log)
    pipe.commit(
        author="gm",
        channel="public",
        content="The tower looms a hundred feet off.",
        audience=("p1",),
        commitments=(_commitment("tower", "distance", "~100ft"),),
    )

    event = pipe.commit(
        author="gm",
        channel="public",
        content="On reflection, the tower is much closer.",
        audience=("p1",),
        commitments=(_commitment("tower", "distance", "~30ft"),),
        override=True,
        reason="rule-of-cool: collapse the approach",
    )
    assert event.type == OVERRIDE_TYPE
    assert "rule-of-cool" in event.content
    fact = pipe.canon_ledger()[("tower", "distance")]
    assert fact.value == "~30ft"
    assert fact.via_override is True


def test_override_requires_a_reason():
    pipe = CommitPipeline(EventLog())
    with pytest.raises(ValueError):
        pipe.commit(
            author="gm",
            channel="public",
            content="x",
            commitments=(_commitment("a", "b", 1),),
            override=True,
        )


# --- derivations are pure folds over the log ------------------------------


def test_committed_facts_latest_value_wins_in_append_order():
    log = EventLog()
    pipe = CommitPipeline(log)
    # Two hidden revisions then a reveal — committed_facts takes the last.
    for value in ("a", "b"):
        pipe.commit(
            author="gm",
            channel="system",
            content=f"prep {value}",
            audience=("gm",),
            commitments=(_commitment("thread", "fixture", value, revealed=False),),
        )
    facts = committed_facts(log.all())
    assert facts[("thread", "fixture")].value == "b"
    # canon_ledger is the same fold filtered to revealed facts.
    assert ("thread", "fixture") not in canon_ledger(log.all())


def test_check_reports_conflicts_without_appending():
    log = EventLog()
    pipe = CommitPipeline(log)
    pipe.commit(
        author="gm",
        channel="public",
        content="A locked door.",
        audience=("p1",),
        commitments=(_commitment("door", "state", "locked"),),
    )
    conflicts = pipe.check((_commitment("door", "state", "open"),))
    assert len(conflicts) == 1
    assert conflicts[0].existing.value == "locked"
    assert len(log) == 1  # check is read-only
