"""Phase 3 — perception model (CORE §6/§7.1; IMPLEMENTATION_PLAN phase 3).

The named scenarios from the plan: whisper, noise, and line-of-sight. Plus the
derived `may_have_perceived` overhear path and the purity of the read.

Scene layout used across tests:

    parlor --- hall --- study        (parlor-hall and hall-study connected)

"""

import pytest

from fable_table_engine import (
    Entity,
    EventLog,
    Scene,
    Stimulus,
    WorldState,
    derive_overhears,
    perceivers,
)


def _world():
    w = WorldState()
    for zid in ("parlor", "hall", "study"):
        w.add_zone(zid)
    w.connect("parlor", "hall")
    w.connect("hall", "study")
    for eid in ("p1", "tm1", "tm2", "guard"):
        w.add_entity(Entity(id=eid, kind="character", name=eid))
    return w


# --- whisper: in-zone, close-only -----------------------------------------


def test_whisper_reaches_only_close_entities_in_zone():
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    w.place("tm2", "parlor")  # present but not close
    w.set_close("p1", "tm1")
    scene = Scene(w)

    heard = perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(volume="whisper"))
    assert heard == {"tm1"}  # tm2 is in the room but not close → does not hear


def test_whisper_does_not_carry_to_adjacent_zone():
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    w.place("guard", "hall")  # adjacent, open connection
    w.set_close("p1", "tm1")
    w.set_close("p1", "guard")  # close but in another zone — still can't hear a whisper
    scene = Scene(w)

    heard = perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(volume="whisper"))
    assert heard == {"tm1"}


# --- normal speech: whole zone, no further ---------------------------------


def test_normal_speech_fills_the_zone_but_not_neighbours():
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    w.place("tm2", "parlor")
    w.place("guard", "hall")
    scene = Scene(w)

    heard = perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(volume="normal"))
    assert heard == {"tm1", "tm2"}  # everyone in the parlor; not the guard next door


# --- noise: carries one hop through open connections, blocked when shut -----


def test_loud_noise_carries_to_adjacent_zone():
    w = _world()
    w.place("p1", "parlor")
    w.place("guard", "hall")
    w.place("tm2", "study")  # two hops away — out of range for one-hop loud
    scene = Scene(w)

    heard = perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(volume="loud"))
    assert heard == {"guard"}


def test_loud_noise_blocked_by_a_closed_connection():
    w = _world()
    w.place("p1", "parlor")
    w.place("guard", "hall")
    scene = Scene(w)
    scene.close("parlor", "hall")  # shut the door

    heard = perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(volume="loud"))
    assert heard == set()


# --- line of sight: lighting + open connection -----------------------------


def test_visual_event_unseen_in_darkness():
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    scene = Scene(w)
    scene.darken("parlor")

    seen = perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(modality="visual"))
    assert seen == set()


def test_visual_event_seen_across_open_connection_but_not_closed():
    w = _world()
    w.place("p1", "parlor")
    w.place("guard", "hall")
    scene = Scene(w)

    seen_open = perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(modality="visual"))
    assert seen_open == {"guard"}  # lit parlor visible from the hall through the open door

    scene.close("parlor", "hall")
    seen_closed = perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(modality="visual"))
    assert seen_closed == set()


def test_audiovisual_is_the_union_of_senses():
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    w.place("guard", "hall")
    scene = Scene(w)
    # Normal volume (parlor only) + visual (parlor + open hall) → union reaches the guard via sight.
    sensed = perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(modality="audiovisual"))
    assert sensed == {"tm1", "guard"}


# --- derived may_have_perceived overhears ----------------------------------


def test_overhear_emitted_for_unintended_perceiver_only():
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    w.place("tm2", "parlor")
    scene = Scene(w)
    log = EventLog()

    # p1 addresses tm1 only, but speaks at normal volume — tm2 is in earshot.
    source = log.append(
        author="p1",
        channel="public",
        type="dialogue",
        content="meet me at the docks at midnight",
        audience=("p1", "tm1"),
    )
    derived = derive_overhears(
        log, source_event=source, scene=scene, origin="parlor", actor="p1",
        stimulus=Stimulus(volume="normal"),
    )

    # Exactly one overhear, for tm2 — not for the actor or the intended audience.
    assert len(derived) == 1
    over = derived[0]
    assert over.audience == ("tm2",)
    assert over.type == "may_have_perceived"
    assert over.derived_from == (source.id,)

    # tm2's projection shows the vague hint, never the secret content or who spoke.
    tm2_view = log.project_for("tm2")
    assert len(tm2_view) == 1
    assert "docks" not in (tm2_view[0].content or "")
    assert tm2_view[0].author == "perception"  # actor identity not leaked
    assert "voices" in tm2_view[0].content

    # The intended recipient sees the real thing and gets no overhear noise.
    tm1_view = log.project_for("tm1")
    assert [e.content for e in tm1_view] == ["meet me at the docks at midnight"]


def test_whisper_produces_no_overhears_when_only_the_audience_is_close():
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    w.place("tm2", "parlor")  # present, not close
    w.set_close("p1", "tm1")
    scene = Scene(w)
    log = EventLog()

    source = log.append(
        author="p1", channel="whisper", type="dialogue",
        content="the seneschal is the traitor", audience=("p1", "tm1"),
    )
    derived = derive_overhears(
        log, source_event=source, scene=scene, origin="parlor", actor="p1",
        stimulus=Stimulus(volume="whisper"),
    )
    assert derived == []                 # tm2 is not close → senses nothing
    assert log.project_for("tm2") == ()  # and learns nothing at all


def test_perception_query_is_read_only():
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    scene = Scene(w)
    log = EventLog()
    perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus())
    assert len(log) == 0  # querying perception appends nothing


# --- guardrails ------------------------------------------------------------


def test_invalid_stimulus_is_rejected():
    with pytest.raises(ValueError):
        Stimulus(modality="telepathy")
    with pytest.raises(ValueError):
        Stimulus(volume="deafening")
