# Implementation Plan

This file converts the CORE roadmap into concrete coding milestones. `STATUS.md` tracks build state; this file defines what to build next.

---

## Current milestone: Phase 1 — Deterministic core + event log

### Goal

Create the smallest working deterministic substrate for the FABLE Table Engine.

The first milestone should make the project capable of recording authoritative events, logging dice, storing minimal world state, and proving that model-generated narration cannot bypass deterministic truth.

### Deliverables

- Event model.
- Append-only event log.
- World-state skeleton.
- Dice service.
- Minimal rules-engine interface.
- Audience and visibility fields on every event.
- Tests for event ordering, append-only behavior, dice logging, and audience filtering.

### Non-goals

- No GM agent.
- No teammate agents.
- No NPC-manager.
- No plot-manager.
- No TTS.
- No polished UI.
- No elaborate FABLE rules implementation beyond the minimal interface required to preserve the determinism boundary.

### Acceptance tests

- Events append with monotonically increasing sequence IDs.
- Events include author, channel, audience, visibility, type, content, commitments, and derived_from.
- Existing events cannot be silently mutated through the normal API.
- Dice rolls are logged as events.
- A model-facing outcome cannot be committed unless it came through the rules/dice path or is logged as a non-mechanical declaration.
- Audience filtering can exclude event content from non-audience entities while preserving permitted metadata if configured.

### Suggested first coding pass

0. Ensure the local environment exists: `python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"` (see `README.md` → Setup). Run all project commands through `./.venv/bin/python`.
1. Create a Python package under `src/fable_table_engine/`.
2. Define event dataclasses or Pydantic models.
3. Implement an in-memory append-only event log.
4. Implement a dice service that writes dice events into the log.
5. Add pytest tests for event append and dice logging.
6. Only then introduce persistence, likely SQLite.

---

## Phase 2 — Access model + commit boundary

### Goal

Make the event log enforce differential information and the declaration→commit→canon lifecycle.

### Deliverables

- Audience/visibility projection function.
- Initial canon-ledger view over committed-and-disclosed events.
- Commitment object schema.
- Conflict detection stub.
- Tests for whisper secrecy and canonical contradiction detection.

### MVP defaults

- Belief stores are read-time projections with optional cache.
- Canon ledger is a view over the event log unless performance requires materialization.
- Structured commitment blocks are preferred for the MVP because they are easier to validate than post-hoc extraction.

---

## Phase 3 — Perception model prototype

### Goal

Create the first deterministic mechanism for deciding who could perceive an event.

### Deliverables

- Presence model.
- Simple audibility/visibility rules.
- Derived `may-have-perceived` events.
- Tests for whisper/noise/line-of-sight scenarios.

---

## Working rule

Do not build a sophisticated agent layer until phases 1–4 are testable. The project exists to defeat omniscience collapse and incoherent multi-agent networks; that requires the deterministic core and access model first.
