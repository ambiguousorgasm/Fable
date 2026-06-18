# Build Status

Descriptive tracker of what is *designed* vs. *actually built*. This file drifts fast and is deliberately separate from the normative design (CORE) so build churn never pollutes the spec. Update whenever implementation state changes, and log the change in `CHANGELOG.md`.

**Status values:** `Designed` (in CORE, not started) · `In progress` · `Built` (working) · `Validated` (meets the relevant success criterion in CORE §13).

## By roadmap phase

CORE §10 defines the phases and *why* they're ordered this way (dependency chain — the deterministic core must exist before anything can be honest or consistent).

| Phase | Component(s) | Status | Notes |
|---|---|---|---|
| 1 | Deterministic core + event log | Built (in-memory) | `src/fable_table_engine/`: Event model + append-only `EventLog` (assigns sequence/id/timestamp; refuses mechanical types without the rules/dice capability), `DiceService`, minimal `RulesEngine` (3d6+Skill vs TN → FABLE band, `fable_engine.md` §5), `WorldState` skeleton, and read-time audience/visibility projection (D-001 seed). All 6 acceptance contracts pass (`tests/test_phase1_contracts.py`); 24 tests total. **Pending:** SQLite persistence (plan step 6) — the log is in-memory only. |
| 2 | Access model + fact-extraction/commit | Built (in-memory) | `access.py`: `CommitPipeline` (sanctioned commit path; canon consistency-check before bind, CORE §6.1–6.2), canon ledger + committed-facts as pure folds over the log (D-009(b)), structural contradiction detection against *revealed* canon, and the logged `override` escape hatch (D-008). 11 tests (`tests/test_phase2_access.py`); 35 total. **Decisions in play:** D-007/008/009 still Open — code follows their MVP defaults (structured commitment blocks, not prose extraction). **Pending:** SQLite persistence (plan step 6). |
| 3 | Perception model | Designed | The load-bearing wall. Prototype early and stress-test. Operates over the zone graph + relational position Truths (fiction-positional, D-002), not coordinates. Nothing in the current substrate covers this. |
| 4 | Context assembly | Designed | Per-POV view construction / belief-store projections. |
| 5 | Cold/warm GM split | Designed | Adjudicator + stakes gate + narrator + world-simulator. Highest-leverage for "lifelike" feel. |
| 6 | Character agents | Designed | Persona + goals + belief store, one per teammate. |
| 7 | Orchestrator / spotlight | Partial substrate | Director-pattern turn routing with `[SPOTLIGHT:]` tags exists in the playtest harness; TTS turn-gating partially explored. Needs port into this architecture. Drains the transient action queue (proposal buffer) it arbitrates. |
| 8 | Auditor | Designed | Live validation gates against committed state. Conceptually an extension of existing FABLE validation-gate testing, run live. Override is a logged `override` event the auditor reads as fiat, not a bug (authority open: D-008). |
| 9 | Plot-manager | Designed | Function/fixture re-binding, hidden-graph revision, interest signals. |
| 10 | Disposition system | Designed | Multi-axis graph, event-derived deltas; couples through Edge/Bonds — no passive modifier, no separate currency (D-004, Resolved). The disposition engine is the authoritative delta-writer; trigger-recognition mechanism open (D-011). |
| 11 | Interface + voice | Partial substrate | React/TypeScript front end and ElevenLabs TTS exist in current implementations; per-character channels/whisper/OOC need building to spec. |

## Existing substrate (starting point, not yet to spec)

- **FABLE_AI_Engine** — FastAPI + SQLite + React/TypeScript. Closest existing base for the deterministic core and interface, but predates this blueprint's access model and GM decomposition.
- **Playtest harness** (`momentum-table` lineage) — Python, director-pattern routing via `[SPOTLIGHT:]` tags, per-character ElevenLabs TTS, browser GUI. Source of the orchestration and voice patterns; not built around belief stores or the determinism boundary.

These are *substrate*, not compliance — where they conflict with CORE, CORE is the target.

## Validation against CORE §13 success criteria

| Criterion | State |
|---|---|
| Secret-keeping (whisper never leaks to non-audience) | Partial — commitment-level secrecy holds via the audience/visibility projection (phase 2 test); full criterion needs perception (3) + context assembly (4). |
| Spatial/causal consistency (no interaction across committed distance without traversal) | Partial — silently contradicting a committed distance is now blocked by the canon consistency-check (phase 2); the traversal/interaction half needs perception (3) + auditor (8). |
| No over-rolling (stakes gate) | Not yet testable — needs phase 5. |
| Invisible improvisation (revisions never contradict canon ledger) | Not yet testable — needs phase 9. |
| Differential believability (teammates act on private info) | Not yet testable — needs phases 4–6. |
| Responsiveness (per-beat budget) | Budget not yet set — see D-005. |
