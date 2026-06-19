"""Phase 11 acceptance tests — Epistemic Commitment Contract (D-024).

Invariants exercised:
  1. An NPC claim does not enter the canon ledger as fact.
  2. A POV observation appears only in the entitled POV's context.
  3. Objective facts remain distinct from theories, suspicions, and claims.
  4. Belief stores never silently convert claims into facts.
  5. Existing untyped commitments migrate conservatively as objective facts.
  6. A later factual confirmation can coexist with an earlier claim without
     collapsing their provenance.

Exit gate: the engine can distinguish what is true, what was said, and what a
character personally observed.
"""

from fable_table_engine import (
    Commitment,
    CommitPipeline,
    ContextAssembler,
    EventLog,
)
from fable_table_engine.access import canon_ledger, committed_facts
from fable_table_engine.context import Belief, BeliefStore


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _log_and_pipeline():
    log = EventLog()
    pipeline = CommitPipeline(log)
    return log, pipeline


def _append_claim(log, *, author, subject, predicate, value,
                  audience, revealed=False, asserting_entity=None):
    return log.append(
        author=author,
        channel="public",
        type="declaration",
        content=f"{author} claims: {subject}.{predicate}={value!r}",
        audience=audience,
        visibility="content",
        commitments=[Commitment(
            subject=subject, predicate=predicate, value=value,
            revealed=revealed, epistemic_type="claim",
            asserting_entity=asserting_entity or author,
        )],
    )


def _append_observation(log, *, author, subject, predicate, value,
                        audience, observing_entity=None):
    return log.append(
        author="perception",
        channel="system",
        type="may_have_perceived",
        content=f"(perceived) {subject}.{predicate}",
        audience=audience,
        visibility="content",
        commitments=[Commitment(
            subject=subject, predicate=predicate, value=value,
            revealed=False, epistemic_type="observation",
            observing_entity=observing_entity or author,
        )],
    )


def _append_fact(pipeline, *, author, subject, predicate, value,
                 audience, revealed=True):
    return pipeline.commit(
        author=author,
        channel="public",
        content=f"{subject}.{predicate} = {value!r}",
        audience=audience,
        visibility="content",
        commitments=[Commitment(
            subject=subject, predicate=predicate,
            value=value, revealed=revealed, epistemic_type="fact",
        )],
    )


# --------------------------------------------------------------------------- #
# Commitment schema and validation                                              #
# --------------------------------------------------------------------------- #

class TestCommitmentSchema:

    def test_fact_is_default_epistemic_type(self):
        c = Commitment(subject="duke", predicate="role", value="funder")
        assert c.epistemic_type == "fact"

    def test_claim_epistemic_type(self):
        c = Commitment(subject="duke", predicate="role", value="funder",
                       epistemic_type="claim", asserting_entity="npc_mason")
        assert c.epistemic_type == "claim"
        assert c.asserting_entity == "npc_mason"

    def test_observation_epistemic_type(self):
        c = Commitment(subject="figure", predicate="location", value="rooftop",
                       epistemic_type="observation", observing_entity="player")
        assert c.epistemic_type == "observation"
        assert c.observing_entity == "player"

    def test_invalid_epistemic_type_raises(self):
        import pytest
        with pytest.raises(ValueError, match="epistemic_type"):
            Commitment(subject="x", predicate="y", value="z", epistemic_type="rumour")

    def test_asserting_entity_defaults_none(self):
        c = Commitment(subject="x", predicate="y", value="z", epistemic_type="claim")
        assert c.asserting_entity is None

    def test_to_dict_includes_asserting_entity(self):
        c = Commitment(subject="duke", predicate="role", value="funder",
                       epistemic_type="claim", asserting_entity="mason")
        d = c.to_dict()
        assert d["asserting_entity"] == "mason"
        assert d["epistemic_type"] == "claim"

    def test_to_dict_omits_none_provenance(self):
        c = Commitment(subject="x", predicate="y", value="z")
        d = c.to_dict()
        assert "asserting_entity" not in d
        assert "observing_entity" not in d

    def test_to_dict_includes_observing_entity(self):
        c = Commitment(subject="figure", predicate="seen_at", value="rooftop",
                       epistemic_type="observation", observing_entity="player")
        d = c.to_dict()
        assert d["observing_entity"] == "player"


# --------------------------------------------------------------------------- #
# Canon ledger: only facts enter (invariants 1, 3)                             #
# --------------------------------------------------------------------------- #

class TestCanonLedger:

    def test_npc_claim_does_not_enter_canon_ledger(self):  # acceptance 1
        log, pipeline = _log_and_pipeline()
        _append_claim(log, author="npc_mason", subject="duke", predicate="funds_cult",
                      value=True, audience=("player", "gm"), revealed=True,
                      asserting_entity="npc_mason")
        ledger = pipeline.canon_ledger()
        assert ("duke", "funds_cult") not in ledger  # invariant 1

    def test_observation_does_not_enter_canon_ledger(self):
        log, pipeline = _log_and_pipeline()
        _append_observation(log, author="player", subject="figure", predicate="location",
                            value="rooftop", audience=("player",),
                            observing_entity="player")
        ledger = pipeline.canon_ledger()
        assert ("figure", "location") not in ledger

    def test_revealed_fact_enters_canon_ledger(self):
        log, pipeline = _log_and_pipeline()
        _append_fact(pipeline, author="gm", subject="duke", predicate="title",
                     value="baron", audience=("player", "gm"), revealed=True)
        ledger = pipeline.canon_ledger()
        assert ("duke", "title") in ledger
        assert ledger[("duke", "title")].value == "baron"

    def test_unrevealed_fact_does_not_enter_canon_ledger(self):
        log, pipeline = _log_and_pipeline()
        _append_fact(pipeline, author="gm", subject="vault", predicate="contents",
                     value="gold", audience=("gm",), revealed=False)
        ledger = pipeline.canon_ledger()
        assert ("vault", "contents") not in ledger

    def test_claim_does_not_conflict_with_different_canonical_fact(self):
        """A claim may assert something false without raising CanonConflictError (invariant 3)."""
        log, pipeline = _log_and_pipeline()
        _append_fact(pipeline, author="gm", subject="duke", predicate="role",
                     value="neutral", audience=("player", "gm"), revealed=True)
        # NPC makes a contradictory claim — should not raise
        _append_claim(log, author="npc_informer", subject="duke", predicate="role",
                      value="traitor", audience=("player", "gm"), revealed=True,
                      asserting_entity="npc_informer")
        # Canon still holds the GM fact
        ledger = pipeline.canon_ledger()
        assert ledger[("duke", "role")].value == "neutral"


# --------------------------------------------------------------------------- #
# Belief-store folding (invariants 3, 4, 6)                                   #
# --------------------------------------------------------------------------- #

class TestBeliefStoreFolding:

    def test_facts_in_beliefs_dict_not_claims(self):  # invariant 4
        log, pipeline = _log_and_pipeline()
        _append_fact(pipeline, author="gm", subject="tower", predicate="height",
                     value="100ft", audience=("player", "gm"), revealed=True)
        _append_claim(log, author="npc", subject="tower", predicate="height",
                      value="50ft", audience=("player", "gm"), revealed=True,
                      asserting_entity="npc")
        assembler = ContextAssembler(log)
        store = assembler.belief_store("player")
        # The fact must be in beliefs
        assert store.believes("tower", "height")
        assert store.value_of("tower", "height") == "100ft"  # fact wins, not the claim

    def test_claim_appears_in_claims_not_beliefs(self):
        log, pipeline = _log_and_pipeline()
        _append_claim(log, author="npc_mason", subject="duke", predicate="funds_cult",
                      value=True, audience=("player", "gm"), revealed=True,
                      asserting_entity="npc_mason")
        assembler = ContextAssembler(log)
        store = assembler.belief_store("player")
        assert not store.believes("duke", "funds_cult")  # not a fact
        assert len(store.claims) == 1
        claim = store.claims[0]
        assert claim.subject == "duke"
        assert claim.predicate == "funds_cult"
        assert claim.epistemic_type == "claim"
        assert claim.asserting_entity == "npc_mason"

    def test_observation_appears_in_observations_not_beliefs(self):
        log, pipeline = _log_and_pipeline()
        _append_observation(log, author="player", subject="figure", predicate="seen_at",
                            value="east_window", audience=("player",),
                            observing_entity="player")
        assembler = ContextAssembler(log)
        store = assembler.belief_store("player")
        assert not store.believes("figure", "seen_at")
        assert len(store.observations) == 1
        obs = store.observations[0]
        assert obs.epistemic_type == "observation"
        assert obs.observing_entity == "player"

    def test_claim_and_later_fact_coexist_with_distinct_provenance(self):  # acceptance 6
        log, pipeline = _log_and_pipeline()
        _append_claim(log, author="npc_informer", subject="duke", predicate="allegiance",
                      value="cult", audience=("player", "gm"), revealed=True,
                      asserting_entity="npc_informer")
        _append_fact(pipeline, author="gm", subject="duke", predicate="allegiance",
                     value="confirmed_cult_member", audience=("player", "gm"), revealed=True)
        assembler = ContextAssembler(log)
        store = assembler.belief_store("player")
        # The fact is in beliefs
        assert store.believes("duke", "allegiance")
        assert store.value_of("duke", "allegiance") == "confirmed_cult_member"
        # The earlier claim is still in claims — provenance not collapsed
        assert len(store.claims) == 1
        assert store.claims[0].asserting_entity == "npc_informer"
        assert store.claims[0].value == "cult"

    def test_multiple_claims_from_different_speakers_all_retained(self):
        log, pipeline = _log_and_pipeline()
        _append_claim(log, author="npc_a", subject="heist", predicate="mastermind",
                      value="baron", audience=("player", "gm"), asserting_entity="npc_a")
        _append_claim(log, author="npc_b", subject="heist", predicate="mastermind",
                      value="duke", audience=("player", "gm"), asserting_entity="npc_b")
        assembler = ContextAssembler(log)
        store = assembler.belief_store("player")
        assert not store.believes("heist", "mastermind")  # no fact
        claims = store.claims_about("heist", "mastermind")
        assert len(claims) == 2
        assertors = {c.asserting_entity for c in claims}
        assert assertors == {"npc_a", "npc_b"}

    def test_facts_epistemic_type_carried_through_belief(self):
        log, pipeline = _log_and_pipeline()
        _append_fact(pipeline, author="gm", subject="door", predicate="state",
                     value="locked", audience=("gm", "player"), revealed=True)
        assembler = ContextAssembler(log)
        store = assembler.belief_store("player")
        fact_belief = store.beliefs[("door", "state")]
        assert fact_belief.epistemic_type == "fact"

    def test_beliefs_from_returns_facts_only(self):
        log, pipeline = _log_and_pipeline()
        _append_fact(pipeline, author="gm", subject="a", predicate="p", value="v",
                     audience=("player",), revealed=True)
        _append_claim(log, author="npc", subject="a", predicate="p", value="other",
                      audience=("player",), asserting_entity="npc")
        assembler = ContextAssembler(log)
        events = log.project_for("player")
        facts = assembler.beliefs_from(events)
        assert ("a", "p") in facts
        assert facts[("a", "p")].epistemic_type == "fact"
        assert facts[("a", "p")].value == "v"


# --------------------------------------------------------------------------- #
# POV partitioning (invariant 2)                                               #
# --------------------------------------------------------------------------- #

class TestEpistemicPOVPartitioning:

    def test_observation_scoped_to_single_pov(self):  # acceptance 2
        log, pipeline = _log_and_pipeline()
        # Only player sees this observation
        _append_observation(log, author="player", subject="shadow", predicate="direction",
                            value="north", audience=("player",), observing_entity="player")
        assembler = ContextAssembler(log)
        player_store = assembler.belief_store("player")
        gm_store = assembler.belief_store("gm")

        assert len(player_store.observations) == 1  # player saw it
        assert len(gm_store.observations) == 0       # gm was not in audience

    def test_claim_scoped_to_audience(self):
        log, pipeline = _log_and_pipeline()
        _append_claim(log, author="npc", subject="traitor", predicate="identity",
                      value="captain", audience=("player", "gm"),
                      asserting_entity="npc")
        _append_claim(log, author="npc", subject="weapon", predicate="location",
                      value="vault", audience=("gm",),
                      asserting_entity="npc")
        assembler = ContextAssembler(log)
        player_store = assembler.belief_store("player")
        gm_store = assembler.belief_store("gm")

        # Player only sees the claim in their audience
        assert len(player_store.claims) == 1
        assert player_store.claims[0].subject == "traitor"
        # GM sees both claims
        assert len(gm_store.claims) == 2

    def test_private_fact_undisclosed_to_uninvited_pov(self):  # acceptance 4
        log, pipeline = _log_and_pipeline()
        _append_fact(pipeline, author="gm", subject="vault", predicate="code",
                     value="7734", audience=("gm",), revealed=False)
        assembler = ContextAssembler(log)
        player_store = assembler.belief_store("player")
        gm_store = assembler.belief_store("gm")

        assert not player_store.believes("vault", "code")   # player not in audience
        assert gm_store.believes("vault", "code")            # gm IS in audience — knows it
        # Not revealed → absent from the public canon ledger
        assert ("vault", "code") not in pipeline.canon_ledger()
        # But committed_facts still tracks it as bound objective state
        committed = committed_facts(log.all())
        assert ("vault", "code") in committed
        assert committed[("vault", "code")].epistemic_type == "fact"

    def test_public_fact_appears_in_all_entitled_povs(self):  # acceptance 3
        log, pipeline = _log_and_pipeline()
        _append_fact(pipeline, author="gm", subject="inn", predicate="owner",
                     value="aldric", audience=("player", "ally", "gm"), revealed=True)
        assembler = ContextAssembler(log)
        for pov in ("player", "ally", "gm"):
            store = assembler.belief_store(pov)
            assert store.believes("inn", "owner")
            assert store.value_of("inn", "owner") == "aldric"


# --------------------------------------------------------------------------- #
# Backward compatibility (invariant 5)                                         #
# --------------------------------------------------------------------------- #

class TestBackwardCompatibility:

    def test_existing_untyped_commitment_defaults_to_fact(self):  # acceptance 5
        log, pipeline = _log_and_pipeline()
        # Simulate a legacy commit with no explicit epistemic_type (uses default)
        pipeline.commit(
            author="gm",
            channel="public",
            content="The tower is 100 feet tall.",
            audience=("player", "gm"),
            commitments=[Commitment(subject="tower", predicate="height", value="100ft",
                                    revealed=True)],
        )
        ledger = pipeline.canon_ledger()
        assert ("tower", "height") in ledger
        assert ledger[("tower", "height")].epistemic_type == "fact"

    def test_belief_without_epistemic_type_defaults_fact(self):
        belief = Belief(subject="x", predicate="y", value="z", source_event_id="abc")
        assert belief.epistemic_type == "fact"

    def test_belief_store_without_claims_defaults_empty(self):
        # Test that BeliefStore can be constructed without claims/observations
        # (backward-compatible for any code that builds one directly)
        store = BeliefStore(
            pov="test",
            events=(),
            beliefs={},
            perceptible=frozenset(),
        )
        assert store.claims == ()
        assert store.observations == ()

    def test_commitment_roundtrip_via_to_dict(self):
        from fable_table_engine.persistence import _commitment_from_dict
        c = Commitment(
            subject="duke", predicate="role", value="funder",
            epistemic_type="claim", asserting_entity="mason",
            confidence=0.8, revealed=True,
        )
        d = c.to_dict()
        c2 = _commitment_from_dict(d)
        assert c2.epistemic_type == "claim"
        assert c2.asserting_entity == "mason"
        assert c2.confidence == 0.8
        assert c2.revealed is True

    def test_commitment_roundtrip_no_provenance(self):
        from fable_table_engine.persistence import _commitment_from_dict
        c = Commitment(subject="x", predicate="y", value="z", revealed=True)
        d = c.to_dict()
        c2 = _commitment_from_dict(d)
        assert c2.epistemic_type == "fact"
        assert c2.asserting_entity is None
        assert c2.observing_entity is None


# --------------------------------------------------------------------------- #
# BeliefStore helper methods                                                    #
# --------------------------------------------------------------------------- #

class TestBeliefStoreHelpers:

    def test_claims_about_filters_by_key(self):
        log, pipeline = _log_and_pipeline()
        _append_claim(log, author="a", subject="duke", predicate="role",
                      value="funder", audience=("player",), asserting_entity="a")
        _append_claim(log, author="b", subject="baron", predicate="role",
                      value="ally", audience=("player",), asserting_entity="b")
        assembler = ContextAssembler(log)
        store = assembler.belief_store("player")
        duke_claims = store.claims_about("duke", "role")
        assert len(duke_claims) == 1
        assert duke_claims[0].asserting_entity == "a"
        baron_claims = store.claims_about("baron", "role")
        assert len(baron_claims) == 1

    def test_observations_about_filters_by_key(self):
        log, pipeline = _log_and_pipeline()
        _append_observation(log, author="player", subject="shadow", predicate="direction",
                            value="north", audience=("player",), observing_entity="player")
        _append_observation(log, author="player", subject="voice", predicate="tone",
                            value="threatening", audience=("player",), observing_entity="player")
        assembler = ContextAssembler(log)
        store = assembler.belief_store("player")
        shadow_obs = store.observations_about("shadow", "direction")
        assert len(shadow_obs) == 1
        assert shadow_obs[0].value == "north"

    def test_believes_false_for_claim(self):
        log, pipeline = _log_and_pipeline()
        _append_claim(log, author="npc", subject="x", predicate="y",
                      value="z", audience=("player",), asserting_entity="npc")
        assembler = ContextAssembler(log)
        store = assembler.belief_store("player")
        assert not store.believes("x", "y")  # claim never enters beliefs

    def test_value_of_returns_none_for_claim_only(self):
        log, pipeline = _log_and_pipeline()
        _append_claim(log, author="npc", subject="x", predicate="y",
                      value="claimed_value", audience=("player",), asserting_entity="npc")
        assembler = ContextAssembler(log)
        store = assembler.belief_store("player")
        assert store.value_of("x", "y") is None  # no factual belief
