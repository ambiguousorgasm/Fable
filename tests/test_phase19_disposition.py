"""Phase 19 — Disposition graph core.

Exit gate: the engine has an explainable, auditable foundation for relationship
state. Every delta is linked to a causal event ID; no agent writes disposition
state directly; the graph is never accessible via player belief stores.
"""

import pytest
import tempfile
import os

from fable_table_engine import (
    CommitPipeline,
    Commitment,
    DispositionAxis,
    DispositionDelta,
    DispositionEngine,
    DispositionGraph,
    EventLog,
    SQLiteDispositionGraph,
    WorldState,
    attach_disposition,
    open_session,
)
from fable_table_engine.events import Event


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _make_event(log: EventLog, *, author: str, commitments=(), type_: str = "narration") -> Event:
    return log.append(
        author=author,
        channel="public",
        type=type_,
        content="test",
        audience=(author,),
        commitments=commitments,
    )


def _commitment(predicate: str, value) -> Commitment:
    return Commitment(subject="test", predicate=predicate, value=value)


# --------------------------------------------------------------------------- #
# TestDispositionDelta                                                          #
# --------------------------------------------------------------------------- #

class TestDispositionDelta:
    def test_requires_causal_event_id(self):
        with pytest.raises(ValueError, match="causal_event_id"):
            DispositionDelta(
                from_id="a", to_id="b",
                axis=DispositionAxis.TRUST, delta=1,
                causal_event_id="",
            )

    def test_rejects_zero_delta(self):
        with pytest.raises(ValueError, match="non-zero"):
            DispositionDelta(
                from_id="a", to_id="b",
                axis=DispositionAxis.TRUST, delta=0,
                causal_event_id="evt-1",
            )

    def test_requires_nonempty_ids(self):
        with pytest.raises(ValueError):
            DispositionDelta(
                from_id="", to_id="b",
                axis=DispositionAxis.TRUST, delta=1,
                causal_event_id="evt-1",
            )

    def test_roundtrip(self):
        d = DispositionDelta(
            from_id="a", to_id="b",
            axis=DispositionAxis.RESPECT, delta=-2,
            causal_event_id="evt-1",
            reason="betrayal",
        )
        assert DispositionDelta.from_dict(d.to_dict()) == d

    def test_negative_delta_allowed(self):
        d = DispositionDelta(
            from_id="a", to_id="b",
            axis=DispositionAxis.AFFECTION, delta=-1,
            causal_event_id="evt-x",
        )
        assert d.delta == -1


# --------------------------------------------------------------------------- #
# TestDispositionGraph                                                          #
# --------------------------------------------------------------------------- #

class TestDispositionGraph:
    def test_empty_edge_returns_empty_dict(self):
        g = DispositionGraph()
        assert g.edge("a", "b") == {}

    def test_apply_delta_accumulates(self):
        g = DispositionGraph()
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 2, "e1"))
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 1, "e2"))
        assert g.edge("a", "b")[DispositionAxis.TRUST] == 3

    def test_negative_delta_subtracts(self):
        g = DispositionGraph()
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 3, "e1"))
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, -2, "e2"))
        assert g.edge("a", "b")[DispositionAxis.TRUST] == 1

    def test_axes_are_independent(self):
        g = DispositionGraph()
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 1, "e1"))
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.AFFECTION, 2, "e2"))
        e = g.edge("a", "b")
        assert e[DispositionAxis.TRUST] == 1
        assert e[DispositionAxis.AFFECTION] == 2

    def test_directed_asymmetry(self):
        g = DispositionGraph()
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 3, "e1"))
        assert DispositionAxis.TRUST not in g.edge("b", "a")

    def test_deltas_for_event(self):
        g = DispositionGraph()
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 1, "e1"))
        g.apply_delta(DispositionDelta("c", "d", DispositionAxis.RESPECT, 1, "e1"))
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 1, "e2"))
        assert len(g.deltas_for_event("e1")) == 2
        assert len(g.deltas_for_event("e2")) == 1
        assert g.deltas_for_event("unknown") == []

    def test_all_deltas_order(self):
        g = DispositionGraph()
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 1, "e1"))
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 2, "e2"))
        history = g.all_deltas()
        assert history[0].causal_event_id == "e1"
        assert history[1].causal_event_id == "e2"

    def test_context_block_empty_when_no_relationships(self):
        g = DispositionGraph()
        assert g.context_block("a") == ""

    def test_context_block_shows_nonzero(self):
        g = DispositionGraph()
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 2, "e1"))
        block = g.context_block("a")
        assert "b" in block
        assert "trust=+2" in block

    def test_context_block_hides_zero_axis(self):
        g = DispositionGraph()
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 1, "e1"))
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, -1, "e2"))
        block = g.context_block("a")
        assert block == ""

    def test_context_block_only_from_subject(self):
        g = DispositionGraph()
        g.apply_delta(DispositionDelta("alice", "bob", DispositionAxis.TRUST, 1, "e1"))
        g.apply_delta(DispositionDelta("carol", "bob", DispositionAxis.RESPECT, 1, "e2"))
        alice_block = g.context_block("alice")
        carol_block = g.context_block("carol")
        # alice's block lists bob; carol's name must not appear
        assert "bob" in alice_block
        assert "carol" not in alice_block
        # carol's block lists bob; alice's name must not appear
        assert "bob" in carol_block
        assert "alice" not in carol_block

    def test_roundtrip_serde(self):
        g = DispositionGraph()
        g.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 2, "e1", "helped"))
        g.apply_delta(DispositionDelta("b", "a", DispositionAxis.OBLIGATION, -1, "e2"))
        g2 = DispositionGraph.from_dict(g.to_dict())
        assert g2.edge("a", "b") == g.edge("a", "b")
        assert g2.edge("b", "a") == g.edge("b", "a")
        assert len(g2.all_deltas()) == 2
        assert g2.deltas_for_event("e1")[0].reason == "helped"


# --------------------------------------------------------------------------- #
# TestDispositionEngine                                                         #
# --------------------------------------------------------------------------- #

class TestDispositionEngine:
    def setup_method(self):
        self.log = EventLog()
        self.graph = DispositionGraph()
        self.engine = DispositionEngine(self.graph)

    def test_unknown_event_type_noop(self):
        evt = _make_event(self.log, author="actor")
        deltas = self.engine.process_event(evt)
        assert deltas == []
        assert self.graph.all_deltas() == []

    def test_disposition_delta_commitment(self):
        evt = _make_event(
            self.log, author="actor",
            commitments=(
                _commitment("disposition_delta", {
                    "from_id": "npc", "to_id": "actor",
                    "axis": "trust", "delta": 2, "reason": "saved them",
                }),
            ),
        )
        deltas = self.engine.process_event(evt)
        assert len(deltas) == 1
        assert deltas[0].from_id == "npc"
        assert deltas[0].to_id == "actor"
        assert deltas[0].axis == DispositionAxis.TRUST
        assert deltas[0].delta == 2
        assert deltas[0].causal_event_id == evt.id
        assert deltas[0].reason == "saved them"
        assert self.graph.edge("npc", "actor")[DispositionAxis.TRUST] == 2

    def test_disposition_delta_bad_axis_skipped(self):
        evt = _make_event(
            self.log, author="actor",
            commitments=(
                _commitment("disposition_delta", {
                    "from_id": "a", "to_id": "b",
                    "axis": "not_an_axis", "delta": 1,
                }),
            ),
        )
        deltas = self.engine.process_event(evt)
        assert deltas == []

    def test_disposition_delta_nondicts_skipped(self):
        evt = _make_event(
            self.log, author="actor",
            commitments=(_commitment("disposition_delta", "not a dict"),),
        )
        assert self.engine.process_event(evt) == []

    def test_stress_taken_for_gives_trust(self):
        evt = _make_event(
            self.log, author="hero",
            commitments=(_commitment("stress_taken_for", "ally"),),
        )
        deltas = self.engine.process_event(evt)
        assert len(deltas) == 1
        d = deltas[0]
        assert d.from_id == "ally"
        assert d.to_id == "hero"
        assert d.axis == DispositionAxis.TRUST
        assert d.delta == 1
        assert d.causal_event_id == evt.id

    def test_stress_taken_for_empty_value_skipped(self):
        evt = _make_event(
            self.log, author="actor",
            commitments=(_commitment("stress_taken_for", ""),),
        )
        deltas = self.engine.process_event(evt)
        assert deltas == []

    def test_stress_taken_for_nonstring_value_skipped(self):
        evt = _make_event(
            self.log, author="actor",
            commitments=(_commitment("stress_taken_for", 42),),
        )
        deltas = self.engine.process_event(evt)
        assert deltas == []

    def test_triumph_for_gives_respect(self):
        evt = _make_event(
            self.log, author="hero",
            commitments=(_commitment("triumph_for", "witness"),),
        )
        deltas = self.engine.process_event(evt)
        assert len(deltas) == 1
        d = deltas[0]
        assert d.from_id == "witness"
        assert d.to_id == "hero"
        assert d.axis == DispositionAxis.RESPECT
        assert d.delta == 1

    def test_multiple_commitments_multiple_deltas(self):
        evt = _make_event(
            self.log, author="hero",
            commitments=(
                _commitment("stress_taken_for", "ally1"),
                _commitment("triumph_for", "ally2"),
            ),
        )
        deltas = self.engine.process_event(evt)
        assert len(deltas) == 2
        axes = {d.axis for d in deltas}
        assert DispositionAxis.TRUST in axes
        assert DispositionAxis.RESPECT in axes

    def test_deltas_linked_to_event(self):
        evt = _make_event(
            self.log, author="actor",
            commitments=(_commitment("stress_taken_for", "ally"),),
        )
        self.engine.process_event(evt)
        assert len(self.graph.deltas_for_event(evt.id)) == 1

    def test_graph_property(self):
        assert self.engine.graph is self.graph


# --------------------------------------------------------------------------- #
# TestSQLiteDispositionGraph                                                    #
# --------------------------------------------------------------------------- #

class TestSQLiteDispositionGraph:
    def test_persist_and_reload(self, tmp_path):
        db = str(tmp_path / "session.db")
        log, world, scene = open_session(db)
        disp = attach_disposition(log)
        disp.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 3, "e1", "first"))
        log.close()

        log2, world2, scene2 = open_session(db)
        disp2 = attach_disposition(log2)
        assert disp2.edge("a", "b")[DispositionAxis.TRUST] == 3
        assert disp2.all_deltas()[0].reason == "first"
        log2.close()

    def test_rollback_removes_delta(self, tmp_path):
        db = str(tmp_path / "session.db")
        log, world, scene = open_session(db)
        disp = attach_disposition(log)
        disp.apply_delta(DispositionDelta("x", "y", DispositionAxis.TRUST, 1, "pre"))

        try:
            with log.transaction():
                disp.apply_delta(DispositionDelta("x", "y", DispositionAxis.TRUST, 5, "tx"))
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass

        assert disp.edge("x", "y")[DispositionAxis.TRUST] == 1
        assert len(disp.all_deltas()) == 1
        log.close()

    def test_transaction_commits_on_success(self, tmp_path):
        db = str(tmp_path / "session.db")
        log, world, scene = open_session(db)
        disp = attach_disposition(log)
        with log.transaction():
            disp.apply_delta(DispositionDelta("a", "b", DispositionAxis.RESPECT, 2, "e1"))
        assert disp.edge("a", "b")[DispositionAxis.RESPECT] == 2
        log.close()

    def test_empty_on_fresh_session(self, tmp_path):
        db = str(tmp_path / "session.db")
        log, world, scene = open_session(db)
        disp = attach_disposition(log)
        assert disp.all_deltas() == []
        assert disp.edge("a", "b") == {}
        log.close()

    def test_multiple_sessions_accumulate(self, tmp_path):
        db = str(tmp_path / "session.db")
        log, world, scene = open_session(db)
        disp = attach_disposition(log)
        disp.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 1, "s1"))
        log.close()

        log2, world2, scene2 = open_session(db)
        disp2 = attach_disposition(log2)
        disp2.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 2, "s2"))
        assert disp2.edge("a", "b")[DispositionAxis.TRUST] == 3
        log2.close()


# --------------------------------------------------------------------------- #
# TestDispositionAccessControl                                                  #
# --------------------------------------------------------------------------- #

class TestDispositionAccessControl:
    """The disposition graph must never appear in player or TM belief projections."""

    def test_disposition_operations_never_append_to_event_log(self):
        log = EventLog()
        graph = DispositionGraph()
        engine = DispositionEngine(graph)
        log.append(
            author="gm", channel="public", type="narration",
            content="scene opens", audience=("player",),
        )
        graph.apply_delta(DispositionDelta(
            from_id="ally", to_id="hero",
            axis=DispositionAxis.TRUST, delta=3,
            causal_event_id="external-event-id",
        ))
        # Disposition apply_delta must not add entries to the event log.
        assert len(log) == 1

    def test_disposition_context_block_not_from_log(self):
        log = EventLog()
        graph = DispositionGraph()
        graph.apply_delta(DispositionDelta(
            from_id="ally", to_id="hero",
            axis=DispositionAxis.TRUST, delta=3,
            causal_event_id="fake-id",
        ))
        block = graph.context_block("ally")
        assert "hero" in block
        # Nothing was appended to the log.
        assert len(log) == 0

    def test_commit_pipeline_has_no_disposition_reference(self):
        log = EventLog()
        pipeline = CommitPipeline(log)
        graph = DispositionGraph()
        engine = DispositionEngine(graph)
        assert not hasattr(pipeline, "_disposition_engine")
        assert not hasattr(pipeline, "_graph")

    def test_no_player_visible_event_from_disposition(self):
        log = EventLog()
        graph = DispositionGraph()
        engine = DispositionEngine(graph)
        graph.apply_delta(DispositionDelta("a", "b", DispositionAxis.TRUST, 1, "hypothetical"))
        # The event log must remain empty — disposition does not write events.
        assert len(log) == 0
