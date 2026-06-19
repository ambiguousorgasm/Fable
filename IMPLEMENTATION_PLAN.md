# Implementation Plan

This file converts the CORE roadmap into concrete coding milestones. `STATUS.md` tracks build state; this file defines what to build next.

Roadmap source: `uploads/f.md`, adopted 2026-06-18. The original three-phase tail (old Phase 9 plot-manager, Phase 10 disposition, Phase 11 interface) is replaced by a 14-phase stabilization plan (Phases 9–22). The old phases are renumbered: old Phase 9 → Phase 18, old Phase 10 → Phase 19, old Phase 11 → Phase 21.

See `uploads/f.md` for the full phase specs, adversarial acceptance tests, exit gates, and operating rules. This file tracks the current milestone and dependency order; `STATUS.md` tracks build state.

---

## Phases 1–20: Built

695 tests pass. See `STATUS.md` for per-phase build notes.

| Phase | Core deliverable |
|---|---|
| 1 | Event model, append-only `EventLog`, `DiceService`, minimal `RulesEngine`, `WorldState` skeleton, `SQLiteEventLog` |
| 2 | `CommitPipeline`, canon ledger, canon contradiction detection; D-007/D-008/D-009 resolved |
| 3 | `Scene`, perception model (auditory + visual), `derive_overhears`, zone graph |
| 4 | `ContextAssembler`, `BeliefStore`, per-POV contiguous index (D-013 resolved) |
| 5 | `CharacterSheet`, `AdjudicatorGM`, `NarratorGM`, `WorldSimulator`, `BeatRunner` (beat loop steps 2–9) |
| 6 | `PersonaSpec`, `Proposal`, `CharacterAgent`, differential-knowledge tests |
| 7 | `ActionQueue`, `Orchestrator` (SPOTLIGHT/INITIATIVE), `run_with_agent`, `run_round` |
| 8 | `Auditor` (pre-commit + post-narration hooks), `AuditTier`, `BeatResult.audit_flags` / `beat_aborted` |
| 9 | `DeliveryScope`, `_resolve_delivery`, OOC bypass, narrator context filtering, 28 adversarial delivery tests (D-033 resolved) |
| 10 | `SQLiteEventLog.transaction()` (D-023 atomic beat), `SQLiteScene` (fail-closed restart), `BeatRunner` wrapped in transaction, beat rollback on post-audit block, scene/world restart tests |
| 11 | `Commitment.epistemic_type` / `asserting_entity` / `observing_entity` (D-024), `committed_facts()` / `canon_ledger()` fact-only filter, `BeliefStore.claims` + `observations`, `ContextAssembler._fold_epistemic()` |
| 12 | `EffectExecutor` + 10 typed operations (CreateTruth → ExpireMaintainedTruth), `WorldState.maintained_truths`, `BeatRunner.executor` param, `"expired"` epistemic tombstone |
| 13 | `ResolutionPlan` (consequence palette, trade fields, triumph_effects), `_apply_trade()`, palette effect application inside transaction, `NarratorGM.narrate()` gets `effective_effect` + `applied_summary`; D-025/D-026 resolved |
| 14 | `ModelGateway` (single model-call seam, role tagging), `TelemetrySink`/`CallRecord` (in-process telemetry, zero coupling to fiction); all four callers migrated; D-022 resolved |
| 15 | `parse_proposal`, `render_event`, `PlaytestSession` (`step` / `player_view` / `export_transcript`); reads only `belief_store(player_id)` — client never computes audiences or hidden state |
| 16 | `SceneMode` (6 narrative modes), `SceneCadence` (`select_companions` with always-active + spotlight priority), `Orchestrator.sorted_by_spotlight`, `run_round` `scene_cadence` param; gated companion = zero model calls; D-021 resolved |
| 17 | `CampaignPackage`, `load_campaign`, `load_campaign_dict` (cross-ref validation); `PlotGraph.update_hook_binding` / `add_hidden_node` / `to_dict` / `from_dict`; `SQLitePlotGraph` (persists within D-023 tx model); `attach_campaign` factory; `schemas/campaign.schema.json`; D-037 resolved |
| 18 | `PlotManager` (sole plot-graph writer; D-016 resolved), `PlotGraph`, `InterestSignalAccumulator`, fixture-health detection, propose/accept re-binding, `post_beat`, `gm_context_summary`. Phase 17 wired `accept_rebinding` through `update_hook_binding` and added `SQLitePlotGraph` persistence. |

**Known gaps carried into Phase 19:**
- **ModelGateway failure policy**: `ModelGateway.call()` is a blocking, naked call with no timeout, retry, or circuit breaker. Address before any live session.
- **Perception-into-delivery gap**: `_resolve_delivery()` uses `world.entities.keys()`, ignoring zone adjacency and lighting. Fix when campaign zone structures make the gap meaningful.

---

| 19 | Disposition graph core | `DispositionAxis`, `DispositionDelta`, `DispositionGraph`, `DispositionEngine` in `disposition.py`; `SQLiteDispositionGraph`, `attach_disposition` in `persistence.py`; D-011 deterministic half resolved. |
| 20 | Social interpretation + Bond compels | `BondRef` in `character_sheet.py`; `GainEdge`, `SpendEdge` in `effects.py`; `ModelCallError`, timeout/retry in `provider.py`; `SocialInterpreter`, `PendingCompel`, `CompelResolution`, `resolve_compel` in `social.py`; D-011 fully resolved. |

---

## Current milestone: Phase 21 — Production Text-Channel API and Interface MVP

---

## Phase 21 — Production Text-Channel API and Interface MVP

*(Formerly old Phase 11 — voice/TTS scope removed.)*

The frontend consumes filtered render events and submits scoped proposals. It never computes audiences, rules, effects, world state, hidden plot, consequences, canon, or perception.

**Voice is not in scope.** Do not build, preserve, or plan for TTS, character voices, audio playback, voice synthesis, voice input, microphone permissions, or audio routing. Any legacy voice or TTS code is deprecated substrate; remove it only as a dedicated cleanup task after the text interface is stable. The post-Phase-21 voice design is locked in D-039; implementation is deferred.

**Non-goal:** Polished React interface, multi-human networking, scene imagery, account/auth system, campaign generation (Campaign-Authoring Studio — post-v1).

**Phase 21 deliverables (dependency order):**

1. **Schema version guard + session manager** (`SessionManifest`, `SessionManager`, `SchemaVersionError`) — `open_session()` writes a `schema_version` row to the session DB on first open; `SessionManager.resume()` validates it and raises `SchemaVersionError` (fail-closed) on mismatch. `SessionManifest` fields: `session_id`, `campaign_id`, `title`, `created_at`, `updated_at`, `last_scene_summary`, `player_summary`, `db_path`, `schema_version`, `engine_version`. Lists saved sessions with metadata; creates new sessions from a `CampaignPackage`; resumes sessions. Phase 22 adds migration; Phase 21 only guards and rejects.

2. **Edge mechanic — Lean / Push / Shield** — Beat-loop integration for the Edge currency (SpendEdge/GainEdge currency side already built in Phase 20). Adds `edge_spend` field to `Proposal` (values: `lean_before`, `lean_after`, `push`, `shield`); `edge_justification` field for Trait/Bond/Truth citation. `BeatRunner` gains pre-roll hook (Lean-before: validate, spend 1 Edge, reduce Exposure by 1) and post-roll hook (Lean-after / Push: validate, spend Edge ± Stress, step band up one; Shield: validate, redirect incoming Harm to shielding entity). Invariants enforced deterministically: at-most-one step-up per roll; no step-up past Triumph; no band-step generates Edge; pre-roll Lean cannot reduce Exposure below 0. `pending_edge_decision` becomes a concrete beat pause point feeding D-027 lifecycle states.

3. **D-027 action lifecycle states** — Backend-owned state machine (`draft → submitted → validating → pending_player_choice → adjudicating → rolling → pending_edge_decision → applying_effects → auditing → narrating → committed`; exits: `cancelled / aborted / failed`). Client reads state only. `pending_edge_decision` state wires the Phase 21-2 Lean pause point into the API.

4. **D-029 roll visibility** — Four values (`table`, `roller_only`, `gm_only`, `revealed`); `gm_only` rolls never reach the client or warm GM context unless explicitly revealed. Enforced in `render_event()` and the event stream filter.

5. **D-031 correction/retcon event types** — `correction` and `retcon` event subtypes; `render_event()` emits superseded markers; `retcon` requires the human player in `authorized_by`; log remains append-only.

6. **D-032 epistemic certainty labels** — Six backend-emitted labels (`Confirmed`, `Claimed`, `Observed`, `Suspected`, `Unknown`, `Corrected`); adds `"theory"` to `EPISTEMIC_TYPES`; label computed in `render_event()` from `epistemic_type`; client renders only.

7. **D-028 knowledge transfer enforcement** — All knowledge transferred between entities enters as `epistemic_type="claim"` via logged authorized events; client never transfers facts between views; enforced at commit pipeline boundary.

8. **D-030 time anchor + scene transition** — Minimal time anchor fields on every rendered event: `scene_id` (UUID), `beat_index`, `scene_phase` (= `SceneMode`), `prose_time_label`, `elapsed_category`. `scene_transition` structural event logged when `scene_id` changes. Client is receiver only.

9. **Settings system** (`SettingsRegistry`, `SettingsManager`) — Layered settings (code defaults → `settings/models.json` → `settings/campaigns/{campaign_id}.json`). All essential model slots have defaults; the system is always in a valid state with zero user configuration. Character agent slots derived from loaded campaign roster. API keys in env only. See D-041 for full spec.

10. **Home screen + play interface** — Text-only session view; home screen with "New Campaign" (select pre-built `CampaignPackage`) and "Return to Saved Session" paths; renders authorized events via `render_event()`; displays epistemic certainty labels; supports correction/retcon markers; settings panel. Client never derives hidden state, computes audience, or transfers knowledge between views.

**Exit gate:** A player can run a complete text-only session — start from home screen, select a campaign, play beats (including Edge spend decisions), save, resume — without learning private events through page state, API payloads, reconnect behavior, transcript export, client-side routing, or debug panes. Sessions are resumable across engine restarts without state corruption or silent schema mismatch. Model choices and agent slots are configurable and persistent.

---

## Phase 22 — Beta Hardening and Release Gate

Golden transcript suite, replay tests, fuzz/property tests (access, projection, transactions, reducer behavior, event ordering, secrecy boundaries), save-format migration, failure/retry/recovery drills, token+latency+cost budget enforcement, security review of client payloads and reconnect flows, repeated short-session text playtests and postmortems.

**Priority order for Phase 22** (earlier items unblock later ones — do not reorder without justification):

1. **Multi-model routing / provider adapter** (D-017) — must-ship first. Without per-role routing, the settings system's model slots (D-041) are cosmetic: all roles hit the same model at the same cost. A 4-seat session on a single premium model is unsustainable. Routing unblocks cost-realistic telemetry, which D-042 budgets depend on. Implement before any other Phase 22 item. Components: formal `ProviderAdapter` interface around `ModelGateway`; per-role model selection driven by `SettingsManager`; structured-output normalization layer (with repair/retry for malformed tool responses); provider-specific failure/backoff policy. The adjudicator needs forced tool-call guarantees; not all providers offer this — the adapter must have an explicit policy for providers that can't guarantee structured output.

2. **Context budget management** (D-042) — second. `ContextBudgeter` with per-role `ContextBudgetPolicy` (max tokens, required sections, recent-event window, summarize-older flag). Six roles: `gm_adjudicator` (40 000 tokens / window 20), `gm_narrator` (20 000 / 8), `character_agent` (12 000 / 12), `social_interpreter` (8 000 / 6), `auditor` (16 000 / 10), `plot_manager` (24 000 / 15). Hybrid preflight estimation via `TokenEstimator` (`count_tokens` API) — called only when word-count proxy is within 20 % of cap. Context quality check emits `AuditFlag(WARNING)` if required sections are missing after trimming. Per-role cap defaults added to `SettingsRegistry` and `settings/models.json` schema. `CONTEXT_EVENT_WINDOW = 12` constant in `beat.py` is replaced by reading per-role window values from `SettingsManager`.

3. **Per-session cost ceiling** (D-042) — part of same work as above. `TelemetrySink` already records per-call cost. Phase 22 adds a configurable per-session cost cap; when cumulative cost exceeds it, the engine emits an advisory log event and the interface surfaces a warning. Hard cutoff is opt-in (default: advisory only).

4. **Lorebook v1 — read-only, audience-gated** (D-043) — **blocks on D-042 being partially complete.** Do not wire lorebook injection before the context budgeter exists to account for the added tokens. Design: `LoreEntry` + `LoreDeck` + `LoreAssembler` integrated as an optional collaborator in `ContextAssembler`; keyword matching against the POV's entitled belief projection only (never raw event content); per-entry `audience_class` gate fires before any content assembly; background/setting context only — never current-state authority; tests proving a `gm_only` entry is never visible in player context.

5. **Prompt/style profiles** — small, settable alongside item 4. Narrator tone and prose-length preferences; format preferences (bullet vs. prose outcomes, etc.); per-campaign style overrides. Lives in `settings/models.json` and the campaign settings file. Cannot override rules, dice, world state, audience, or hidden-state boundaries. Tests proving style settings affect only prompt text, not beat outcomes.

**Additional Phase 22 items (reliability and correctness hardening):**

- **RNG seed / replay determinism**: Dice results are logged as events (the authoritative source), but persisted sessions do not record RNG seed or state. For deterministic golden-transcript replay, either log rolls as the sole authority (reconstruct on replay from the log, no re-roll) or capture seed at session-open and store it with the session manifest. Decide and implement before golden transcripts are written.
- **SQLite schema versioning**: Phase 21 pulls forward the minimal version marker: `open_session()` writes and validates `schema_version`; mismatches fail-closed. Phase 22 adds the full migration registry and forward-compatibility tests so transcript files from earlier phases can be brought forward.
- **`event.schema.json` round-trip validation**: `schemas/event.schema.json` predates the Phase 11 epistemic fields (`epistemic_type`, `asserting_entity`, `observing_entity` on `Commitment`). The schema is stale. Phase 22 should add schema validation tests that round-trip persisted events through the schema and fail on unknown fields or missing required fields. Update the schema first.
- **Tool output validation**: `AdjudicatorGM`, `NarratorGM`, and `CharacterAgent` trust model-returned block shapes and field names without schema validation. A malformed tool response crashes rather than producing a graceful audit flag. This is partially addressed by the Phase 22 item 1 structured-output normalization layer; the remaining gap is catch `KeyError`/`TypeError` at tool-block extraction and convert to a `CRITICAL` audit flag so the beat can abort cleanly rather than raising.

**`uploads/FABLE_Engine_Schema_v6.md` mechanic gaps (audited 2026-06-18):**

The items below were identified by cross-referencing `effects.py`/`rules.py`/`character_sheet.py` against the v6 spec. "Phase X" is the earliest phase where the gap should close; earlier phases may address them if the implementation naturally requires them. See the coverage table in `STATUS.md` for the full breakdown.

_Phase 19–20 (built):_
- **`GainEdge` typed effect** — built in Phase 20. Cap-3 enforced in `EffectExecutor._gain_edge()`.
- **`SpendEdge` typed effects** — built in Phase 20. `SpendEdge(entity_id, amount, spend_type)` in `EffectExecutor`.
- **Edge compel / costly expression gain** — built in Phase 20. `resolve_compel()` always applies `GainEdge(1)` on accept.

_Phase 22 (beta hardening):_
- **`ApplyScar` typed effect** — `CharacterSheet.scars` field exists but nothing mutates it through `EffectExecutor`. Add `ApplyScar(character_id, scar_type, description)` with 3-slot cap enforcement (§14).
- **Stress overflow → Scar** — when `ApplyStress` would exceed 6 boxes, route overflow to `ApplyScar` and clear Stress. This invariant (§23 inv. 9) is the mechanically critical path for consequences at the table.
- **Scar route invariant enforcement** — Scars should only be created via Stress overflow or live Seam terminal consequence (§14/§23 inv. 9). Enforce in `EffectExecutor` — reject any `ApplyScar` that isn't downstream of overflow or Seam.
- **`CreateSeam` typed effect** — vulnerability marker enabling terminal consequence; planned in D-025 minimum set but not in Phase 12 build (§15).
- **Recovery clocks** — add `recovery_for: str | None` field to the clock schema so a clock can be flagged as the opposition countdown that lapses a named Maintained Truth when it fires (§12).
- **Stress 6-box cap and breather-clear** — `ApplyStress` does not enforce the 6-box hard limit or clear the track on a genuine breather. Add enforcement in `EffectExecutor` (§14).
- **TN table enforcement** — TN values (8/10/12/13/14; contested = 10+Skill) live in adjudicator prompt text, not in the rules engine. Move to a deterministic lookup so the `RulesEngine` can validate TN regardless of model behavior (§6).
- **Cost register completeness** — Ground / Trace / Relational registers have no typed effects (§7). Add at minimum a generic `ApplyCostRegister(register, character_id, description)` that logs the cost as a commitment even when no mechanical consequence is immediately deterministic.
- **Prep Rounds** — one prep action per character; Front/mission clock ticks at round end (§18). No mechanism exists; requires orchestrator round-type discrimination.
- **Volatile overlay** — minimum Exposure 1 on Volatile scenes; can't Top-Exit; result-table overlay (§20). No scene-volatility flag; no overlay enforcement.
- **Advancement** — causal accomplishment triggers; Skill/Trait/Bond spend (§21). Not implemented. Must be causal (invariant 17): only triggered by demonstrated play, not declared by the GM.
- **Opposition classes** — Obstacle / Minor / Significant / Front formal model (§19); currently adjudicator-managed prose only.
- **Front Levers and Seams** — `Front` dataclass has `name`/`threat`/`clock_name`/`consequence_truth`/`faction_id` but not the Lever or Seam lists that v6 specifies (§17). Add these fields to `Front` and the campaign schema.
- **Mode-as-constraint enforcement** — `SceneMode` tracks cadence/pacing; FABLE Modes (§22) are configurations of primitives that constrain valid action types. The Mode invariant (primitives only, not new subsystems) is policy today, not enforced by the engine.

**Exit gate:** Several real text sessions run without secret leakage, state divergence, unexplained narration/state mismatch, uncontrolled model-call cost, or client-side hidden-state exposure.

---

## Post-v1 tracks (do not block core roadmap)

- **Configurable Seats and Multi-Human Play** — build only after Phase 21 is proven.

- **Campaign-Authoring Studio** — separate workflow for validated campaign graph creation. See D-040 for the decided pipeline. Two entry modes (auto-generate from minimal input; generate from prompt/file) both produce a validated `CampaignPackage` via `CampaignCompiler` → schema validation → repair/retry. Raw user input never reaches GM runtime context directly. Phase 21 home screen supports loading pre-built packages only; generation UI comes here. Planned components: `CampaignCompiler`, `CampaignCompilerGateway` (repair/retry loop). **Do not implement before Phase 21 is stable.**

- **Voice / TTS (manual click-to-play)** (D-039) — post-Phase-21 presentation-layer track. Design locked in D-039. Manual click-to-play per rendered bubble; off by default; per-speaker voice IDs in `settings/voice.json`; API key in env only; audio artifacts cached per event ID + voice ID hash; TTS failure degrades to text. Planned components: `VoiceGateway` (thin ElevenLabs wrapper), `VoiceArtifactCache`. No game-state coupling; no event log access. **Do not implement during Phase 21 or Phase 22.**

- **Image Generation Layer** (D-038) — post-Phase-21; see D-038 for the full spec. Covers character portraits, scene images, map backgrounds, and text-graphic artifacts. Four components: `ImageGenerationGateway`, `ImagePromptAssembler`, `ImageArtifactStore`/`ImageArtifact`, and a user-editable style profile (`settings/style_profile.json`). Key constraints: prompt from viewer's authorized belief store only, style separate from subject, event log always wins if image contradicts it, `non_authoritative=True` on every artifact. Visual mode config: off/cheap/premium. Maps: deterministic rendering first; image model for aesthetic background only. **Do not implement before Phase 21 is stable.**

- **Legacy Voice/TTS Removal** — confirm no game-state component depends on any pre-existing voice code before removing; separate cleanup task after Phase 21 is stable.

---

## Dependency order

```
Phase 10 (atomic session)
    ↓
Phase 11 (epistemic commitment)
    ↓
Phase 12 (typed effect executor)
    ↓
Phase 13 (narrow FABLE resolution slice)
    ↓
Phase 14 (provider gateway + telemetry)
    ↓
Phase 15 (human-seat adapter + text console)
    ↓
Phase 16 (scene cadence + companion activation)
    ↓
Phase 17 (campaign package + plot graph core)
    ↓
Phase 18 (plot-manager runtime)
    ↓
Phase 19 (disposition graph core)
    ↓
Phase 20 (social interpretation + Bond compels)
    ↓
Phase 21 (production text-channel API)
    ↓
Phase 22 (beta hardening + release gate)
```

---

## Working rules

1. One phase at a time. The engineer receives only the current phase prompt, relevant decisions, relevant component registry entries, relevant code and tests, and the previous phase's completion report.
2. A phase must have one durable outcome — one coherent contract, subsystem boundary, or playable vertical slice.
3. Do not pull later-phase functionality forward because it appears convenient.
4. Text is the only supported presentation medium. Voice, TTS, audio playback, and microphone integration are outside project scope.
