"""Phase 22 event schema structural tests.

Verifies that every event emitted by the engine serializes to a dict that
matches the shape required by schemas/event.schema.json — without requiring
a runtime jsonschema install. Tests cover:

1. Required top-level fields present in every event's to_dict().
2. Channel enum values match the schema's allowed set.
3. Visibility values are valid ("content" | "metadata" | per-member dict).
4. Commitment fields round-trip through to_dict() faithfully.
5. Epistemic type values match the schema enum.
6. A complete beat produces events whose dicts all pass the shape check.
7. AdditionalProperties invariant: no unexpected keys in to_dict() output.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fable_table_engine.access import CommitPipeline
from fable_table_engine.beat import BeatRunner
from fable_table_engine.character_sheet import CharacterSheet
from fable_table_engine.context import ContextAssembler
from fable_table_engine.dice import DiceService
from fable_table_engine.effects import EffectExecutor
from fable_table_engine.event_log import EventLog
from fable_table_engine.events import Event, Commitment
from fable_table_engine.gm import AdjudicatorGM, NarratorGM
from fable_table_engine.perception import Scene
from fable_table_engine.provider import ModelGateway, TelemetrySink
from fable_table_engine.rules import RulesEngine
from fable_table_engine.world_state import WorldState, Entity


# --------------------------------------------------------------------------- #
# Schema constants (mirrors event.schema.json to avoid runtime dependency)      #
# --------------------------------------------------------------------------- #

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "event.schema.json"

REQUIRED_EVENT_FIELDS = {
    "id", "sequence", "timestamp", "author", "channel",
    "audience", "visibility", "type", "content",
}
OPTIONAL_EVENT_FIELDS = {
    "commitments", "derived_from", "roll_visibility", "authorized_by",
}
ALL_KNOWN_EVENT_FIELDS = REQUIRED_EVENT_FIELDS | OPTIONAL_EVENT_FIELDS

VALID_CHANNELS = {"public", "whisper", "ooc", "dice", "system"}
VALID_VISIBILITY_LEVELS = {"content", "metadata"}
VALID_ROLL_VISIBILITY = {"table", "roller_only", "gm_only", "revealed", None}
VALID_EPISTEMIC_TYPES = {"fact", "claim", "observation", "expired", "theory"}

REQUIRED_COMMITMENT_FIELDS = {"subject", "predicate", "value"}


# --------------------------------------------------------------------------- #
# Helpers                                                                        #
# --------------------------------------------------------------------------- #

def _gw_tool(name, data):
    b = MagicMock(); b.type = "tool_use"; b.name = name; b.input = data
    r = MagicMock(); r.content = [b]
    c = MagicMock(); c.messages.create = MagicMock(return_value=r)
    return ModelGateway(c, sink=TelemetrySink(), timeout_secs=None, max_retries=0)


def _gw_text(text="Ok."):
    b = MagicMock(); b.text = text
    r = MagicMock(); r.content = [b]
    c = MagicMock(); c.messages.create = MagicMock(return_value=r)
    return ModelGateway(c, sink=TelemetrySink(), timeout_secs=None, max_retries=0)


def _adj_data(facts=None, has_stakes=False, palette=None):
    return {
        "has_stakes": has_stakes, "reasoning": "ok", "action_domain": "social",
        "skill": "Physique" if has_stakes else None,
        "tn": 10 if has_stakes else None,
        "declared_facts": facts or [],
        "exposure": 1 if has_stakes else 0, "effect": "standard",
        "consequence_palette": palette or {},
        "triumph_effects": [], "trade_options": [], "trade_default": "Balanced",
        "edge_label": None, "seam": False, "narrative_hint": "ok",
    }


def _run_beat(seed=0, facts=None, has_stakes=False, palette=None):
    log = EventLog()
    world = WorldState()
    world.add_zone("hall")
    world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
    world.place("hero", "hall")
    pipeline = CommitPipeline(log)
    dice = DiceService(log, rng=random.Random(seed))
    rules = RulesEngine(log, dice)
    executor = EffectExecutor(log, world, pipeline)
    assembler = ContextAssembler(log, Scene(world))
    adj = AdjudicatorGM(_gw_tool("adjudicate_action", _adj_data(facts, has_stakes, palette)))
    narr = NarratorGM(_gw_text())
    BeatRunner(
        log=log, world=world, pipeline=pipeline, rules=rules,
        assembler=assembler, adjudicator=adj, narrator=narr,
        sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
        executor=executor,
    ).run("hero", "look around")
    return log.all()


def _assert_event_shape(event_dict: dict) -> None:
    """Assert that event_dict matches the required schema shape."""
    # Required fields.
    for field in REQUIRED_EVENT_FIELDS:
        assert field in event_dict, f"Required field {field!r} missing from event dict"
    # No unknown fields (additionalProperties: false).
    extra = set(event_dict.keys()) - ALL_KNOWN_EVENT_FIELDS
    assert not extra, f"Unexpected fields in event dict: {extra}"
    # Channel.
    assert event_dict["channel"] in VALID_CHANNELS, \
        f"Invalid channel: {event_dict['channel']!r}"
    # Visibility.
    vis = event_dict["visibility"]
    if isinstance(vis, str):
        assert vis in VALID_VISIBILITY_LEVELS, f"Invalid visibility: {vis!r}"
    elif isinstance(vis, dict):
        for entity_id, level in vis.items():
            assert isinstance(entity_id, str)
            assert level in VALID_VISIBILITY_LEVELS, \
                f"Invalid per-member visibility: {level!r}"
    else:
        pytest.fail(f"Visibility must be str or dict, got {type(vis)}")
    # Audience: list of strings.
    assert isinstance(event_dict["audience"], list)
    assert all(isinstance(m, str) for m in event_dict["audience"])
    # roll_visibility.
    assert event_dict.get("roll_visibility") in VALID_ROLL_VISIBILITY, \
        f"Invalid roll_visibility: {event_dict.get('roll_visibility')!r}"
    # Commitments: list of dicts.
    for c_dict in event_dict.get("commitments", []):
        for cf in REQUIRED_COMMITMENT_FIELDS:
            assert cf in c_dict, f"Commitment missing field {cf!r}"
        if "epistemic_type" in c_dict:
            assert c_dict["epistemic_type"] in VALID_EPISTEMIC_TYPES, \
                f"Invalid epistemic_type: {c_dict['epistemic_type']!r}"
    # derived_from: list of strings.
    assert isinstance(event_dict.get("derived_from", []), list)
    # authorized_by: list of strings.
    assert isinstance(event_dict.get("authorized_by", []), list)


# --------------------------------------------------------------------------- #
# 1. Schema file is valid JSON                                                   #
# --------------------------------------------------------------------------- #

class TestSchemaFile:

    def test_schema_file_exists(self):
        assert SCHEMA_PATH.exists(), f"Schema file not found: {SCHEMA_PATH}"

    def test_schema_file_is_valid_json(self):
        with SCHEMA_PATH.open() as f:
            schema = json.load(f)
        assert isinstance(schema, dict)

    def test_schema_has_required_properties(self):
        with SCHEMA_PATH.open() as f:
            schema = json.load(f)
        props = schema.get("properties", {})
        for field in REQUIRED_EVENT_FIELDS:
            assert field in props, f"Schema missing property definition for {field!r}"

    def test_schema_has_additional_properties_false(self):
        with SCHEMA_PATH.open() as f:
            schema = json.load(f)
        assert schema.get("additionalProperties") is False, \
            "Schema must have additionalProperties: false"

    def test_schema_commitment_def_has_required_fields(self):
        with SCHEMA_PATH.open() as f:
            schema = json.load(f)
        commitment_def = schema.get("$defs", {}).get("commitment", {})
        assert commitment_def, "Schema missing $defs/commitment"
        required = commitment_def.get("required", [])
        for field in REQUIRED_COMMITMENT_FIELDS:
            assert field in required, f"Commitment schema missing required field {field!r}"

    def test_schema_commitment_has_epistemic_type(self):
        with SCHEMA_PATH.open() as f:
            schema = json.load(f)
        c_props = schema["$defs"]["commitment"]["properties"]
        assert "epistemic_type" in c_props, "Commitment schema missing epistemic_type"

    def test_schema_commitment_has_asserting_entity(self):
        with SCHEMA_PATH.open() as f:
            schema = json.load(f)
        c_props = schema["$defs"]["commitment"]["properties"]
        assert "asserting_entity" in c_props

    def test_schema_has_roll_visibility(self):
        with SCHEMA_PATH.open() as f:
            schema = json.load(f)
        assert "roll_visibility" in schema["properties"]

    def test_schema_has_authorized_by(self):
        with SCHEMA_PATH.open() as f:
            schema = json.load(f)
        assert "authorized_by" in schema["properties"]


# --------------------------------------------------------------------------- #
# 2. Event.to_dict() shape                                                       #
# --------------------------------------------------------------------------- #

class TestEventToDict:

    def _make_event(self, **overrides):
        defaults = dict(
            id="test-id",
            sequence=0,
            timestamp="2026-06-19T00:00:00+00:00",
            author="gm",
            channel="system",
            audience=("gm",),
            visibility="content",
            type="test",
            content="test content",
        )
        defaults.update(overrides)
        return Event(**defaults)

    def test_to_dict_has_all_required_fields(self):
        event = self._make_event()
        d = event.to_dict()
        for field in REQUIRED_EVENT_FIELDS:
            assert field in d, f"to_dict() missing {field!r}"

    def test_to_dict_no_extra_fields(self):
        event = self._make_event()
        d = event.to_dict()
        extra = set(d.keys()) - ALL_KNOWN_EVENT_FIELDS
        assert not extra, f"to_dict() has unexpected keys: {extra}"

    def test_to_dict_audience_is_list(self):
        event = self._make_event(audience=("hero", "gm"))
        d = event.to_dict()
        assert isinstance(d["audience"], list)
        assert "hero" in d["audience"]
        assert "gm" in d["audience"]

    def test_to_dict_commitments_is_list(self):
        c = Commitment(subject="a", predicate="b", value="c")
        event = self._make_event(commitments=(c,))
        d = event.to_dict()
        assert isinstance(d["commitments"], list)
        assert len(d["commitments"]) == 1
        assert d["commitments"][0]["subject"] == "a"

    def test_to_dict_commitment_has_required_fields(self):
        c = Commitment(subject="hero", predicate="alive", value=True,
                       revealed=True, epistemic_type="fact")
        event = self._make_event(commitments=(c,))
        d = event.to_dict()
        c_dict = d["commitments"][0]
        for field in REQUIRED_COMMITMENT_FIELDS:
            assert field in c_dict

    def test_to_dict_commitment_epistemic_type_valid(self):
        for et in VALID_EPISTEMIC_TYPES:
            c = Commitment(subject="x", predicate="y", value=1, epistemic_type=et)
            event = self._make_event(commitments=(c,))
            d = event.to_dict()
            assert d["commitments"][0].get("epistemic_type") == et

    def test_to_dict_roll_visibility_null_by_default(self):
        event = self._make_event()
        d = event.to_dict()
        assert d.get("roll_visibility") is None

    def test_to_dict_roll_visibility_valid_values(self):
        for rv in ["table", "roller_only", "gm_only", "revealed"]:
            event = self._make_event(roll_visibility=rv)
            d = event.to_dict()
            assert d["roll_visibility"] == rv
            assert d["roll_visibility"] in VALID_ROLL_VISIBILITY

    def test_to_dict_is_json_serializable(self):
        c = Commitment(subject="torch", predicate="lit", value=True, revealed=True)
        event = self._make_event(commitments=(c,), roll_visibility="table")
        d = event.to_dict()
        # Should not raise.
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        # Round-trip through JSON.
        parsed = json.loads(json_str)
        assert parsed["id"] == event.id
        assert parsed["commitments"][0]["subject"] == "torch"


# --------------------------------------------------------------------------- #
# 3. Complete beat events all pass shape check                                   #
# --------------------------------------------------------------------------- #

class TestBeatEventShapes:

    def test_stakeless_beat_events_all_valid_shape(self):
        events = _run_beat(seed=0, facts=[
            {"subject": "key", "predicate": "found", "value": True, "revealed": True}
        ])
        for event in events:
            d = event.to_dict()
            _assert_event_shape(d)

    def test_stakes_beat_events_all_valid_shape(self):
        # seed=0 gives Cost outcome.
        events = _run_beat(seed=0, has_stakes=True, palette={
            "cost": [{"kind": "apply_stress", "entity_id": "hero", "amount": 1}]
        })
        for event in events:
            d = event.to_dict()
            _assert_event_shape(d)

    def test_dice_roll_event_has_dice_channel(self):
        events = _run_beat(seed=0, has_stakes=True)
        dice_events = [e for e in events if e.type == "dice_roll"]
        assert len(dice_events) >= 1
        for de in dice_events:
            assert de.channel == "dice"

    def test_narration_event_has_public_channel(self):
        events = _run_beat(seed=0)
        narrations = [e for e in events if e.type == "narration"]
        assert len(narrations) == 1
        assert narrations[0].channel == "public"

    def test_system_events_have_system_channel(self):
        events = _run_beat(seed=0, facts=[
            {"subject": "relic", "predicate": "held_by", "value": "hero", "revealed": True}
        ])
        system_types = {"action_lifecycle", "declaration"}
        for event in events:
            if event.type in system_types:
                assert event.channel == "system", \
                    f"Event type {event.type!r} should have channel='system', got {event.channel!r}"

    def test_all_events_have_non_empty_id(self):
        events = _run_beat(seed=0)
        for event in events:
            assert event.id, f"Event {event.type!r} has empty ID"

    def test_all_events_have_monotone_sequence(self):
        events = _run_beat(seed=0)
        seqs = [e.sequence for e in events]
        assert seqs == sorted(seqs)
        assert seqs[0] == 0

    def test_commitment_subject_predicate_value_all_present(self):
        events = _run_beat(seed=0, facts=[
            {"subject": "hero", "predicate": "role", "value": "thief", "revealed": True}
        ])
        commit_events = [e for e in events if e.commitments]
        assert len(commit_events) >= 1
        for event in commit_events:
            for c in event.commitments:
                d = c.to_dict() if hasattr(c, "to_dict") else {
                    "subject": c.subject, "predicate": c.predicate, "value": c.value
                }
                assert d.get("subject"), "Commitment missing subject"
                assert d.get("predicate"), "Commitment missing predicate"
                assert "value" in d, "Commitment missing value"

    def test_multi_beat_all_events_valid_shape(self):
        """Three back-to-back beats all produce schema-conformant events."""
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        pipeline = CommitPipeline(log)
        rng = random.Random(99)
        assembler = ContextAssembler(log, Scene(world))
        sheets = {"hero": CharacterSheet(entity_id="hero", concept="Fighter")}
        executor = EffectExecutor(log, world, pipeline)
        for i in range(3):
            adj = AdjudicatorGM(_gw_tool("adjudicate_action", _adj_data()))
            narr = NarratorGM(_gw_text())
            BeatRunner(
                log=log, world=world, pipeline=pipeline,
                rules=RulesEngine(log, DiceService(log, rng=rng)),
                assembler=assembler, adjudicator=adj, narrator=narr,
                sheets=sheets, executor=executor,
            ).run("hero", f"action {i}")
        for event in log.all():
            _assert_event_shape(event.to_dict())
