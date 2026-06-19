# Component Registry & Dependency Map

Authoritative list of every model-driven agent, deterministic service, and data store in the FABLE Table Engine. CORE (`FABLE_Table_Engine_Blueprint.md`) defines *why* these exist and how they compose; this file is the operational registry of *what each one is and what depends on it*. When a component changes, this file is updated first, then CORE is reconciled (see `00_README.md` → Change protocol).

Each entry: **Purpose · Kind · Reads · Writes · Depends on · Depended-on-by.** The `Depended-on-by` field is the impact checklist — to remove a component, reconcile every item listed there.

Component status (designed / in progress / built) is tracked separately in `STATUS.md`, not here.

---

## Model-driven agents

These run on LLM inference. They live *above* the determinism boundary: they produce voice, intent, and judgment, never authoritative mechanical outcomes.

### GM agent
- **Purpose:** Constructs and runs the world; the player-facing voice of the table. Decomposed into three roles, which may be separate model calls or staged passes of one model.
  - *Adjudicator (cold):* runs the stakes gate; decides what is at risk; **reads** mechanical outcomes from the rules engine rather than inventing them.
  - *Narrator (warm):* renders the resolved, cold result into prose. Never sees the dice.
  - *World-simulator / front-runner:* advances clocks and offscreen threats.
- **Kind:** Agent (model). Largest private knowledge base (includes world hidden state).
- **Reads:** Its filtered context view; rules-engine results; world state (entitled facts); plot graph (via plot-manager); canon ledger.
- **Writes:** Declarations (→ fact-extraction → world state / canon ledger); narration events to the log; clock/front advances.
- **Depends on:** Rules engine, dice service, world state, fact-extraction pipeline, context assembly, plot-manager, perception model.
- **Depended-on-by:** Beat loop (steps 1, 4, 6, 8); auditor (checks its narration); access matrix (serves distance queries); interface (narration channel).

### Character agents (teammates / TMs)
- **Purpose:** Play the player's AI teammates — one persistent agent per teammate, each with its own persona, goals, and private knowledge, so it can act on information others lack.
- **Kind:** Agent (model), persistent. One instance per teammate.
- **Reads:** Its own filtered context view (belief-store projection + persona + entitled state/relationships + retrieved memory).
- **Writes:** Action/dialogue proposals to the queue; consequent events to the log (audience-tagged).
- **Depends on:** Context assembly, perception model, disposition graph, world state, orchestrator (for turn/spotlight).
- **Depended-on-by:** Orchestrator (routes them); access matrix (whisper target, witnesses); interface (per-character channels/TTS).

### NPC-manager agent *(optional; see DECISIONS D-006)*
- **Purpose:** Runs NPCs that don't warrant their own persistent agent, aligned with the GM so NPCs still drive story. Fidelity tiering: recurring NPCs may instead be promoted to full character agents.
- **Kind:** Agent (model), GM-aligned. May be merged into the GM rather than separate.
- **Reads:** GM-shared context for NPCs in scene; world state (entitled); perception results (e.g. overheard events).
- **Writes:** NPC action/dialogue events; *proposes* NPC disposition deltas (applied via the disposition engine, never written to the graph directly).
- **Depends on:** Context assembly, perception model, disposition graph, world state.
- **Depended-on-by:** Access matrix (overhear path; trivial-action perception); interface (NPC channels).

### Plot-manager agent
- **Purpose:** Owns the *future*. Holds the plot graph as a loose structure of fronts, factions, clocks, and unresolved tensions (standing forces with momentum, not a fixed sequence); detects divergence; re-binds plot **functions** to new **fixtures**; promotes high-interest threads; accumulates player-interest signals. Edits only the hidden graph, never the canon ledger.
- **Ownership (D-016, leaning distributed-proposal/single-writer):** the plot-manager is the **sole authoritative writer** of the plot graph; other agents (GM, character agents, disposition engine) may *propose* revisions but never edit it directly, mirroring the disposition engine (D-004). Coherence is enforced by the canon-ledger boundary (phase-2 consistency-check) plus the auditor. Revision is first-class (promote a thread, escalate a faction, retire a stale front), but salience-gated — evaluate input for promotion, don't promote everything.
- **Kind:** Agent (model), GM-side, never in any player/TM audience.
- **Reads:** Plot graph; event log (for divergence detection and interest signals); canon ledger (as the immutable boundary it may not cross); world state.
- **Writes:** Plot graph (hidden nodes, fixture bindings, new fronts/clocks); interest-signal accumulator.
- **Depends on:** Plot graph store, event log, canon ledger, world state.
- **Depended-on-by:** GM agent (consumes revised plot/pacing); beat loop (divergence handling); roadmap phase 9.

### Auditor / Referee
- **Purpose:** Live integrity. Checks proposed narration and outcomes against world state and the rules engine; flags contradictions and illegal results; distinguishes a logged override from a bug.
- **Kind:** Mostly deterministic checks; a small model may surface findings in natural language.
- **Reads:** World state, rules engine, canon ledger, the proposed event before commit.
- **Writes:** Flags/blocks; audit events to the log.
- **Depends on:** World state, rules engine, canon ledger, fact-extraction (so committed facts exist to check against).
- **Depended-on-by:** Beat loop (step 7); override mechanism (reads its intentional/​bug distinction).

---

## Human-seat adapter / Text playtest console

### Human-seat adapter (`parse_proposal`)
- **Purpose:** Converts raw player text into a channel-tagged `Proposal` (Phase 15). Syntax: `whisper <target>: <intent>` → whisper channel; `/ooc <intent>` → OOC channel; everything else → public. The human proposal path is otherwise identical to the AI-agent path — the beat runner, delivery scope, and audience computation are unchanged.
- **Kind:** Deterministic function (pure text parsing; no I/O, no model call).
- **Reads:** Player text input.
- **Writes:** Returns a `Proposal` with `agent`, `intent`, `channel`, `target` set.
- **Depends on:** `Proposal` (from `character_agent`).
- **Depended-on-by:** `PlaytestSession.step`; any future human-facing interface.

### Text playtest console (`PlaytestSession`, `render_event`)
- **Purpose:** Wraps `BeatRunner` with a clean per-player interface: `step(text)` parses input, runs the player's beat, and returns only the player's entitled text lines. `export_transcript` / `export_transcript_json` serialize the player's entitled event stream for review or replay. The client never computes audiences, rules, effects, or hidden state — all computation stays in the engine.
- **Kind:** Presentation and plumbing (deterministic; no model calls).
- **Reads:** `assembler.belief_store(player_id)` — never the raw log, world state, or GM context.
- **Writes:** No authoritative state; only renders.
- **Depends on:** `BeatRunner`, `ContextAssembler`, `Proposal`.
- **Depended-on-by:** Future human-facing interface layers (Phase 21).

---

## Provider gateway / Telemetry sink

### Provider gateway (`ModelGateway`, `ModelCallError`)
- **Purpose:** Single controlled seam for all model calls (Phase 14; D-017, D-022). Every GM, narrator, character-agent, and auditor call routes through `ModelGateway.call(role, **kwargs)`. Records per-call operational telemetry (latency, token counts, cost) to a `TelemetrySink`. Phase 20 adds configurable timeout, at-most-1-retry with exponential backoff on transient errors, and typed `ModelCallError` after all attempts fail. Never part of fictional state.
- **Kind:** Thin proxy (deterministic wrapper around the Anthropic SDK client).
- **Reads:** Kwargs forwarded verbatim to `client.messages.create`; response `usage` fields.
- **Writes:** `CallRecord` entries to `TelemetrySink` (one per attempt, including failed ones with zero tokens).
- **Depends on:** Anthropic SDK client (injected); `TelemetrySink`.
- **Depended-on-by:** `AdjudicatorGM`, `NarratorGM`, `CharacterAgent`, `Auditor`, `SocialInterpreter` — all callers accept a `ModelGateway` instead of a raw `anthropic.Anthropic` client.

### Social interpreter (`SocialInterpreter`, `PendingCompel`, `CompelResolution`, `resolve_compel`)
- **Purpose:** Analyzes social events for relationship shifts and Bond-compel opportunities via model tool calls. Proposals are validated before returning to the caller — invalid entities, unknown Bonds, and interiority language are screened and rejected. The caller applies delta proposals through `DispositionEngine.apply_delta()` and resolves compels via `resolve_compel()`. `SocialInterpreter` never writes to the event log or world state — it is a pure proposal source.
- **`resolve_compel()`:** The sole authoritative write point for compel outcomes. On accept: logs `compel_accepted`, applies `GainEdge(1)` via `EffectExecutor`, applies any additional typed effects from the proposal, logs `compel_resolved`. On refuse: logs `compel_refused`, logs `compel_resolved`, no mechanical effects. Both branches derive all events from `compel_proposed_event_id`.
- **Interiority invariant:** Compel text asserting what a player character *feels, believes, wants, or chooses* is rejected at validation time. Compels pressure situation/reputation/obligations/relationships only.
- **Kind:** Agent (model) for analysis; deterministic for validation and compel resolution.
- **Reads:** A single `Event`; social context string; `BondRef` table per character; valid entity set.
- **Writes:** Nothing directly. Outcomes via `resolve_compel()`: `compel_accepted` / `compel_refused` / `compel_resolved` events; Edge via `EffectExecutor`.
- **Depends on:** `ModelGateway`, `DispositionDelta`, `DispositionAxis`, `BondRef`, `GainEdge`, `EffectExecutor` (for `resolve_compel`), `EventLog` (for `resolve_compel`).
- **Depended-on-by:** Beat loop (social analysis step, after narration); D-004 compel/Edge coupling; D-011 model-proposed delta path.

### Telemetry sink (`TelemetrySink`, `CallRecord`)
- **Purpose:** In-process store of per-call operational data. Zero coupling to fictional state — never referenced by `EventLog`, `CommitPipeline`, `ContextAssembler`, or any belief store (D-022).
- **Kind:** Deterministic store (plain Python, no I/O).
- **Reads:** — (written by `ModelGateway`).
- **Writes:** Appends `CallRecord` entries; `summary()` returns totals and per-role breakdowns.
- **Depends on:** `ModelGateway` (the writer).
- **Depended-on-by:** Operational monitoring; future cost/latency budget enforcement (Phase 22).

---

## Deterministic services

Code, not models. These live *below* the determinism boundary and carry truth.

### Orchestrator / Director
- **Purpose:** Decides who may act next — initiative order in combat, spotlight or bidding in social scenes. Operates on routing **metadata only** (presence, spotlight, initiative), never private content, so it cannot become an omniscience leak. Also gates TTS playback order.
- **Reads:** Scene/presence metadata, initiative order, spotlight state.
- **Writes:** Turn grants; spotlight assignment.
- **Depends on:** World state (presence/initiative metadata only), perception model (presence).
- **Depended-on-by:** Beat loop (step 1); all agents (their turns); `SceneCadence` (uses `sorted_by_spotlight`); interface (TTS turn-gating).

### Scene cadence / companion activation gate (`SceneCadence`, `SceneMode`)
- **Purpose:** Deterministic companion activation for each round based on narrative scene mode (D-021). Holds the current `SceneMode` (quiet/dialogue/tactical/combat/downtime/high-drama) and any always-active companion designations. `select_companions(candidates, spotlight_order)` returns which AI companions are invited to act; companions not returned must receive no model call. Mode transitions are pure state changes — no model call required.
- **Key invariant:** Reads routing metadata only (entity IDs, mode string). Never reads event content or private fictional state — same omniscience invariant as the Orchestrator.
- **Companion limits by mode:** quiet/downtime → 1; dialogue → 2; tactical/combat/high-drama → all present.
- **Reads:** `SceneMode` state, always-active set, spotlight priority order (from `Orchestrator.sorted_by_spotlight`).
- **Writes:** No persistent state — pure selection function plus mutable mode/always-active fields.
- **Depends on:** `Orchestrator.sorted_by_spotlight` (for least-recently-acted priority in limited modes).
- **Depended-on-by:** `BeatRunner.run_round` (`scene_cadence` parameter — pre-filters `remaining` before the round loop).

### Action queue / proposal buffer
- **Purpose:** The blackboard's write surface (CORE §4.3). Agents (GM, teammates, NPC-manager) write proposed intents and dialogue here each beat (beat loop step 3); the orchestrator and adjudicator drain and arbitrate them (steps 4–7). **Transient and non-authoritative** — unlike the event log, it holds *candidates, not truth*. A proposal becomes a logged event only after it is resolved and committed (steps 6–9), at which point its audience is computed; until then it never enters any belief projection, so an unresolved proposal cannot leak across POVs. This is what keeps the append-only log purely authoritative while still giving agents somewhere to propose.
- **Reads:** — (written by agents).
- **Writes:** Pending proposals; drained/cleared each beat.
- **Depends on:** — (a buffer the mediator drains; depends on nothing below it).
- **Depended-on-by:** Beat loop (steps 3–7); orchestrator (drains and arbitrates); GM/character/NPC-manager agents (their write target).
- **Precondition for `run_with_agent`**: `BeatRunner.run_with_agent(agent, queue)` enqueues the agent's proposal and immediately drains the entire queue, taking `proposals[0]`. If the queue contained pending proposals from a prior step that were never drained, the agent will execute a *different* proposal than its own. In normal `run_round` usage the queue is always empty before each `run_with_agent` call (the prior call fully drained it). Callers using `run_with_agent` directly must guarantee the queue is empty or None before calling.

### Context assembly / fog-of-war filter
- **Purpose:** Builds each agent's prompt by projecting the event log through that agent's audience membership and adding persona, entitled state/relationships, and retrieved memory. Implements fog of war.
- **Reads:** Event log, persona specs, world state, disposition graph, perception results.
- **Writes:** Ephemeral per-agent context (and optional cache).
- **Depends on:** Event log, perception model, persona specs, world state, disposition graph.
- **Depended-on-by:** Beat loop (step 2); every agent; the entire access model.

### Perception model
- **Purpose:** Computes what each entity could sense (presence, line of sight, audibility, lighting, positioning). Determines/validates event audiences, including overhears. **The load-bearing wall** for secrets and differential information.
- **Reads:** Scene/positioning state, world state.
- **Writes:** Audience computations; derived `may-have-perceived` events.
- **Depends on:** Scene/perception state, world state.
- **Depended-on-by:** Context assembly, orchestrator (presence), event audiences (whole access model), access matrix rows.

### Effect executor
- **Purpose:** The single sanctioned path for mutating world state via typed operations (Phase 12). Validates TypedEffect proposals from GM/rules-engine against current world state, applies the mutation, and logs a provenance event with `derived_from` linkage to the source beat or resolution. Narration never holds a reference to this executor — that structural gap is what prevents prose from creating state changes.
- **Minimum operation set:** CreateTruth, ChangeTruth, ExpireTruth, AdvanceClock, ApplyStress, ChangeAccess, MoveEntity, ChangeResource, CreateMaintainedTruth, ExpireMaintainedTruth. Phase 20 adds GainEdge (cap-3 Edge grant; compel-accept path) and SpendEdge (lean/push/shield; v6 §13). Pre-Phase-21 pull-forward adds ApplyScar (3-slot cap; Scar Route Invariant; `character_broken` event at cap) and enforces STRESS_CAP=6/SCAR_CAP=3 with automatic stress-overflow cascade (clear stress → ApplyScar with via_overflow=True).
- **Kind:** Deterministic service.
- **Reads:** World state, canon ledger (via CommitPipeline.check), scene state.
- **Writes:** World state mutations; logged `effect_applied` events (with provenance); maintained_truths in WorldState; tombstone commitments for ExpireTruth; `character_broken` event when Scar cap is reached.
- **Depends on:** EventLog, WorldState, CommitPipeline, Scene (optional — required for ChangeAccess).
- **Depended-on-by:** Beat loop (step 6); BeatResult.effect_results; Phase 13 (typed consequence palette selection); `resolve_compel` (GainEdge on accept).

### Rules engine
- **Purpose:** Implements FABLE's mechanics per `uploads/FABLE_Engine_Schema_v6.md`: the 3d6 roll and result bands, TN/Exposure/Effect, the Trade and Ledger economies, Truths, Clocks, Fronts, Edge, and Stress/Scars. Combat, intrigue, etc. are **Modes** (configurations of these surfaces), not separate subsystems. The single authority for mechanical outcomes.
- **Reads:** World state, character sheets, dice service.
- **Writes:** Resolved outcomes (→ world state via committed events).
- **Depends on:** World state, character sheets, dice service.
- **Depended-on-by:** GM adjudicator, auditor, beat loop (step 5), disposition engine (some deltas), disposition→Edge/Bonds coupling (D-004).

### Disposition engine (`DispositionEngine` in `disposition.py`)
- **Purpose:** Derives and applies disposition deltas from logged events ("took a hit meant for me → +trust"), writing each change to the disposition graph **linked to its causal event id** so attitudes stay auditable and explainable, never free-floating (CORE §7.5). The single authoritative writer of the disposition graph: agent-proposed deltas (e.g. from the NPC-manager) are applied *through* it, not written directly.
- **Kind:** Deterministic service (Phase 19). Deterministic recognition fires on commitment predicates `"disposition_delta"` (explicit signal), `"stress_taken_for"`, and `"triumph_for"`. Model-proposed deltas for social cues are Phase 20; the engine is the commit point either way (D-011 option c).
- **Reads:** Event log (causal events via `process_event`).
- **Writes:** Disposition graph deltas (each linked to a causal event id).
- **Depends on:** Disposition graph.
- **Depended-on-by:** Beat loop (step 9); disposition graph (its writer of record).

### Dice service
- **Purpose:** Logged, auditable randomness. No claimed outcome is real unless it came from here.
- **Reads:** —
- **Writes:** Dice events to the log.
- **Depends on:** Event log.
- **Depended-on-by:** Rules engine, auditor (verifies claimed rolls), interface (dice feed).

### Fact-extraction & commit pipeline
- **Purpose:** Parses declarations (prose) into structured commitments and checks them against the canon ledger — the same step that *defines* "contradictory." Converts improvised worldbuilding into self-binding state.
- **Kind:** Deterministic pipeline; may use a small model for prose→structure (see DECISIONS D-007).
- **Reads:** Declaration events, canon ledger, world state.
- **Writes:** Commitments → world state / canon ledger; conflict flags.
- **Depends on:** World state, canon ledger, event log.
- **Depended-on-by:** GM agent (declarations), auditor (needs committed facts), beat loop (step 6).

### Channel router / interface
- **Purpose:** Routes attributed events to the correct UI channels (public, whisper, OOC, dice) and per-character boxes; drives per-character TTS.
- **Reads:** Events with audience/visibility; turn order from orchestrator.
- **Writes:** UI render; TTS queue.
- **Depends on:** Event log, orchestrator, TTS service.
- **Depended-on-by:** The human player (sole external consumer).

### TTS service
- **Purpose:** Per-character voice synthesis (e.g. ElevenLabs), played in orchestrator-gated turn order to avoid overlap.
- **Reads:** Narration/dialogue events; turn order.
- **Writes:** Audio output.
- **Depends on:** Orchestrator (turn-gating), channel router.
- **Depended-on-by:** Interface.

---

## Data stores

Authoritative state. No model owns these; services read and write them.

### Event log
- **Purpose:** Append-only single source of historical truth. `{author, channel, audience, visibility, type, content, commitments, derived_from, sequence}`.
- **Depended-on-by:** Belief-store projections, context assembly, auditor, plot-manager (divergence/interest), interface, dice service.

### World state
- **Purpose:** Structured, authoritative present state: entities, positions, conditions, resources, clocks/fronts, scene/zone graph, terrain. Position is **fiction-positional** — Truths within the zone graph, not coordinates and not a formal band system (D-002).
- **Depended-on-by:** Rules engine, perception model, context assembly, auditor, GM, fact-extraction.

### Canon ledger
- **Purpose:** Immutable set of committed-and-*revealed* facts. The boundary above which nothing may be silently changed.
- **Depended-on-by:** Fact-extraction (consistency check), auditor, plot-manager (may not cross it).

### Disposition graph (`DispositionGraph`, `SQLiteDispositionGraph` in `disposition.py` / `persistence.py`)
- **Purpose:** Directed, asymmetric, multi-axis (trust/affection/respect/obligation) attitudes; every delta linked to its causal event id. The fine-grained relational *state*; it surfaces mechanically only through **Bonds** (Held Truths) and **Edge** spends, never as a passive modifier and never as a separate currency (D-004). `SQLiteDispositionGraph` persists all deltas within the D-023 transaction model; wired into `SQLiteEventLog._disposition_ref` for rollback.
- **Written by:** Disposition engine (the authoritative writer; all deltas flow through it, including model-proposed deltas from `SocialInterpreter`).
- **Reads:** `context_block(from_id)` consumed by context assembly for agent prompts.
- **Depended-on-by:** Context assembly, character agents, NPC-manager, mechanics coupling (D-004).
- **Access invariant:** Never referenced by `project_for`, `CommitPipeline`, or any player-facing projection — structural isolation. Use `attach_disposition(log)` to create the persistent variant after `open_session`.

### Character sheet (`CharacterSheet`, `BondRef` in `character_sheet.py`)
- **Purpose:** Mechanical anatomy for one character (PC or significant NPC): skills, stress, Edge, traits, scars, and Bonds. Phase 20 adds `BondRef` — a stable, frozen reference linking a narrative Bond to a canonical commitment ID in the event log, so compels and advancement can target a specific Held Truth rather than a free string. `CharacterSheet.bonds: list[str]` is preserved for display and backward compatibility; `bond_refs: list[BondRef]` is the mechanical handle.
- **Written by:** Session setup / campaign load; advancement (future). Never written by models.
- **Reads:** Skills read by rules engine; `bond_refs` read by `SocialInterpreter` (compel target selection) and context assembly.
- **Depended-on-by:** Rules engine, context assembly, `SocialInterpreter` (compel validation), advancement (Phase 22).

### Campaign package (`CampaignPackage`, `load_campaign`, `load_campaign_dict`)
- **Purpose:** Validated, deserialized campaign data loaded from a JSON file at session start (Phase 17). Carries function nodes, hooks (with embedded alternatives), fronts, factions, hidden nodes, and world clocks. `to_plot_graph()` produces an in-memory `PlotGraph`; `seed_world(world)` seeds `WorldState.clocks`. Immutable after load — mutations go through `PlotManager`/`SQLitePlotGraph` only.
- **Kind:** Deterministic loader + value type (no model calls; no persistent state itself).
- **Cross-reference validation:** hook `function_id` must be in `function_nodes`; front `clock_name` must be in `world_clocks` (if any); front `faction_id` must be in `factions` (if any). Duplicates rejected at load time.
- **Hidden invariant:** Campaign data is GM-private — it must never be passed to a player or TM belief store or used to construct their context. Audience enforcement is structural: no player-facing code path takes a `CampaignPackage` argument.
- **Reads:** JSON file on disk.
- **Writes:** Returns a `CampaignPackage`; `seed_world` mutates `WorldState.clocks`.
- **Depends on:** `PlotGraph`, `WorldState`.
- **Depended-on-by:** `attach_campaign` (seeds `SQLitePlotGraph`); `PlotManager` (operates on the graph after seeding); session setup code.

### Plot graph store (`PlotGraph`, `SQLitePlotGraph`)
- **Purpose:** Fronts, clocks, hooks, secrets, hidden nodes with preconditions; function nodes and their fixture bindings; interest-signal accumulator. Hidden from all player/TM audiences. `PlotGraph` is the in-memory form; `SQLitePlotGraph` is the SQLite-backed subclass (Phase 17) that persists every mutation and participates in the D-023 transaction rollback via `SQLiteEventLog._plot_graph_ref`.
- **Mutation seams (D-016):** `PlotManager` is the sole external writer. Direct callers (`SQLitePlotGraph` setup via `attach_campaign`) use the mutation methods (`add_function`, `add_hook`, `add_front`, `add_faction`, `add_hidden_node`, `set_alternatives`, `update_hook_binding`) which each trigger `_save()`. `PlotManager.accept_rebinding` routes through `update_hook_binding`, not direct attribute mutation, so the `SQLitePlotGraph` override can intercept and persist.
- **Access control:** No code path from the plot graph leads to `project_for`, `CommitPipeline`, or any player-facing projection. The isolation is structural, not behavioral.
- **Depended-on-by:** Plot-manager, GM (via plot-manager), `attach_campaign`, `open_session` (via rollback wire).

### Character sheets
- **Purpose:** FABLE character anatomy (Concept, Skills 0–4, Traits, Bonds, Drive, Question, Gear) plus the Stress track, Scars, and Edge. Mechanical truth. See `uploads/FABLE_Engine_Schema_v6.md` §4, §13–14.
- **Depended-on-by:** Rules engine, character/GM agents (entitled views).

### Persona specs
- **Purpose:** Per-agent voice, values, public goals, hidden agenda.
- **Depended-on-by:** Context assembly, the agent it describes.

### Scene / perception state
- **Purpose:** Presence, line of sight, audibility, lighting, positioning — inputs to perception checks.
- **Depended-on-by:** Perception model, orchestrator (presence).

---

## Session management *(Phase 21 deliverable)*

The session manager is the entry point for the production interface. It surfaces saved sessions, creates new ones, and guards schema compatibility. No session management component holds game authority or writes to the event log.

### Session manifest (`SessionManifest`)
- **Purpose:** Frozen dataclass carrying the metadata for one saved session. Stored in a `sessions` index (SQLite table or JSON sidecar) separate from the session DB itself. Provides enough information to display the session list without opening the session DB.
- **Fields:** `session_id: str`, `campaign_id: str`, `title: str`, `created_at: str` (ISO-8601), `updated_at: str`, `last_scene_summary: str` (GM-written; short), `player_summary: str` (party/character names), `db_path: str` (path to session SQLite file), `schema_version: str`, `engine_version: str`.
- **Kind:** Frozen dataclass (data only; no methods that mutate state).
- **Reads:** Written at session create and updated at session close/checkpoint.
- **Depends on:** Nothing (plain dataclass).
- **Depended-on-by:** `SessionManager` (list and resume); home screen (display).

### Session manager (`SessionManager`)
- **Purpose:** Lists saved sessions, creates new sessions from a `CampaignPackage`, and resumes sessions. Enforces the **schema version guard**: on resume, reads `schema_version` from the session DB `schema_version` table and rejects the load (fail-closed) if it does not match the current engine's `ENGINE_SCHEMA_VERSION` constant. Phase 22 adds migration; Phase 21 only guards and rejects.
- **Schema version contract:** `open_session()` writes a `schema_version` row to a `schema_version` table on first open. On resume, `SessionManager.resume()` reads this row and raises `SchemaVersionError` if the stored version does not match `ENGINE_SCHEMA_VERSION`. The caller must either upgrade the DB (Phase 22) or inform the user the save is incompatible.
- **Kind:** Service (stateless between calls; does not hold open session connections).
- **Reads:** Session index (manifest store); DB `schema_version` table on resume.
- **Writes:** Session manifest entries on create; `schema_version` table in session DB (via `open_session()`).
- **Depends on:** `open_session()`, `attach_campaign()`, `SessionManifest`, `CampaignPackage`.
- **Depended-on-by:** Home screen (New Campaign / Return to Saved Session paths); Phase 22 migration tooling.

---

## Settings system *(Phase 21 deliverable; D-041)*

Layered configuration for model choices and optional integration keys. No settings component holds game authority or writes to the event log or world state.

### Settings registry (`SettingsRegistry`)
- **Purpose:** Holds code-level defaults for every essential setting. The engine is always in a valid state with zero user configuration — every key has a baked-in default value. Acts as the fallback layer at the bottom of the override hierarchy.
- **Essential keys (with defaults):** `gm_adjudicator_model` (`claude-opus-4-8`), `gm_narrator_model` (`claude-opus-4-8`), `gm_world_simulator_model` (`claude-opus-4-8`), `auditor_model` (`claude-haiku-4-5-20251001`), `social_interpreter_model` (`claude-sonnet-4-6`), `character_agent_default_model` (`claude-opus-4-8`), `character_agent_{entity_id}_model` (inherits default per campaign roster).
- **Kind:** Frozen dataclass or module-level constant dict (no I/O; pure data).
- **Depends on:** Nothing.
- **Depended-on-by:** `SettingsManager` (fallback layer); play interface (placeholder text).

### Settings manager (`SettingsManager`)
- **Purpose:** Resolves the active value for any setting key by walking the three-layer hierarchy: code defaults → `settings/models.json` → `settings/campaigns/{campaign_id}.json`. Loads the relevant files on initialization; exposes `get(key)`, `set(key, value, scope)`, and `reset(key, scope)`. Writes per-campaign overrides to the campaign settings file; writes user-level overrides to `settings/models.json`.
- **Campaign-aware slot discovery:** When a campaign is loaded, `SettingsManager` reads the campaign roster and registers one `character_agent_{entity_id}_model` key per character agent seat. Keys are derived from the live campaign; stale keys from unloaded campaigns are not surfaced.
- **Kind:** Service (stateful across a session; reloads on campaign change).
- **Reads:** `settings/models.json`, `settings/campaigns/{campaign_id}.json`, `SettingsRegistry` defaults, campaign roster (entity IDs for agent slots).
- **Writes:** `settings/models.json` (user-level overrides); `settings/campaigns/{campaign_id}.json` (per-campaign overrides; creates file on first per-campaign write).
- **Depends on:** `SettingsRegistry`, `CampaignPackage` (roster), file system.
- **Depended-on-by:** `ModelGateway` (reads active model IDs at call time); play interface settings panel; Phase 22 settings migration.

### Settings panel *(interface component; not a code component)*
- **Purpose:** GUI panel (within the play interface) that renders all essential settings with their current effective value, default placeholder, and a per-row Reset button. Displays the full file path for the active user-level and campaign-level settings files, with a button to open the file in the system editor (or copy-to-clipboard fallback). Character agent slot rows are generated dynamically from the campaign roster.
- **API key display:** For voice and any other third-party API keys, the panel shows only the environment variable name and a "set / not set" status indicator. No text field accepts or displays the key value itself.
- **Depended-on-by:** Play interface (settings panel sub-view).

---

## Image generation layer *(post-Phase-21; D-038 — designed, not built)*

Presentation-only rendering. No component here may become game authority. All components in this section are downstream consumers of the engine; none write to the event log, world state, or canon ledger. See D-038 for the full design spec.

### Image generation gateway (`ImageGenerationGateway`)
- **Purpose:** Parallel seam to `ModelGateway`, dedicated to image-model API calls. Holds a registry of named model profiles (`cheap_scene`, `premium_scene`, `portrait`, `map_background`, `text_graphic`). Records per-call telemetry (model, provider, cost, latency, cache-hit) in `TelemetrySink` — never in the event log. Handles async dispatch and result callbacks; returns `ImageArtifact` on completion.
- **Kind:** Thin async proxy (deterministic wrapper; no game logic).
- **Reads:** Model profile name; assembled prompt; style profile ID.
- **Writes:** `ImageArtifact` entries to `ImageArtifactStore`; telemetry records.
- **Depends on:** `ImageArtifactStore`, `TelemetrySink`, image model provider APIs.
- **Depended-on-by:** Interface / channel router (triggers generation on scene transitions and portrait requests); user visual mode setting gates whether calls are made at all.

### Image prompt assembler (`ImagePromptAssembler`)
- **Purpose:** Builds image prompts exclusively from the viewer's authorized belief store / render projection. Concatenates subject/context description (from entitled world state, committed scene facts, and `epistemic_type="fact"` commitments only) with the global style instructions loaded from the style profile. Subject and style are kept as separate strings throughout — they are combined at call time, never pre-merged.
- **Authority invariant:** Must never read hidden plot, unaudienced events, whispered content, secret identities, private NPC interiors, GM-side adjudicator output, or unrevealed map locations. The same fog-of-war constraint that governs belief stores governs this assembler. If the assembler has access to `project_for` output, it has correct access; nothing else is permitted.
- **Style invariant:** Style instructions come from the style profile only (see below). The assembler must not invent or embed aesthetic direction. Style instructions must not contain game-state facts.
- **Kind:** Deterministic assembler (pure function; no model calls; no I/O except style profile read).
- **Reads:** Viewer belief store / render projection; style profile (style instructions only).
- **Writes:** Returns `(subject_prompt: str, style_prompt: str)` — separate strings, never merged here.
- **Depends on:** `ContextAssembler` / belief store, style profile.
- **Depended-on-by:** `ImageGenerationGateway` (receives assembled prompts).

### Style profile *(config file; not a code component)*
- **Purpose:** Holds the project owner's global visual style instructions. Applied identically to every generated image unless an explicit per-artifact override exists (not yet designed). Must be editable without code changes; loaded at session start or image-generation call time.
- **Location:** `settings/style_profile.json` (or `.toml`/`.yaml` — format TBD; see D-038). One field: `style_instructions: str`. Optional: `version: str` for artifact provenance.
- **Content invariant:** Style instructions are aesthetic direction only — mood, rendering style, palette, medium, tone, era, artistic reference. Must not contain character names, location names, game-state facts, plot details, or any content that could create a narrative constraint. The project owner supplies this manually; the engine never generates or modifies it.
- **Depended-on-by:** `ImagePromptAssembler`; `ImageArtifact.style_prompt_version` (provenance).

### Image artifact store (`ImageArtifactStore`, `ImageArtifact`)
- **Purpose:** Stores generated image files and their provenance metadata. `ImageArtifact` records are append-only (new generations produce new records; no retroactive state changes). Never referenced by `project_for`, `CommitPipeline`, or game-state derivations.
- **`ImageArtifact` fields:** `artifact_id`, `kind` (portrait/scene/map_background/text_graphic), `viewer_id` / `audience`, `source_event_ids` (the event log IDs that contributed to the prompt), `source_snapshot_hash` (hash of the belief-store snapshot at generation time — for cache invalidation), `prompt_used` (the full subject+style string sent to the model), `style_profile_id` / `style_prompt_version`, `provider_model`, `cost_usd`, `status` (pending/complete/failed), `non_authoritative: bool = True` (always True — this field exists so any code that reads artifacts can assert it).
- **Caching policy:** Portraits cached per character until manually refreshed. Scene images cached per major scene transition (trigger definition: TBD — D-038 open). Cache key is `source_snapshot_hash` so a changed belief store invalidates the cache entry without invalidating artifacts from earlier snapshots.
- **Authority invariant:** If an image contradicts the event log or world state, the event log and world state win. Regeneration never changes game state. `non_authoritative = True` is enforced as a load-time assertion, not a runtime check.
- **Kind:** Deterministic store (file system + SQLite metadata; no model calls).
- **Depends on:** File system; session DB (SQLite table separate from event log and world state).
- **Depended-on-by:** Interface / channel router (displays generated images); `ImageGenerationGateway` (cache lookup before calling model).

---

## Cross-cutting protocols

---

## Voice / TTS layer *(post-Phase-21; D-039 — designed, not built)*

Manual click-to-play audio for rendered text bubbles. No component here writes to the event log, world state, or any deterministic store. See D-039 for the full design spec and API key policy.

### Voice gateway (`VoiceGateway`)
- **Purpose:** Thin wrapper around the ElevenLabs API (or compatible TTS provider). Takes `(text: str, voice_id: str, model_id: str)` and returns a local audio file path. Checks `VoiceArtifactCache` before calling the API; writes the result to cache on success. Records per-call telemetry (latency, cost) in `TelemetrySink` — never in the event log.
- **Kind:** Thin async proxy (no game logic; no authority).
- **Authority constraint:** No reference to `EventLog`, `CommitPipeline`, `WorldState`, or `EffectExecutor`. Reads only entitled text (the rendered event content the interface already displays).
- **Depends on:** `VoiceArtifactCache`, `TelemetrySink`, ElevenLabs API.
- **Depended-on-by:** Interface / play view (audio button per rendered bubble).

### Voice artifact cache (`VoiceArtifactCache`)
- **Purpose:** Maps `(event_id, voice_id)` → local audio file path. Prevents re-billing for the same rendered bubble. Cache entries are keyed by `event_id + voice_id` hash; a new voice ID assignment for the same event generates a new cache entry.
- **Kind:** Deterministic cache (file system + lightweight index; no model calls).
- **Depends on:** File system.
- **Depended-on-by:** `VoiceGateway`.

### Voice settings *(config file; not a code component)*
- **Location:** `settings/voice.json`.
- **Content:** `enabled` flag, `provider`, `api_key_env` (env var name only — never the key itself), `default_model`, per-speaker `voice_id` / `model_id` map. Speaker keys match entity IDs or the reserved key `"gm"`.
- **API key policy:** The API key must never appear in this file or in any save file. It is read at call time from the environment variable named by `api_key_env`.
- **Depended-on-by:** `VoiceGateway`; interface (reads `enabled` flag before showing audio buttons).

---

## Campaign-Authoring Studio *(post-v1; D-040 — designed, not built)*

Separate workflow for creating campaigns. Both entry modes (auto-generate, generate-from-prompt) produce a validated `CampaignPackage` via `CampaignCompiler`. Raw user input never reaches GM runtime context directly. See D-040 for the full pipeline and required output fields.

### Campaign compiler (`CampaignCompiler`)
- **Purpose:** Structured-output model call that converts raw user input (prompt, file, or minimal choices) into a `CampaignPackage` draft. Output is a JSON object conforming to `campaign.schema.json`. Never placed in GM runtime context; always validated before use.
- **Kind:** Model component (structured output; no game authority).
- **Reads:** Raw user input (source material only); defaults/settings for auto-generate mode.
- **Writes:** `CampaignPackage` JSON draft (to `CampaignCompilerGateway` for validation).
- **Depends on:** `ModelGateway`, `campaign.schema.json`.
- **Depended-on-by:** `CampaignCompilerGateway`.

### Campaign compiler gateway (`CampaignCompilerGateway`)
- **Purpose:** Orchestrates the `CampaignCompiler` call, validates output against `campaign.schema.json`, issues repair/retry requests up to a configured maximum, and surfaces a `CampaignPackage` on success or a structured error on exhaustion. Ensures no invalid package reaches `attach_campaign()`.
- **Kind:** Deterministic orchestrator (repair/retry loop; no authority).
- **Depends on:** `CampaignCompiler`, `campaign.schema.json`, `load_campaign_dict`.
- **Depended-on-by:** Campaign-Authoring Studio UI (home screen "Generate Campaign" path).

---

Not components (no model, service, or store of their own), but referenced by components above and registered here so those references resolve.

### Override *(protocol; see DECISIONS D-008)*
- **What it is:** A deliberate, logged revision of committed state — recorded as an event (`type: override`) carrying an author and a reason. The `event.schema.json` `type` field is already free-form, so no schema change is needed.
- **How it works:** The auditor keys off the override marker to read the change as **intentional fiat rather than a bug** (CORE §3, §6.2). This is what distinguishes a sanctioned rule-of-cool / self-correction from the one forbidden move (silent contradiction).
- **MVP default (D-008):** no unstructured overrides; every override is an explicit logged event with author and reason.
- **Authority (D-008, Resolved):** the AI GM holds override authority; the human player is co-authority and backstop (final say, table-safety). Override is the **reserved exception** — normal GM authority is *latent*, exercised through Add / Change-via-causation (§6.2) and plot-bending (§7.4), so divergence meets friction, consequence, and adjacent hooks rather than veto. Reserve override for genuine coherence-breaks and table-safety.
- **Depends on:** Event log (carries the override event), auditor (intentional-vs-bug distinction).
- **Depended-on-by:** Auditor (treats flagged overrides as fiat); CORE §6.2 forbidden-move boundary.

---

## Quick dependency lookup (remove-impact)

If you remove or rename a component, these are the most commonly missed reconciliation points:

- **Any agent** → orchestrator routing, access matrix, interface channels, CORE §4/§5.
- **Perception model** → context assembly, every event audience, access matrix, CORE §6/§7.1 (this one touches almost everything — treat removal as a redesign).
- **Plot-manager** → GM consumption, beat-loop divergence handling, roadmap phase 9, CORE §4.2/§7.4.
- **Rules engine / dice** → adjudicator, auditor, disposition deltas, CORE §6.1/§7.2.
- **Fact-extraction** → GM declarations, auditor's ability to check anything, CORE §6.1/§7.3.
- **Action queue** → beat-loop steps 3–7, orchestrator drain, every agent's propose step, CORE §4.3/§5. (Transient; not on the authoritative log.)
- **Disposition engine** → disposition-graph writes, beat-loop step 9, roadmap phase 10, CORE §7.5.
