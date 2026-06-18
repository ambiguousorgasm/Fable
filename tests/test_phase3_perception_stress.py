"""Phase 3 — perception model adversarial stress pass (CORE §6/§7.1, §13).

The plan flags perception as the load-bearing wall and says to stress-test it
early. These tests probe the *dangerous* direction — can a stimulus reach an
entity it shouldn't, or can a non-audience entity learn more than "nothing"? —
plus they pin the known fail-safe limitations of the thin D-012 model so a later
fidelity bump can't quietly regress them.

Findings surfaced by this pass are recorded in DECISIONS D-012 and CHANGELOG;
the one genuine leak (global `sequence` side-channel) is encoded as an xfail.

Scene layout:  parlor --- hall --- study   (two open connections)
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
    for eid in ("p1", "tm1", "tm2", "guard", "spy"):
        w.add_entity(Entity(id=eid, kind="character", name=eid))
    return w


# === over-disclosure probes (the dangerous direction) =====================


def test_whisper_does_not_leak_to_a_close_entity_in_another_zone():
    """Closeness must not tunnel a whisper across a zone boundary."""
    w = _world()
    w.place("p1", "parlor")
    w.place("spy", "hall")
    w.set_close("p1", "spy")  # adjacent zone, open door, marked close
    scene = Scene(w)
    assert perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(volume="whisper")) == set()


def test_loud_noise_does_not_carry_two_hops():
    """Loud carries exactly one open hop; a two-hop listener hears nothing."""
    w = _world()
    w.place("p1", "parlor")
    w.place("spy", "study")  # parlor -> hall -> study is two hops
    scene = Scene(w)
    assert perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(volume="loud")) == set()


def test_loud_does_not_leak_through_a_zone_with_one_leg_closed():
    """parlor->hall open, hall->study closed: a study listener still can't hear."""
    w = _world()
    w.place("p1", "parlor")
    w.place("guard", "hall")
    w.place("spy", "study")
    scene = Scene(w)
    scene.close("hall", "study")
    heard = perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(volume="loud"))
    assert heard == {"guard"}  # hall hears (open, one hop); study never in range anyway


def test_sight_does_not_pass_through_a_closed_door_even_when_lit():
    w = _world()
    w.place("p1", "parlor")
    w.place("guard", "hall")
    scene = Scene(w)
    scene.close("parlor", "hall")
    assert perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(modality="visual")) == set()


def test_closing_a_nonexistent_connection_is_inert():
    """Closing parlor<->study (never connected) must not affect anything."""
    w = _world()
    w.place("p1", "parlor")
    w.place("guard", "hall")
    scene = Scene(w)
    scene.close("parlor", "study")  # no such connection
    assert perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(volume="loud")) == {"guard"}


# === modality independence ================================================


def test_darkness_blocks_sight_but_not_sound():
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    scene = Scene(w)
    scene.darken("parlor")
    assert perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(modality="visual")) == set()
    assert perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(volume="normal")) == {"tm1"}


def test_audiovisual_whisper_seen_but_not_heard_by_a_nonclose_witness():
    """A non-close witness in the room sees the hushed exchange but can't hear it.

    The overhear they get is visual-only ('movement'), never the words.
    """
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")  # the whisper target
    w.place("tm2", "parlor")  # present, not close
    w.set_close("p1", "tm1")
    scene = Scene(w)
    log = EventLog()

    sensed = perceivers(scene, origin="parlor", actor="p1",
                        stimulus=Stimulus(modality="audiovisual", volume="whisper"))
    assert sensed == {"tm1", "tm2"}  # tm1 by sound+sight, tm2 by sight only

    source = log.append(author="p1", channel="whisper", type="dialogue",
                        content="the seneschal is the traitor", audience=("p1", "tm1"))
    derived = derive_overhears(log, source_event=source, scene=scene, origin="parlor",
                               actor="p1", stimulus=Stimulus(modality="audiovisual", volume="whisper"))
    assert len(derived) == 1 and derived[0].audience == ("tm2",)
    hint = log.project_for("tm2")[0].content
    assert "movement" in hint and "traitor" not in hint and "murmur" not in hint


# === overhear leak surface =================================================


def test_overhear_reveals_no_identity_no_content_no_source_link():
    """A may_have_perceived event must not leak who, what, or which event."""
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    w.place("tm2", "parlor")
    scene = Scene(w)
    log = EventLog()
    source = log.append(author="p1", channel="public", type="dialogue",
                        content="meet me at the docks at midnight", audience=("p1", "tm1"))
    derive_overhears(log, source_event=source, scene=scene, origin="parlor",
                     actor="p1", stimulus=Stimulus(volume="normal"))

    view = log.project_for("tm2")[0]
    assert view.author == "perception"        # not "p1" — actor identity withheld
    assert "docks" not in (view.content or "")  # content withheld
    # The projection type carries no back-reference to the source event.
    assert not hasattr(view, "derived_from") or getattr(view, "derived_from", None) is None


def test_metadata_audience_member_is_not_also_overheard():
    """An audience member at metadata visibility gets the event (degraded), not a
    duplicate overhear — overhears are only for entities outside the audience."""
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    w.place("tm2", "parlor")
    scene = Scene(w)
    log = EventLog()
    source = log.append(
        author="p1", channel="public", type="dialogue", content="the plan",
        audience=("p1", "tm1", "tm2"),
        visibility={"p1": "content", "tm1": "content", "tm2": "metadata"},
    )
    derived = derive_overhears(log, source_event=source, scene=scene, origin="parlor",
                               actor="p1", stimulus=Stimulus(volume="normal"))
    assert derived == []  # tm2 is in the audience already; no overhear is synthesized
    assert len(log) == 1


# === documented fail-safe limitations (thin model, D-012) ==================


def test_same_room_nonaddressee_gets_only_a_vague_hint_not_content():
    """KNOWN LIMITATION (D-012, fail-safe): the thin model degrades every overhear
    to a vague hint, so a non-addressee standing right there at normal volume gets
    'voices nearby', not the actual words. This under-discloses (safe for secrecy);
    expressing 'fully overheard the content' is deferred to audience-derivation in
    phase 4. Pinned so a fidelity bump can't silently start leaking content here."""
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    w.place("tm2", "parlor")
    scene = Scene(w)
    log = EventLog()
    source = log.append(author="p1", channel="public", type="dialogue",
                        content="the vault code is 4471", audience=("p1", "tm1"))
    derive_overhears(log, source_event=source, scene=scene, origin="parlor",
                     actor="p1", stimulus=Stimulus(volume="normal"))
    assert "4471" not in (log.project_for("tm2")[0].content or "")


def test_derive_overhears_is_not_idempotent():
    """KNOWN BEHAVIOR: calling derive twice duplicates overhears. There is no
    chokepoint yet; dedup belongs at the future beat-loop call site, not here.
    Pinned so the duplication is visible when that chokepoint is built."""
    w = _world()
    w.place("p1", "parlor")
    w.place("tm2", "parlor")
    scene = Scene(w)
    log = EventLog()
    source = log.append(author="p1", channel="public", type="dialogue",
                        content="x", audience=("p1",))
    kw = dict(source_event=source, scene=scene, origin="parlor", actor="p1",
              stimulus=Stimulus(volume="normal"))
    derive_overhears(log, **kw)
    derive_overhears(log, **kw)
    assert len(log.project_for("tm2")) == 2  # two identical hints — duplication


# === robustness ============================================================


def test_unknown_origin_zone_fails_loud():
    w = _world()
    w.place("p1", "parlor")
    scene = Scene(w)
    with pytest.raises(ValueError):
        perceivers(scene, origin="nowhere", actor="p1", stimulus=Stimulus())


def test_entity_with_no_position_perceives_nothing_and_is_never_perceived():
    w = _world()
    w.place("p1", "parlor")
    # tm1 has no position set at all.
    scene = Scene(w)
    assert perceivers(scene, origin="parlor", actor="p1", stimulus=Stimulus(volume="loud")) == set()


# === FINDING (now fixed in phase 4, D-013): sequence side-channel ==========


def test_nonaudience_pov_cannot_infer_hidden_event_count():
    """Regression for D-013. Surfaced by this stress pass as an xfail; fixed in
    phase 4 by giving `project_for` a per-POV contiguous index. A non-audience
    POV's view must be densely indexed, leaking no evidence of hidden events."""
    w = _world()
    w.place("p1", "parlor")
    w.place("tm1", "parlor")
    w.place("spy", "study")  # out of all earshot/sight
    scene = Scene(w)
    log = EventLog()

    # A public event the spy can see-by-nothing (different zone, no perception).
    log.append(author="gm", channel="public", type="narration", content="dawn",
               audience=("spy",))
    # Several hidden whispers the spy is not party to and cannot perceive.
    for _ in range(3):
        src = log.append(author="p1", channel="whisper", type="dialogue",
                         content="secret", audience=("p1", "tm1"))
        derive_overhears(log, source_event=src, scene=scene, origin="parlor",
                         actor="p1", stimulus=Stimulus(volume="whisper"))
    log.append(author="gm", channel="public", type="narration", content="dusk",
               audience=("spy",))

    seqs = [e.sequence for e in log.project_for("spy")]
    # The invariant we WANT: the spy's view is densely indexed (0, 1, ...), leaking
    # no evidence of the events in between. Currently it's [0, 4] → gap reveals them.
    assert seqs == list(range(len(seqs)))
