"""E-2: bootstrap_opening tests.

Contracts:
  1.  bootstrap_opening() emits a GM narration event for player_intro.
  2.  bootstrap_opening() emits a second GM narration event for starting_scene when different.
  3.  bootstrap_opening() emits only one event when starting_scene equals player_intro.
  4.  bootstrap_opening() is a no-op when both fields are empty.
  5.  Emitted events are visible via ContextAssembler.belief_store for the player.
  6.  bootstrap_opening() does NOT emit gm_context (hidden field must not reach player).
  7.  Events from bootstrap are authored as 'gm' and typed 'narration'.
"""

from __future__ import annotations

import pytest

from fable_table_engine import EventLog, bootstrap_opening
from fable_table_engine.campaign import CampaignPackage
from fable_table_engine.context import ContextAssembler


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _pkg(**kwargs) -> CampaignPackage:
    base = dict(title="Test", version="1.0", description="")
    base.update(kwargs)
    return CampaignPackage(**base)


def _events_for(log: EventLog, player_id: str) -> list:
    store = ContextAssembler(log=log).belief_store(player_id)
    return list(store.events)


# --------------------------------------------------------------------------- #
# Tests                                                                         #
# --------------------------------------------------------------------------- #

def test_bootstrap_emits_player_intro():
    log = EventLog()
    pkg = _pkg(player_intro="You are a debt collector in a rain-soaked city.")
    bootstrap_opening(log, "player_1", pkg)
    events = log.all()
    assert len(events) == 1
    assert events[0].type == "narration"
    assert events[0].author == "gm"
    assert "debt collector" in events[0].content


def test_bootstrap_emits_two_events_when_scene_differs():
    log = EventLog()
    pkg = _pkg(
        player_intro="You are a debt collector.",
        starting_scene="Rain hammers the docks as you arrive at midnight.",
    )
    bootstrap_opening(log, "player_1", pkg)
    events = log.all()
    assert len(events) == 2
    contents = [e.content for e in events]
    assert any("debt collector" in c for c in contents)
    assert any("docks" in c for c in contents)


def test_bootstrap_emits_one_event_when_scene_equals_intro():
    log = EventLog()
    same_text = "You are a debt collector in a rain-soaked city."
    pkg = _pkg(player_intro=same_text, starting_scene=same_text)
    bootstrap_opening(log, "player_1", pkg)
    assert len(log.all()) == 1


def test_bootstrap_noop_when_both_empty():
    log = EventLog()
    pkg = _pkg(player_intro="", starting_scene="  ")
    bootstrap_opening(log, "player_1", pkg)
    assert len(log.all()) == 0


def test_bootstrap_noop_minimal_package():
    log = EventLog()
    pkg = _pkg()  # no intro or scene
    bootstrap_opening(log, "player_1", pkg)
    assert len(log.all()) == 0


def test_bootstrap_events_visible_to_player():
    log = EventLog()
    pkg = _pkg(player_intro="Welcome to the city of salt and iron.")
    bootstrap_opening(log, "player_1", pkg)
    events = _events_for(log, "player_1")
    assert len(events) == 1
    assert "city of salt" in events[0].content


def test_bootstrap_does_not_emit_gm_context():
    log = EventLog()
    pkg = _pkg(
        player_intro="You are a detective.",
        gm_context="The mayor is the murderer.",
    )
    bootstrap_opening(log, "player_1", pkg)
    all_contents = [e.content for e in log.all()]
    assert not any("murderer" in c for c in all_contents)


def test_bootstrap_events_have_correct_channel():
    log = EventLog()
    pkg = _pkg(player_intro="Welcome.", starting_scene="Fog rolls in.")
    bootstrap_opening(log, "player_1", pkg)
    for event in log.all():
        assert event.channel == "public"
        assert "player_1" in event.audience
        assert "gm" in event.audience
