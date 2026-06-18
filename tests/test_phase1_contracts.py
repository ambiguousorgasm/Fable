"""Phase 1 acceptance contracts (deterministic core + event log).

These mirror the acceptance tests in IMPLEMENTATION_PLAN.md one-for-one.
"""

import dataclasses
import random

import pytest

from fable_table_engine import (
    DeterminismBoundaryError,
    DiceService,
    EventLog,
    RulesEngine,
)


def test_events_append_with_monotonic_sequence():
    """Events append with monotonically increasing sequence IDs."""
    log = EventLog()
    seqs = [
        log.append(
            author="gm", channel="public", type="declaration", content=f"beat {i}"
        ).sequence
        for i in range(5)
    ]
    assert seqs == [0, 1, 2, 3, 4]
    assert [e.sequence for e in log.all()] == seqs


def test_event_has_required_fields():
    """Events carry author, channel, audience, visibility, type, content, commitments, derived_from."""
    log = EventLog()
    event = log.append(
        author="gm",
        channel="public",
        type="declaration",
        content="A tower looms a hundred feet off.",
        audience=("p1", "tm1"),
        visibility="content",
    )
    for field_name in (
        "id",
        "sequence",
        "timestamp",
        "author",
        "channel",
        "audience",
        "visibility",
        "type",
        "content",
        "commitments",
        "derived_from",
    ):
        assert hasattr(event, field_name)
    assert event.author == "gm"
    assert event.channel == "public"
    assert event.audience == ("p1", "tm1")
    assert event.commitments == ()
    assert event.derived_from == ()


def test_existing_events_are_immutable():
    """Existing events cannot be silently mutated through the normal API."""
    log = EventLog()
    event = log.append(author="gm", channel="public", type="declaration", content="fixed")

    # The event itself is frozen.
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.content = "tampered"  # type: ignore[misc]

    # The log hands back a tuple, not its internal list.
    snapshot = log.all()
    with pytest.raises(AttributeError):
        snapshot.append(event)  # type: ignore[attr-defined]

    # No public mutation path exists for a stored event.
    assert log.get(event.id).content == "fixed"


def test_dice_rolls_are_logged_as_events():
    """Dice rolls are logged as events via the dice service."""
    log = EventLog()
    dice = DiceService(log, rng=random.Random(1))
    result = dice.roll(3, 6, author="gm", audience=("gm",), reason="test")

    logged = log.get(result.event_id)
    assert logged.type == "dice_roll"
    assert logged.channel == "dice"
    assert result.total == sum(result.rolls)
    assert str(result.total) in logged.content


def test_mechanical_outcome_requires_rules_or_dice_path():
    """A mechanical outcome cannot be committed unless it came through the rules/dice path."""
    log = EventLog()

    # Authoring a mechanical outcome directly is refused at the chokepoint.
    with pytest.raises(DeterminismBoundaryError):
        log.append(
            author="gm",
            channel="dice",
            type="dice_roll",
            content="3d6 = [6, 6, 6] = 18 (faked)",
            audience=("gm",),
        )
    with pytest.raises(DeterminismBoundaryError):
        log.append(
            author="gm", channel="system", type="resolution", content="auto-success"
        )

    # A non-mechanical declaration is always allowed.
    decl = log.append(author="gm", channel="public", type="declaration", content="A door.")
    assert decl.type == "declaration"

    # The rules/dice path produces the mechanical events legitimately.
    dice = DiceService(log, rng=random.Random(0))
    rules = RulesEngine(log, dice)
    check = rules.resolve_check(actor="p1", skill=2, tn=10, audience=("p1", "gm"))
    assert log.get(check.dice_event_id).type == "dice_roll"
    assert log.get(check.resolution_event_id).type == "resolution"


def test_audience_filtering_excludes_nonaudience_content():
    """Audience filtering hides content from non-audience entities while preserving permitted metadata."""
    log = EventLog()
    # A whisper: p1 and tm1 see content; gm knows it happened (metadata); others nothing.
    log.append(
        author="p1",
        channel="whisper",
        type="dialogue",
        content="the guard is bribable",
        audience=("p1", "tm1", "gm"),
        visibility={"p1": "content", "tm1": "content", "gm": "metadata"},
    )

    tm1_view = log.project_for("tm1")
    assert len(tm1_view) == 1
    assert tm1_view[0].content == "the guard is bribable"

    gm_view = log.project_for("gm")
    assert len(gm_view) == 1
    assert gm_view[0].visibility == "metadata"
    assert gm_view[0].content is None  # knows it happened, not what was said

    # A teammate outside the audience sees nothing at all.
    assert log.project_for("tm2") == ()
