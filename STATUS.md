# Build Status

Descriptive tracker of what is *designed* vs. *actually built*. This file drifts fast and is deliberately separate from the normative design (CORE) so build churn never pollutes the spec. Update whenever implementation state changes, and log the change in `CHANGELOG.md`.

**Status values:** `Designed` (in CORE, not started) · `In progress` · `Built` (working) · `Validated` (meets the relevant success criterion in CORE §13).

## By roadmap phase

CORE §10 defines the phases and *why* they're ordered this way (dependency chain — the deterministic core must exist before anything can be honest or consistent).

| Phase | Component(s) | Status | Notes |
|---|---|---|---|
| 1 | Deterministic core + event log | Built (in-memory) | `src/fable_table_engine/`: Event model + append-only `EventLog` (assigns sequence/id/timestamp; refuses mechanical types without the rules/dice capability), `DiceService`, minimal `RulesEngine` (3d6+Skill vs TN → FABLE band, `fable_engine.md` §5), `WorldState` skeleton, and read-time audience/visibility projection (D-001 seed). All 6 acceptance contracts pass (`tests/test_phase1_contracts.py`); 24 tests total. **Pending:** SQLite persistence (plan step 6) — the log is in-memory only. |
| 2 | Access model + fact-extraction/commit | Built (in-memory) | `access.py`: `CommitPipeline` (sanctioned commit path; canon consistency-check before bind, CORE §6.1–6.2), canon ledger + committed-facts as pure folds over the log (D-009(b)), structural contradiction detection against *revealed* canon, and the logged `override` escape hatch (D-008). 11 tests (`tests/test_phase2_access.py`); 35 total. **Decisions in play:** D-007/008/009 still Open — code follows their MVP defaults (structured commitment blocks, not prose extraction). **Pending:** SQLite persistence (plan step 6). |
| 3 | Perception model | Built (in-memory) | `perception.py`: `Scene` (volatile sensory conditions — lighting, open/closed connections) over the `WorldState` zone graph (zones + adjacency + presence + intra-zone closeness Truths, all added to `world_state.py`). `perceivers`/`perception_map` compute who could sense a `Stimulus` (auditory by volume: whisper=close-only/in-zone, normal=zone, loud=+one open hop; visual=lit + line of sight); `derive_overhears` emits `may_have_perceived` events for unintended perceivers (neutral `perception` author, vague hint, `derived_from` the source). 12 functional + 14 adversarial stress tests (`tests/test_phase3_perception.py`, `…_stress.py`); 60 total + 1 xfail. Thin first cut (D-012) — fiction-positional (D-002), no coordinates. **Stress pass:** over-disclosure probes all hold (no whisper/loud/sight leak); fail-safe limitations pinned. **Found:** global-`sequence` side-channel leak (D-013, xfail-tracked) — a non-audience POV can infer hidden-event counts; fix deferred to phase 4. **Pending:** richer propagation (D-012); the D-013 fix; SQLite persistence. |
| 4 | Context assembly | Built (in-memory) | `context.py`: `ContextAssembler.belief_store(pov)` → `BeliefStore` (the POV's projected events + `beliefs` folded only from commitments it saw at content level — never the global canon, so revealed-elsewhere facts don't leak — + ambient `perceptible` entities via the perception model when a `Scene` is supplied). Belief stores are read-time projections (D-001), derived snapshots, never authoritative. **Resolved D-013** here: `project_for` now emits a per-POV contiguous index, closing the global-`sequence` side-channel (regression-tested). 9 tests (`tests/test_phase4_context.py`); 70 total. **Omits until later phases:** persona (6), disposition (10), memory. **Pending:** SQLite persistence. |
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
| Secret-keeping (whisper never leaks to non-audience) | Substantially covered (access path end-to-end) — projection secrecy (2) + perception's who-could-sense with no content/identity leak (3, stress-tested) + belief stores that exclude non-audience content and derive beliefs only from what the POV saw (4). The `sequence` side-channel is closed (D-013, resolved). Live validation pends the beat loop driving it (phase 7). |
| Spatial/causal consistency (no interaction across committed distance without traversal) | Partial — canon contradiction of a committed distance is blocked (phase 2), and perception now refuses sensing across a closed/non-adjacent connection (phase 3). Live enforcement against proposals still needs the auditor (8). |
| No over-rolling (stakes gate) | Not yet testable — needs phase 5. |
| Invisible improvisation (revisions never contradict canon ledger) | Not yet testable — needs phase 9. |
| Differential believability (teammates act on private info) | Partial — substrate built: two POVs assembled from one log demonstrably hold divergent beliefs (phase 4). Acting on private info needs character agents (6). |
| Responsiveness (per-beat budget) | Budget not yet set — see D-005. |
