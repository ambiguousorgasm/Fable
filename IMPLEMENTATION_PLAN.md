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

## Phases 1–21: Built

All 21 phases complete. 1401 tests pass. See `STATUS.md` for per-phase build notes.

---

## Phase 22 — Core Release Hardening and Text-Only Release Gate

**This is the final numbered core phase.** Completing it means the FABLE Table Engine is ready for a first text-only public release:

- stable text-only session engine
- safe save/resume across restarts with automatic schema migration
- no hidden-state leakage through any client surface (page state, API payloads, reconnect, transcript export)
- bounded model cost and context behavior
- sufficient replay, golden-transcript, property, and security test coverage

No new numbered phases are planned after Phase 22.

---

### Phase 22 items already built

| Item | Notes |
|---|---|
| D-017 multi-model routing / `ProviderAdapter` | `AnthropicAdapter`, per-role model resolution in `ModelGateway`, `ToolOutputError` 2-attempt retry |
| D-042 context budget management | `ContextBudgeter`, per-role `ContextBudgetPolicy`, `TokenEstimator`, `from_settings` |
| D-042 per-session cost ceiling | `CostCeilingStatus`, `TelemetrySink.ceiling_status()`, `PlayInterface.render_status()` alert |
| D-043 lorebook v1 | `LoreEntry`, `LoreDeck`, `LoreAssembler`; keyword match against entitled corpus; audience gate fires before keyword match |
| Lorebook prompt injection | `ContextAssembler.lore_block()`; injected into adjudicator, narrator, and character-agent prompts via `BeatRunner.run()` |
| `build_play_interface()` full wiring | All optional subsystems (executor, auditor, simulator, plot_manager, budgeter, lore_assembler) forwarded |
| Save-format migration registry | `_MIGRATION_REGISTRY`, `_apply_migrations()`, `ENGINE_SCHEMA_VERSION=22.0`; auto-migrates Phase 21.x sessions |
| `event.schema.json` update | Phase 11 epistemic fields, D-029 `roll_visibility`, D-031 `authorized_by`; `additionalProperties: false` |
| Golden transcript suite | `tests/test_phase22_golden.py` — 53 end-to-end regression tests with mocked models and seeded dice |
| Property / invariant suite | `tests/test_phase22_properties.py` — 39 tests (log monotonicity, projection subset, secrecy, canon conflict, transaction atomicity, replay) |
| Security suite | `tests/test_phase22_security.py` — 26 tests (S-1 history gate, S-3 lore gate, S-4 telemetry isolation, S-5 input validation, S-7 OOC bypass, S-10 narrator lore gate) |
| Schema structural suite | `tests/test_phase22_schema.py` — 27 tests (schema file validity, `Event.to_dict()` shape, complete beat event shapes) |
| Rule-gap decision audit | D-044–D-048 explicit defer decisions (TN table, CreateSeam, recovery clocks, cost registers, Prep Rounds/Volatile/Advancement/Opposition) |

---

### A. Remaining Core Release Blockers (Phase 22 checklist)

These must be complete before tagging a release candidate.

- [ ] **Replay correctness drills** — close → reopen → play with seeded dice produces the same event sequence; orphaned dice events in aborted beats (D-035) handled correctly on resume
- [ ] **Short-session playtests** — run 3–5 real text sessions end-to-end; log postmortems; fix anything that breaks rules correctness, state consistency, or audience safety
- [ ] **Security review of reconnect / export flows** — `export_transcript()`, `export_transcript_json()`, session resume — confirm none exposes GM-private events or crosses audience boundaries
- [ ] **Any rule or schema gap discovered during playtesting that is a live-play blocker** (tracked in DECISIONS.md if non-trivial; see rule gap audit table below)
- [ ] **Final public-release hygiene:**
  - Remove personal or local paths from all docs and config
  - Verify all paths in setup docs and test fixtures are portable
  - Update README / setup docs with current Python / venv / test instructions
  - Add or verify a setup helper script (`Makefile`, `just`, or shell)
  - Run full test suite from a fresh clone into a clean venv
  - Verify `.gitignore` covers: `*.db`, `sessions/`, `logs/`, `transcripts/`, `.env`, `__pycache__/`, `.venv/`
- [ ] **Tag release candidate**
- [ ] **Prepare release notes** (summary of what FABLE Table Engine v1.0 is and is not)

---

## B. Post-Phase-22 Cleanup / Release Polish

*Not a new feature phase.* A stabilization and cleanup pass run after Phase 22 closes and alongside public release packaging. No new gameplay features, media systems, TTS, image generation, GUI, or mechanics.

- **Audit and classify `uploads/`, `static/`, `memory/`, `image_prompts/`** — for each file/directory: keep as public asset, move to `docs/` as internal reference, remove, or add to `.gitignore` as a local artifact
- **Confirm no legacy TTS/voice code is coupled to game state** — if any wiring is found, sever it before removing the code
- **Prune dead code** — unused imports, obsolete helpers, duplicate test utilities, stale compat shims
- **Clean stale doc references** — remove old phase numbering aliases, superseded file names (`fable_engine.md`), and v1 non-goals that were once presented as planned (TTS, multi-human play, polished React GUI)
- **Verify full test run from a clean clone** — fresh `git clone` → `python -m venv .venv` → `pip install -e .` → `pytest` must pass without anything beyond what the README says
- **Update README** with current architecture summary and quick-start instructions

---

## C. Post-Core / After Game Complete Backlog

*None of these block the text-only v1 release.*

| Feature | Decision | Notes |
|---|---|---|
| Image generation layer | D-038 | Portraits, scene images, map backgrounds; `ImageGenerationGateway`, `ImagePromptAssembler`, `ImageArtifactStore` |
| Manual click-to-play TTS / voice | D-039 | Off by default; per-speaker voice IDs; no game-state coupling; `VoiceGateway`, `VoiceArtifactCache` |
| Campaign-Authoring Studio | D-040 | `CampaignCompiler` → validation → `CampaignPackage`; raw input never in GM runtime context |
| Multi-human play / configurable seats | D-015 | Seat-agnostic contract exists; multi-human routing requires interface work |
| Polished React / web GUI | — | Current `PlaytestSession` / `PlayInterface` text layer is sufficient for v1 |
| Semantic / vector lorebook retrieval | D-043 | Upgrade from keyword matching to embedding retrieval when scale demands it |
| Advanced settings panels | D-041 | Per-campaign model overrides, budget visualization, character-slot UI |
| NPC-manager agent | D-006 | GM puppets walk-ons for now; promote recurring NPCs later |
| Agent bidding / cost-gated spotlight | D-005 | After per-call cost profiling confirms budget headroom |
| Richer perception propagation | D-012 | Full attenuation/occlusion, overhear content reveal |
| Positioning query IC mode | D-003 | Fog-of-war / IC assessment for exploration-heavy scenes |
| Opening model extension | D-034 | Extend `MaintainedTruth` with optional `group`/`effect_text` |
| Front Levers and Seams on `Front` dataclass | — | Schema enrichment; post-core |

---

## D. Final Extraction Track — General Multi-Agent Orchestration Architecture

*This track is last — after Phase 22 closes, after cleanup is complete, and only once the game is proven stable through actual play.*

**What this is:** FABLE is a domain-specific implementation of a more general governed multi-agent orchestration pattern. The extraction track documents and packages the reusable architectural skeleton — stripped of FABLE rules, dice, Edge, Stress, clocks, and all TTRPG mechanics — as a foundation for other multi-agent systems where private knowledge, validated proposals, and append-only event history are the core requirements.

**Core design principle to preserve:**
> "Agents propose; deterministic systems dispose. Models suggest, validators decide, event logs remember."

**Candidate reusable components** (game-specific internals stripped):

| Component | Reusable abstraction |
|---|---|
| `EventLog` | Append-only event history; the source of truth for what happened |
| Audience / Visibility Model | Who is entitled to see which events; differential knowledge by role |
| `BeliefStore` / Context Projection | Each agent's authorized view of the domain state |
| Proposal Queue | Agents submit proposed actions; no direct state mutation |
| `Orchestrator` | Decides whose proposal is handled next and in what order |
| `CommitPipeline` | Validates proposed changes before they become truth |
| World / Domain State | Current structured state of the task or domain |
| `Auditor` | Detects contradictions, policy violations, leakage, invalid output |
| `ModelGateway` | Provider abstraction and per-role model routing |
| `TelemetrySink` | Cost/latency/token tracking completely outside domain state |
| Settings System | Role-specific model and behavior configuration |
| Persistence / Replay | Save, resume, audit, and reproduce sessions |

**Non-TTRPG domains this architecture fits:** AI research team simulations, software engineering agent clusters with scoped repo access, legal/investigation workflows with evidence asymmetry, negotiation simulations with private positions, red-team/blue-team exercises, multi-agent writing/editing rooms, incident response simulations, executive decision-support systems.

**Timing:** Begin only after Phase 22 sign-off and cleanup are complete.

---

## Rule gap audit — v6 mechanics

Classification key:
- **Built** — deterministic code implements and enforces this
- **Stale note corrected** — a prior doc said Missing/Partial; it was actually built in an earlier phase
- **Deferred post-core** — safe to omit from first text-only release; adjudicator/narrator handles it narratively in the interim

| § | Mechanic | Classification | Notes |
|---|---|---|---|
| §13 | Edge spend — mechanic side: Lean steps band; Push costs 2 Stress; Shield redirects Harm | **Stale note corrected — Built in Phase 21** | `BeatRunner` pre-roll Lean hook, post-roll Lean-after/Push hook, Shield redirect; `Proposal.edge_spend`; invariants enforced deterministically. STATUS.md §13 "Missing" row was stale. |
| §14 | Stress overflow → exactly 1 Scar (then clear Stress) | **Stale note corrected — Built pre-Phase-21** | `STRESS_CAP=6` enforced; overflow cascade to `ApplyScar(via_overflow=True)`. |
| §14 | Scar route invariant (only Stress overflow or live Seam terminal) | **Stale note corrected — Built pre-Phase-21** | `EffectExecutor._apply_scar` rejects without `via_overflow=True` or `seam_event_id`. |
| §6 | TN table deterministic enforcement | **Deferred post-core (D-044)** | TNs live in adjudicator prompt; `RulesEngine` does not validate TN legality. Not a live-play blocker with a well-prompted adjudicator. |
| §7 | Ground / Trace / Relational cost registers | **Deferred post-core (D-047)** | No typed effect. Workaround: adjudicator describes these in narration; `ChangeResource` approximates resource costs. Full ledger model needed first. |
| §10 | Ledger one-source / one-payout enforcement | **Deferred post-core** | Adjudicator-managed; no deterministic payout deduplication. Not a live-play blocker for MVP with a well-prompted adjudicator. |
| §12 | Recovery clocks (`recovery_for` field) | **Deferred post-core (D-046)** | Clocks fire correctly; `recovery_for` metadata for maintained-truth auto-lapse is missing. Workaround: GM fires `ExpireMaintainedTruth` effect manually. |
| §14 | Breather-clear for Stress | **Deferred post-core** | No `ClearStress` typed effect. Workaround: `ChangeResource(resource_key="stress", new_value=0)` in a breather-action consequence palette handles this. |
| §15 | Live-Seam validation / `CreateSeam` typed effect | **Deferred post-core (D-045)** | `seam_event_id` on `ApplyScar` accepts any event ID; no active-Seam check. Not live in practice because `CreateSeam` doesn't exist — `seam_event_id` is never set. |
| §17 | Front Levers and Seams | **Deferred post-core** | `Front` has `name`/`threat`/`clock_name`/`consequence_truth`/`faction_id`; no `levers`/`seams` lists. Fronts still drive clock advancement and narrative tension without them. |
| §18 | Prep Rounds | **Deferred post-core (D-048)** | No mechanism. Handled narratively by GM. |
| §19 | Opposition classes | **Deferred post-core (D-048)** | Adjudicator-managed prose categorization; no formal `Obstacle`/`Minor`/`Significant`/`Front` model. |
| §20 | Volatile overlay | **Deferred post-core (D-048)** | No `volatile` flag on scene or beat. Workaround: adjudicator sets minimum Exposure 1 via prompt when scene is Volatile. |
| §21 | Advancement | **Deferred post-core (D-048)** | No causal-accomplishment triggers or mechanical advancement tracks. |
| §22 | Mode-as-constraint enforcement | **Deferred post-core** | `SceneMode` handles cadence/pacing; FABLE Mode-as-configuration-of-primitives is policy, not enforced by the engine. |
| D-037 | Multi-effect palette atomic groups | **Deferred post-core** | `atomic_group` reserved in `schemas/campaign.schema.json`; not enforced at runtime. Current: each effect independently; failure logs `audit_advisory` without aborting the beat. Property tests cover palette correctness; grouped atomicity is a future correctness enhancement. |

---

## Phase 22 exit gate

A player can run a complete text-only session — start from the home screen, select a campaign, play beats (including Edge spend decisions), save, and resume — without learning private events through page state, API payloads, reconnect behavior, transcript export, client-side routing, or debug panes. Sessions are resumable across engine restarts without state corruption or silent schema mismatch. Model choices and agent slots are configurable and persistent.

**Operationally:** Several real text sessions run without secret leakage, state divergence, unexplained narration/state mismatch, uncontrolled model-call cost, or client-side hidden-state exposure. Replay from the event log matches original outcomes for seeded sessions.

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
Phase 21 (production text-channel API — built)
    ↓
Phase 22 (core release hardening — final numbered phase)
    ↓
Post-Phase-22 Cleanup / Release Polish
    ↓
Post-Core / After Game Complete Backlog
    ↓
Final Extraction Track (general multi-agent architecture)
```

---

## Working rules

1. One phase at a time. The engineer receives only the current phase prompt, relevant decisions, relevant component registry entries, relevant code and tests, and the previous phase's completion report.
2. A phase must have one durable outcome — one coherent contract, subsystem boundary, or playable vertical slice.
3. Do not pull later-phase functionality forward because it appears convenient.
4. Text is the only supported presentation medium for v1. Voice, TTS, audio playback, microphone integration, and polished React GUI are out of v1 scope.
5. Post-core and extraction tracks do not begin until Phase 22 is signed off and cleanup is complete.
