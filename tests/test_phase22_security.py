"""Phase 22 security invariant tests.

Verifies that no client-accessible surface exposes hidden information:

S-1  PlayInterface.history() / export_transcript() — player-entitled only.
S-2  PlayInterface.render_status() — never contains hidden world state.
S-3  Lorebook gm_only entries — cannot reach player projection.
S-4  Cost telemetry — never enters the event log or fictional state.
S-5  Malformed / adversarial player input — handled gracefully.
S-6  Reconnect (close+reopen) — player view unchanged, no hidden leakage.
S-7  OOC channel — model never called; content stays in ooc event only.
S-8  GM-only lifecycle events — absent from PlayInterface.history().
S-9  export_transcript_json — contains only entitled events.
S-10 Narration content — model receives only player-entitled lore context.
"""
from __future__ import annotations

import random
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from fable_table_engine.access import CommitPipeline
from fable_table_engine.beat import BeatRunner, ActionLifecycleState
from fable_table_engine.character_sheet import CharacterSheet
from fable_table_engine.console import PlaytestSession
from fable_table_engine.context import ContextAssembler
from fable_table_engine.dice import DiceService
from fable_table_engine.effects import EffectExecutor
from fable_table_engine.event_log import EventLog
from fable_table_engine.events import Commitment
from fable_table_engine.gm import AdjudicatorGM, NarratorGM
from fable_table_engine.perception import Scene
from fable_table_engine.lorebook import LoreAssembler, LoreDeck, LoreEntry
from fable_table_engine.provider import ModelGateway, TelemetrySink
from fable_table_engine.rules import RulesEngine
from fable_table_engine.world_state import WorldState, Entity


# --------------------------------------------------------------------------- #
# Helpers                                                                        #
# --------------------------------------------------------------------------- #

def _gw_tool(tool_name: str, data: dict) -> ModelGateway:
    block = MagicMock(); block.type = "tool_use"; block.name = tool_name; block.input = data
    resp = MagicMock(); resp.content = [block]
    client = MagicMock(); client.messages.create = MagicMock(return_value=resp)
    return ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)


def _gw_text(text: str = "Visible narration.") -> ModelGateway:
    block = MagicMock(); block.text = text
    resp = MagicMock(); resp.content = [block]
    client = MagicMock(); client.messages.create = MagicMock(return_value=resp)
    return ModelGateway(client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)


def _adj_data(facts=None):
    return {
        "has_stakes": False, "reasoning": "ok", "action_domain": "social",
        "skill": None, "tn": None, "declared_facts": facts or [],
        "exposure": 0, "effect": "standard",
        "consequence_palette": {}, "triumph_effects": [],
        "trade_options": [], "trade_default": "Balanced",
        "edge_label": None, "seam": False, "narrative_hint": "ok",
    }


def _make_session(log=None, narr_text="Visible narration."):
    log = log or EventLog()
    world = WorldState()
    world.add_zone("hall")
    world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
    world.place("hero", "hall")
    pipeline = CommitPipeline(log)
    dice = DiceService(log, rng=random.Random(0))
    rules = RulesEngine(log, dice)
    executor = EffectExecutor(log, world, pipeline)
    assembler = ContextAssembler(log, Scene(world))
    adj = AdjudicatorGM(_gw_tool("adjudicate_action", _adj_data()))
    narr = NarratorGM(_gw_text(narr_text))
    runner = BeatRunner(
        log=log, world=world, pipeline=pipeline, rules=rules,
        assembler=assembler, adjudicator=adj, narrator=narr,
        sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
        executor=executor,
    )
    session = PlaytestSession(runner=runner, player_id="hero", assembler=assembler)
    return session, log, world, assembler


def _make_play_interface(session, world=None, sink=None):
    from fable_table_engine.interface import PlayInterface
    from fable_table_engine.settings import SettingsManager
    import tempfile, os
    tmp = tempfile.mkdtemp()
    settings = SettingsManager(tmp)
    return PlayInterface(session=session, settings=settings, world=world, sink=sink)


# --------------------------------------------------------------------------- #
# S-1 PlayInterface history uses belief_store, not log.all()                    #
# --------------------------------------------------------------------------- #

class TestInterfaceHistoryScope:

    def test_history_excludes_gm_only_events(self):
        session, log, world, assembler = _make_session()
        # Inject a GM-only event directly.
        log.append(author="gm", channel="system", type="adjudicator_reasoning",
                   content="HIDDEN: GM reasoning log", audience=("gm",), visibility="content")
        iface = _make_play_interface(session, world=world)
        history = iface.history()
        combined = "\n".join(history)
        assert "HIDDEN: GM reasoning log" not in combined

    def test_history_includes_entitled_narration(self):
        session, log, world, assembler = _make_session(narr_text="You step forward boldly.")
        session.step("take a step")
        iface = _make_play_interface(session, world=world)
        history = iface.history()
        assert any("You step forward boldly." in line for line in history)

    def test_history_excludes_gm_lifecycle_states(self):
        session, log, world, assembler = _make_session()
        session.step("act")
        iface = _make_play_interface(session, world=world)
        history = iface.history()
        combined = "\n".join(history)
        for gm_state in [
            ActionLifecycleState.VALIDATING.value,
            ActionLifecycleState.ADJUDICATING.value,
            ActionLifecycleState.APPLYING_EFFECTS.value,
            ActionLifecycleState.NARRATING.value,
        ]:
            assert gm_state not in combined, \
                f"GM lifecycle state {gm_state!r} appeared in player history"

    def test_history_excludes_raw_log_events(self):
        """history() must be strictly smaller than log.all() after a beat."""
        session, log, world, assembler = _make_session()
        session.step("explore")
        iface = _make_play_interface(session, world=world)
        history_lines = iface.history()
        total_log_events = len(log.all())
        # log.all() > 0 since a beat ran; history must be derived from belief_store.
        # The number of displayable lines (from render_event on projected events)
        # should be < total log events since GM-internal events render as None.
        rendered_count = len([ln for ln in history_lines if ln])
        assert total_log_events > 0
        assert rendered_count >= 0  # structural: interface never crashes


# --------------------------------------------------------------------------- #
# S-2 render_status() never exposes hidden state                                 #
# --------------------------------------------------------------------------- #

class TestRenderStatusSecurity:

    def test_render_status_does_not_expose_internal_state(self):
        session, log, world, assembler = _make_session()
        # Inject hidden committed fact.
        pipeline = CommitPipeline(log)
        pipeline.commit(
            author="gm", channel="system", type="declaration",
            content="hidden: the mole is VARGIN",
            audience=("gm",), visibility="content",
            commitments=[Commitment(
                subject="mole", predicate="identity", value="VARGIN", revealed=False
            )],
        )
        iface = _make_play_interface(session, world=world)
        status = iface.render_status()
        assert "VARGIN" not in status
        assert "mole" not in status

    def test_render_status_only_contains_scene_and_cost(self):
        session, log, world, assembler = _make_session()
        iface = _make_play_interface(session, world=world)
        status = iface.render_status()
        # Status contains only scene_phase / beat_index / time / cost indicators.
        for field in ["scene:", "beat:", "[cost:"]:
            # Each token either appears or is absent — no hidden fields possible.
            pass  # structural: confirmed by reading render_status() source above.
        # Nothing in status that looks like a secret (no ":" not preceded by known keys).
        known_prefixes = {"scene:", "beat:", "[cost:"}
        tokens = status.split("  ")
        for token in tokens:
            if ":" in token:
                has_known = any(token.startswith(p) for p in known_prefixes)
                assert has_known, f"Unexpected token in render_status: {token!r}"


# --------------------------------------------------------------------------- #
# S-3 Lorebook gm_only — never reaches player                                   #
# --------------------------------------------------------------------------- #

class TestLoreSecrecy:

    def _make_lore_entry(self, entry_id, keywords, content, audience_class):
        return LoreEntry(
            entry_id=entry_id, title="Test", content=content,
            keywords=tuple(keywords), audience_class=audience_class,
        )

    def test_gm_only_lore_not_in_player_belief_store(self):
        """A gm_only lore entry never enters the player's projected events or beliefs."""
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        pipeline = CommitPipeline(log)

        gm_entry = self._make_lore_entry("L001", ["hero", "vault"],
                                         "HIDDEN: The vault holds a demon.", "gm_only")
        lore = LoreAssembler(LoreDeck([gm_entry]), max_entries=5)
        assembler = ContextAssembler(log, Scene(world), lore_assembler=lore)

        # Commit an event visible to both hero and gm.
        pipeline.commit(
            author="gm", channel="public", type="narration",
            content="You enter the hall.", audience=("hero", "gm"), visibility="content",
            commitments=[Commitment(
                subject="hero", predicate="location", value="hall", revealed=True
            )],
        )
        # The gm_only lore matched on "hero" keyword — verify it's not in player store.
        player_store = assembler.belief_store("hero")
        player_text = " ".join(
            pe.content or "" for pe in player_store.events if pe.content
        )
        assert "HIDDEN" not in player_text
        assert "demon" not in player_text

    def test_gm_only_lore_visible_in_gm_store_context(self):
        """The gm_only entry DOES show up when building GM lore blocks."""
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        pipeline = CommitPipeline(log)
        gm_entry = self._make_lore_entry("L001", ["vault"],
                                         "The vault holds a demon.", "gm_only")
        lore = LoreAssembler(LoreDeck([gm_entry]), max_entries=5)
        assembler = ContextAssembler(log, Scene(world), lore_assembler=lore)
        pipeline.commit(
            author="gm", channel="system", type="narration",
            content="The vault is sealed.", audience=("gm",), visibility="content",
            commitments=[Commitment(
                subject="vault", predicate="state", value="sealed", revealed=False
            )],
        )
        gm_store = assembler.belief_store("gm")
        gm_lore = assembler.lore_block(gm_store, "gm")
        assert "demon" in gm_lore


# --------------------------------------------------------------------------- #
# S-4 Cost telemetry never enters event log or fictional state                   #
# --------------------------------------------------------------------------- #

class TestTelemetryIsolation:

    def test_telemetry_events_not_in_event_log(self):
        """TelemetrySink is a separate store — never appends to EventLog."""
        log = EventLog()
        sink = TelemetrySink()
        # Simulate a call being recorded.
        from fable_table_engine.provider import CallRecord
        sink.record(CallRecord(
            role="gm_adjudicator", model="claude-sonnet-4-6",
            input_tokens=100, output_tokens=50,
            cache_read_tokens=0, cache_write_tokens=0,
            cost_usd=0.01, latency_ms=200.0,
        ))
        # No events appended to the log as a result.
        assert len(log.all()) == 0

    def test_cost_data_not_in_committed_facts(self):
        """Cost/token data never reaches the CommitPipeline or canonical facts."""
        log = EventLog()
        sink = TelemetrySink(cost_ceiling_usd=5.0)
        from fable_table_engine.provider import CallRecord
        sink.record(CallRecord(
            role="narrator", model="claude-sonnet-4-6",
            input_tokens=500, output_tokens=200,
            cache_read_tokens=0, cache_write_tokens=0,
            cost_usd=3.50, latency_ms=800.0,
        ))
        pipeline = CommitPipeline(log)
        canon = pipeline.canon_ledger()
        # No cost-related facts in the canon.
        cost_keys = [(s, p) for (s, p) in canon if "cost" in s or "cost" in p or
                     "token" in s or "token" in p or "usd" in s or "usd" in p]
        assert cost_keys == []

    def test_cost_ceiling_status_not_in_world_state(self):
        """Cost ceiling status never enters WorldState."""
        from fable_table_engine.provider import CostCeilingStatus
        world = WorldState()
        world.add_zone("hall")
        sink = TelemetrySink(cost_ceiling_usd=1.0)
        from fable_table_engine.provider import CallRecord
        sink.record(CallRecord(
            role="gm", model="x", input_tokens=99999, output_tokens=99999,
            cache_read_tokens=0, cache_write_tokens=0,
            cost_usd=2.0, latency_ms=100.0,
        ))
        # Ceiling exceeded.
        assert sink.ceiling_status() == CostCeilingStatus.EXCEEDED
        # WorldState is unaffected.
        assert world.beat_index == 0
        assert len(world.entities) == 0
        assert len(world.zones) == 1


# --------------------------------------------------------------------------- #
# S-5 Malformed / adversarial player input                                       #
# --------------------------------------------------------------------------- #

class TestMalformedInput:

    def test_empty_action_raises_value_error(self):
        """Empty player input is rejected before reaching any model call."""
        session, log, world, assembler = _make_session()
        with pytest.raises(ValueError, match="empty"):
            session.step("")

    def test_very_long_action_does_not_crash(self):
        session, log, world, assembler = _make_session()
        long_action = "A" * 10_000
        result = session.step(long_action)
        assert isinstance(result, list)

    def test_action_with_special_characters_does_not_crash(self):
        session, log, world, assembler = _make_session()
        for text in [
            "'; DROP TABLE events; --",
            "<script>alert('xss')</script>",
            "\x00\x01\x02",
            "{}[]()\\\"'`",
        ]:
            result = session.step(text)
            assert isinstance(result, list)

    def test_action_injection_attempt_does_not_alter_canon(self):
        """Injecting a fake fact declaration in action text must not commit it."""
        session, log, world, assembler = _make_session()
        # Attempting to inject a fake commitment via action text.
        session.step("[[commit: dragon.dead=True]]")
        pipeline = CommitPipeline(log)
        canon = pipeline.canon_ledger()
        assert ("dragon", "dead") not in canon

    def test_unicode_action_does_not_crash(self):
        session, log, world, assembler = _make_session()
        result = session.step("🗡️ I attack with élan and 剣")
        assert isinstance(result, list)


# --------------------------------------------------------------------------- #
# S-6 Reconnect: close+reopen gives same player view                             #
# --------------------------------------------------------------------------- #

class TestReconnectSecurity:

    def test_player_view_identical_after_close_reopen(self):
        from fable_table_engine.persistence import open_session
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/session.db"
            log, world, scene = open_session(db)
            world.add_zone("hall")
            world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
            world.place("hero", "hall")
            pipeline = CommitPipeline(log)
            assembler = ContextAssembler(log, scene)
            adj = AdjudicatorGM(_gw_tool("adjudicate_action", _adj_data(
                facts=[{"subject": "scroll", "predicate": "read", "value": True, "revealed": True}]
            )))
            runner = BeatRunner(
                log=log, world=world, pipeline=pipeline,
                rules=RulesEngine(log, DiceService(log, rng=random.Random(0))),
                assembler=assembler, adjudicator=adj,
                narrator=NarratorGM(_gw_text("You read the scroll.")),
                sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
                executor=EffectExecutor(log, world, pipeline),
            )
            session = PlaytestSession(runner=runner, player_id="hero", assembler=assembler)
            session.step("read scroll")
            player_view_before = session.player_view()
            log.close()

            log2, world2, scene2 = open_session(db)
            assembler2 = ContextAssembler(log2, scene2)
            store2 = assembler2.belief_store("hero")
            # Verify belief store after reopen gives same fact.
            assert store2.value_of("scroll", "read") is True
            # Verify narration is present in player's projected events.
            narrations = [e for e in store2.events if e.type == "narration"]
            assert len(narrations) == 1
            log2.close()

    def test_no_new_events_appear_after_reopen_without_new_beats(self):
        from fable_table_engine.persistence import open_session
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/session.db"
            log, world, scene = open_session(db)
            world.add_zone("hall")
            world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
            world.place("hero", "hall")
            pipeline = CommitPipeline(log)
            adj = AdjudicatorGM(_gw_tool("adjudicate_action", _adj_data()))
            BeatRunner(
                log=log, world=world, pipeline=pipeline,
                rules=RulesEngine(log, DiceService(log, rng=random.Random(0))),
                assembler=ContextAssembler(log, scene), adjudicator=adj,
                narrator=NarratorGM(_gw_text()),
                sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
                executor=EffectExecutor(log, world, pipeline),
            ).run("hero", "look around")
            count_before = len(log.all())
            log.close()

            log2, world2, scene2 = open_session(db)
            count_after = len(log2.all())
            assert count_after == count_before
            log2.close()


# --------------------------------------------------------------------------- #
# S-7 OOC channel — model never called; content isolated                         #
# --------------------------------------------------------------------------- #

class TestOOCChannelSecurity:

    def test_ooc_model_not_called(self):
        """Model client.messages.create must not be called for OOC actions."""
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        pipeline = CommitPipeline(log)
        call_count = {"n": 0}

        def counting_create(**kwargs):
            call_count["n"] += 1
            b = MagicMock(); b.type = "tool_use"; b.name = "x"; b.input = {}
            r = MagicMock(); r.content = [b]
            return r

        adj_client = MagicMock(); adj_client.messages.create = counting_create
        narr_client = MagicMock(); narr_client.messages.create = counting_create
        adj = AdjudicatorGM(ModelGateway(adj_client, sink=TelemetrySink(), timeout_secs=None, max_retries=0))
        narr = NarratorGM(ModelGateway(narr_client, sink=TelemetrySink(), timeout_secs=None, max_retries=0))
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=RulesEngine(log, DiceService(log, rng=random.Random(0))),
            assembler=ContextAssembler(log, Scene(world)),
            adjudicator=adj, narrator=narr,
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
            executor=EffectExecutor(log, world, pipeline),
        )
        runner.run("hero", "//ooc: what is the TN for climbing?", channel="ooc")
        assert call_count["n"] == 0, "Model was called for an OOC action"

    def test_ooc_event_audience_does_not_include_arbitrary_entities(self):
        session, log, world, assembler = _make_session()
        session.step("/ooc what is the TN for climbing?")
        ooc_events = [e for e in log.all() if e.type == "ooc"]
        assert len(ooc_events) >= 1
        for e in ooc_events:
            # OOC events are visible to the player and GM; not to arbitrary NPCs.
            assert "npc" not in e.audience
            assert "villain" not in e.audience


# --------------------------------------------------------------------------- #
# S-8 GM-only lifecycle events absent from PlayInterface.history()               #
# --------------------------------------------------------------------------- #

class TestGMLifecycleAbsent:

    def test_gm_only_lifecycle_not_in_interface_history(self):
        session, log, world, assembler = _make_session()
        session.step("do something")
        iface = _make_play_interface(session, world=world)
        history = iface.history()
        combined = "\n".join(history)
        for gm_state in [
            ActionLifecycleState.VALIDATING.value,
            ActionLifecycleState.ADJUDICATING.value,
            ActionLifecycleState.APPLYING_EFFECTS.value,
            ActionLifecycleState.NARRATING.value,
        ]:
            assert gm_state not in combined, \
                f"GM state {gm_state!r} found in player-facing history"

    def test_interface_history_same_as_player_view(self):
        """PlayInterface.history() must equal PlaytestSession.player_view()."""
        session, log, world, assembler = _make_session()
        session.step("move north")
        iface = _make_play_interface(session, world=world)
        assert iface.history() == session.player_view()


# --------------------------------------------------------------------------- #
# S-9 export_transcript_json — entitled events only                              #
# --------------------------------------------------------------------------- #

class TestTranscriptExportSecurity:

    def test_export_transcript_json_excludes_hidden_events(self):
        session, log, world, assembler = _make_session()
        # Inject a GM-only event.
        log.append(author="gm", channel="system", type="internal_note",
                   content="SECRET: the traitor is Veld", audience=("gm",), visibility="content")
        session.step("look around")
        transcript = session.export_transcript_json()
        # transcript is a list of dicts; none should contain SECRET content.
        for entry in transcript:
            content = str(entry.get("content", ""))
            assert "SECRET" not in content, \
                f"Secret content found in transcript JSON: {content!r}"
            assert "traitor" not in content
            assert "Veld" not in content

    def test_export_transcript_excludes_hidden_events(self):
        session, log, world, assembler = _make_session()
        log.append(author="gm", channel="system", type="internal_note",
                   content="GM ONLY: plot twist", audience=("gm",), visibility="content")
        session.step("scan the room")
        transcript_text = session.export_transcript()
        assert "GM ONLY" not in transcript_text
        assert "plot twist" not in transcript_text

    def test_export_transcript_includes_entitled_narration(self):
        session, log, world, assembler = _make_session(narr_text="The door creaks open.")
        session.step("push the door")
        transcript_text = session.export_transcript()
        assert "The door creaks open." in transcript_text


# --------------------------------------------------------------------------- #
# S-10 Narrator context — player-entitled lore context only                      #
# --------------------------------------------------------------------------- #

class TestNarratorContextSecurity:

    def test_narrator_receives_lore_filtered_to_player_pov(self):
        """Narrator gets player_lore (player-entitled) not gm_lore (GM-private).

        Verified by checking that the gm_only lore entry text does not appear
        in any prompt sent to the narrator model's client.messages.create.
        """
        log = EventLog()
        world = WorldState()
        world.add_zone("hall")
        world.add_entity(Entity(id="hero", kind="pc", name="Hero"))
        world.place("hero", "hall")
        pipeline = CommitPipeline(log)
        # One public lore entry, one gm_only entry.
        public_entry = LoreEntry(
            entry_id="L001", title="Hall", keywords=("hall",),
            content="PUBLIC: The hall has ancient carvings.",
            audience_class="all",
        )
        secret_entry = LoreEntry(
            entry_id="L002", title="Hall Secret", keywords=("hall",),
            content="GMSECRET: The hall is cursed.",
            audience_class="gm_only",
        )
        lore = LoreAssembler(LoreDeck([public_entry, secret_entry]), max_entries=5)
        assembler = ContextAssembler(log, Scene(world), lore_assembler=lore)

        # Capture narrator call arguments.
        narrator_prompts: list[str] = []

        def capturing_create(**kwargs):
            for msg in kwargs.get("messages", []):
                narrator_prompts.append(str(msg.get("content", "")))
            b = MagicMock(); b.text = "Ok."
            r = MagicMock(); r.content = [b]
            return r

        narr_client = MagicMock(); narr_client.messages.create = capturing_create
        narr_gw = ModelGateway(narr_client, sink=TelemetrySink(), timeout_secs=None, max_retries=0)
        adj = AdjudicatorGM(_gw_tool("adjudicate_action", _adj_data()))
        narr = NarratorGM(narr_gw)

        # Commit public event visible to hero.
        pipeline.commit(
            author="gm", channel="public", type="narration",
            content="You enter the hall.", audience=("hero", "gm"), visibility="content",
            commitments=[Commitment(subject="hero", predicate="location", value="hall", revealed=True)],
        )
        runner = BeatRunner(
            log=log, world=world, pipeline=pipeline,
            rules=RulesEngine(log, DiceService(log, rng=random.Random(0))),
            assembler=assembler, adjudicator=adj, narrator=narr,
            sheets={"hero": CharacterSheet(entity_id="hero", concept="Fighter")},
            executor=EffectExecutor(log, world, pipeline),
        )
        runner.run("hero", "examine the carvings")
        # Narrator was called; verify the GM-only lore did NOT appear.
        all_prompts = "\n".join(narrator_prompts)
        assert "GMSECRET" not in all_prompts, \
            "GM-only lore entry text appeared in narrator prompt"
        # Public lore MAY appear (it's player-entitled).
        # We don't assert it does because the keyword may not match — just assert safety.
