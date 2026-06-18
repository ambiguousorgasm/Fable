"""Phase 1 behavior tests beyond the headline acceptance contracts."""

import random

import pytest

from fable_table_engine import (
    Band,
    Commitment,
    DiceService,
    Entity,
    Event,
    EventLog,
    RulesEngine,
    WorldState,
    band_for_margin,
)


# --- events / validation --------------------------------------------------


def test_unknown_channel_rejected():
    log = EventLog()
    with pytest.raises(ValueError):
        log.append(author="gm", channel="telepathy", type="declaration", content="x")


def test_visibility_must_name_only_audience_members():
    log = EventLog()
    with pytest.raises(ValueError):
        log.append(
            author="gm",
            channel="whisper",
            type="dialogue",
            content="x",
            audience=("p1",),
            visibility={"p2": "content"},  # p2 not in audience
        )


def test_duplicate_audience_rejected():
    with pytest.raises(ValueError):
        Event(
            sequence=0,
            id="x",
            timestamp="t",
            author="gm",
            channel="public",
            audience=("p1", "p1"),
            visibility="content",
            type="declaration",
            content="x",
        )


def test_commitment_confidence_bounds():
    with pytest.raises(ValueError):
        Commitment(subject="tower", predicate="distance", value="~100ft", confidence=1.5)


def test_event_carries_commitments_and_serializes():
    log = EventLog()
    c = Commitment(subject="tower", predicate="distance", value="~100ft")
    event = log.append(
        author="gm",
        channel="public",
        type="declaration",
        content="The tower looms a hundred feet off.",
        audience=("p1",),
        commitments=(c,),
    )
    d = event.to_dict()
    assert d["commitments"][0]["subject"] == "tower"
    assert d["audience"] == ["p1"]
    assert d["type"] == "declaration"


# --- log-only events (empty audience) -------------------------------------


def test_empty_audience_event_is_log_only():
    log = EventLog()
    log.append(author="system", channel="system", type="note", content="scene start")
    # No entity is in the audience, so nobody projects it.
    assert log.project_for("gm") == ()
    assert log.project_for("p1") == ()
    # But it is still in the authoritative log.
    assert len(log) == 1


# --- dice -----------------------------------------------------------------


def test_dice_is_deterministic_under_seed():
    log_a, log_b = EventLog(), EventLog()
    a = DiceService(log_a, rng=random.Random(42)).roll(3, 6, author="gm")
    b = DiceService(log_b, rng=random.Random(42)).roll(3, 6, author="gm")
    assert a.rolls == b.rolls
    assert all(1 <= r <= 6 for r in a.rolls)


def test_dice_rejects_degenerate_rolls():
    dice = DiceService(EventLog(), rng=random.Random(0))
    with pytest.raises(ValueError):
        dice.roll(0, 6, author="gm")
    with pytest.raises(ValueError):
        dice.roll(3, 1, author="gm")


# --- rules engine band table (fable_engine.md §5) -------------------------


@pytest.mark.parametrize(
    "margin,band",
    [
        (5, Band.TRIUMPH),
        (3, Band.TRIUMPH),
        (2, Band.SUCCESS),
        (0, Band.SUCCESS),
        (-1, Band.COST),
        (-2, Band.COST),
        (-3, Band.SETBACK),
        (-9, Band.SETBACK),
    ],
)
def test_band_for_margin(margin, band):
    assert band_for_margin(margin) == band


def test_resolve_check_links_resolution_to_its_dice_event():
    log = EventLog()
    dice = DiceService(log, rng=random.Random(7))
    rules = RulesEngine(log, dice)
    check = rules.resolve_check(actor="p1", skill=3, tn=10, audience=("p1", "gm"))

    resolution = log.get(check.resolution_event_id)
    # The cold resolution is provenance-linked back to the dice roll it read.
    assert check.dice_event_id in resolution.derived_from
    assert check.margin == check.roll_total - check.tn
    assert check.band == band_for_margin(check.margin)
    # Author is the engine, not the actor: a cold read, not a claim.
    assert resolution.author == "rules-engine"


# --- world state skeleton -------------------------------------------------


def test_world_state_add_and_get_entity():
    ws = WorldState()
    ws.add_entity(Entity(id="guard1", kind="npc", name="Rampart Guard"))
    assert ws.get_entity("guard1").name == "Rampart Guard"
    with pytest.raises(ValueError):
        ws.add_entity(Entity(id="guard1", kind="npc", name="dup"))
