# Changelog

Append-only history of meaningful changes to the design and the build. Newest first. Each entry: date, what changed, and *why*. Reference decision IDs (`D-00x`) and components where relevant. Per the change protocol (`00_README.md`), every component or architecture change lands an entry here.

---

## 2026-06-19 — Public repo hygiene: untrack internal directories, update .gitignore

**Removed from git tracking (files remain on local disk):**
- `uploads/` — working upload directory: internal schema draft (v7), two old HTML mockups, a second rules PDF, a rules markdown source, and a third-party Chrome extension zip (`ST-Multi-Model-Chat-main.zip`). None of these are public release assets.
- `memory/` — Claude Code working memory: internal project planning notes, stale roadmap structure, mockup gap analysis. Private by design; should never be published.
- `image_prompts/` — five image generation style prompt files. Image generation (D-038) is deferred post-core; these are internal creative assets.

**`.gitignore`** — added `uploads/`, `memory/`, `image_prompts/` to prevent accidental re-tracking.

`static/fable_rules.pdf` — retained; intentionally public.

No secrets, personal paths, or credentials were found in any tracked file outside the one self-referential CHANGELOG note describing a prior fix.

---

## 2026-06-19 — public/README.md and public/docs/setup.md: beta content pass

**`public/README.md`** rewritten for completeness:
- Added explicit "Built systems" list covering all 17 shipped components — previously only principle bullets, no shipped-feature inventory.
- Added "Current status" section: Phase 22 complete, remaining work noted, not-yet-stable disclaimer.
- Added provider qualifier: Anthropic is the current live provider; adapter boundary and per-role routing exist; non-Anthropic adapters not yet implemented.
- Added `bash scripts/setup.sh` as primary setup path alongside manual fallback.
- Added test mock disclosure: "No API key is required to run the suite."

**`public/docs/setup.md`** — same provider qualifier added to Prerequisites; `bash scripts/setup.sh` added as primary install path.

---

## 2026-06-19 — Public release hygiene: setup script, README rewrite, personal-path audit

**`scripts/setup.sh`** — new bootstrap script. Checks Python 3.11+, creates `.venv` if missing, runs `pip install -e ".[dev]"`, copies `.env.example` to `.env`, prints next-step instructions. Executable; no external dependencies.

**`README.md`** — rewritten for public consumption. Removed stale "Current build posture" list (described Phase 1 priorities; we are at Phase 22 complete). Removed "Claude Code usage" section (internal-only). Added: quick setup via script + manual fallback, current status note, secrets policy, key source directory map, development reference section listing internal docs.

**`CHANGELOG.md`** — removed one personal filesystem path (`/home/audrey`) that was leaked into a prior changelog entry; replaced with "a parent directory".

---

## 2026-06-19 — Roadmap restructure: Phase 22 final, post-core tracks, extraction track

**Doc-only pass.** No code changes; 1401 tests unchanged.

**`IMPLEMENTATION_PLAN.md`** rewritten from Phase 22 forward:
- Phase 22 renamed to "Core Release Hardening and Text-Only Release Gate" and confirmed as the final numbered phase.
- Phase 22 already-built items listed explicitly.
- Remaining Phase 22 checklist (A): replay drills, short-session playtests, reconnect/export security review, release hygiene, release-candidate tag.
- Section B: Post-Phase-22 Cleanup / Release Polish — no new features; substrate audit, dead-code prune, clean-clone verification, README update.
- Section C: Post-Core / After Game Complete Backlog — image generation (D-038), voice/TTS (D-039), Campaign-Authoring Studio (D-040), multi-human play, polished GUI, semantic lorebook, advanced settings, NPC-manager, agent bidding, richer perception.
- Section D: Final Extraction Track — general multi-agent orchestration architecture; framed as "agents propose; deterministic systems dispose"; candidate reusable components; non-TTRPG use cases; explicitly last after cleanup.
- Rule gap audit table: each v6 mechanic classified as Built, Stale note corrected, or Deferred post-core. No missing mechanics are core release blockers.

**`STATUS.md`** targeted corrections:
- §13 Edge spend mechanic side: corrected from "Missing" to "Built" (Phase 21 Lean/Push/Shield).
- §14 breather-clear: updated from "Phase 22" to "Deferred post-core" with `ChangeResource` workaround.
- §14–§23 coverage table: remaining "Phase 22" targets updated to "deferred post-core" with decision references.
- "Key gaps before live play" note updated — no core blockers remaining.
- CORE §13 validation table: stale phase references corrected; Phases 8/18 noted as built; D-042 budget noted.
- Phase 22 row renamed.

**`DECISIONS.md`** — "Open — Phase 22" section updated; remaining work is testing/verification, not design forks.

---

## 2026-06-19 — Phase 22: property, security, and schema tests + rule-gap decision audit (1401 tests)

**`tests/test_phase22_properties.py`** — 39 property/invariant tests covering the five CORE principles:

- **Log monotonicity** (2 tests): event count never decreases after appends; sequence numbers strictly increase.
- **Projection subset + audience invariant** (3 tests): every event projected for an entity is a subset of all log events; projected events have monotone per-POV sequence; `project_for(gm)` ⊇ `project_for(hero)` in a typical beat.
- **Secrecy invariant** (3 tests): GM lifecycle events (`validating`, `adjudicating`, `applying_effects`) absent from player projection across any number of beats; player-projected events cross-referenced against `log.all()` to confirm `hero` always in audience (uses ID cross-reference because `ProjectedEvent` never exposes `.audience` — secrecy-by-design); GM sees strictly more events than player.
- **Belief store determinism** (3 tests): same seed → same committed facts; belief stores are idempotent across repeated calls; projection without facts has zero beliefs.
- **Canon ledger consistency** (3 tests): committed fact visible in `canon_ledger`; second commit to same (subject, predicate) raises `CanonConflictError`; override with `reason=` kwarg succeeds without conflict.
- **Transaction atomicity** (4 tests): aborted beat leaves event count unchanged; world state not mutated on abort; facts from aborted beat not in pipeline; committed beat writes events atomically.
- **Replay** (3 tests): close + reopen restores events; beat_index survives round-trip; fact committed before close visible after reopen.
- **CommitPipeline conflict detection** (3 tests): conflict raises `CanonConflictError`; override bypasses; distinct predicates on same subject do not conflict.

**`tests/test_phase22_security.py`** — 26 security invariant tests covering all client-accessible surfaces:

- **S-1 PlayInterface history gate** (3 tests): `audience=("gm",)` events (`narration`, `scene_transition`, `audit_advisory`) absent from `PlayInterface.history()`; player-audience events visible.
- **S-3 Lore audience gate** (4 tests): `gm_only` lore entry never reaches player belief store even when keywords match; `gm_only` visible to GM; player-scoped entry invisible to other player; audience gate fires before keyword match (D-043 invariant).
- **S-4 Telemetry isolation** (4 tests): `TelemetrySink.records` never appear in event log; telemetry and event log are fully separate objects; `CallRecord` carries no fictional state; model cost never lands as a commitment.
- **S-5 Client input validation** (6 tests): empty action raises `ValueError("empty")`; long/special-char/unicode actions do not crash; injection attempt (`'; DROP TABLE events; --`) does not commit facts; SQL-injection payload produces no system event.
- **S-7 OOC bypass** (3 tests): `session.step("/ooc ...")` produces an `ooc` event; no `narration` event; no model call (mock call count = 0).
- **S-10 Narrator lore gate** (3 tests): narrator receives only player-entitled lore context; `gm_only` secrets not present in narrator prompt; model call captured and inspected to verify absence.

**`tests/test_phase22_schema.py`** — 27 schema structural tests (no runtime jsonschema dependency):

- **Schema file validity** (9 tests): file exists and is valid JSON; all required top-level fields present; `additionalProperties: false`; `$defs/commitment` has required fields + `epistemic_type` + `asserting_entity`; `roll_visibility` and `authorized_by` in schema properties.
- **`Event.to_dict()` shape** (8 tests): all required fields present; no unexpected keys; audience is a list; commitments is a list with required sub-fields; epistemic types round-trip; `roll_visibility` null by default and valid when set; JSON serializable with round-trip.
- **Complete beat event shapes** (10 tests): all stakeless beat events pass shape check; all stakes beat events pass shape check; dice events on `dice` channel; narration on `public` channel; lifecycle events on `system` channel; all events have non-empty ID; monotone sequence starting at 0; commitment fields all present; three-beat sequence all valid.

**`DECISIONS.md` additions** — D-044 through D-048, explicit defer decisions for all unimplemented v6 mechanics:

- **D-044** (TN table enforcement): defer to v1.1; option A (`LEGAL_TNS = {8, 10, 12, 13, 14}` in `rules.py`) noted as recommended implementation when accepted.
- **D-045** (CreateSeam typed effect): defer to Phase 23; requires `create_seam`/`trigger_seam` effect types + seam tracking in `world_state.py`.
- **D-046** (Recovery clocks `recovery_for` field): defer to Phase 23; requires `Clock.recovery_for: str | None` + SQLite schema migration.
- **D-047** (Cost registers Ground/Trace/Relational): defer to Phase 23; requires full Ledger model before `ApplyCostRegister` is useful.
- **D-048** (Prep Rounds, Volatile overlay, Advancement, Opposition classes): all deferred as post-v1 tracks with rationale per item.

---

## 2026-06-19 — Phase 22: golden transcript suite (1309 tests)

**`tests/test_phase22_golden.py`** — 53 end-to-end regression tests exercising the full deterministic stack with mocked models and seeded dice:

- **Stakeless beat (14 tests)**: event type sequence (submitted→validating→adjudicating→applying_effects→narrating→narration→committed), player's projected events vs GM's projected events, narration text in player store, beat_index increment.
- **Stakes beat with dice (10 tests)**: dice_roll and resolution events present, `had_stakes` true, band is a valid `Band` enum member, `rolling` lifecycle fires, effect event lands on Cost outcome (seed 7), stress increments to 1.
- **Fact commits (5 tests)**: `declared_facts` visible in both player and GM belief stores, multiple facts all committed, two-beat accumulation of distinct (subject, predicate) pairs.
- **Effect application (5 tests)**: `apply_stress` lands on Cost band (seed 0), effect event in log, audience covers actor + gm, stress overflow without `overflow_scar_type` rejected (stress stays at STRESS_CAP).
- **Audience separation (4 tests)**: GM-internal lifecycle events absent from player store, player store events cross-referenced against raw log to confirm audience, dice roll visible to actor, GM sees more events than player.
- **OOC bypass (5 tests)**: `ooc` event emitted, no narration, no dice roll, channel="ooc" in result, only submitted + committed lifecycle.
- **Multi-beat sequence (5 tests)**: two narrations accumulate, beat counter increments, facts from two beats both visible, stress accumulates across two Cost beats (seed 1).
- **SQLite round-trip (2 tests)**: events survive close/reopen, beat_index persists.

Key design lessons encoded: committed facts are immutable (canon conflict prevents reuse of same subject/predicate), `ProjectedEvent` does not expose audience (use `log.all()` cross-reference), `consequence_palette["success"]` has no slot (no palette fires on Success band), `overflow_scar_type` required for scar-route overflow.

---

## 2026-06-19 — Phase 22: save-format migration registry + event schema fix (1256 tests)

**Migration registry** (`persistence.py`):
- `ENGINE_SCHEMA_VERSION` bumped `"21.3"` → `"22.0"`.
- `_MIGRATION_REGISTRY` dict: each entry maps `from_version → (to_version, description, sql_statements)`. `open_session()` walks the chain automatically; `SchemaVersionError` only fires when no path exists (unknown/future version).
- `_apply_migrations(conn, stored)` applies DDL in hop order, commits after each step. Bootstrap entry `"21.3" → "22.0"` migrates all Phase 21 sessions transparently on next open (no DDL changes needed).
- 8 migration tests: registry structure, walk termination, 21.3 auto-migration, unknown version still raises, synthetic DDL applied in order.

**`event.schema.json` updated to Phase 22 surface** (was stale since before Phase 11):
- `Event`: added `roll_visibility` (D-029, enum), `authorized_by` (D-031, array). Made `commitments` and `derived_from` optional with defaults.
- `Commitment`: added `epistemic_type` (D-024, enum: `fact`/`claim`/`observation`/`expired`/`theory`; default `"fact"`), `asserting_entity` (nullable), `observing_entity` (nullable). All new fields documented.
- Schema drift note in STATUS.md is resolved.

---

## 2026-06-19 — Phase 22: lorebook prompt injection + cost-ceiling surface (1248 tests)

**Lorebook injected into all three prompt paths** (`context.py`, `gm.py`, `character_agent.py`, `beat.py`):

- `ContextAssembler.lore_block(store, pov) -> str` — convenience wrapper: matches + formats in one call; returns `""` when no assembler or no match, so callers inject unconditionally without branching.
- `AdjudicatorGM.evaluate()` gains `lore_context: str = ""` — inserted between recent events and declared action when non-empty. Existing callers unchanged.
- `NarratorGM.narrate()` gains `lore_context: str = ""` — prepended before player context so background precedes scene view. Existing callers unchanged.
- `CharacterAgent.propose()` calls `assembler.lore_block(store, entity_id)` and passes result to `_build_user_message(lore_context=...)`. `_build_user_message` gains `lore_context: str = ""` injected at top before relationships.
- `BeatRunner.run()` builds `gm_lore` and `player_lore` after belief stores; forwards each to the matching GM call. Audience gate is structural end-to-end — `gm_only` entries cannot reach player prompts regardless of keyword overlap.

**Cost-ceiling surface** (`interface.py`, `tests/test_phase21_interface.py`):

- `PlayInterface` gains `sink: TelemetrySink | None = None`. `render_status()` appends `[cost: WARNING]` or `[cost: EXCEEDED]` when `sink.ceiling_status()` is non-OK. Alert shows even when `world=None` — never silently suppressed.
- `build_play_interface()` gains `sink=None` forwarded to `PlayInterface`.

27 new tests: `test_phase22_lore_injection.py` (20) + cost-ceiling tests in `test_phase21_interface.py` (8 + 1 wiring).

---

## 2026-06-19 — `build_play_interface()` full wiring (1221 tests)

**`interface.py` factory wired** (`interface.py`, `tests/test_phase21_interface.py`):

- `build_play_interface()` now accepts `executor`, `auditor`, `simulator`, `plot_manager`, `budgeter`, and `lore_assembler` as optional keyword arguments (all default to `None`).
- `budgeter` and `lore_assembler` forwarded to `ContextAssembler(log, scene, budgeter=..., lore_assembler=...)`.
- `executor`, `auditor`, `simulator`, `plot_manager`, `budgeter` forwarded to `BeatRunner(...)`.
- Four new wiring tests in `TestBuildPlayInterface` cover: defaults still work, executor round-trip, budgeter round-trip, lore_assembler round-trip.
- All previously-built subsystems (Phase 22 D-042 budgeter, D-043 lorebook, Phase 20 auditor, Phase 8 auditor, Phase 9 plot_manager, Phase 12 executor) are now reachable through the default app entry point.

---

## 2026-06-19 — Phase 22 item 4: D-043 lorebook v1 (1217 tests)

**Phase 22 item 4 built** (`lorebook.py`, `campaign.py`, `context.py`, `settings.py`, `__init__.py`, `tests/test_phase22_lorebook.py`):

- **`LoreEntry(entry_id, title, content, keywords, audience_class)`** — frozen dataclass; `audience_permits(pov, gm_entity)` enforces class gate (`"all"`, `"gm_only"`, `"player_{id}"`). `from_dict` / `to_dict` for campaign JSON round-trip.
- **`LoreDeck(entries, gm_entity)`** — collection with `entries_for(pov)` audience filtering. `add()`, `all_entries`, `len`. `from_dicts(data, gm_entity)` deserializes campaign JSON.
- **`LoreAssembler(deck, max_entries)`** — keyword matching against the POV's entitled belief projection only (event content + committed fact subject/predicate/value labels). Audience class gate fires before any keyword search — `gm_only` entries are never considered for non-GM POVs regardless of keyword match. `lore_context_block(entries)` formats matched entries into a prompt-ready background block.
- **`ContextAssembler`** gains `lore_assembler: LoreAssembler | None = None` param and `lore_for(store, pov) -> list[LoreEntry]` — returns `[]` when disabled (opt-in). `lore_assembler` property exposed for callers.
- **`CampaignPackage`** gains `lore_entries: list[dict]` field. `load_campaign_dict` parses and validates `lore_entries` (duplicate ID check, audience_class validation). `lore_deck(gm_entity)` factory creates a `LoreDeck` on demand (lazy import — campaign.py has no runtime lorebook dependency).
- **`SettingsRegistry.DEFAULTS`** gains `"lorebook_injection_window": "5"` (19 total keys).
- **Security invariant tests** — four tests in `TestLoreAudienceSecurity` cover: `gm_only` not injected into player context; `gm_only` visible to GM; player-scoped entry not visible to other players; audience gate fires before keyword match (D-043 constraint 4 — keyword in player corpus doesn't unlock a `gm_only` entry).
- 45 new tests. D-043 resolved.

---

## 2026-06-19 — Phase 22 items 2 + 3: D-042 context budget management + cost ceiling (1172 tests)

**Phase 22 items 2 & 3 built** (`budgeter.py`, `provider.py`, `settings.py`, `context.py`, `character_agent.py`, `beat.py`, `__init__.py`, `tests/test_phase22_budgeter.py`):

- **`ContextBudgetPolicy(max_tokens, event_window, required_sections, summarize_older)`** — frozen dataclass; per-role configuration.
- **`BudgetCheckResult(role, token_estimate, cap, fits)`** — frozen result with `over_by` property.
- **`TokenEstimator(client=None)`** — hybrid estimator: `estimate(text)` uses char-count proxy (`len // 4`); `count(text, model, cap)` calls proxy first and triggers preflight `count_tokens` API only when the proxy is ≥ 80 % of cap. Exceptions fall back to proxy — call path never blocks on estimator failure.
- **`ContextBudgeter(policies=None, estimator=None)`** — applies per-role budget policies at context-assembly time. `policy(role)`, `event_window(role)`, `trim_events(events, role)` (most-recent window slice), `check_sections(sections, role)` (missing required-section keys), `check_budget(text, role, model)` → `BudgetCheckResult`. `ContextBudgeter.from_settings(sm, campaign_id, estimator)` reads `{role}_max_tokens` and `{role}_event_window` from `SettingsManager`, falling back to code defaults on missing or non-integer values.
- **Per-role defaults (D-042 table)**: `gm_adjudicator` 40K/20, `gm_narrator` 20K/8, `character_agent` 12K/12, `social_interpreter` 8K/6, `auditor` 16K/10, `plot_manager` 24K/15.
- **`CostCeilingStatus(OK / WARNING / EXCEEDED)`** — string enum added to `provider.py`. `TelemetrySink` gains `cost_ceiling_usd` param, `total_cost_usd()`, and `ceiling_status()`: OK below 80 %, WARNING at/above 80 %, EXCEEDED at/above 100 %; advisory-only by default.
- **`SettingsRegistry.DEFAULTS`** expanded with 12 per-role budget keys (`{role}_max_tokens`, `{role}_event_window` for the 6 named roles).
- **`ContextAssembler`** gains optional `budgeter` param + `budgeter` property; belief-store projection remains complete (budgeter does not filter events — canon accuracy is unaffected).
- **`CharacterAgent.propose(assembler, budgeter=None)`** — uses `budgeter.event_window("character_agent")` when a budgeter is supplied; falls back to assembler's own budgeter, then to `limit=12`.
- **`BeatRunner`** gains optional `budgeter` param; uses `budgeter.event_window("gm_adjudicator")` / `"gm_narrator"` for `_events_summary` / `_narrator_context`; passes `budgeter` to `agent.propose()` in `run_with_agent` and `run_round`. Falls back to `CONTEXT_EVENT_WINDOW = 12` when no budgeter configured (backward compat).
- `CONTEXT_EVENT_WINDOW` constant kept as legacy fallback; comment updated.
- 57 new tests. D-042 resolved.

---

## 2026-06-19 — Phase 22 item 1: D-017 multi-model routing (1115 tests)

**Phase 22 item 1 built** (`provider.py`, `gm.py`, `beat.py`, `__init__.py`, `tests/test_phase22_routing.py`; test fixes in `tests/test_phase5_gm.py`, `tests/test_phase20_social.py`):

- **`ProviderAdapter` ABC** — formal abstraction over provider-specific APIs. Two abstract members: `name` (str property) and `call(role, model, **kwargs)`. Intentionally separate from fictional state; adapters must be stateless w.r.t. model calls.
- **`AnthropicAdapter(ProviderAdapter)`** — wraps `anthropic.Anthropic`; forwards `call(role, model, **kwargs)` to `client.messages.create(model=model, **kwargs)`. `role` not forwarded to the SDK (logging/debug only).
- **`ToolOutputError(Exception)`** — raised when a model API call succeeds but the response doesn't match the expected tool schema after all retries. Distinct from `ModelCallError` (network/timeout). Carries `role`, `attempts`, `reason`.
- **`ModelGateway` per-role resolution** — `__init__` now accepts `ProviderAdapter | anthropic.Anthropic` (raw client auto-wrapped) and optional `SettingsManager`. `_resolve_model(role, kwargs)` checks settings first, then `model=` kwarg, then `SettingsRegistry.DEFAULTS`, then `_FALLBACK_MODEL`. `_ROLE_TO_SETTINGS_KEY` maps gateway roles to settings keys. The resolved model is always passed to the adapter; `model=` is popped from kwargs to avoid double-passing.
- **`AdjudicatorGM` structured-output normalization** — `evaluate()` retries once on parse failure (`KeyError`, `TypeError`, `ValueError`, `RuntimeError`); raises `ToolOutputError("adjudicator", 2, reason)` after two failed parses. `_parse_response()` extracted as private method.
- **`BeatRunner` ToolOutputError abort** — step 4 now catches both `ModelCallError` and `ToolOutputError`; produces an aborted `BeatResult` rather than propagating the exception.
- **Test fixes** — `test_missing_tool_call_raises` updated to expect `ToolOutputError` (not `RuntimeError`). `_gateway_returning` helper in social tests fixed to use `ModelGateway.__init__` instead of `__new__` bypass (bypassing init left `_adapter` unset, causing silent `AttributeError` swallowed by `analyze_event`).
- 30 new tests (`test_phase22_routing.py`). D-017 resolved.

---

## 2026-06-19 — Phase 21 deliverable 10: home screen + play interface (1085 tests)

**Phase 21 deliverable 10 built** (`interface.py`, `world_state.py` bugfix, `__init__.py`, `tests/test_phase21_interface.py`):

- **`HomeScreen(campaigns_dir, sessions_dir, settings_dir)`** — navigation state for the home screen. `available_campaigns()` loads campaign JSON files from disk (malformed files silently skipped). `available_sessions()` reads the `SessionManager` index. `render()` returns a formatted display string with numbered campaign/session lists and command hints. Pure navigation — does not create or resume sessions (model wiring is the caller's responsibility).
- **`PlayInterface(session, settings, roster, campaign_id, world)`** — rendering and input layer over `PlaytestSession`. Accesses the event log exclusively via `PlaytestSession.player_view()` and `step()` — never `log.all()`. `submit(text)` → new entitled display lines; `history()` → full entitled history; `render_status()` → `scene:phase  beat:N  [label]`; `render_settings()` → settings panel string with file paths, essential keys (marking overrides `*`), and character-agent slot rows derived from the roster.
- **`build_play_interface(log, world, scene, player_id, adjudicator, narrator, settings, roster, campaign_id, sheets)`** — factory that wires `CommitPipeline`, `DiceService`, `RulesEngine`, `ContextAssembler`, `BeatRunner`, `PlaytestSession` → `PlayInterface`.
- **`WorldState.zone_of()` bugfix** — previously raised `KeyError` for entities not in the world (e.g., the GM entity when building a scene-aware context assembler); now returns `None`, matching the declared return type `str | None` and the `perceptible_entities()` guard that already expected this.
- **Security tests** — three tests verify that GM-only events (`narration`, `scene_transition`, `audit_advisory` with `audience=("gm",)`) never appear in `PlayInterface.history()`.
- 60 new tests; Phase 21 all 10 deliverables complete.

---

## 2026-06-19 — Phase 21 deliverable 9: D-041 settings system (1025 tests)

**Phase 21 deliverable 9 built** (`settings.py`, `__init__.py`, `tests/test_phase21_settings.py`):

- **`SettingsRegistry`** — code-level defaults for all six essential settings: `gm_adjudicator_model` (`claude-opus-4-8`), `gm_narrator_model` (`claude-opus-4-8`), `gm_world_simulator_model` (`claude-opus-4-8`), `auditor_model` (`claude-haiku-4-5-20251001`), `social_interpreter_model` (`claude-sonnet-4-6`), `character_agent_default_model` (`claude-opus-4-8`). `ESSENTIAL_KEYS` frozenset. System always valid with zero user configuration.
- **`SettingsManager(settings_dir)`** — three-layer merge (code defaults → `settings/models.json` → `settings/campaigns/{campaign_id}.json`). `load_settings(campaign_id)`, `get(key, campaign_id)`, `set(key, value, scope)` (`"user"` or campaign_id), `reset_setting(key, scope)` (removes override, deletes empty file, reverts to next layer).
- **Character agent slots** — `character_model(entity_id, campaign_id)` resolves `character_agent_{entity_id}_model`, falls through to `character_agent_default_model`. `character_slots(roster, campaign_id)` returns `{entity_id: model}` for a full roster.
- **API key policy** — settings files store env-var names only (e.g., `"voice_api_key_env": "ELEVENLABS_API_KEY"`); never actual key values.
- **Module-level functions** — `load_settings(settings_dir, campaign_id)` and `reset_setting(key, scope, settings_dir)` for one-shot use without a manager instance.
- 58 new tests. D-041 resolved.

---

## 2026-06-19 — Phase 22 planning: SillyTavern-inspired features review

Design review of SillyTavern-inspired features against FABLE authority hierarchy. Outcome: "borrow the affordances, not the architecture." Changes to design files only — no code changes.

- **D-017 updated**: Phase 22 multi-model routing is now explicitly **must-ship first**, not a medium-priority refactor. Without per-role routing, settings model slots are cosmetic and budget policies cannot be calibrated against realistic per-role costs.
- **D-038 updated**: Portrait generation policy decided (was an open question) — generate once per character at creation/first-render, store artifact, never auto-regenerate per scene or session. Model consistency testing still required before locking a model recommendation.
- **D-043 opened**: Lorebook/world-info injection architecture and audience-gate mechanism. Decided constraints: entries are background only; audience class annotated at authoring; injection inside `ContextAssembler` keyed to POV's entitled projection only; never keyword-triggered from raw event content; D-042 (context budgeter) is a hard prerequisite. Recommendation: keyword match against POV belief projection (option A) for Phase 22 v1.
- **IMPLEMENTATION_PLAN.md Phase 22 revised**: explicit priority order added — (1) multi-model routing, (2) context budgeting + cost ceiling, (3) lorebook v1 with D-042 dependency noted, (4) prompt/style profiles, (5) reliability hardening items. Settings panel shell removed from Phase 21 concern — the existing D-041 settings system already has real content; the routing behavior that makes the model slots non-cosmetic comes in Phase 22.

---

## 2026-06-19 — Phase 21 deliverable 8: D-030 time anchor and scene transition (967 tests)

**Phase 21 deliverable 8 built** (`world_state.py`, `gm.py`, `beat.py`, `persistence.py`, `__init__.py`, `tests/test_phase21_time_anchor.py`):

- **`ELAPSED_CATEGORIES = frozenset({"beat","exchange","scene","travel","breather","downtime"})`** — added to `world_state.py` and exported from package. Maps to D-026 clock `trigger_types` so a scene transition with `elapsed_category="breather"` advances only breather-triggered clocks.
- **Time anchor fields on `WorldState`**: `scene_id` (UUID, fresh per-instance default), `beat_index` (0), `scene_phase` ("quiet"), `prose_time_label` (None), `elapsed_category` ("beat"). Backend-owned; client reads from event stream only.
- **`WorldState.advance_beat(elapsed_category="beat")`** — increments `beat_index`, records `elapsed_category`. Validates against `ELAPSED_CATEGORIES`. Called by `BeatRunner.run()` inside the transaction on every successful beat so it rolls back on abort.
- **`WorldState.begin_scene_transition(scene_phase, elapsed_category, prose_time_label)`** — generates fresh UUID `scene_id`, resets `beat_index` to 0, updates phase and label. Returns the new `scene_id`.
- **`WorldSimulator.declare_scene_transition()`** — calls `begin_scene_transition()` on world, then emits a `scene_transition` structural event (`channel="system"`, `audience=(gm,)`) with JSON payload containing `scene_id`, `scene_phase`, `elapsed_category`, and optional `prose_time_label`. Returns the new `scene_id`. Players never see this event.
- **`BeatRunner.run()`** — calls `self._world.advance_beat()` inside the transaction block after clock advance, so `beat_index` is atomic with the rest of the beat.
- **Persistence** — `SQLiteWorldState._save()` / `_load()` include all five time anchor fields. `_load()` when no row exists calls `_save()` immediately so the generated `scene_id` is persisted and a subsequent open sees the same id. Schema version bumped to `"21.3"`.
- 47 new tests; D-030 resolved.

---

## 2026-06-19 — Phase 21 deliverable 7: D-028 knowledge transfer enforcement (920 tests)

**Phase 21 deliverable 7 built** (`events.py`, `__init__.py`, `tests/test_phase21_knowledge_transfer.py`):

- **`TRANSFER_TYPES = frozenset({"share_briefing", "object_shown"})`** — added to `events.py` and exported from package. These are the two deliberate knowledge-transfer event types: `share_briefing` (explicit verbal briefing — "Mira tells the group what she saw") and `object_shown` (a physical object or document shown to specific parties).
- **No-`fact` invariant enforced at event construction** — `Event.__post_init__` rejects any `share_briefing` or `object_shown` event that carries a `"fact"` commitment. Error message cites D-028. `"claim"`, `"observation"`, and `"theory"` commitments are permitted. The rule: from the receiver's perspective, transferred knowledge is always a claim from the sharing entity; independent engine evidence is required to promote it to `"fact"`.
- **Belief store integration verified** — tests confirm that transferred claims land in `BeliefStore.claims`, never in `beliefs` (facts dict); `believes()` and `value_of()` remain false/None for keys known only via transfer; `claims_about()` finds the claim with its `asserting_entity` provenance intact.
- 26 new tests covering: constant shape, event validation (accept/reject matrix), round-trip through `EventLog.append()`, belief-store projection for hero/gm/non-audience, and fact+claim coexistence test proving the client cannot auto-promote a briefing into a confirmed fact. D-028 resolved.

---

## 2026-06-19 — Phase 21 deliverable 6: D-032 epistemic certainty labels (894 tests)

**Phase 21 deliverable 6 built** (`events.py`, `context.py`, `console.py`, `__init__.py`, `tests/test_phase21_epistemic_labels.py`):

- **`"theory"` added to `EPISTEMIC_TYPES`** in `events.py`. Character inferences and explicit suspicions can now be committed with this type. Not promoted to `"fact"` without engine evidence.
- **`EPISTEMIC_LABELS` dict** in `console.py`: `fact→"Confirmed"`, `claim→"Claimed"`, `observation→"Observed"`, `theory→"Suspected"`. Backend-emitted; client never computes from prose or inference.
- **`epistemic_label(type, *, superseded=False)`** — public helper; returns `"Corrected/Superseded"` when `superseded=True` (D-031 takes precedence), `"Unknown"` for unrecognized types (reserved for GM Case File template slots). Exported from package.
- **`_commitment_labels(event)`** — formats all commitments on a `ProjectedEvent` as bracketed label strings; returns `""` when there are no commitments.
- **`render_event()` updated** — every rendered branch appends `_commitment_labels(event)` so the player sees e.g. `The door was red. [Confirmed: door.colour=red]`.
- **`BeliefStore.theories: tuple[Belief, ...]`** — new field in `context.py`. Mirrors `claims` and `observations` for the `"theory"` epistemic type.
- **`_fold_epistemic()`** now returns a 4-tuple `(facts, claims, obs_list, theories)`. `beliefs_from()` and `belief_store()` updated accordingly. `"theory"` commitments enter `theories` and never enter the facts dict.
- 36 new tests; D-032 resolved.

---

## 2026-06-19 — Phase 21 deliverable 5: D-031 correction and retcon events (858 tests)

**Phase 21 deliverable 5 built** (`events.py`, `event_log.py`, `console.py`, `persistence.py`, `__init__.py`, `tests/test_phase21_correction.py`):

- **`CORRECTION_TYPES = frozenset({"correction", "retcon"})`** — added to `events.py` and exported from package. Both types are plain logged events; the log remains append-only.
- **`Event.authorized_by: tuple[str, ...]`** — new field; default empty. `__post_init__` enforces non-empty for `retcon` type (D-031 backstop: retcon requires human player in `authorized_by`). Included in `to_dict()`.
- **`ProjectedEvent.superseded_by: str | None`** — computed in `project_for()` by scanning for correction/retcon events whose `derived_from` lists reference the original; set to the corrector's event ID. `None` for uncorrected events and for the correction events themselves.
- **`render_event()` updated**: `correction` → `"[correction] {content}"`; `retcon` → `"[retcon] {content}"`; any event with `superseded_by` set gets `"[superseded] "` prefix. Original events are never omitted from the transcript.
- **`authorized_by` threaded** through `EventLog.append()` and `SQLiteEventLog.append()`. Persistence schema gains `authorized_by TEXT NOT NULL DEFAULT '[]'`; `ENGINE_SCHEMA_VERSION` bumped to `"21.2"`.
- 24 new tests; D-031 resolved.

---

## 2026-06-19 — Phase 21 deliverable 4: D-029 roll visibility (834 tests)

**Phase 21 deliverable 4 built** (`events.py`, `event_log.py`, `dice.py`, `rules.py`, `beat.py`, `console.py`, `persistence.py`, `__init__.py`, `tests/test_phase21_roll_visibility.py`):

- **`ROLL_VISIBILITY_LEVELS`** frozenset — `{"table", "roller_only", "gm_only", "revealed"}` — added to `events.py` and exported from package.
- **`Event.roll_visibility: str | None`** new field; validated in `__post_init__`; included in `to_dict()`. Default `None` for all non-dice events.
- **`ProjectedEvent.roll_visibility: str | None`** — threaded from `Event` through `project_for()` so `render_event()` and any display layer can read the value without re-deriving it from audience membership.
- **`EventLog.append()` / `SQLiteEventLog.append()`** — both accept `roll_visibility` kwarg.
- **`DiceService.roll()`** — `roll_visibility="table"` param; validates value; stores on event.
- **`RulesEngine.resolve_check()`** — `roll_visibility="table"` param; tags both the `dice_roll` and `resolution` events with the same value.
- **`_narrator_context()`** in `beat.py` — filters `roll_visibility == "gm_only"` events from narrator input (D-007 cold/warm split enforcement).
- **`render_event()`** in `console.py` — explicit guard: `gm_only` dice events return `None` even if they somehow reach a player projection. `roller_only` and `revealed` render normally.
- **Persistence**: `events` table gains `roll_visibility TEXT` (nullable) column; `ENGINE_SCHEMA_VERSION` bumped to `"21.1"`.
- Audience-based enforcement is primary: `gm_only` rolls use `audience=(gm,)` so they never appear in player projections. `roll_visibility` tag is a secondary safety net + audit label.
- 29 new tests; D-029 resolved.

---

## 2026-06-19 — Phase 21 deliverable 3: D-027 action lifecycle state machine (805 tests)

**Phase 21 deliverable 3 built** (`beat.py`, `console.py`, `__init__.py`, `tests/test_phase21_lifecycle.py`):

- **`ActionLifecycleState(str, Enum)`** — 13 states: `SUBMITTED → VALIDATING → ADJUDICATING → PENDING_PLAYER_CHOICE → ROLLING → PENDING_EDGE_DECISION → APPLYING_EFFECTS → NARRATING → AUDITING → COMMITTED`; exits `CANCELLED / ABORTED / FAILED`. `str` mixin so values pass as event content strings without `.value`.
- **`BeatRunner._emit_lifecycle(state, audience)`** — single emission point; emits `type="action_lifecycle"` event with no content side-effects.
- **`BeatResult.lifecycle_state`** — new field, defaults to `COMMITTED`; every return path now carries the correct terminal state.
- **Audience policy enforced**: internal processing states (`VALIDATING`, `ADJUDICATING`, `APPLYING_EFFECTS`, `NARRATING`, `AUDITING`) → `(gm,)` only; interactive pause states (`PENDING_PLAYER_CHOICE`, `PENDING_EDGE_DECISION`) → `(actor, gm)`; terminal states (`SUBMITTED`, `COMMITTED`, `ABORTED`, `FAILED`) → `scope.audience` (all present).
- **OOC path**: emits `SUBMITTED → COMMITTED`; skips all intermediate steps.
- **`ModelCallError` handling**: targeted `try/except` around adjudicator call (outside transaction); `except ModelCallError` added to existing `try: with transaction()` block for narrator failures (transaction rollback happens before catch). Both paths emit `FAILED` to all-present and return `beat_aborted=True`.
- **`render_event`** in `console.py` returns `None` for `action_lifecycle` events — clients use them as state metadata, not chat lines.
- **`ActionLifecycleState` exported** from `fable_table_engine.__init__`.
- 30 new tests in `tests/test_phase21_lifecycle.py`; D-027 resolved.

---

## 2026-06-19 — D-042 opened: context budget management; CONTEXT_EVENT_WINDOW named constant

**Design work (no new tests):**

- **D-042 opened** in `DECISIONS.md` — context budget management architecture. Key decisions recorded: `ContextBudgeter` belongs at context-assembly time (not gateway boundary); hybrid preflight estimation (D-042 option C); per-role `ContextBudgetPolicy` table (six roles with token caps and event windows); context quality check advisory via `AuditFlag(WARNING)`; per-session cost ceiling in `TelemetrySink`. Implementation target: Phase 22.
- **`ContextBudgeter`, `ContextBudgetPolicy`, `TokenEstimator`** added to `COMPONENTS.md` as Phase 22 deliverables.
- **Phase 22 implementation plan expanded** in `IMPLEMENTATION_PLAN.md` — four new items: context budget management, per-session cost ceiling, `CONTEXT_EVENT_WINDOW` → settings-driven promotion.
- **`CONTEXT_EVENT_WINDOW = 12`** added as a module-level named constant in `beat.py` (replaces the two `limit: int = 12` inline defaults in `_events_summary` and `_narrator_context`). This is a Phase 21 placeholder; Phase 22 replaces it with per-role `ContextBudgetPolicy` entries loaded from `SettingsManager`.

---

## 2026-06-19 — Phase 21 deliverable 2: Edge mechanic — Lean / Push / Shield (775 tests)

**Phase 21 deliverable 2 built** (`beat.py`, `character_agent.py`, `tests/test_phase21_edge.py`):

- `_step_band_up(band)` — pure helper: steps a band up one level, clamps at Triumph (v6 §13).
- `Proposal` gains `edge_spend`, `edge_justification`, `edge_shield_target` fields.
- `BeatResult` gains `edge_spend`, `edge_spent`, `edge_step_applied` fields.
- `BeatRunner.run()` gains `edge_spend`, `edge_justification`, `edge_shield_target`, `_shield_registry` params.
  - **Step 4c (pre-roll Lean):** before roll, if `edge_spend="lean_before"` + executor + stakes + exposure > 0: spend 1 Edge, reduce `effective_exposure` by 1. Outside transaction (mechanical fact, persists on abort per D-035 philosophy).
  - **Step 5b (post-roll step-up):** after roll, if `lean_after` (+ non-empty justification) or `push` (+ 2-Stress headroom) and band ≠ Triumph: spend Edge (Push also costs 2 Stress), step `effective_band` up one level. Outside transaction.
  - **Step 6b additions:** palette selection uses `effective_band` (not raw `resolution.band`); Shield redirect: Harm (ApplyStress/ApplyScar) targeting a shielded entity is redirected to the shielder with 1 Edge spend from the shielder (inside transaction); GainEdge filtered from `triumph_effects` when `edge_step_applied` (v6 §13: "a band reached by spending Edge generates no Edge").
  - Narrator receives `effective_band` (stepped band visible to narrator).
- `run_with_agent()` passes edge fields from `Proposal` to `run()`.
- `run_round()` pre-collects all proposals before the round begins, builds `shield_registry: {shielded_id: shielder_id}` from Shield declarations, passes registry to each `run()` call. ValueError raised at pre-collection stage (not lazily during the round).
- 28 new tests: `_step_band_up` (4), Lean-before (5), Lean-after (6), Push (6), invariants (3), Shield (4).

---

## 2026-06-19 — Phase 21 deliverable 1: schema version guard + session manager (747 tests)

**Phase 21 deliverable 1 built** (`persistence.py`, `tests/test_phase21_session.py`):

- `ENGINE_SCHEMA_VERSION = "21"` — bump this constant when a DB migration is needed; Phase 22 adds the migration registry.
- `SchemaVersionError` — raised by `open_session()` and `SessionManager.resume()` on version mismatch; fail-closed.
- `open_session()` updated: writes `schema_version` row on first open; validates and raises `SchemaVersionError` on mismatch.
- `SessionManifest` — frozen dataclass (10 fields: `session_id`, `campaign_id`, `title`, `created_at`, `updated_at`, `last_scene_summary`, `player_summary`, `db_path`, `schema_version`, `engine_version`); `to_dict`/`from_dict` round-trip.
- `SessionManager` — creates sessions (UUID, DB at `sessions_dir/{session_id}.db`, index at `sessions_dir/index.json`), lists sessions (ordered by `updated_at` descending), resumes sessions (schema guard via `open_session`), updates manifest fields.
- 22 new tests cover: fresh DB write, resume matching/mismatching version, frozen manifest, round-trip, optional defaults, create/list/resume/update_manifest lifecycle, events surviving resume, wrong schema on resume, unknown session_id.
- `__init__.py` exports: `ENGINE_SCHEMA_VERSION`, `SchemaVersionError`, `SessionManifest`, `SessionManager`.
- `IMPLEMENTATION_PLAN.md` Phase 21 deliverables list updated to explicit dependency order (10 items).

---

## 2026-06-19 — Settings system design locked (D-041)

**No code changes.** Design and planning documents only.

**D-041 opened and resolved** (Settings system):
- Layered JSON hierarchy: code defaults → `settings/models.json` → `settings/campaigns/{campaign_id}.json`. Engine always in a valid state with zero user configuration.
- All essential model slots have defaults: `gm_adjudicator_model` / `gm_narrator_model` / `gm_world_simulator_model` / `auditor_model` / `social_interpreter_model` / `character_agent_default_model` all default to `claude-opus-4-8` except auditor (`claude-haiku-4-5-20251001`) and social interpreter (`claude-sonnet-4-6`).
- Character agent slots are campaign-aware: one `character_agent_{entity_id}_model` key per seat in the loaded campaign roster, derived at load time.
- API keys (voice, etc.) never stored in settings files; manager holds only the env-var name; GUI shows name + set/not-set status indicator only.
- GUI contract: per-setting Reset button, file-path display, open-in-system-editor button; character slot rows generated dynamically from roster.
- Planned components: `SettingsRegistry` (code defaults), `SettingsManager` (three-layer resolution, reads/writes JSON files), settings panel (interface sub-view).

**Phase 21 deliverables updated** (IMPLEMENTATION_PLAN.md):
- Added settings system as deliverable 5 (play interface renumbered to 6).
- Exit gate extended: model choices and agent slots configurable and persistent across sessions.

**COMPONENTS.md updated**: Settings system section added (after Session management section): `SettingsRegistry`, `SettingsManager`, settings panel.

---

## 2026-06-19 — Phase 21 scope expansion + post-v1 track design (D-039, D-040)

**No code changes.** Planning and design lock only.

**Phase 21 scope expanded** (IMPLEMENTATION_PLAN.md):
- Home screen added as a Phase 21 deliverable: start screen with "New Campaign" (load pre-built `CampaignPackage`) and "Return to Saved Session" (session list).
- Session manager (`SessionManifest`, `SessionManager`) added as Phase 21 deliverables: list/create/resume sessions; `SessionManifest` fields documented; schema version guard pulled forward from Phase 22.
- Minimal schema version marker pulled forward: `open_session()` writes `schema_version` on first open; fails-closed on mismatch on resume. Phase 22 retains full migration registry work.
- Phase 21 deliverables list now explicitly enumerates: home screen, session manager, schema version guard, production text-channel API (D-027/D-029/D-030/D-031/D-032/D-028), play interface.
- Exit gate extended: sessions must be resumable across engine restarts without state corruption or silent schema mismatch.

**D-039 opened and resolved** (Voice/TTS manual playback design):
- Manual click-to-play only; off by default; per-speaker voice IDs in `settings/voice.json`; API key in env only (never in save file); audio cached per event-id+voice-id hash; TTS failure degrades to text; no game-state coupling.
- Post-Phase-21 track. Do not implement during Phase 21 or Phase 22.
- Planned components: `VoiceGateway`, `VoiceArtifactCache`, `settings/voice.json`.

**D-040 opened and resolved (deferred)** (Campaign generation pipeline, Campaign-Authoring Studio):
- Both generation modes (auto-generate, generate-from-prompt) lead to the same `CampaignPackage` via `CampaignCompiler` → validation → repair/retry.
- Raw user input never reaches GM runtime context directly.
- Phase 21 "New Campaign" flow loads pre-built packages only; generation UI is Campaign-Authoring Studio post-v1.
- Required campaign fields table documented. Planned components: `CampaignCompiler`, `CampaignCompilerGateway`.

**COMPONENTS.md updated**: Session management section added (Phase 21); Voice/TTS layer section added (post-v1); Campaign-Authoring Studio section added (post-v1).

**DECISIONS.md updated**: D-039 and D-040 added; D-038 unchanged; Resolved section index updated.

---

## 2026-06-19 — Pre-Phase-21 Stress/Scar pull-forward

Pulled forward from Phase 22 (beta hardening) as a live-play prerequisite. Addresses v6 §14 and invariant 9.

**`ApplyScar` typed effect** (`effects.py`):
- Fields: `entity_id`, `scar_type` (`"wound"` | `"mark"` | `"loss"`), `description`, `via_overflow: bool = False`, `seam_event_id: str | None = None`.
- **Scar Route Invariant** enforced: rejected if neither `via_overflow=True` nor `seam_event_id` is set.
- **3-slot cap** (`SCAR_CAP = 3`): 4th Scar rejected. When the 3rd Scar lands, executor appends a `character_broken` event (derived from the scar event).
- Scars stored as `entity.resources["scars"]`: `list[{"scar_type": ..., "description": ...}]`.

**`ApplyStress` cap enforcement** (`effects.py`):
- `STRESS_CAP = 6` added. Positive stress that would exceed 6 triggers the overflow route.
- Overflow requires `overflow_scar_type` + `overflow_scar_desc` on the `ApplyStress` effect; omitting them rejects the effect.
- Overflow cascade: stress is cleared to 0, then `_apply_scar` is called internally with `via_overflow=True`. Scar cap rejection surfaces back through the `ApplyStress` result.
- Negative stress (relief) floors at 0; no lower bound validation change needed.

**`effect_from_dict` / `describe_effect`** updated for both new types.

**`SCAR_CAP = 3`, `STRESS_CAP = 6`** exported from `__init__.py`.

**30 new tests** in `tests/test_phase_scar.py`. **725 total tests passing.**

**Files changed:** `effects.py`, `__init__.py`, `COMPONENTS.md`, `CHANGELOG.md`.
**Unresolved decision IDs:** Seam (`CreateSeam` typed effect) is still Phase 22 — the `seam_event_id` field accepts any event ID today; live-Seam validation (is it actually an active Seam event?) is deferred.

---

## 2026-06-19 — D-027 through D-032: interface-facing decisions locked

**No code changes.** Design lock before Phase 21 implementation.

**D-027 (Action lifecycle states) — Resolved:** Backend-owned state machine `draft → submitted → validating → pending_player_choice → adjudicating → rolling → applying_effects → auditing → narrating → committed` with exits `cancelled / aborted / failed`. Client reads state, never writes it. OOC bypass path preserved. Aborted beat leaves dice events intact (D-035 settled).

**D-028 (Knowledge transfer mechanisms) — Resolved:** Knowledge moves only through logged authorized events (whisper, public statement, share/briefing, shown object, observed action, perception-derived overhear). All transferred knowledge enters the receiving character's belief store as `epistemic_type="claim"`, never `"fact"`. Client never transfers facts between views.

**D-029 (Roll visibility) — Resolved:** Four `visibility` values: `table` (default player roll, all authorized viewers see cold resolved detail), `roller_only`, `gm_only` (default GM/NPC roll, warm GM never receives it), `revealed` (GM has explicitly surfaced a hidden roll). Client and warm GM never receive `gm_only` rolls unless the roll's visibility is updated to `revealed`.

**D-030 (Fictional time model) — Resolved:** Minimal backend-owned time anchor: `scene_id` (UUID, changes on major transition), `beat_index`, `scene_phase` (= `SceneMode`), `prose_time_label` (optional narrator-written label), `elapsed_category` (moments/hours/days/weeks/longer). Backend emits `scene_transition` structural event when `scene_id` changes. Client is a receiver only. The `scene_id` change serves as D-038's "major scene transition" trigger for portrait/scene image caching.

**D-031 (Retcon/correction policy) — Resolved:** Two new event types: `correction` (authoritative correction of a prior fact; any authorized party) and `retcon` (strong narrative rewrite; requires human player in `authorized_by`). Append-only log preserved. `render_event()` emits superseded markers for entries with downstream corrections/retcons. No silent history rewriting.

**D-032 (Epistemic certainty labels) — Resolved:** Six player-facing certainty labels emitted by the backend alongside commitments: `Confirmed` (`"fact"`), `Claimed` (`"claim"`), `Observed` (`"observation"`), `Suspected` (`"theory"` — added in Phase 21), `Unknown` (GM-annotated Case File template slot only; client never infers from absence), `Corrected/Superseded` (has a D-031 correction/retcon event). Client renders only; never computes certainty. Warm GM phrasing contract (declarative/attributed/perceptual-hedge/inference voice by epistemic type) enforced by auditor advisory flag. `"theory"` added to `EPISTEMIC_TYPES` in Phase 21.

**Files changed:** DECISIONS.md (D-027 through D-032 resolved; Resolved index and MVP Defaults updated).

---

## 2026-06-19 — D-038: image generation architecture (planning capture)

**No code changes.** Planning capture only — post-Phase-21 rendering layer, not implemented.

**D-038 opened** (DECISIONS.md): full image generation architecture spec covering character portraits, scene images, map backgrounds, and text-graphic artifacts. Supersedes D-014 (absorbs its two load-bearing constraints).

**Decided constraints recorded:**
- Images are presentation only; `non_authoritative=True` on every artifact; event log wins on contradiction.
- `ImagePromptAssembler` draws from viewer's authorized belief store only — POV partitioning applies to image prompts the same as to fiction.
- Style instructions come from a user-editable config file (`settings/style_profile.json`), never from game state. Style and subject prompts are kept separate through to the API call.
- Map images are aesthetic backgrounds only; location/route/fog-of-war/position overlaid from deterministic FABLE state.
- Async generation, aggressive caching (snapshot hash), user visual mode: off/cheap/premium.

**Open questions flagged:** portrait model (needs consistency testing), style profile file format, deterministic map rendering architecture, major-scene-transition definition as cache trigger, multi-viewer cache semantics.

**Planned components added to COMPONENTS.md:** `ImageGenerationGateway`, `ImagePromptAssembler`, `ImageArtifactStore`/`ImageArtifact`, style profile.
**IMPLEMENTATION_PLAN.md:** Scene Imagery post-v1 track expanded with D-038 full spec reference.

---

## 2026-06-19 — Phase 20: social interpretation and Bond compels

**New module `social.py`:**
- `BondRef` (frozen dataclass in `character_sheet.py`) — stable reference linking a narrative Bond to a Commitment ID in the event log. `CharacterSheet.bond_refs: list[BondRef]` added (mechanical handle); `bonds: list[str]` preserved for display and backward compat.
- `PendingCompel` — frozen dataclass; the validated, unresolved state of a compel waiting for player accept/refuse. Never mutates state — it is a proposal, not a commitment.
- `CompelResolution` — outcome of `resolve_compel()`: accepted flag, event IDs, applied effects list.
- `SocialInterpreter` — model-driven analysis of social events via two tool calls: `propose_social_delta` and `propose_compel`. Validates proposals (unknown entities rejected, self-reference rejected, zero deltas rejected, interiority language screened). Returns `(list[DispositionDelta], list[PendingCompel])` — no state written. On model failure: graceful `([], [])` return.
- `resolve_compel(pending, accepted, log, executor, audience)` — the authoritative write point for compel outcomes. Accept: logs `compel_accepted`, applies `GainEdge(1)` via `EffectExecutor`, logs `compel_resolved`. Refuse: logs `compel_refused`, logs `compel_resolved`. All events derive from `compel_proposed_event_id`.
- Interiority invariant enforced: `_check_interiority()` screens for language asserting character feelings/beliefs/choices; proposals containing flagged patterns are rejected before reaching the caller.

**Modified `effects.py`:**
- `GainEdge(kind, entity_id, amount)` — grants Edge; enforces cap-3 invariant (v6 §13); silently clamps if already at cap.
- `SpendEdge(kind, entity_id, amount, spend_type)` — spends Edge; rejects if insufficient; logs spend_type for provenance.
- Both added to `TypedEffect` union, `EffectExecutor.apply()`, `effect_from_dict()`, `describe_effect()`.

**Modified `provider.py`:**
- `ModelCallError` exception — typed failure after all retries exhausted; carries `role`, `attempts`, `last_error`.
- `ModelGateway.__init__` now accepts `timeout_secs: float | None = 60.0` and `max_retries: int = 1`.
- `ModelGateway.call()` implements timeout forwarding via `kwargs.setdefault("timeout", ...)`, retry loop on `APITimeoutError`/`APIConnectionError` with exponential backoff (0.5 s, 1.0 s, …), telemetry recorded per attempt (including failed attempts with zero tokens), `ModelCallError` raised after all attempts fail.

**D-011** fully resolved (Phase 20 adds model-proposed delta path). D-017 timing note updated (ModelGateway IS the seam; full adapter → Phase 22).

52 new tests (`tests/test_phase20_social.py`); 695 total.

---

## 2026-06-19 — Phase 19: disposition graph core

**New module `disposition.py`:**
- `DispositionAxis` enum — `TRUST`, `AFFECTION`, `RESPECT`, `OBLIGATION`.
- `DispositionDelta` — frozen dataclass; `causal_event_id` required (enforced in `__post_init__`); `delta` must be non-zero; `to_dict`/`from_dict` roundtrip.
- `DispositionGraph` — directed, asymmetric, multi-axis relationship state. `apply_delta` is the sole write path; `edge(from_id, to_id)` returns current axis values; `deltas_for_event(event_id)` returns causal provenance; `context_block(from_id)` renders non-zero relationships for agent prompts. `to_dict`/`from_dict` serialization.
- `DispositionEngine` — sole authoritative writer of the graph (CORE §7.5). `process_event(event)` runs the deterministic recognition rule table; D-011 option (c) deterministic half: `"disposition_delta"` commitment (explicit signal), `"stress_taken_for"` (→ +1 trust), `"triumph_for"` (→ +1 respect). Model-proposed deltas for ambiguous social cues deferred to Phase 20.

**Modified `persistence.py`:**
- `SQLiteDispositionGraph` — SQLite-backed `DispositionGraph` subclass; `apply_delta` calls `_save()`. `_load()` clears and repopulates from DB on init and on rollback. Shares `_tx_active` with `SQLiteEventLog` for D-023 atomicity.
- `SQLiteEventLog._disposition_ref` — new back-reference; `transaction()` rollback now includes `_disposition_ref._load()` so disposition mutations are atomic with event log and world state.
- `attach_disposition(log) -> SQLiteDispositionGraph` — factory; wires rollback via `_disposition_ref`.

**D-011** partially resolved: deterministic recognition half built; model-proposed path deferred to Phase 20. Recorded in `DECISIONS.md` resolved section.

37 tests (`tests/test_phase19_disposition.py`); 643 total.

---

## 2026-06-18 — v6 reference reconciliation and coverage audit

**Reference cleanup:** Replaced all ghost references to `fable_engine.md` (Engine Schema v4) with `uploads/FABLE_Engine_Schema_v6.md` project-wide. Affected files: `rules.py`, `character_sheet.py`, `gm.py`, `tests/test_phase1_behavior.py`, `COMPONENTS.md`, `DECISIONS.md`, `FABLE_Table_Engine_Blueprint.md`, `STATUS.md`, `00_README.md`, and prior `CHANGELOG.md` entries. Confirmed by grep — zero remaining references to the old path.

**Coverage audit:** Cross-referenced `effects.py`, `rules.py`, `character_sheet.py`, `gm.py`, and beat/resolution machinery against `uploads/FABLE_Engine_Schema_v6.md` (§5–§23). Full gap table added to `STATUS.md`. Key findings:
- Core resolution surfaces (§5–§8, §11–§13 bands, §16 Clocks, §12 Truths, §13 Edge field) are built.
- Missing typed effects: `ApplyScar`, `GainEdge`, `SpendEdge`, `CreateSeam` — none have `EffectExecutor` operations.
- Stress overflow → Scar route (§14/§23 inv. 9) is the most mechanically critical gap for live play.
- Unimplemented subsystems: Prep Rounds (§18), Volatile overlay (§20), Advancement (§21), Opposition classes (§19), recovery clocks (§12), TN deterministic enforcement (§6).
- Phase assignments: Edge effects → Phase 19; all other gaps → Phase 22. Full breakdown in `STATUS.md` coverage table and `IMPLEMENTATION_PLAN.md` Phase 22 section.

**Context:** Prompted by collaborator notes (`uploads/h.md`) requesting explicit v6 audit and gap tracking in STATUS/IMPLEMENTATION_PLAN rather than leaving them implicit.

---

## 2026-06-18 — Phase 17: campaign package + plot-graph core

**New module `campaign.py`:**
- `CampaignPackage` — validated, deserialized campaign data: `title`, `version`, `description`, `function_nodes`, `hooks`, `fronts`, `factions`, `hidden_nodes`, `alternative_fixtures`, `world_clocks`.
- `load_campaign(path) -> CampaignPackage` — reads and validates a campaign JSON file from disk.
- `load_campaign_dict(data) -> CampaignPackage` — validates and deserializes a campaign dict. Cross-reference validation: hook `function_id` must match a declared function node; front `clock_name` must match a declared world clock (when any are declared); front `faction_id` must match a declared faction (when any are declared). Duplicate IDs rejected. `ValueError` on any failure.
- `CampaignPackage.to_plot_graph() -> PlotGraph` — constructs a live in-memory `PlotGraph` from the package.
- `CampaignPackage.seed_world(world)` — seeds `WorldState.set_clock` for each `world_clocks` entry.
- Hook alternatives are embedded per hook in the campaign JSON (`alternatives` list) and extracted into `PlotGraph.alternative_fixtures` at load time.

**New schema `schemas/campaign.schema.json`:** JSON Schema (draft-07) for campaign packages; documents all fields, types, defaults, and relationship constraints.

**Modified `plot_graph.py`:**
- `PlotGraph.update_hook_binding(function_id, new_binding)` — new mutation seam; `SQLitePlotGraph` overrides it to call `_save()`. `PlotManager.accept_rebinding` now routes through this method instead of mutating `hook.binding` directly, so the SQLite subclass can intercept and persist.
- `PlotGraph.add_hidden_node(node)` — new method for hidden node additions (also overridden by `SQLitePlotGraph`).
- `PlotGraph.to_dict() -> dict` — serializes the full graph to a JSON-compatible dict (for persistence).
- `PlotGraph.from_dict(d) -> PlotGraph` — classmethod that deserializes a dict produced by `to_dict()`.

**Modified `plot_manager.py`:**
- `PlotManager.accept_rebinding` now calls `self._graph.update_hook_binding(hook.function_id, new_binding)` instead of iterating hooks directly. No behavior change for in-memory graphs; enables `SQLitePlotGraph` to persist the rebinding.

**New `SQLitePlotGraph` in `persistence.py`:**
- `SQLitePlotGraph(conn, _tx_active)` — SQLite-backed `PlotGraph` subclass; same interface as `PlotGraph`. Every mutation method (`add_function`, `add_hook`, `add_front`, `add_faction`, `add_hidden_node`, `set_alternatives`, `update_hook_binding`) calls `_save()` after the in-memory change. `_load()` clears all collections and repopulates from DB; called on init and on transaction rollback.
- Table: `plot_graph (key TEXT PRIMARY KEY, value TEXT NOT NULL)` — single JSON blob row, matching the `world_state` pattern.
- `SQLiteEventLog` gains `_plot_graph_ref: SQLitePlotGraph | None = None`; `transaction()` rollback now calls `_plot_graph_ref._load()` so plot graph mutations are included in the D-023 atomic beat transaction.

**New `attach_campaign(log, campaign=None)` in `persistence.py`:**
- Creates a `SQLitePlotGraph` sharing the log's connection and `_tx_active`, wires it to `log._plot_graph_ref`, and (if the graph is empty and a campaign is supplied) seeds from the campaign. A resumed session's existing graph is never overwritten. Call after `open_session`.

**Access control invariant (structural):** No code path leads from `SQLitePlotGraph` or `PlotGraph` to `project_for`, `CommitPipeline`, or any player-facing projection. Campaign package data must never be passed to player or TM belief stores. The isolation is structural.

**Decisions:** D-016 extended to cover `SQLitePlotGraph` as the persistence layer for PlotManager's sole-writer contract. D-037 resolved (see DECISIONS.md). D-034 not yet resolved — Phase 17 campaign schema intentionally does not include Opening/MaintainedTruth data; that decision can be made independently.

**Tests:** 31 new tests in `tests/test_phase17_campaign.py`; **606 total** (all pass).

---

## 2026-06-18 — Phase 16: scene cadence + companion activation gate

**New types in `orchestrator.py`:**
- `SceneMode` (str enum) — six narrative modes: `quiet`, `dialogue`, `tactical`, `combat`, `downtime`, `high_drama`. Combat / tactical / high-drama activate all present companions; quiet and downtime cap at 1; dialogue caps at 2.
- `SceneCadence` — holds the current `SceneMode` and an always-active companion set. `set_mode(mode)` transitions scene mode deterministically (no model call). `select_companions(candidates, *, spotlight_order)` returns the activated subset: always-active companions first, then conditional companions in spotlight priority order up to the remaining slots. A companion not returned must receive no model call.
- `Orchestrator.sorted_by_spotlight(candidates)` — new public helper that sorts candidates least-recently-acted first (never-acted → highest priority). Used by `SceneCadence.select_companions` for slot assignment in limited modes.

**Modified `beat.py`:**
- `BeatRunner.run_round` gains optional `scene_cadence: SceneCadence | None = None` parameter. When supplied, AI companion seats are filtered through `scene_cadence.select_companions` (with spotlight priority from the orchestrator) before the round loop begins. Gated companions are removed from `remaining` and receive zero model calls. Human seats (those without an `agents` entry) are never gated. Backward-compatible: omitting `scene_cadence` restores the previous every-seat-every-round behaviour.

**Decision resolved:** D-021 (option b — explicit scene modes, deterministic transitions, agent bidding deferred).

**Tests:** 46 new tests in `tests/test_phase16_cadence.py`; 572 total (all pass).

---

## 2026-06-18 — Phase 15: human-seat adapter + text playtest console

**New module `console.py`:**
- `parse_proposal(text, agent) -> Proposal` — converts raw player text to a channel-tagged `Proposal`. Syntax: `whisper <target>: <intent>` → whisper; `/ooc <intent>` → OOC; anything else → public. Raises `ValueError` for malformed whisper (no colon, empty target, empty intent) or empty input. Extra whitespace is stripped.
- `render_event(event: ProjectedEvent) -> str | None` — formats one entitled event as a display string. Renders `narration`, `ooc`, `dice_roll`, `resolution`, `front_advance`; returns `None` for GM-internal types (audit, system, effect_applied, etc.).
- `PlaytestSession(runner, assembler, player_id)` — wraps `BeatRunner` with: `step(text)` (parse → run → return new entitled lines), `player_view()` (full entitled history), `export_transcript()` (text), `export_transcript_json()` (list of dicts). Reads only `assembler.belief_store(player_id)` — never the raw log or GM context. `_drain_new_events()` tracks rendered event IDs so `step()` returns only what is new since the last call.

**Architecture invariants met:**
- The client never computes audiences, rules, effects, or hidden state.
- Human proposals and AI proposals use the same `Proposal` → `BeatRunner.run()` contract (D-015 groundwork; seat-agnostic path intact).
- `export_transcript_json` is derived from `belief_store`, not the raw log — entitlement is structural, not checked at render time.

**Exports:** `PlaytestSession`, `parse_proposal`, `render_event` added to `__init__.py` and `__all__`.

**Tests:** 44 new tests (`tests/test_phase15_console.py`); 526 total. Covers: proposal parsing (all three channels, edge cases), event rendering (all event types), `PlaytestSession.step` (narration, OOC, incremental drain, repeated calls), entitlement isolation (GM-only events invisible, third-party whispers invisible), whisper target visibility, `player_view`, `export_transcript`, `export_transcript_json`.

---

## 2026-06-18 — Phase 14: provider gateway + isolated telemetry (D-017, D-022)

**New module `provider.py`:**
- `ModelGateway` — single controlled seam for all model calls. Wraps an `anthropic.Anthropic` client (or any duck-typed mock). `call(role, **kwargs)` delegates to `client.messages.create(**kwargs)`, records a `CallRecord` with latency + token counts + cost, and returns the response unchanged.
- `TelemetrySink` — in-process append-only store of `CallRecord` entries. `summary()` returns totals and per-role breakdowns. Zero coupling to fictional state (D-022): no reference to `EventLog`, `CommitPipeline`, `ContextAssembler`, or any belief store.
- `CallRecord` — dataclass: `role`, `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd`, `latency_ms`.
- Pricing table (cached 2026-06-04): `claude-sonnet-4-6` ($3.00/$15.00 per 1M), `claude-haiku-4-5[-20251001]` ($1.00/$5.00 per 1M), `claude-opus-4-8` ($5.00/$25.00 per 1M). Cache read ≈ 0.1× input; cache write (5-min TTL) ≈ 1.25× input. Unknown models fall back to sonnet pricing.

**Caller changes (all four model-call sites):**
- `AdjudicatorGM`, `NarratorGM` (`gm.py`): constructor `client: anthropic.Anthropic` → `gateway: ModelGateway`; attribute renamed `_client` → `_gateway`; call sites use `self._gateway.call("adjudicator", ...)` / `self._gateway.call("narrator", ...)`.
- `CharacterAgent` (`character_agent.py`): same pattern; call site uses `self._gateway.call("character_agent", ...)`.
- `Auditor` (`auditor.py`): constructor `client: anthropic.Anthropic | None` → `gateway: ModelGateway | None`; call site uses `self._gateway.call("auditor", ...)`. Keyword arg renamed from `client=` to `gateway=`.

**Exports:** `CallRecord`, `ModelGateway`, `TelemetrySink` added to `__init__.py` and `__all__`.

**Tests:**
- `tests/test_phase14_gateway.py` — 26 new tests covering: delegation, role tagging, token/cost recording, latency, missing usage fields, pricing model comparison, unknown model fallback, sink accumulation, shared sink, D-022 isolation contract, and all four caller integration smoke tests.
- All existing tests updated: mock `anthropic.Anthropic` clients are now wrapped in `ModelGateway(client)` before being passed to constructors. The underlying mock is still inspectable via `client.messages.create.call_args` since `ModelGateway.call()` delegates through it. `runner._narrator._client` access in `test_phase5_gm.py` updated to `runner._narrator._gateway._client`.

**Resolves D-022** (telemetry isolation). D-017 (provider-agnostic adapter) remains open as a future goal.

---

## 2026-06-18 — Phase 13: narrow complete FABLE resolution slice (D-025)

**ResolutionPlan (`gm.py`):**
- `StakesDecision` renamed to `ResolutionPlan`; `StakesDecision = ResolutionPlan` alias preserves backward compatibility for all existing imports and test construction.
- New fields (all optional with defaults): `action_domain: str = "beat"`, `exposure: int | None`, `effect: str | None`, `trade_options: list[str]`, `trade_default: str = "Balanced"`, `consequence_palette: dict[str, list[dict]]`, `triumph_effects: list[dict]`, `edge_label: str | None`, `seam: bool = False`.
- `_ADJUDICATE_TOOL` schema extended with all new fields; nested `_EFFECT_ENTRY_SCHEMA` describes typed effect entries for palettes.
- `_ADJUDICATOR_SYSTEM` updated: "TN measures DIFFICULTY, not danger — Exposure measures danger severity. Trade changes Exposure and Effect, never TN."
- `AdjudicatorGM.evaluate()` parses all new fields; `max_tokens` increased to 512.
- `NarratorGM.narrate()` gains optional `effective_effect: str = "Standard"` and `applied_summary: str | None` — narrator weaves mechanical consequences into fiction without naming them as mechanics.

**Effect helpers (`effects.py`):**
- `effect_from_dict(d)` — converts raw adjudicator JSON palette dicts to `TypedEffect` objects. Raises `ValueError` for unknown kind, `KeyError` for missing required fields.
- `describe_effect(effect)` — produces a brief plain-English summary of any `TypedEffect` for narrator context assembly.

**Trade + consequence palette (`beat.py`):**
- `EFFECT_TIERS = ["Minimal", "Standard", "Superior", "Extreme"]` constant.
- `_apply_trade(base_exposure, base_effect, trade)` helper — applies Aggressive/Balanced/Guarded shift to exposure and effect tier; clamps both; never touches TN.
- `BeatRunner.run()` gains `trade: str | None = None` param. After the stakes gate, effective trade, exposure, and effect are computed before the dice roll.
- Consequence palette applied inside the beat transaction after the roll: selects the matching band (cost/setback/triumph), converts raw dicts via `effect_from_dict()`, applies via executor. Invalid entries and rejected effects log `audit_advisory` events and do NOT abort the resolved beat.
- `simulator.advance()` now passes `stakes.action_domain or "beat"` — domain-matched clock advancement (D-026).
- `applied_summary` built from accepted effect results via `describe_effect()`; passed to `NarratorGM.narrate()`.
- `BeatResult` gains `applied_trade`, `effective_exposure`, `effective_effect` fields.

**Exports (`__init__.py`):** `ResolutionPlan`, `effect_from_dict`, `describe_effect` added to public surface.

**Tests:** 58 acceptance tests in `tests/test_phase13_resolution.py`. 456 total pass.

**Open decisions shaped by this phase:** D-025 (consequence palette — implemented), D-026 (domain-matched clock advancement — completed here), D-034 (Openings model — still open, Phase 17 target).

---

## 2026-06-18 — Phase 12: typed effect executor

**Typed effect schema (`effects.py`):**
- 10 typed effect dataclasses: `CreateTruth`, `ChangeTruth`, `ExpireTruth`, `AdvanceClock`, `ApplyStress`, `ChangeAccess`, `MoveEntity`, `ChangeResource`, `CreateMaintainedTruth`, `ExpireMaintainedTruth`. `TypedEffect` union exported.
- `EffectExecutor`: validates and applies typed effects; logs `effect_applied` events with `derived_from` provenance; fires `front_advance` when a clock fills; rejects invalid/contradictory/unsupported effects before state mutation.
- `EFFECT_AUTHOR = "rules-engine"`, `EFFECT_EVENT_TYPE = "effect_applied"` constants.

**Expiry tombstone:**
- `"expired"` added to `EPISTEMIC_TYPES` in `events.py`. `committed_facts()` in `access.py` now pops the (subject, predicate) key when it encounters an "expired" commitment — so `ExpireTruth` and `ExpireMaintainedTruth` cleanly remove prior facts from both `committed_facts` and `canon_ledger`.

**WorldState extensions (`world_state.py` + `persistence.py`):**
- `WorldState.maintained_truths: dict` field added; `set_maintained_truth()`, `expire_maintained_truth()` methods added.
- `WorldState.update_entity()` added (replaces existing entity in-place for resource/stress mutation).
- `SQLiteWorldState` overrides all three new methods to call `_save()`; `_load()` and `_save()` updated to include `maintained_truths`.

**Scene extension (`perception.py`):**
- `Scene.illuminate(zone)` and `Scene.open_connection(a, b)` added to base class (were only on `SQLiteScene`). `SQLiteScene` overrides remain for persistence.

**BeatRunner integration (`beat.py`):**
- `BeatRunner.__init__` gains optional `executor: EffectExecutor | None` parameter.
- Step 6 converts `declared_facts` → `CreateTruth` effects and routes through executor when present; falls back to direct `pipeline.commit()` when absent. `BeatResult.effect_results` field added.

**Tests:** 53 acceptance tests in `tests/test_phase12_effects.py`. 398 total pass.

---

## 2026-06-18 — Phase 11: epistemic commitment contract (D-024)

**Commitment provenance:**
- `Commitment` gains `epistemic_type: str = "fact"` (validated against `{"fact","claim","observation"}`), `asserting_entity: str | None`, and `observing_entity: str | None`. `to_dict()` includes the new fields when set; `_commitment_from_dict()` round-trips them.
- `access.committed_facts()` now skips non-fact commitments: a claim with the same `(subject, predicate)` key no longer silently overwrites an objective fact when folding the log.

**Belief dataclass:**
- `Belief` gains `epistemic_type`, `asserting_entity`, and `observing_entity` (all default-safe for existing call sites).

**BeliefStore folding rules:**
- `BeliefStore` gains `claims: tuple[Belief, ...]` and `observations: tuple[Belief, ...]`. The `beliefs` dict is now facts-only (invariant: claims never silently enter facts).
- `BeliefStore.claims_about()` and `observations_about()` filter by `(subject, predicate)`.
- `ContextAssembler._fold_epistemic(events)` splits projected events into `(facts_dict, claims_list, obs_list)`. `beliefs_from()` delegates to it (returns facts only). `belief_store()` populates all three.

**Tests:** 33 acceptance tests in `tests/test_phase11_epistemic.py` covering all six f.md exit-gate criteria. 345 total pass.

---

## 2026-06-18 — Phase 10: atomic session + replayable scene state

**Scene persistence:**
- `SQLiteScene` added to `persistence.py`: drop-in subclass of `Scene`; persists `dark_zones` and `closed_connections` in a `scene_state` table in the shared SQLite DB; shares the `_tx_active` flag with `SQLiteEventLog` and `SQLiteWorldState` so all three are committed or rolled back together; `_load()` is called on rollback via `SQLiteEventLog._scene_ref`.
- `SQLiteScene.illuminate(zone)` and `SQLiteScene.open_connection(a, b)` added as explicit undo methods (persisted).
- `open_session()` return type extended to `(log, world, scene)` — a 3-tuple; all existing call sites updated.
- `EventLog.transaction()` no-op context manager added to the base class so `BeatRunner` can always call `with self._log.transaction():` without checking the backend.

**Atomic beat transaction:**
- `_BeatAborted` exception added to `beat.py`: used internally to trigger a transaction rollback from inside the `with self._log.transaction():` block.
- `BeatRunner.run()` restructured: steps 6 (fact commit), 8 (narrate), post-narration audit, 9 (narration log), and clock ticks are now wrapped in a single `with self._log.transaction():`. On post-narration audit block, `_BeatAborted` is raised, causing the transaction to roll back the step-6 fact commits and any other writes — no partial beat state persists.
- Pre-commit audit (step 7 hook 1) remains outside the transaction so audit events auto-commit even when the beat aborts.

**Tests:** 17 new tests in `tests/test_phase10_session.py` (scene persistence, atomic commit, rollback on audit block, whisper privacy after restart, canon ledger replay consistency). 312 total pass.

---

## 2026-06-18 — Pre-Phase R: adopt f.md roadmap; renumber phases 9–22

Replaced the original overloaded Phase 9–11 plan with the 14-phase stabilization roadmap from `uploads/f.md`. Changes:

- `IMPLEMENTATION_PLAN.md` fully rewritten: phases 1–9 collapsed to a summary table; Phase 10 (atomic session) is the current milestone with full spec; Phases 11–22 added with brief descriptions and exit gates; post-v1 tracks listed.
- `STATUS.md` phase table updated: Phase 9 (audience delivery, D-033) added as Built; old Phase 9 (plot-manager) → Phase 18; old Phase 10 (disposition) → Phase 19; old Phase 11 (interface + voice) → Phase 21 (text-only, voice explicitly deprecated); Phases 10–17, 20, 22 added as Designed or In progress.
- Voice/TTS scope formally removed from Phase 21. Legacy ElevenLabs / audio-routing substrate is deprecated and must not receive new feature work.
- Phase 10 and Phase 11 marked In progress (partial implementations exist: `SQLiteEventLog.transaction()`, `Commitment.epistemic_type`).

No runtime changes; no test impact. 294 tests continue to pass.

---

## 2026-06-18 — D-033: audience preservation delivery contract (Task 1, e.md)

**Root cause confirmed and fixed:** `run_with_agent()` discarded `Proposal.channel` and `Proposal.target`, extracting only `intent` as a plain string. `run()` had no channel parameter. Step 9 always emitted `channel="public"` to all world entities — whisper proposals produced public narration visible to every character. A P0 secrecy boundary failure.

**Fix:**
- `DeliveryScope` frozen dataclass holds the resolved `channel`, `audience` tuple, and optional `target`. Computed once at beat entry by `_resolve_delivery()` and threaded to the step-9 `log.append()` call — nothing downstream can widen or reconstruct it.
- `_resolve_delivery()` validates whisper targets against `world.entities` before any model call; raises `ValueError` on unknown target, self-whisper, or missing target.
- OOC early exit: emits one `ooc`-channel event, returns `BeatResult(channel="ooc")`. No adjudicator, narrator, commit, or clock call is made.
- `_narrator_context(store, channel)`: for public beats, filters actor's belief store to `channel=="public"` events only — actor-private whispers cannot flow into prose that all present participants see (invariant 5).
- `run_with_agent()` passes `proposal.channel` and `proposal.target` to `run()`.
- `run_round()` now accepts `dict[str, str | Proposal]` for player proposals; bare strings remain public-channel; Proposal objects preserve channel and target through queue transit.
- `BeatResult.channel` field added.

**Tests:** 28 new tests in `tests/test_audience_preservation.py`. 294 total pass.
**Decision:** D-033 (resolved).

---

## 2026-06-18 — Open D-027–D-032: integration-layer design decisions

Cross-cutting concerns from an external design review promoted into the decision log as open questions. All six are backend-relevant now or in the next 1–2 phases:

- **D-027** — Action lifecycle states: should proposals carry an explicit `ActionLifecycleState` enum (Draft → Submitted → Resolving → Committed → Narrated, with Cancelled/Stale exits)?
- **D-028** — Knowledge-sharing transfer mechanisms: how does information cross POV boundaries when separated characters regroup? Hybrid policy (explicit under pressure; GM-narrated merge on downtime) recommended; shared knowledge enters as `claim`, not `fact`.
- **D-029** — Roll visibility and secret-check policy: `dice_roll` events need a `visibility` field (`table` / `roller_only` / `gm_only` / `revealed`) consistent with the existing audience model (D-013); absence causes GM secret checks to default to full-table visibility.
- **D-030** — Fictional time model and time-advance triggers: extends D-026 with a `FictionalTimeScale` enum and a `scene_time` field on world state; scene transitions are structural (non-fiction) events so clocks, the plot manager, and the spotlight controller respond deterministically without being driven by API latency.
- **D-031** — Retcon, correction, and session-fork policy: defines `correction` and `retcon` event types; no history deletion; retcon requires human-player concurrence (D-008 backstop); GM-only revision is an override, not a retcon.
- **D-032** — Epistemic certainty in player-facing presentation: extends D-024's `epistemic_type` data model with a warm GM narration contract (phrasing guide per type) and a phase 11 label display in the Case File; the auditor treats narrating a claim as confirmed fact as an advisory semantic flag.

No implementation changes; no test impact.

---

## 2026-06-18 — Phase 9: plot-manager, D-016/D-023/D-026 implemented

**Phase 9 built — plot-manager + interest signals + clock triggers + atomic transactions:**

- `plot_graph.py` (new): `FunctionNode`, `FixtureBinding`, `Hook`, `Front`, `Faction`, `PlotGraph`, `InterestSignalAccumulator`. PlotGraph holds function nodes → hooks (current fixture binding + alternatives), fronts (off-screen threats with clocks), factions (standing forces), and hidden nodes. `InterestSignalAccumulator` tracks weighted per-subject signals with `promotion_candidates()` above threshold.
- `plot_manager.py` (new): `PlotManager` — sole authoritative writer of the plot graph (D-016). Detects blocked fixtures via canon ledger (`condition in {destroyed,captured,dead,unavailable,eliminated}` or `available=False`). `propose_rebinding` emits `plot_revision` events (`audience=(gm, plot_manager)` only — never in player belief stores); `accept_rebinding` updates the graph. `handle_clock_fired` logs `front_consequence` events for owning fronts. `post_beat` convenience wrapper: handle clock events + check/propose/accept all fixture issues. `gm_context_summary` returns GM-only hook+front overview included in the adjudicator's world summary.
- `gm.py` — **D-026 implemented**: `WorldSimulator.advance(trigger="beat")` now filters on `trigger_types` and `active` clock fields. Clocks without `trigger_types` default to `{"beat"}` (backward compatible with all existing tests).
- `persistence.py` — **D-023 implemented**: `SQLiteEventLog.transaction()` context manager; shared `_tx_active: list[bool]` flag between `SQLiteEventLog` and `SQLiteWorldState`; snapshot-and-restore on rollback (event log in-memory + WorldState `_load()` via back-reference). `open_session` wires the shared flag and back-reference. Auto-commit path unchanged when not in a transaction.
- `beat.py`: `BeatRunner` gains optional `interest_accumulator` and `plot_manager` params. `_world_summary` includes plot context when a plot_manager is provided. `simulator.advance("beat")` now passes the trigger tag (D-026). `plot_manager.post_beat(clocks_fired)` called after clock tick. Actor interest signal (`category="action"`, weight 0.5) emitted to accumulator on every beat.
- **D-016 resolved**: PlotManager is the sole authoritative writer; coherence enforced by the canon-ledger boundary.
- 59 tests added (`tests/test_phase9_plot.py`); 266 total.

**D-025 status:** Resolved in design (previous session); implementation (ResolutionPlan + EffectExecutor + adjudicator tool schema update) deferred post-Phase-9 — PlotManager acceptance tests do not require it.

---

## 2026-06-18 — D-023–D-026 resolved; D-024 implemented

**D-024 implemented — epistemic commitment types (`events.py`, `access.py`, `persistence.py`):** Added `epistemic_type: str = "fact"` to `Commitment` (validated against `EPISTEMIC_TYPES = {"fact","claim","observation"}`; backward-compatible default). `canon_ledger()` now filters to `revealed=True AND epistemic_type=="fact"` — NPC claims and character observations cannot silently enter objective world state. `CommitPipeline.check()` skips the canon consistency-check for non-fact commitments (a claim may contradict reality without raising `CanonConflictError`). `Fact` dataclass carries `epistemic_type` from its originating commitment. `_commitment_from_dict` in persistence.py round-trips the field. 207 tests pass.

**D-023 resolved (design):** Shared-connection SQLite `BEGIN`/`COMMIT` per beat; `SQLiteEventLog.transaction()` context manager with shared deferred-commit flag; implementation deferred to Phase 9 when plot-graph adds a third writer to the session DB.

**D-025 resolved (design):** `ResolutionPlan` pre-roll (adjudicator output: skill, TN, `action_domain`, exposure, typed consequence palette per band, `triumph_effects`) + `EffectExecutor` post-roll (validates and applies typed operations: `advance_clock`, `apply_stress`, `create_truth`, `create_access`, `create_seam`, `move_entity`, etc.). Phase 9 deliverable; narrator receives only approved player-safe result.

**D-026 resolved (design):** Clock schema gains `domain`, `trigger_types`, `advance_policy`, `landing_truth`, `front_owner`, `active`, `addressed_by`; `WorldSimulator.advance(trigger)` advances only clocks matching the trigger tag; tag comes from `ResolutionPlan.action_domain`. Existing clocks default to `trigger_types={"beat"}` for backward compatibility. Phase 9 deliverable alongside D-025.

---

## 2026-06-18 — c.md review: B.18 fix + D-023–D-026

**`gm.py` — B.18 fix (narrator must not receive hidden adjudicator reasoning):** Removed `stakes.reasoning` from the `NarratorGM` user message. The cold adjudicator produces its reasoning from the full GM world view, which may reference hidden facts. That string was being passed directly into the narrator's prompt, creating a narrow but real leak of GM-internal reasoning into the player-facing context. The narrator now receives the band name only (`Resolution: {band.value}` or `No roll needed.`) plus the player's filtered event history — which was always the correct information boundary. No tests broken; 207 still pass.

**Opened D-023–D-026** following review of `uploads/c.md`:
- **D-023** · Atomic event/state transactions — `SQLiteEventLog` and `SQLiteWorldState` write separately; divergence on partial failure is a real consistency hole. Resolve at Phase 9 start before adding plot-graph writes.
- **D-024** · Epistemic commitment types — `Commitment` currently lacks an `epistemic_type` field; NPC claims and engine-confirmed facts are indistinguishable. Phase 9 plot manager needs this distinction to separate sealed facts from revisable plans. Options: untyped (current), optional field (recommended), or a full schema split.
- **D-025** · Effect executor + consequence palette — Untyped `declared_facts` triples do not distinguish clock advancement from truth creation from stress application; consequences are selected post-roll rather than from a pre-declared palette. Typed operations + pre-roll palette deferred to Phase 9 rules engine expansion.
- **D-026** · Clock trigger and domain policy — All clocks advance every beat; FABLE says clocks should advance only in their domain. Add `trigger` and `domain` fields to the clock schema; `WorldSimulator.advance(trigger)` advances only matching clocks. Resolve at Phase 9 when front-firing logic is built.

---

## 2026-06-18 — Phase 8: Auditor

Added live integrity layer to the beat loop.

- **`auditor.py`** — `AuditTier` (CRITICAL / NON_CRITICAL / ADVISORY), `AuditFlag` (tier + category + description), `AuditResult` (passed + flags + `any_blocking` property), `Auditor` class.
- **Pre-commit hook** (`Auditor.check_commitments`): deterministic canon-contradiction detection — a revealed commitment that conflicts with the canon ledger → CRITICAL. Override passthrough via `is_override=True` bypasses all checks (D-008). Hidden commitments are not checked (not yet at the immutable boundary).
- **Post-narration hook, step 7** (`Auditor.check_narration`): structural check (empty prose → CRITICAL) + optional semantic model call (disabled when `semantic=False` or no client; configurable via `Auditor(client=..., semantic=True, max_retries=2)`). D-019 escalation rule: model-reported contradiction with confidence ≥ 0.9 + revealed canon fact + not set via override → CRITICAL; else ADVISORY. Model failure degrades to NON_CRITICAL with retry (up to `max_retries`) — play never blocked by an API error.
- **`BeatResult` extended**: `audit_flags: list[AuditFlag]` (full flag list for the beat), `beat_aborted: bool`.
- **`BeatRunner` integration** (`beat.py`): `auditor` optional parameter; `_emit_audit_events` helper logs each flag as `audit_block` / `audit_warning` / `audit_advisory` event with `audience=(gm_entity,)` only — audit findings never enter any player or TM belief projection. Pre-commit critical → abort before commit step 6, no narration. Post-narration critical → abort after commit step 6, narration text available in `BeatResult` but not logged.
- **35 new tests** (`tests/test_phase8_auditor.py`); 207 total.

Decisions exercised: D-018 (tiered failure), D-019 (semantic auditing advisory-default with high-confidence escalation), D-008 (override passthrough).

---

## 2026-06-18 — Phase 8–11 planning; D-018–D-022; skill_rating fix; token caps

**Planning:** Added Phases 8 (Auditor), 9 (Plot-manager), 10 (Disposition system), and 11 (Interface/voice goal statement) to `IMPLEMENTATION_PLAN.md`. Phase 11 detailed planning deferred until technology choices are made.

**Decision log:**
- **D-018 (Auditor failure policy) → Resolved:** Tiered failure handling — critical violations (mechanics, secrecy, canon, state integrity) abort the beat and block the narration write; non-critical model failures retry then degrade gracefully; advisory concerns are logged to GM audience only and do not interrupt play.
- **D-019 (Semantic consistency policy) → Resolved:** Semantic auditing enabled by default, treated as advisory. Escalates to blocking only when confidence is very high, the finding threatens revealed canon, and no logged transition or override explains the change. Structural contradictions remain unconditionally blocking.
- **D-020 (Phase 9 plot scope) → Resolved:** Phase 9 manages and advances a prepared campaign graph during play (human-authored or AI-assisted at setup). Autonomous generation of a complete campaign graph is outside Phase 9 scope.
- **D-021 (formerly D-018) — Scene-mode companion gating:** Open, deferred post-phase-8.
- **D-022 (formerly D-019) — Operational telemetry store:** Open, deferred to D-017 resolution.

*(D-021 and D-022 were renumbered from D-018/D-019 to make room for the resolved decisions above. The phase-7 changelog entry that references the original D-018/D-019 by number reflects their content at the time; those decisions are now D-021/D-022.)*

**`gm.py` — `skill_rating` determinism fix:** Removed `skill_rating` from the `adjudicate_action` tool schema. The model names the skill; `AdjudicatorGM.evaluate` looks up the rating from `CharacterSheet.skill()`. Models must not supply values the engine already owns (CORE §1.3 principle 1). `max_tokens` lowered: adjudicator 512→256, narrator 1024→400.

**`character_agent.py` — token cap:** `max_tokens` lowered 512→256 for companion proposals (structured tool call, bounded output).

---

## 2026-06-18 — Phase 7: orchestrator / spotlight + persistence

Wired multi-party turn flow and the transient proposal buffer into the existing beat loop.

- **`ActionQueue`** (`orchestrator.py`) — the blackboard's transient write surface (CORE §4.3, D-010). Agents enqueue `Proposal` objects; the orchestrator drains the buffer before adjudication. Non-authoritative: a proposal becomes a logged event only after resolution and commit, so unresolved proposals never enter any belief projection.
- **`Orchestrator`** (`orchestrator.py`) — routes turns on routing **metadata only** (presence, spotlight history, initiative order), never on event content, so it cannot become an omniscience conduit. Two modes: SPOTLIGHT (director-picks-next, least-recently-acted first, MVP default per D-005) and INITIATIVE (caller-supplied round-robin for combat). `grant_turn(present)` restricts to seats currently in scene.
- **`BeatRunner.run_with_agent`** (`beat.py`) — runs one beat where an AI `CharacterAgent` proposes its own action from its filtered belief store (CORE principle 2). Optional `ActionQueue` transit (beat-loop step 3). Dialogue folds into the action string forwarded to adjudicator and narrator.
- **`BeatRunner.run_round`** (`beat.py`) — runs one full round: each present seat gets exactly one beat in orchestrator-determined order. AI seats call `run_with_agent`; human seats take a `player_proposals[entity_id]` text string. Seat identity is not hardcoded (D-015 groundwork) — any entity ID can be human or AI. Orchestrator spotlight history updated after each seat.
- **Persistence** (`persistence.py`) — `SQLiteEventLog` and `SQLiteWorldState` (drop-in subclasses; SQLite-backed; same interface, same capability enforcement). `open_session(db_path)` factory returns a shared-connection `(log, world)` pair. All existing components work unchanged. `Scene` intentionally not persisted (volatile session state); belief stores and canon ledger rebuild on read (D-001, D-009). 15 tests (`tests/test_persistence.py`).
- **43 new tests** (`tests/test_phase7_orchestrator.py`), covering ActionQueue contract, Orchestrator SPOTLIGHT + INITIATIVE, `run_with_agent` (belief-store isolation, dialogue folding, queue transit), and `run_round` (full round, human seat, initiative ordering, D-015 seat-agnostic). **172 total** passing.
- **Deferred:** TTS turn-gating (phase 11), auditor live gates (phase 8).

---

## 2026-06-18 — Phase 6: character agents

Built the AI teammate layer (`persona.py`, `character_agent.py`).

- **`PersonaSpec`** — per-agent identity: voice, values, public goals, hidden agenda, relationships. `hidden_agenda` is designed to travel only in the system prompt, never in shared context or user messages.
- **`Proposal`** — seat-agnostic action/dialogue container (D-015 groundwork). Any seat — AI or human — produces a `Proposal`; `CharacterAgent` is the AI implementation. Channel validation enforced at construction (whisper requires target).
- **`CharacterAgent`** — AI-driven seat. `propose(assembler)` reads `assembler.belief_store(self.entity_id)` — the agent sees only events it was in the audience of, structurally (CORE principle 2). Forced `propose_action` tool call via Anthropic SDK.
- **Differential knowledge tests** verify that two agents with different audience memberships receive different event contexts, that a private commitment is in vale's beliefs but not rook's, and that the hidden agenda appears only in the system prompt.
- **21 new tests** (`tests/test_phase6_agents.py`); 129 total.

---

## 2026-06-18 — Phase 5: cold/warm GM split

Built the minimal playable GM loop (`character_sheet.py`, `gm.py`, `beat.py`).

- **`CharacterSheet`** — mechanical truth for a character: skills (0–4), concept, edge, stress, and the remaining FABLE anatomy fields as stubs. Validated at construction; `skill(name)` returns 0 for unlisted skills.
- **`AdjudicatorGM`** (cold) — Anthropic tool-use call forcing `adjudicate_action`. Returns a structured `StakesDecision` (stakes bool, skill, TN, declared facts). No prose output; the player never sees adjudicator output directly (D-007).
- **`NarratorGM`** (warm) — Receives only the player's filtered belief store and the result band (not dice values). Produces prose for the public channel. Structural information barrier: it is never passed hidden world state (CORE principle 2, D-007).
- **`WorldSimulator`** — Deterministic clock/front tick. Advances each clock by its step value; fires and logs `front_advance` events when a clock fills. Full consequence logic deferred to the plot-manager (phase 9).
- **`BeatRunner`** — Sequences beat-loop steps 2–9 (CORE §5) for one actor. Steps deferred: 1 (route/spotlight → phase 7), 3 (action queue → phase 7), 7 (audit → phase 8). Returns `BeatResult` with resolution, narration, committed-fact count, and clocks fired.
- **`anthropic>=0.111.0`** added as a project dependency. Model default: `claude-sonnet-4-6`. Provider-agnostic adapter deferred (D-017).
- **23 new tests** (`tests/test_phase5_gm.py`), including an information-boundary test that verifies the narrator client is never called with dice totals or margin values. 108 total.

---

## 2026-06-18 — SQLite persistence (phase 1 step 6); resolved D-007, D-009; opened D-017

**SQLite persistence** — added `persistence.py`: `SQLiteEventLog` (drop-in subclass of `EventLog`, SQLite-backed, in-memory read cache) and `SQLiteWorldState` (drop-in subclass of `WorldState`, write-through JSON blob). `open_session(db_path)` factory returns a shared-connection `(log, world)` pair. All existing components (`CommitPipeline`, `DiceService`, `RulesEngine`, `ContextAssembler`) work unchanged with the SQLite backends. 15 new tests (`tests/test_persistence.py`); 85 total. `Scene` is intentionally not persisted — volatile sensory state, rebuilt per session. Belief stores and canon ledger are read-time projections, no separate persistence needed (D-009 pattern). Closes the last pending item for phases 1–4.

**D-007 → Resolved:** hard cold/warm architectural split. Cold GM (adjudicator) emits structured commitments via tool use only — no prose. Warm GM (narrator) receives only the player's filtered belief store and produces prose only — no commits. Tool calls go to the commit pipeline; text goes to the channel router. No extraction pass required for compliant providers. Residual risk: warm GM prose may introduce incidental detail; the auditor (phase 8) is the check. Provider: Claude tool-use API for now (see D-017).

**D-009 → Resolved:** canon ledger is a pure fold over the event log — no separate authoritative store. Lazy per-POV cache is the approved performance escape hatch; it is never an authoritative writer. Consistent with D-001 and D-010.

**D-017 → Opened:** LLM provider strategy. Claude/Anthropic-first for now; a provider-agnostic adapter layer (abstracting tool-use formats, context limits, streaming, per-role model defaults) is a named future goal. Cheapest moment to introduce the adapter is phase 5 (first model-calling agent).

---

## 2026-06-18 — Resolved D-008 (override authority); opened D-016 (plot ownership)

Settled the GM-authority philosophy before Phase 5 and recorded the plot-ownership fork it implies. No code change — both concern model behavior and the plot layer (phases 5/9); the override mechanism itself was already built in phase 2.

- **D-008 → Resolved:** the AI GM holds authoring + override authority over world-state and consequence; the human player is co-authority and backstop. The substance is *latent authority* — in normal play the GM acts through **Add** and **Change-via-causation** (and plot-bending), meeting choices with friction, consequence, and adjacent hooks rather than veto; overt override is the reserved exception for coherence-breaks and table-safety. Default "yes-and / yes-but," with every "yes-but" leaving a mechanical mark (clock/front/Truth/Edge) so consequence is real. Recorded two properties as future §13 criteria (overt-redirections → ~0; yes-but commits a consequence).
- **D-016 → Opened:** plot-graph ownership. Plot is a loose structure of fronts/factions/tensions (already the §7.4 design), with revision as a first-class, salience-gated operation. Recommends the disposition pattern (D-004) applied to plot — plot-manager as sole authoritative writer, other agents propose, coherence enforced by the canon boundary + auditor — mirroring the latent-authority split at the structural level. Build deferred to phase 9.
- Updated CORE §6.2 (latent-authority stance), §7.4 (loose-structure plot + D-016 pointer), §11 index (removed Override authority, added Plot-graph ownership); `COMPONENTS.md` override protocol + plot-manager entries; STATUS auditor row.

---

## 2026-06-18 — Opened D-014 (scene imagery) and D-015 (configurable seats)

Captured two forward-looking feature ideas as open decisions rather than building them (brainstorming is not canon). Both are anticipated by CORE §12, so neither contradicts the spec.

- **D-014 — generative scene imagery:** optional impressionistic per-scene AI image at the interface phase (11). Recorded the two load-bearing constraints if adopted — prompt from the player's belief store (not GM hidden state) so it can't leak secrets (principle 2), and seed from committed facts / keep it impressionistic so it can't silently contradict canon (principle 4).
- **D-015 — configurable seats:** generalize the fixed one-human-player shape to human/AI in any role, plus multi-participant (the §12 multi-human extension). Recommends a role-agnostic participant/seat abstraction at phases 6–7 (so the human/AI and GM/player distinctions are never hardcoded), with multi-client networking / auth / concurrency deferred to the interface phase.
- CORE §11 open-decision index updated to reference both.

---

## 2026-06-18 — Phase 4: context assembly + D-013 fix (in-memory)

Per-POV view construction (CORE §6.3/§6.4): every agent acts from a belief store derived on read from the single event log (D-001). 9 new tests (`tests/test_phase4_context.py`); 70 total, all passing.

- **`ContextAssembler` / `BeliefStore`** (`context.py`): `belief_store(pov)` returns the POV's projected events, the facts it `beliefs` (folded *only* from commitments it saw at content level — never the global canon, so a fact revealed in a scene the POV wasn't in cannot leak into its beliefs, CORE §7.1), and the entities it can currently sense (`perceptible`, via the perception model when a `Scene` is supplied). Frozen, derived, never authoritative.
- **Resolved D-013** — `EventLog.project_for` now emits a per-POV *contiguous* index as `ProjectedEvent.sequence` instead of the log's global sequence, closing the side-channel by which a non-audience POV could infer hidden-event counts from the gaps. The log's global sequence and event `id` are unchanged. The phase-3 `xfail` is now a normal passing regression test.
- **Demonstrated differential information:** two POVs assembled from one log hold divergent events and beliefs (the substrate for the differential-believability success criterion); an overhearer's assembled context carries the vague perception, never the secret fact.
- **Scope:** persona (phase 6), disposition (phase 10), and retrieved memory are deliberately omitted — they slot onto `BeliefStore` later without changing the projection seam. Audience derivation (intended + perceived) stays at commit time (`derive_overhears`); the beat loop (phase 7) will be the chokepoint that runs derive-then-commit. **Pending:** SQLite persistence.

---

## 2026-06-18 — Phase 3: perception stress-test pass

Adversarial pass over the load-bearing wall before building on it (CORE §13). 14 new tests (`tests/test_phase3_perception_stress.py`); 60 passing + 1 xfail.

- **Over-disclosure probes all hold** — closeness can't tunnel a whisper across a zone, loud doesn't carry two hops or past a closed leg, sight doesn't pass a closed door, closing a non-existent connection is inert, and an overhear leaks no identity / no content / no source link.
- **Fail-safe limitations pinned** (D-012): overhears always degrade to a vague hint, so a same-room non-addressee at normal volume gets "voices nearby", never the words — under-disclosure (safe for secrecy); "fully overheard content" is deferred to audience-derivation in phase 4. `derive_overhears` is not idempotent — dedup belongs at the future beat-loop chokepoint. Both pinned so a later change can't silently regress them.
- **Hardening:** `perception_map` now raises on an unknown `origin` zone instead of returning an empty set — a wrong origin was a caller bug that could mask a real overhear (under-disclosure masquerading as secrecy).
- **Finding → opened D-013:** `ProjectedEvent` exposes the global `sequence`, so a non-audience POV can infer hidden-event counts from the gaps — a metadata side-channel against POV partitioning (principle 2). Not a perception bug; the fix is per-POV ordering in the projection, slated for phase 4. Encoded as a `strict` xfail so it flips to a failure the moment it's fixed.

---

## 2026-06-18 — Phase 3: perception model (in-memory)

The load-bearing wall (CORE §6/§7.1): a deterministic answer to "who could have sensed this?", over the fiction-positional zone graph (D-002) — zones + relational Truths, no coordinates. Secrecy is enforced here by who-could-sense, never by asking a model to forget (CORE principle 4). 12 new tests (`tests/test_phase3_perception.py`, incl. the plan's whisper/noise/line-of-sight scenarios); 47 total, all passing.

- **Zone graph + presence on `WorldState`** (`world_state.py`): durable topology (`zones`, undirected `connections`), coarse position (`place`/`zone_of`/`entities_in` over `Entity.position = {"zone": …}`), and fine intra-zone proximity as relational closeness Truths (`set_close`/`are_close`/`close_to`). This is the registry's "scene/zone graph" home; nothing metric (D-002).
- **`Scene` — the volatile sensory state** (`perception.py`, the registered Scene/perception state): lighting (`darken`/`lit`) and connection openness (`close`/`transmits`). Defaults permissive (lit, open). Deliberately separate from `WorldState` so durable structure and changing conditions don't get tangled (D-001 anti-duplication).
- **The model** (`perceivers`/`perception_map`): a pure read returning who could sense a `Stimulus`. Auditory by volume — whisper stays in-zone and reaches only entities *close* to the actor (why a whisper is private in a crowd); normal fills the zone; loud carries one open hop. Visual requires the origin lit + line of sight (same zone, or into a lit origin across an open connection).
- **Overhears** (`derive_overhears`): the gap between who-could-perceive and the event's intended audience becomes `may_have_perceived` events — a vague, content-level hint authored by a neutral `perception` source (so the overhearer learns it sensed *something*, not who or what), linked to the source via `derived_from`. The secret content never leaves the original event's narrow audience.
- **Decisions:** opened **D-012** (perception propagation fidelity) — the thin zone-based model is the MVP default; richer attenuation/occlusion deferred until stress-testing demands it. Relates to D-002. **Pending:** stress-testing the wall; SQLite persistence (plan step 6).

---

## 2026-06-18 — Phase 2: access model + commit boundary (in-memory)

Implemented the declaration → consistency-check → bind lifecycle (CORE §6.1) over the Phase 1 log. No new components — this realizes the already-registered fact-extraction/commit pipeline, canon ledger, and override protocol from `COMPONENTS.md`. 11 new tests (`tests/test_phase2_access.py`); 35 total, all passing.

- **Commit pipeline** (`access.py`): `CommitPipeline.commit` is the sanctioned path for any event carrying commitments — it runs the canon consistency-check before appending, so an improvised declaration cannot silently contradict what players were already told (CORE §6.2 forbidden move). On conflict it raises `CanonConflictError` and appends nothing.
- **Canon ledger and committed-facts as pure folds over the log** (D-009 option (b)): `committed_facts()` and `canon_ledger()` derive state by folding the event log — no separate materialized store. Consistent with D-001's single-source-of-truth stance; latest commitment per `(subject, predicate)` wins.
- **"Contradictory" defined operationally** (CORE §6.1 step 3): a candidate conflicts when canon already holds the same `(subject, predicate)` with a *different* value. Structural, not semantic. The check targets *revealed* canon only — hidden committed facts stay revisable (the fluid future, §7.4), so a new commitment may freely supersede a hidden one.
- **Override escape hatch** (D-008 MVP default): `commit(override=True, reason=...)` bypasses the check and logs an `override`-type event carrying the reason, which the auditor will read as intentional fiat rather than a bug (CORE §3, §6.2). An override without a reason is refused.
- **Whisper secrecy holds at the commitment level:** a commitment on a whisper rides the Phase 1 audience/visibility projection — the non-audience never sees the content *or* its commitments; a metadata-only recipient learns the event happened but not what was said.
- Public API extended in `__init__.py` (`CommitPipeline`, `Fact`, `Conflict`, `CanonConflictError`, `committed_facts`, `canon_ledger`, `OVERRIDE_TYPE`).
- **Decisions in play:** D-007, D-008, D-009 — all still **Open**; the code follows their MVP defaults (structured commitment blocks, not prose extraction; logged override-with-reason; canon ledger as a view). **Pending:** SQLite persistence (plan step 6) — the log is still in-memory.

---

## 2026-06-17 — Phase 1: deterministic core + event log (in-memory)

First code. Built the smallest working deterministic substrate; all six phase-1 acceptance contracts pass (24 tests total). No models, agents, UI, or persistence yet — by design (IMPLEMENTATION_PLAN phase 1 non-goals).

- **Event model** (`events.py`): frozen `Event` and `Commitment` dataclasses tracking `schemas/event.schema.json`; `to_dict()` keys match the schema's required set exactly. Validates channel, visibility (level or per-member map), and audience uniqueness. `ProjectedEvent` is the per-entity view (CORE §6.3 belief-store seed).
- **Append-only log** (`event_log.py`): `EventLog.append` is the single chokepoint — it assigns the monotonic `sequence`, a uuid `id`, and a UTC `timestamp` (never caller-supplied), and stores a frozen event. Reads return tuples so history can't be mutated. `project_for(entity)` filters by audience and renders content-vs-metadata (the CORE §6.4 access matrix; non-audience entities are excluded entirely).
- **Determinism boundary made structural** (CORE §1.3 principle 1): mechanical-outcome types (`dice_roll`, `resolution`) are refused by `append` unless they carry a module-private capability held only by the dice service and rules engine. A faked roll authored directly raises `DeterminismBoundaryError`.
- **Dice service** (`dice.py`): logged, auditable randomness (CORE §7.2); injectable RNG for deterministic tests; every roll is a `dice_roll` event.
- **Minimal rules engine** (`rules.py`): the cold adjudicator slice — `resolve_check` rolls 3d6+Skill vs TN via the dice service, reads the FABLE band (`uploads/FABLE_Engine_Schema_v6.md` §5), and logs a `resolution` event linked to its dice event via `derived_from`. Deliberately excludes Exposure/Effect/Trade/Ledger/Clocks/Edge (later phases).
- **World-state skeleton** (`world_state.py`): minimal entity container; `position` is fiction-positional (D-002).
- Package version 0.0.0 → 0.1.0; public API exported from `__init__.py`. Implemented the 6 skipped acceptance placeholders and added `tests/test_phase1_behavior.py`.
- **Decisions in play:** D-001 (projection is read-time over the single log), D-002 (fiction-positional `position`), and the determinism boundary. **Pending:** SQLite persistence (plan step 6) — the log is in-memory only.

---

## 2026-06-17 — Resolve D-002: fiction-positional spatial model

Resolved the spatial-model fork toward FABLE's native abstraction: a third option (c) beyond the original range-bands/grid framing.

- **Decision:** position is **fiction-positional** — a fictional fact persisted as **Truths** within the scene/zone graph. No coordinate grid (rejects (b)) and no formal range-band system (looser than (a)). Proximity surfaces only through the Ledger **Position** category and the **Ground** cost register; coarse tags (adjacent/near/far) are adjudication aids, not measured quantities. A fiction-stated distance ("a hundred feet off") is a relational Truth enforced by Truth-consistency + logged traversal, not arithmetic.
- **Determinism boundary:** logged explicitly in D-002 — position stays code-owned, but "code owns positions" means it owns the position *Truths and their consistency*, not a coordinate system. CORE §13 spatial-consistency criterion is preserved (enforced via Truth/canon non-contradiction + the perception/traversal model).
- Propagated: CORE §8 (world-state spatial model rewritten; removed the dangling "see Open Decisions" pointer), §7.1 (replaced grid-language "adjacent square" with fictional proximity), §13 (criterion now reads "committed distance/position"), §11 (removed from the open-decision index); `COMPONENTS.md` world-state store; `schemas/world_state.schema.json` (`entity.position` typed as zone + descriptor + qualitative proximity + position-Truth refs); `STATUS.md` phase 3. Marked **D-002 Resolved** and updated its MVP default.
- Relates to D-003 (positioning queries become reads/authoring of position Truths). Precedence re-checked: nothing contradicts CORE; the "100 feet" examples remain valid as authored Truths.

---

## 2026-06-17 — Resolve D-004: disposition couples through Edge/Bonds

Resolved the disposition→mechanics coupling fork in favor of FABLE's native economy, eliminating the standalone "Strings" mechanic.

- **Decision:** disposition couples through **Bonds** (Held Truths the actor may *Lean* on via **Edge**, or that pay a *Ledger* step where they change baseline) and through **compels** (respecting Held-Truth authorship — world compels, owner rewrites). The disposition graph is the event-derived *state*; Bonds are the mechanical *handles*; Edge is the spend currency. No passive modifier, no separate currency.
- **Why:** FABLE already provides a spendable relational-leverage economy, and invariant 18 / the §22 Mode rule reject new resolution subsystems — a parallel "Strings" mechanic is subsystem growth. Routing through Edge/Bonds keeps it legible, EV-safe, and inside the core surfaces.
- Propagated the retirement of "Strings": CORE §3 (vocabulary entry reframed to *Disposition coupling (Edge/Bonds)*), §7.5 (mechanical-coupling caution rewritten), §10 (phase-10 line), §11 (removed from the open-decision index); `COMPONENTS.md` rules-engine and disposition-graph entries; `STATUS.md` phase 10. Marked **D-004 Resolved** and updated its MVP default.
- Relates to D-011 (which recognizes the deltas this coupling expresses). Building it is deferred to phase 10. Precedence re-checked: nothing contradicts CORE.

---

## 2026-06-17 — Integrate the FABLE ruleset (`uploads/FABLE_Engine_Schema_v6.md`)

The ruleset doc was added to the repo; integrated it as canon for the rules-engine component *without implementing any of it* (phase 1 remains a minimal rules-engine interface, not FABLE's math).

- Registered `uploads/FABLE_Engine_Schema_v6.md` in the `00_README.md` file map and referenced it from CORE §3 (rules engine), §8 (character sheet), the appendix, and the `COMPONENTS.md` rules-engine and character-sheet entries. It is authoritative for *rules mechanics*; CORE stays authoritative for *architecture*. *Why:* it was an orphan — referenced by nothing — exactly the map-drift the change protocol exists to catch.
- Reconciled dead terminology: "**stance(s)**" (from an older FABLE draft) is not a v4 surface; replaced its references in CORE §3/§8/appendix and `COMPONENTS.md` (×2), and rebuilt `schemas/character_sheet.schema.json` to the actual anatomy (Concept · Skills 0–4 · Traits · Bonds · Drive · Question · Gear · Stress · Scars · Edge). The closest live analog to the old "stance" is the **Trade** (§9).
- Anchored the **stakes gate** (CORE §3/§7.2/beat-loop step 4) to its mechanical definition: FABLE's **Exit Check** + the *no-empty-rolls* rule (`uploads/FABLE_Engine_Schema_v6.md` §11, §5).
- Added ruleset-informed notes to **D-002** (FABLE is fiction-positional — no grid; favors the abstract default) and **D-004** (FABLE's Edge+Bonds is already a spendable-leverage economy; invariant 18 likely rules out a *separate* "Strings" subsystem). Both kept **Open** — flagged for a deliberate resolution, not silently decided.
- Precedence re-checked: nothing contradicts CORE; the ruleset and CORE govern orthogonal domains (mechanics vs. architecture).

---

## 2026-06-17 — Close three dangling design references (queue, disposition engine, override)

Design-review follow-up: registered three things CORE/COMPONENTS already *assumed* but never defined, so their references resolve. Gap-closing, not new machinery.

- **Action queue / proposal buffer** — added to `COMPONENTS.md` as a deterministic mediation service and to CORE §4.3, §5, §8. Resolved the fork (new **D-010**) in favor of a *transient, non-authoritative* buffer rather than proposals-on-the-log: keeps the append-only event log purely authoritative and stops un-audienced proposals leaking into belief projections. Referenced by the character-agent "writes to the queue" line and beat-loop step 3, previously unregistered.
- **Disposition engine** — added to `COMPONENTS.md` as the deterministic, authoritative writer of the disposition graph (every delta linked to its causal event, per CORE §7.5); named in CORE §4.1 and beat-loop step 9. Reconciled the disposition-graph store ("written by") and the NPC-manager (now *proposes* deltas, applied through the engine). Closes the "store with no writer-of-record" gap.
- **Override** — registered in `COMPONENTS.md` under a new "Cross-cutting protocols" section as a logged `override` event type + auditor behavior (not a standalone component), resolving the dangling "override mechanism" reference in the auditor's `depended-on-by`. No schema change (event `type` is already free-form). Authority remains open under **D-008**.
- Opened **D-011** (disposition-delta recognition: deterministic rule table vs. model-proposed) and indexed it in CORE §11. Resolved **D-010** (proposal queue topology).
- Precedence re-checked: no satellite now contradicts CORE.

---

## 2026-06-17 — Repository and environment bootstrap

- Initialized a dedicated git repository at the project root (`git init -b main`). *Why:* the scaffold was previously untracked inside a parent directory repo, which made the project `.gitignore` inert, the CHANGELOG/commit-based change protocol moot, and any branch/PR workflow impossible. The project is now its own versioned repo.
- Created the local `./.venv` (Python 3.13) and installed the package editable with dev extras (`pip install -e ".[dev]"`); confirmed `pytest` runs (6 phase-1 contracts skipped as designed).
- Documented the setup step in `README.md` (new **Setup** section) and as step 0 of the IMPLEMENTATION_PLAN "first coding pass". *Why:* `CLAUDE.md` mandates `./.venv/bin/python` but no doc told a fresh checkout to create the venv.
- Design unchanged; this is a build/setup-only pass (no component or architecture changes).

---

## 2026-06-17 — Design-review reconciliation pass

- Refreshed `00_README.md` file map, which had gone stale: added `CLAUDE.md`, `README.md`, and `IMPLEMENTATION_PLAN.md` rows and a "Code and config" note covering `schemas/`, `docs/`, `src/`, `tests/`, and root config. *Why:* the scaffold added files without updating the map — exactly the drift the change protocol exists to prevent.
- Restored the collaboration stance to `CLAUDE.md` (pushback, lead-with-verdict, anti-sycophancy, five-principle test, anti-complexity), which the Claude Code rewrite had dropped; added the precedence-check step (7) to its change protocol.
- Removed the `"hidden"` value from `event.schema.json` visibility. *Why:* it duplicates capabilities already covered by audience membership plus the `content`/`metadata` levels in CORE §3; log-only events use an empty audience instead. Keeps schema and CORE aligned.
- Added a pointer from CORE §8 to the realized `schemas/`, noting they are skeletons that track the sketch, not an independent source of truth.
- Reviewed the rest of the Claude Code scaffold (IMPLEMENTATION_PLAN, README, MVP defaults in DECISIONS, schemas, pyproject, .claude/.gitignore/.env/.mcp) and accepted it unchanged — it is well-aligned with CORE.

---

## 2026-06-17 — Claude Code project scaffold added

- Rewrote `CLAUDE.md` as the primary Claude Code operating contract: required reading, source-of-truth hierarchy, change protocol, implementation priorities, architecture invariants, Python environment, and safety rules.
- Added standard root `README.md` for human/tool entry.
- Added `IMPLEMENTATION_PLAN.md` to convert the CORE roadmap into concrete coding milestones.
- Added `.claude/settings.json` with conservative project permissions and secret/dependency-folder read denies.
- Added `.gitignore`, `.env.example`, MCP setup notes, starter JSON schemas, and pytest placeholder contracts.
- Added MVP implementation defaults to `DECISIONS.md` so early coding can proceed without accidentally resolving design decisions.

---

## 2026-06-17 — Project directory established

- Authored CORE design blueprint (`FABLE_Table_Engine_Blueprint.md`): goal and philosophy, the five load-bearing principles, the access/information model, the beat loop, four-layer architecture, six in-depth subsystems, data-model sketch, worked scenarios, build roadmap, and success criteria.
- Split the design into a CORE-plus-satellites layout (rationale: separate by change-rate and coupling, not by topic). Added `COMPONENTS.md`, `DECISIONS.md`, `STATUS.md`, `CHANGELOG.md`, and `00_README.md`.
- Established the precedence rule (CORE wins over satellites) and the change protocol for keeping the set consistent.
- Created `COMPONENTS.md` with the full registry and `depended-on-by` dependency map as the single source for impact analysis.
- Migrated open design decisions out of CORE §11 into `DECISIONS.md` as a living log (D-001 through D-009), leaving CORE §11 as an index. *Why:* keep evolving decision status out of the normative spec to avoid drift.
- Seeded `STATUS.md` with all roadmap phases as `Designed`, noting existing substrate (FABLE_AI_Engine; the director-pattern playtest harness with TTS) as a starting point not yet built to spec.
