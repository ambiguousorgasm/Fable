"""Phase 4 — context assembly / belief stores (CORE §6.3, §6.4; plan phase 4).

Belief stores are per-POV read-time projections of the event log (D-001). These
tests show that two POVs assembled from the same log hold *different* knowledge
— the substrate for differential believability (CORE §13) — and that a POV's
believed facts come only from what it was entitled to see, never the global
canon. Also covers the ambient perceptual situation and the D-013 ordering fix
as seen through the assembler.
"""

from fable_table_engine import (
    CommitPipeline,
    Commitment,
    ContextAssembler,
    Entity,
    EventLog,
    Scene,
    WorldState,
    derive_overhears,
    Stimulus,
)


def _commit(pipe, **kw):
    return pipe.commit(**kw)


# === differential information: two POVs, one log ==========================


def test_two_povs_hold_different_events_and_beliefs():
    log = EventLog()
    pipe = CommitPipeline(log)
    # A whisper between p1 and tm1, carrying a secret fact. tm2 is not in it.
    pipe.commit(
        author="p1",
        channel="whisper",
        content="the seneschal is the traitor",
        audience=("p1", "tm1"),
        commitments=(Commitment("seneschal", "loyalty", "traitor", revealed=True),),
    )
    asm = ContextAssembler(log)

    tm1 = asm.belief_store("tm1")
    tm2 = asm.belief_store("tm2")

    # tm1 saw the whisper and believes the secret; tm2 saw nothing and believes nothing.
    assert len(tm1.events) == 1
    assert tm1.value_of("seneschal", "loyalty") == "traitor"
    assert tm2.events == ()
    assert not tm2.believes("seneschal", "loyalty")


def test_metadata_visibility_event_contributes_no_beliefs():
    """A POV that only learns *that* something happened gains no facts from it."""
    log = EventLog()
    pipe = CommitPipeline(log)
    pipe.commit(
        author="p1",
        channel="whisper",
        content="the seneschal is the traitor",
        audience=("p1", "tm1", "gm"),
        visibility={"p1": "content", "tm1": "content", "gm": "metadata"},
        commitments=(Commitment("seneschal", "loyalty", "traitor", revealed=True),),
    )
    asm = ContextAssembler(log)

    gm = asm.belief_store("gm")
    assert len(gm.events) == 1            # the GM knows it happened
    assert gm.events[0].content is None   # but not what was said
    assert not gm.believes("seneschal", "loyalty")  # and learns no fact from it


def test_hidden_commitment_is_not_in_a_player_belief_store():
    """A GM-only prep fact stays out of every player's beliefs (CORE §7.4)."""
    log = EventLog()
    pipe = CommitPipeline(log)
    pipe.commit(
        author="gm",
        channel="system",
        content="(prep) the vault is trapped",
        audience=("gm",),
        commitments=(Commitment("vault", "trapped", True, revealed=False),),
    )
    asm = ContextAssembler(log)
    assert asm.belief_store("gm").believes("vault", "trapped")
    assert not asm.belief_store("p1").believes("vault", "trapped")


def test_belief_reflects_latest_value_the_pov_actually_saw():
    log = EventLog()
    pipe = CommitPipeline(log)
    pipe.commit(author="gm", channel="public", content="A locked door.",
                audience=("p1",), commitments=(Commitment("door", "state", "locked", revealed=True),))
    # The door is later opened in p1's presence (a normal sanctioned change).
    pipe.commit(author="gm", channel="public", content="The door swings open.",
                audience=("p1",), commitments=(Commitment("door", "state", "open", revealed=True),),
                override=True, reason="the party unlocked it")
    p1 = ContextAssembler(log).belief_store("p1")
    assert p1.value_of("door", "state") == "open"


# === belief store is a derived snapshot ===================================


def test_belief_store_is_read_only_over_the_log():
    log = EventLog()
    CommitPipeline(log).commit(author="gm", channel="public", content="hi", audience=("p1",))
    before = len(log)
    ContextAssembler(log).belief_store("p1")
    assert len(log) == before  # assembling a context appends nothing


# === ambient perceptual situation (fog of war) ============================


def _scene_world():
    w = WorldState()
    for z in ("parlor", "hall", "study"):
        w.add_zone(z)
    w.connect("parlor", "hall")
    w.connect("hall", "study")
    for e in ("p1", "tm1", "guard", "spy"):
        w.add_entity(Entity(id=e, kind="character", name=e))
    return w


def test_perceptible_situation_is_co_present_and_visible_adjacent():
    w = _scene_world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")   # same room
    w.place("guard", "hall")   # adjacent, open, lit → visible
    w.place("spy", "study")    # two hops away → not perceptible
    scene = Scene(w)
    store = ContextAssembler(log=EventLog(), scene=scene).belief_store("p1")
    assert store.perceptible == frozenset({"tm1", "guard"})


def test_darkness_and_closed_doors_shrink_the_situation():
    w = _scene_world()
    w.place("p1", "parlor")
    w.place("guard", "hall")
    scene = Scene(w)
    scene.darken("hall")          # can't see into the dark hall...
    # guard makes no ambient sound across the boundary at normal volume from another zone,
    # so a darkened adjacent zone removes the guard from view.
    store = ContextAssembler(log=EventLog(), scene=scene).belief_store("p1")
    assert "guard" not in store.perceptible


def test_no_scene_means_empty_situation_but_full_beliefs():
    log = EventLog()
    CommitPipeline(log).commit(
        author="gm", channel="public", content="A tower.", audience=("p1",),
        commitments=(Commitment("tower", "distance", "~100ft", revealed=True),),
    )
    store = ContextAssembler(log).belief_store("p1")  # no scene supplied
    assert store.perceptible == frozenset()
    assert store.value_of("tower", "distance") == "~100ft"


# === integration: overhear shapes the overhearer's belief store ===========


def test_overhearer_belief_store_has_the_hint_not_the_secret():
    """End to end: a normal-volume aside is overheard by a co-present non-addressee.
    Their assembled context carries the vague perception, never the secret fact."""
    w = WorldState()
    w.add_zone("parlor")
    for e in ("p1", "tm1", "tm2"):
        w.add_entity(Entity(id=e, kind="character", name=e))
    for e in ("p1", "tm1", "tm2"):
        w.place(e, "parlor")
    scene = Scene(w)
    log = EventLog()

    source = log.append(
        author="p1", channel="public", type="dialogue",
        content="the vault code is 4471", audience=("p1", "tm1"),
        commitments=(Commitment("vault", "code", "4471", revealed=True),),
    )
    derive_overhears(log, source_event=source, scene=scene, origin="parlor",
                     actor="p1", stimulus=Stimulus(volume="normal"))

    asm = ContextAssembler(log, scene)
    tm2 = asm.belief_store("tm2")
    assert len(tm2.events) == 1                      # only the overhear
    assert not tm2.believes("vault", "code")         # no secret fact
    assert "4471" not in (tm2.events[0].content or "")

    tm1 = asm.belief_store("tm1")
    assert tm1.value_of("vault", "code") == "4471"   # the intended recipient learns it
