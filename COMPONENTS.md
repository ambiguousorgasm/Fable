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
- **Writes:** NPC action/dialogue events; NPC disposition deltas (event-derived).
- **Depends on:** Context assembly, perception model, disposition graph, world state.
- **Depended-on-by:** Access matrix (overhear path; trivial-action perception); interface (NPC channels).

### Plot-manager agent
- **Purpose:** Owns the *future*. Holds the plot graph; detects divergence; re-binds plot **functions** to new **fixtures**; promotes high-interest threads; accumulates player-interest signals. Edits only the hidden graph, never the canon ledger.
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

## Deterministic services

Code, not models. These live *below* the determinism boundary and carry truth.

### Orchestrator / Director
- **Purpose:** Decides who may act next — initiative order in combat, spotlight or bidding in social scenes. Operates on routing **metadata only** (presence, spotlight, initiative), never private content, so it cannot become an omniscience leak. Also gates TTS playback order.
- **Reads:** Scene/presence metadata, initiative order, spotlight state.
- **Writes:** Turn grants; spotlight assignment.
- **Depends on:** World state (presence/initiative metadata only), perception model (presence).
- **Depended-on-by:** Beat loop (step 1); all agents (their turns); interface (TTS turn-gating).

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

### Rules engine
- **Purpose:** Implements FABLE mechanics: resolution, stances, the Trade/Ledger economy, combat math, clocks/fronts. The single authority for mechanical outcomes.
- **Reads:** World state, character sheets, dice service.
- **Writes:** Resolved outcomes (→ world state via committed events).
- **Depends on:** World state, character sheets, dice service.
- **Depended-on-by:** GM adjudicator, auditor, beat loop (step 5), disposition (some deltas), Strings/economy coupling.

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
- **Purpose:** Structured, authoritative present state: entities, positions, conditions, resources, clocks/fronts, scene/zone graph, terrain.
- **Depended-on-by:** Rules engine, perception model, context assembly, auditor, GM, fact-extraction.

### Canon ledger
- **Purpose:** Immutable set of committed-and-*revealed* facts. The boundary above which nothing may be silently changed.
- **Depended-on-by:** Fact-extraction (consistency check), auditor, plot-manager (may not cross it).

### Disposition graph
- **Purpose:** Directed, asymmetric, multi-axis (trust/affection/respect/obligation) attitudes; every delta linked to its causal event. Optional Strings resource.
- **Depended-on-by:** Context assembly, character agents, NPC-manager, mechanics coupling (see DECISIONS D-004).

### Plot graph store
- **Purpose:** Fronts, clocks, hooks, secrets, hidden nodes with preconditions; function nodes and their fixture bindings; interest-signal accumulator. Hidden from all player/TM audiences.
- **Depended-on-by:** Plot-manager, GM (via plot-manager).

### Character sheets
- **Purpose:** FABLE stats, current stance, economy/resource state. Mechanical truth.
- **Depended-on-by:** Rules engine, character/GM agents (entitled views).

### Persona specs
- **Purpose:** Per-agent voice, values, public goals, hidden agenda.
- **Depended-on-by:** Context assembly, the agent it describes.

### Scene / perception state
- **Purpose:** Presence, line of sight, audibility, lighting, positioning — inputs to perception checks.
- **Depended-on-by:** Perception model, orchestrator (presence).

---

## Quick dependency lookup (remove-impact)

If you remove or rename a component, these are the most commonly missed reconciliation points:

- **Any agent** → orchestrator routing, access matrix, interface channels, CORE §4/§5.
- **Perception model** → context assembly, every event audience, access matrix, CORE §6/§7.1 (this one touches almost everything — treat removal as a redesign).
- **Plot-manager** → GM consumption, beat-loop divergence handling, roadmap phase 9, CORE §4.2/§7.4.
- **Rules engine / dice** → adjudicator, auditor, disposition deltas, CORE §6.1/§7.2.
- **Fact-extraction** → GM declarations, auditor's ability to check anything, CORE §6.1/§7.3.
