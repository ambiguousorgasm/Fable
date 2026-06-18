"""Phase 1 acceptance contracts (deterministic core + event log).

Executable placeholders for the acceptance tests in IMPLEMENTATION_PLAN.md.
They are skipped until the corresponding code exists; implement and un-skip
them one at a time as Phase 1 is built.
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="Phase 1 (deterministic core + event log) not yet implemented"
)


def test_events_append_with_monotonic_sequence():
    """Events append with monotonically increasing sequence IDs."""
    raise NotImplementedError


def test_event_has_required_fields():
    """Events carry author, channel, audience, visibility, type, content, commitments, derived_from."""
    raise NotImplementedError


def test_existing_events_are_immutable():
    """Existing events cannot be silently mutated through the normal API."""
    raise NotImplementedError


def test_dice_rolls_are_logged_as_events():
    """Dice rolls are logged as events via the dice service."""
    raise NotImplementedError


def test_mechanical_outcome_requires_rules_or_dice_path():
    """A mechanical outcome cannot be committed unless it came through the rules/dice path."""
    raise NotImplementedError


def test_audience_filtering_excludes_nonaudience_content():
    """Audience filtering hides content from non-audience entities while preserving permitted metadata."""
    raise NotImplementedError
