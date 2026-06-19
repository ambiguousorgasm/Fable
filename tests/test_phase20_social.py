"""Phase 20 tests — Social Interpretation and Bond Compels.

Covers: BondRef, GainEdge, SpendEdge, SocialInterpreter (mock gateway),
ModelCallError/retry, resolve_compel, and integrity invariants.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from fable_table_engine import (
    BondRef,
    CharacterSheet,
    CompelResolution,
    COMPEL_AUTHOR,
    EDGE_CAP,
    EffectExecutor,
    EffectResult,
    EventLog,
    GainEdge,
    ModelCallError,
    ModelGateway,
    PendingCompel,
    SocialInterpreter,
    SpendEdge,
    TelemetrySink,
    WorldState,
    resolve_compel,
)
from fable_table_engine.access import CommitPipeline
from fable_table_engine.character_sheet import BondRef
from fable_table_engine.disposition import DispositionAxis, DispositionDelta
from fable_table_engine.effects import EDGE_CAP, describe_effect, effect_from_dict
from fable_table_engine.world_state import Entity


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _make_log() -> EventLog:
    log = EventLog()
    log.append(author="gm", channel="system", type="scene_open",
                content="test", audience=("gm", "player"))
    return log


def _make_world(*entity_ids: str) -> WorldState:
    world = WorldState()
    if entity_ids:
        world.add_zone("hall")
    for eid in entity_ids:
        world.add_entity(Entity(id=eid, kind="character", name=eid, resources={}))
        world.place(eid, "hall")
    return world


def _make_executor(log: EventLog, world: WorldState) -> EffectExecutor:
    pipeline = CommitPipeline(log)
    return EffectExecutor(log, world, pipeline)


def _seed_edge(world: WorldState, entity_id: str, amount: int) -> None:
    entity = world.entities[entity_id]
    entity.resources["edge"] = amount
    world.update_entity(entity)


def _tool_block(name: str, input_: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_
    return block


def _fake_response(*blocks) -> MagicMock:
    resp = MagicMock()
    resp.content = list(blocks)
    resp.usage = None
    return resp


def _make_event(log: EventLog, *, author: str = "npc", content: str = "said something") -> object:
    return log.append(author=author, channel="public", type="speech",
                      content=content, audience=("gm", "player", "npc"))


# --------------------------------------------------------------------------- #
# BondRef                                                                       #
# --------------------------------------------------------------------------- #

class TestBondRef:
    def test_valid(self):
        b = BondRef(bond_id="b1", character_id="hero", description="Bond with Mira")
        assert b.bond_id == "b1"
        assert b.commitment_id is None

    def test_with_commitment(self):
        b = BondRef(bond_id="b1", character_id="hero", description="Bond with Mira",
                    commitment_id="evt-abc")
        assert b.commitment_id == "evt-abc"

    def test_empty_bond_id_rejected(self):
        with pytest.raises(ValueError):
            BondRef(bond_id="", character_id="hero", description="Bond with Mira")

    def test_empty_character_id_rejected(self):
        with pytest.raises(ValueError):
            BondRef(bond_id="b1", character_id="", description="Bond with Mira")

    def test_empty_description_rejected(self):
        with pytest.raises(ValueError):
            BondRef(bond_id="b1", character_id="hero", description="")

    def test_frozen(self):
        b = BondRef(bond_id="b1", character_id="hero", description="Bond with Mira")
        with pytest.raises((AttributeError, TypeError)):
            b.bond_id = "other"  # type: ignore

    def test_character_sheet_carries_bond_refs(self):
        b = BondRef(bond_id="b1", character_id="hero", description="Bond with Mira")
        sheet = CharacterSheet(
            entity_id="hero", concept="knight",
            bonds=["Mira"], bond_refs=[b],
        )
        assert sheet.bond_refs[0].bond_id == "b1"
        assert sheet.bonds == ["Mira"]  # backward compat preserved


# --------------------------------------------------------------------------- #
# GainEdge                                                                      #
# --------------------------------------------------------------------------- #

class TestGainEdge:
    def test_gain_from_zero(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        result = ex.apply(GainEdge(kind="gain_edge", entity_id="hero", amount=1),
                          audience=("gm", "player"))
        assert result.accepted
        assert world.entities["hero"].resources["edge"] == 1

    def test_cap_enforced(self):
        log = _make_log()
        world = _make_world("hero")
        _seed_edge(world, "hero", 2)
        ex = _make_executor(log, world)
        ex.apply(GainEdge(kind="gain_edge", entity_id="hero", amount=3),
                 audience=("gm", "player"))
        assert world.entities["hero"].resources["edge"] == EDGE_CAP

    def test_already_at_cap_accepted_but_no_change(self):
        log = _make_log()
        world = _make_world("hero")
        _seed_edge(world, "hero", EDGE_CAP)
        ex = _make_executor(log, world)
        result = ex.apply(GainEdge(kind="gain_edge", entity_id="hero", amount=1),
                          audience=("gm", "player"))
        assert result.accepted
        assert world.entities["hero"].resources["edge"] == EDGE_CAP

    def test_unknown_entity_rejected(self):
        log = _make_log()
        world = _make_world()
        ex = _make_executor(log, world)
        result = ex.apply(GainEdge(kind="gain_edge", entity_id="ghost", amount=1),
                          audience=("gm",))
        assert not result.accepted
        assert "not found" in result.rejection_reason

    def test_zero_amount_rejected(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        result = ex.apply(GainEdge(kind="gain_edge", entity_id="hero", amount=0),
                          audience=("gm",))
        assert not result.accepted

    def test_logs_provenance_event(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        before = len(log)
        ex.apply(GainEdge(kind="gain_edge", entity_id="hero", amount=1),
                 audience=("gm", "player"))
        assert len(log) == before + 1

    def test_effect_from_dict_roundtrip(self):
        d = {"kind": "gain_edge", "entity_id": "hero", "amount": 2}
        effect = effect_from_dict(d)
        assert isinstance(effect, GainEdge)
        assert effect.amount == 2

    def test_describe_effect(self):
        desc = describe_effect(GainEdge(kind="gain_edge", entity_id="hero", amount=1))
        assert "Edge" in desc
        assert "hero" in desc


# --------------------------------------------------------------------------- #
# SpendEdge                                                                     #
# --------------------------------------------------------------------------- #

class TestSpendEdge:
    def test_spend_succeeds(self):
        log = _make_log()
        world = _make_world("hero")
        _seed_edge(world, "hero", 2)
        ex = _make_executor(log, world)
        result = ex.apply(SpendEdge(kind="spend_edge", entity_id="hero", amount=1),
                          audience=("gm",))
        assert result.accepted
        assert world.entities["hero"].resources["edge"] == 1

    def test_spend_insufficient_rejected(self):
        log = _make_log()
        world = _make_world("hero")
        _seed_edge(world, "hero", 0)
        ex = _make_executor(log, world)
        result = ex.apply(SpendEdge(kind="spend_edge", entity_id="hero", amount=1),
                          audience=("gm",))
        assert not result.accepted
        assert "insufficient" in result.rejection_reason

    def test_spend_zero_rejected(self):
        log = _make_log()
        world = _make_world("hero")
        _seed_edge(world, "hero", 2)
        ex = _make_executor(log, world)
        result = ex.apply(SpendEdge(kind="spend_edge", entity_id="hero", amount=0),
                          audience=("gm",))
        assert not result.accepted

    def test_spend_type_logged(self):
        log = _make_log()
        world = _make_world("hero")
        _seed_edge(world, "hero", 2)
        ex = _make_executor(log, world)
        result = ex.apply(SpendEdge(kind="spend_edge", entity_id="hero", amount=1, spend_type="shield"),
                          audience=("gm",))
        assert result.accepted
        last = log.all()[-1]
        assert "shield" in last.content

    def test_effect_from_dict_roundtrip(self):
        d = {"kind": "spend_edge", "entity_id": "hero", "amount": 1, "spend_type": "push"}
        effect = effect_from_dict(d)
        assert isinstance(effect, SpendEdge)
        assert effect.spend_type == "push"

    def test_describe_effect(self):
        desc = describe_effect(SpendEdge(kind="spend_edge", entity_id="hero", amount=1, spend_type="lean"))
        assert "Edge" in desc
        assert "lean" in desc


# --------------------------------------------------------------------------- #
# ModelGateway retry / timeout                                                  #
# --------------------------------------------------------------------------- #

class TestModelGatewayRetry:
    def _make_client(self, side_effects):
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = MagicMock(side_effect=side_effects)
        return client

    def test_success_first_try(self):
        resp = MagicMock()
        resp.usage = None
        client = self._make_client([resp])
        gw = ModelGateway(client, timeout_secs=None, max_retries=1)
        result = gw.call("test", model="claude-sonnet-4-6", max_tokens=10,
                         messages=[{"role": "user", "content": "hi"}])
        assert result is resp
        assert client.messages.create.call_count == 1

    def test_retry_on_timeout_then_success(self):
        resp = MagicMock()
        resp.usage = None
        timeout_exc = MagicMock(spec=Exception)
        import anthropic as ant
        timeout_err = ant.APITimeoutError(request=MagicMock())
        client = self._make_client([timeout_err, resp])
        gw = ModelGateway(client, timeout_secs=None, max_retries=1)
        with patch("time.sleep"):
            result = gw.call("test", model="claude-sonnet-4-6", max_tokens=10,
                             messages=[{"role": "user", "content": "hi"}])
        assert result is resp
        assert client.messages.create.call_count == 2

    def test_raises_model_call_error_after_all_retries(self):
        import anthropic as ant
        timeout_err = ant.APITimeoutError(request=MagicMock())
        client = self._make_client([timeout_err, timeout_err])
        gw = ModelGateway(client, timeout_secs=None, max_retries=1)
        with patch("time.sleep"):
            with pytest.raises(ModelCallError) as exc_info:
                gw.call("gm", model="claude-sonnet-4-6", max_tokens=10,
                        messages=[{"role": "user", "content": "hi"}])
        assert exc_info.value.role == "gm"
        assert exc_info.value.attempts == 2

    def test_no_retry_on_non_transient_error(self):
        import anthropic as ant
        api_err = ant.BadRequestError(
            message="bad", response=MagicMock(), body={}
        )
        client = self._make_client([api_err])
        gw = ModelGateway(client, timeout_secs=None, max_retries=1)
        with pytest.raises(ant.BadRequestError):
            gw.call("gm", model="claude-sonnet-4-6", max_tokens=10,
                    messages=[{"role": "user", "content": "hi"}])
        assert client.messages.create.call_count == 1

    def test_failed_attempt_recorded_in_telemetry(self):
        import anthropic as ant
        timeout_err = ant.APITimeoutError(request=MagicMock())
        client = self._make_client([timeout_err, timeout_err])
        sink = TelemetrySink()
        gw = ModelGateway(client, sink=sink, timeout_secs=None, max_retries=1)
        with patch("time.sleep"):
            with pytest.raises(ModelCallError):
                gw.call("gm", model="claude-sonnet-4-6", max_tokens=10,
                        messages=[{"role": "user", "content": "hi"}])
        # Both failed attempts should be recorded
        assert len(sink.records) == 2
        assert all(r.input_tokens == 0 for r in sink.records)

    def test_timeout_forwarded_to_sdk(self):
        resp = MagicMock()
        resp.usage = None
        client = self._make_client([resp])
        gw = ModelGateway(client, timeout_secs=30.0, max_retries=0)
        gw.call("test", model="claude-sonnet-4-6", max_tokens=10,
                messages=[{"role": "user", "content": "hi"}])
        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs.get("timeout") == 30.0

    def test_caller_timeout_not_overridden(self):
        resp = MagicMock()
        resp.usage = None
        client = self._make_client([resp])
        gw = ModelGateway(client, timeout_secs=30.0, max_retries=0)
        gw.call("test", model="claude-sonnet-4-6", max_tokens=10, timeout=5.0,
                messages=[{"role": "user", "content": "hi"}])
        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs.get("timeout") == 5.0  # caller wins via setdefault


# --------------------------------------------------------------------------- #
# SocialInterpreter (mock gateway)                                              #
# --------------------------------------------------------------------------- #

class TestSocialInterpreter:
    def _bond(self, bond_id: str = "bond-1", char_id: str = "hero",
              desc: str = "Bond with Mira") -> BondRef:
        return BondRef(bond_id=bond_id, character_id=char_id, description=desc)

    def _gateway_returning(self, *blocks) -> ModelGateway:
        resp = _fake_response(*blocks)
        client = MagicMock()
        client.messages.create = MagicMock(return_value=resp)
        sink = TelemetrySink()
        return ModelGateway(client, sink=sink, timeout_secs=None, max_retries=0)

    def _make_event(self) -> object:
        log = EventLog()
        return log.append(author="npc", channel="public", type="speech",
                          content="You helped me before.", audience=("gm", "hero", "npc"))

    def test_no_tool_calls_returns_empty(self):
        gw = self._gateway_returning()
        interp = SocialInterpreter(gw)
        event = self._make_event()
        deltas, compels = interp.analyze_event(
            event, "", {"hero": []}, {"hero", "npc"},
        )
        assert deltas == []
        assert compels == []

    def test_valid_delta_proposal_accepted(self):
        block = _tool_block("propose_social_delta", {
            "from_id": "npc", "to_id": "hero", "axis": "trust", "delta": 1,
            "reason": "hero helped in the market",
        })
        gw = self._gateway_returning(block)
        interp = SocialInterpreter(gw)
        event = self._make_event()
        deltas, compels = interp.analyze_event(
            event, "", {}, {"hero", "npc"},
        )
        assert len(deltas) == 1
        d = deltas[0]
        assert d.from_id == "npc"
        assert d.to_id == "hero"
        assert d.axis == DispositionAxis.TRUST
        assert d.delta == 1
        assert d.causal_event_id == event.id

    def test_delta_unknown_entity_rejected(self):
        block = _tool_block("propose_social_delta", {
            "from_id": "ghost", "to_id": "hero", "axis": "trust", "delta": 1, "reason": "x",
        })
        gw = self._gateway_returning(block)
        interp = SocialInterpreter(gw)
        event = self._make_event()
        deltas, _ = interp.analyze_event(event, "", {}, {"hero", "npc"})
        assert deltas == []

    def test_delta_zero_rejected(self):
        block = _tool_block("propose_social_delta", {
            "from_id": "npc", "to_id": "hero", "axis": "respect", "delta": 0, "reason": "none",
        })
        gw = self._gateway_returning(block)
        interp = SocialInterpreter(gw)
        event = self._make_event()
        deltas, _ = interp.analyze_event(event, "", {}, {"hero", "npc"})
        assert deltas == []

    def test_delta_self_reference_rejected(self):
        block = _tool_block("propose_social_delta", {
            "from_id": "hero", "to_id": "hero", "axis": "trust", "delta": 1, "reason": "self",
        })
        gw = self._gateway_returning(block)
        interp = SocialInterpreter(gw)
        event = self._make_event()
        deltas, _ = interp.analyze_event(event, "", {}, {"hero", "npc"})
        assert deltas == []

    def test_valid_compel_accepted(self):
        bond = self._bond()
        block = _tool_block("propose_compel", {
            "bond_id": "bond-1",
            "target_character_id": "hero",
            "source_entity": "npc",
            "pressure_description": "Your Bond with Mira puts you in an awkward position.",
            "accept_consequence": "Accepting means losing travel time.",
            "refuse_note": "Refusing may be noticed.",
        })
        gw = self._gateway_returning(block)
        interp = SocialInterpreter(gw)
        event = self._make_event()
        _, compels = interp.analyze_event(
            event, "", {"hero": [bond]}, {"hero", "npc"},
        )
        assert len(compels) == 1
        c = compels[0]
        assert c.bond_ref.bond_id == "bond-1"
        assert c.target_character_id == "hero"
        assert c.compel_proposed_event_id == event.id

    def test_compel_unknown_bond_rejected(self):
        bond = self._bond(bond_id="bond-1")
        block = _tool_block("propose_compel", {
            "bond_id": "bond-99",  # not in character_bonds
            "target_character_id": "hero",
            "source_entity": "npc",
            "pressure_description": "Pressure.",
            "accept_consequence": "Cost.",
        })
        gw = self._gateway_returning(block)
        interp = SocialInterpreter(gw)
        event = self._make_event()
        _, compels = interp.analyze_event(
            event, "", {"hero": [bond]}, {"hero", "npc"},
        )
        assert compels == []

    def test_compel_interiority_in_pressure_rejected(self):
        bond = self._bond()
        block = _tool_block("propose_compel", {
            "bond_id": "bond-1",
            "target_character_id": "hero",
            "source_entity": "npc",
            "pressure_description": "You feel guilty about this.",  # interiority!
            "accept_consequence": "Cost.",
        })
        gw = self._gateway_returning(block)
        interp = SocialInterpreter(gw)
        event = self._make_event()
        _, compels = interp.analyze_event(
            event, "", {"hero": [bond]}, {"hero", "npc"},
        )
        assert compels == []

    def test_compel_interiority_in_consequence_rejected(self):
        bond = self._bond()
        block = _tool_block("propose_compel", {
            "bond_id": "bond-1",
            "target_character_id": "hero",
            "source_entity": "npc",
            "pressure_description": "External situation.",
            "accept_consequence": "You feel obligated to stay.",  # interiority!
        })
        gw = self._gateway_returning(block)
        interp = SocialInterpreter(gw)
        event = self._make_event()
        _, compels = interp.analyze_event(
            event, "", {"hero": [bond]}, {"hero", "npc"},
        )
        assert compels == []

    def test_model_failure_returns_empty(self):
        import anthropic as ant
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = MagicMock(
            side_effect=ant.APITimeoutError(request=MagicMock())
        )
        gw = ModelGateway.__new__(ModelGateway)
        gw._client = client
        gw.sink = TelemetrySink()
        gw.timeout_secs = None
        gw.max_retries = 0
        interp = SocialInterpreter(gw)
        event = self._make_event()
        deltas, compels = interp.analyze_event(event, "", {}, {"hero", "npc"})
        assert deltas == []
        assert compels == []

    def test_non_tool_blocks_ignored(self):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Nothing to propose."
        gw = self._gateway_returning(text_block)
        interp = SocialInterpreter(gw)
        event = self._make_event()
        deltas, compels = interp.analyze_event(event, "", {}, {"hero", "npc"})
        assert deltas == []
        assert compels == []


# --------------------------------------------------------------------------- #
# resolve_compel                                                                 #
# --------------------------------------------------------------------------- #

class TestResolveCompel:
    def _pending(self, log: EventLog) -> PendingCompel:
        bond = BondRef(bond_id="b1", character_id="hero", description="Bond with Mira")
        proposed_event = log.append(
            author="npc", channel="public", type="speech",
            content="Tension.", audience=("gm", "hero", "npc"),
        )
        return PendingCompel(
            compel_id="cmp-1",
            bond_ref=bond,
            pressure_description="Your Bond puts you in a difficult position.",
            accept_consequence="Accepting means losing time.",
            refuse_note="Refusing may be noticed.",
            proposed_accept_effects=(),
            compel_proposed_event_id=proposed_event.id,
            source_entity="npc",
            target_character_id="hero",
        )

    def test_accept_logs_accepted_and_resolved(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        pending = self._pending(log)
        before = len(log)
        resolution = resolve_compel(pending, True, log, ex, audience=("gm", "hero"))
        assert resolution.accepted
        assert resolution.compel_accepted_event_id is not None
        assert resolution.compel_refused_event_id is None
        # Should log: compel_accepted + effect_applied (GainEdge) + compel_resolved
        assert len(log) >= before + 3

    def test_accept_grants_edge(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        pending = self._pending(log)
        resolve_compel(pending, True, log, ex, audience=("gm", "hero"))
        assert world.entities["hero"].resources["edge"] == 1

    def test_accept_edge_gain_is_EffectResult(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        pending = self._pending(log)
        resolution = resolve_compel(pending, True, log, ex, audience=("gm", "hero"))
        assert len(resolution.applied_effects) >= 1
        assert isinstance(resolution.applied_effects[0], EffectResult)
        assert resolution.applied_effects[0].accepted

    def test_refuse_logs_refused_and_resolved(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        pending = self._pending(log)
        resolution = resolve_compel(pending, False, log, ex, audience=("gm", "hero"))
        assert not resolution.accepted
        assert resolution.compel_refused_event_id is not None
        assert resolution.compel_accepted_event_id is None

    def test_refuse_no_edge_gain(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        pending = self._pending(log)
        resolve_compel(pending, False, log, ex, audience=("gm", "hero"))
        assert world.entities["hero"].resources.get("edge", 0) == 0

    def test_refuse_no_effects_applied(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        pending = self._pending(log)
        resolution = resolve_compel(pending, False, log, ex, audience=("gm", "hero"))
        assert resolution.applied_effects == []

    def test_accept_without_executor_no_edge(self):
        log = _make_log()
        world = _make_world("hero")
        pending = self._pending(log)
        resolution = resolve_compel(pending, True, log, None, audience=("gm", "hero"))
        assert resolution.accepted
        assert resolution.applied_effects == []

    def test_compel_resolved_event_author(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        pending = self._pending(log)
        resolve_compel(pending, True, log, ex, audience=("gm", "hero"))
        events = log.all()
        resolved = [e for e in events if e.type == "compel_resolved"]
        assert resolved
        assert resolved[-1].author == COMPEL_AUTHOR

    def test_source_event_id_forwarded(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        pending = self._pending(log)
        src = log.append(author="gm", channel="system", type="beat_start",
                         content="x", audience=("gm",))
        resolution = resolve_compel(pending, True, log, ex, audience=("gm", "hero"),
                                    source_event_id=src.id)
        accepted_evt = next(e for e in log.all() if e.id == resolution.compel_accepted_event_id)
        assert src.id in accepted_evt.derived_from

    def test_pending_compel_is_frozen(self):
        log = _make_log()
        pending = self._pending(log)
        with pytest.raises((AttributeError, TypeError)):
            pending.target_character_id = "other"  # type: ignore


# --------------------------------------------------------------------------- #
# Integrity invariants                                                           #
# --------------------------------------------------------------------------- #

class TestIntegrityInvariants:
    def test_social_interpreter_does_not_write_log(self):
        log = EventLog()
        bond = BondRef(bond_id="b1", character_id="hero", description="Bond with Mira")
        event = log.append(author="npc", channel="public", type="speech",
                           content="hello", audience=("gm", "hero", "npc"))
        before = len(log)

        block = _tool_block("propose_social_delta", {
            "from_id": "npc", "to_id": "hero", "axis": "trust", "delta": 1, "reason": "x",
        })
        resp = _fake_response(block)
        client = MagicMock()
        client.messages.create = MagicMock(return_value=resp)
        gw = ModelGateway.__new__(ModelGateway)
        gw._client = client
        gw.sink = TelemetrySink()
        gw.timeout_secs = None
        gw.max_retries = 0

        interp = SocialInterpreter(gw)
        interp.analyze_event(event, "", {"hero": [bond]}, {"hero", "npc"})
        assert len(log) == before  # no events written

    def test_edge_cap_never_exceeded(self):
        log = _make_log()
        world = _make_world("hero")
        _seed_edge(world, "hero", EDGE_CAP)
        ex = _make_executor(log, world)
        for _ in range(5):
            ex.apply(GainEdge(kind="gain_edge", entity_id="hero", amount=2),
                     audience=("gm",))
        assert world.entities["hero"].resources["edge"] <= EDGE_CAP

    def test_compel_events_derive_from_proposal(self):
        log = _make_log()
        world = _make_world("hero")
        ex = _make_executor(log, world)
        bond = BondRef(bond_id="b1", character_id="hero", description="Bond with Mira")
        proposed = log.append(author="npc", channel="public", type="speech",
                              content="Tension.", audience=("gm", "hero", "npc"))
        pending = PendingCompel(
            compel_id="cmp-1",
            bond_ref=bond,
            pressure_description="External pressure.",
            accept_consequence="Costs time.",
            refuse_note="May be noticed.",
            proposed_accept_effects=(),
            compel_proposed_event_id=proposed.id,
            source_entity="npc",
            target_character_id="hero",
        )
        resolution = resolve_compel(pending, True, log, ex, audience=("gm", "hero"))
        accepted_evt = next(e for e in log.all() if e.id == resolution.compel_accepted_event_id)
        assert proposed.id in accepted_evt.derived_from
