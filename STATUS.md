# Build Status

Descriptive tracker of what is *designed* vs. *actually built*. This file drifts fast and is deliberately separate from the normative design (CORE) so build churn never pollutes the spec. Update whenever implementation state changes, and log the change in `CHANGELOG.md`.

**Status values:** `Designed` (in CORE, not started) · `In progress` · `Built` (working) · `Validated` (meets the relevant success criterion in CORE §13).

## By roadmap phase

CORE §10 defines the phases and *why* they're ordered this way (dependency chain — the deterministic core must exist before anything can be honest or consistent).

| Phase | Component(s) | Status | Notes |
|---|---|---|---|
| 1 | Deterministic core + event log | Designed | World state, rules engine, dice, event log with audience/visibility schema. Existing FastAPI + SQLite substrate partially covers state + persistence. |
| 2 | Access model + fact-extraction/commit | Designed | Audience tagging, commit pipeline, canon ledger, consistency check. Fact-extraction approach unresolved (D-007). |
| 3 | Perception model | Designed | The load-bearing wall. Prototype early and stress-test. Nothing in the current substrate covers this. |
| 4 | Context assembly | Designed | Per-POV view construction / belief-store projections. |
| 5 | Cold/warm GM split | Designed | Adjudicator + stakes gate + narrator + world-simulator. Highest-leverage for "lifelike" feel. |
| 6 | Character agents | Designed | Persona + goals + belief store, one per teammate. |
| 7 | Orchestrator / spotlight | Partial substrate | Director-pattern turn routing with `[SPOTLIGHT:]` tags exists in the playtest harness; TTS turn-gating partially explored. Needs port into this architecture. |
| 8 | Auditor | Designed | Live validation gates against committed state. Conceptually an extension of existing FABLE validation-gate testing, run live. |
| 9 | Plot-manager | Designed | Function/fixture re-binding, hidden-graph revision, interest signals. |
| 10 | Disposition system | Designed | Multi-axis graph, event-derived deltas, Strings coupling (D-004). |
| 11 | Interface + voice | Partial substrate | React/TypeScript front end and ElevenLabs TTS exist in current implementations; per-character channels/whisper/OOC need building to spec. |

## Existing substrate (starting point, not yet to spec)

- **FABLE_AI_Engine** — FastAPI + SQLite + React/TypeScript. Closest existing base for the deterministic core and interface, but predates this blueprint's access model and GM decomposition.
- **Playtest harness** (`momentum-table` lineage) — Python, director-pattern routing via `[SPOTLIGHT:]` tags, per-character ElevenLabs TTS, browser GUI. Source of the orchestration and voice patterns; not built around belief stores or the determinism boundary.

These are *substrate*, not compliance — where they conflict with CORE, CORE is the target.

## Validation against CORE §13 success criteria

| Criterion | State |
|---|---|
| Secret-keeping (whisper never leaks to non-audience) | Not yet testable — needs phases 1–4. |
| Spatial/causal consistency (no interaction across committed distance without traversal) | Not yet testable — needs phases 1–2, 8. |
| No over-rolling (stakes gate) | Not yet testable — needs phase 5. |
| Invisible improvisation (revisions never contradict canon ledger) | Not yet testable — needs phase 9. |
| Differential believability (teammates act on private info) | Not yet testable — needs phases 4–6. |
| Responsiveness (per-beat budget) | Budget not yet set — see D-005. |
