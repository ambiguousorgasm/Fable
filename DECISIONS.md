# Design Decision Log

Living record of design forks — open and resolved. Authoritative for decision *status*; CORE §11 carries only an index of what is open. Each decision has a stable ID so other files and the changelog can reference it.

**Format:** `ID · Title · Status (Open / Resolved / Superseded) · Date.` Then: the question, the options, the recommendation/decision, rationale, and any downstream impact.

When a decision is resolved, change its status and date, record the choice, and walk the change protocol (`00_README.md`) — a resolution usually changes CORE and `COMPONENTS.md`.

---

## D-001 · Belief store: read-time projection vs. write-time materialization · Resolved · 2026-06-18
**Question:** Is each agent's belief store derived on read by filtering the event log, or materialized per-agent at write time?
**Options:** (a) Read-time projection from the single log, cached. (b) Write-time fan-out into per-agent stores.
**Decision:** (a). Belief stores are read-time projections over the single event log, with optional cache. Implemented in phase 4 (`ContextAssembler.belief_store`). Two materialized stores drifting apart reintroduces omniscience-style bugs by the back door — the same reasoning that settled D-009 and D-010.
**Impact if changed:** Context assembly, event-log schema, caching layer.

## D-002 · Spatial model · Resolved · 2026-06-17
**Question:** How is position/distance represented in world state?
**Options:** (a) Abstract range bands (close/near/far). (b) Coordinates or a grid. (c) Fiction-positional — position as Truths, no measured space.
**Decision:** (c) Fiction-positional, following FABLE's native abstraction. Position is a fictional fact persisted as **Truths** (`uploads/FABLE_Engine_Schema_v6.md` §12) within the scene/zone graph; there is no coordinate grid (rejects (b)) and no formal range-band system (looser than (a)). Proximity surfaces mechanically only through the Ledger **Position** category (§10) and the **Ground** cost register (§7); coarse qualitative tags (adjacent / near / far) are descriptive adjudication aids, not measured quantities. A distance the GM states in fiction ("a hundred feet off") is committed as a relational Truth and enforced by Truth-consistency + logged traversal, not by arithmetic.
**Determinism-boundary note:** position stays code-owned (CORE principle 1). The engine authoritatively owns which position Truths exist, whether a proposed action contradicts one, and whether a traversal has been logged — it simply does not compute metric distance. "Code owns positions" means code owns the *position Truths and their consistency*, not a coordinate system.
**Rationale:** FABLE is fiction-positional; imposing a grid or a band system would be a spatial subsystem the ruleset doesn't use and would fight invariant 18. The spatial-consistency success criterion (CORE §13) is preserved — it enforces via Truth/canon non-contradiction and the perception/traversal model rather than coordinates.
**Relates to:** D-003 (positioning queries become reads/authoring of position Truths), the perception model (phase 3, operating over zones + relational Truths), and CORE §6/§9.B (the "100 feet to the tower" frame, now an authored Truth).
**Impact:** World state schema (`entity.position`), rules engine, perception model, distance-query handling.

## D-003 · Positioning queries: free OOC read vs. in-character assessment · Open · 2026-06-17
**Question:** Is "how far am I from X?" a free clarification, or an in-character action? And is the map itself fogged?
**Options:** (a) Free OOC read, no fiction cost. (b) IC assessment that costs a beat and enables map fog-of-war (unscouted distances unknown).
**Recommendation:** Lean (a) for routine play; consider (b) selectively for exploration-heavy scenes where not-knowing is the point.
**Impact:** Adjudicator, perception model, world state (map visibility).

## D-004 · Disposition→mechanics coupling · Resolved · 2026-06-17
**Question:** How does disposition affect mechanics, if at all?
**Options:** (a) Always-on passive modifier on cooperation/social rolls. (b) A spendable relational resource for one-time, legible effects.
**Decision:** Option (b), realized **through FABLE's native Edge + Bonds** — *not* a separate "Strings" currency and *not* a passive modifier.
- The **disposition graph** is the fine-grained, event-derived, multi-axis relational *state* (written by the disposition engine; trigger recognition per D-011).
- **Bonds** (Held Truths, `uploads/FABLE_Engine_Schema_v6.md` §12) are the mechanical *handles*: a relationship surfaces as a Bond the actor may **Lean** on (Edge, §13) or that pays a **Ledger** step where it *changes* baseline (§10). **Edge** (cap 3) is the spend currency.
- Disposition *pressures* Bonds through **compels** (world pressure on a Held Truth; accepting one grants Edge, §13), respecting Held-Truth authorship — the world compels, only the owner rewrites; for NPCs the disposition engine / NPC-manager holds authorship. A Bond changing through play is an advancement trigger (§21).
- **No always-on modifier** (preserves the anti-EV-corruption reason behind rejecting (a)) and **no new subsystem** (FABLE invariant 18 / §22 Mode rule).
**Rationale:** FABLE already supplies a spendable relational-leverage economy; a parallel "Strings" mechanic is subsystem growth the ruleset's own invariants reject. Routing through Edge/Bonds keeps coupling legible, EV-safe, and inside the core surfaces. Any coupling still passes the FABLE EV audit before a live table.
**Supersedes:** the standalone "Strings" framing in CORE §3/§7.5/§10. **Relates to:** D-011 (the deltas this coupling expresses).
**Impact:** Disposition graph, disposition engine, rules engine (Edge/Bonds/compels), economy/EV balance.

## D-005 · Spotlight: director-picks-next vs. agent-bidding · Open · 2026-06-17
**Question:** In free social scenes, how is the next speaker chosen?
**Options:** (a) Director picks who is most pressed to act. (b) Agents bid/raise-hand and the director arbitrates.
**Trade-off:** (b) is more reactive and lifelike but costs more — every agent evaluates every beat. (a) is cheaper but less spontaneous.
**Recommendation:** Start (a); prototype (b) behind the cost budget once a cheap "should I act?" gate model exists.
**Impact:** Orchestrator, cost/latency budget, character agents.

## D-006 · NPC management: GM-puppeted vs. dedicated NPC-manager agent · Open · 2026-06-17
**Question:** Who runs NPCs without their own agent?
**Options:** (a) GM puppets minor NPCs ad hoc. (b) A dedicated NPC-manager agent aligned with the GM.
**Recommendation:** Likely both, split by fidelity tier — GM puppets walk-ons, a manager (or promotion to full agent) handles recurring NPCs.
**Impact:** NPC-manager component existence, GM scope, cost budget.

## D-007 · Fact-extraction: post-hoc pass vs. GM-emitted structured block · Resolved · 2026-06-18
**Question:** How are declared facts lifted into structured commitments?
**Options:** (a) A structured-output extraction pass over the GM's free prose. (b) The GM emits a structured commitment block alongside its prose.
**Decision:** (b), realized through a hard cold/warm architectural split. The **cold GM (adjudicator)** emits structured commitments via the API's tool-use mechanism — never in prose. The **warm GM (narrator)** produces prose only, receiving just the player's filtered belief store. These are two separate agent personas (not a logical split within one call): the cold GM never produces player-facing text; the warm GM never commits facts. Tool calls go to the commit pipeline; text goes to the channel router for display. No extraction pass is needed because the cold GM has no prose channel to extract from.
**Current provider:** Claude's tool-use API. A provider-agnostic adapter layer is a named future goal (see D-017); other providers' function-calling mechanisms are equivalent in concept but differ in format.
**Residual risk:** The warm GM's prose may introduce incidental world-detail not explicitly committed by the cold GM (e.g. "the innkeeper limps slightly"). The auditor (phase 8) is the check against warm-prose canon contradiction. Non-compliant providers that unreliably honor tool-call instructions may require Option A (extraction) as a fallback — tracked under D-017.
**Relates to:** §7.2 (cold/warm split), §7.3 (commitment pipeline), D-008 (GM authority), D-017 (provider agnosticism), phase 5 (implementation target).
**Impact:** GM output contract (strictly split by persona), fact-extraction pipeline (no extraction pass for compliant providers), auditor, channel router.

## D-008 · Override authority · Resolved · 2026-06-18
**Question:** Who may invoke a deliberate override of committed state, and how is it surfaced and logged?
**Decision:** The **AI GM holds authoring and override authority** over world-state and consequence; the **human player is the co-authority and backstop** (final say, table-safety) and may also override. Every override remains an explicit logged `override` event with author and reason, which the auditor reads as intentional fiat (mechanism unchanged from phase 2).
The substance is *when*, not just *who*. Override is the **reserved exception**, not the working tool. The GM's authority is **latent**: in normal play it is exercised through the other two legal modes — Add by fiat and Change via causation (§6.2) — and through plot-bending (§7.4), so player choices meet friction, consequence, and adjacent hooks rather than veto. Overt override is reserved for genuine coherence-breaks and table-safety. Default stance is "yes-and / yes-but," and every "yes-but" must leave a **mechanical mark** in deterministic state (a clock ticks, a front advances, a Truth or Edge changes) so consequence is real, not narrated away.
**Rationale:** Delivers high felt agency with coherence held by latent structural authority. Most of what reads as "GM authority" is not the override path at all — it is Add + Causation — so the forbidden move (silent contradiction) is never approached in normal play. Aligns with §7.4 (agency sovereign over plot; never negate to protect a script) and principle 4 (honesty enforceable).
**Design intent → future criteria:** two properties should become testable success criteria (CORE §13) once the GM/plot phases make them measurable — (1) overt redirections trend toward ~zero per session (divergence absorbed via causation/re-bind, not veto); (2) every "yes-but" commits a mechanical consequence. Recorded here; added to §13 when measurable.
**Relates to:** §6.2 (legal modes), §7.4 (plot-manager), D-016 (the same latent-authority split at the structural level), the auditor (phase 8), D-007 (still open).
**Impact:** GM agent behavior/prompts, auditor, the override protocol (`COMPONENTS.md`), plot-manager.

## D-009 · Canon ledger: separate store vs. view over events · Resolved · 2026-06-18
**Question:** Is the canon ledger a distinct store, or a query over committed-and-disclosed events?
**Options:** (a) Separate materialized store. (b) A view over the event log.
**Decision:** (b). The canon ledger is a pure fold over the event log — no separate authoritative store. `canon_ledger()` is already implemented this way (phase 2). One source of truth by construction; no sync bugs possible.
**Performance escape hatch:** If the event log grows large enough that a full fold on every context-assembly beat becomes slow, the answer is a **lazy cache** — a per-POV snapshot invalidated on new relevant commits — not a separate store. The cache is a read-optimization derived from the log, never an authoritative writer. This is the same pattern D-001 recommends for belief stores.
**Rationale:** Consistent with D-001 (read-time projection, single source) and D-010 (proposals are not truth; only committed events are). We have made this call — one authoritative log, views derived on read — three times now. Deviating here for performance before a problem exists would be premature.
**Relates to:** D-001 (same pattern), D-007 (what gets committed into the log this ledger reads), D-010 (proposals excluded until committed).
**Impact:** Canon ledger (no separate store), fact-extraction pipeline, auditor, context assembly (cache layer if needed).

## D-010 · Proposal/action queue: transient buffer vs. events on the log · Resolved · 2026-06-17
**Question:** Where do agents' proposed actions live between proposal (beat-loop step 3) and commit (steps 6–9) — on the append-only event log, or in a separate buffer?
**Options:** (a) Uncommitted events on the event log, marked `proposed`. (b) A distinct transient, non-authoritative proposal buffer the mediator drains each beat.
**Decision:** (b). Proposals are candidates, not truth. Putting them on the authoritative log pollutes "the log is historical truth" and risks un-audienced proposals entering belief projections — an omniscience leak by the back door. A proposal becomes an event only once resolved and committed, at which point its audience is computed.
**Rationale:** Consistent with D-001/D-009's single-authoritative-source stance and with principles 1 (determinism boundary) and 2/3 (POV partitioning / blackboard).
**Impact:** Blackboard topology (CORE §4.3), beat loop (§5 steps 3/9), data model (§8), orchestrator, the `COMPONENTS.md` action-queue entry.

## D-011 · Disposition-delta recognition: deterministic rules vs. model-proposed · Resolved · 2026-06-19
**Question:** The disposition engine is the authoritative writer of event-linked deltas — but how is it decided *which* logged event triggers *which* delta on *which* axis?
**Options:** (a) A deterministic rule table over engine-legible events (redirected damage → +trust, etc.). (b) A model proposes deltas from ambiguous social/fictional cues, which the engine commits as event-linked changes. (c) Both, split by whether the trigger is mechanically legible.
**Decision:** Option (c) fully implemented across Phases 19 and 20.
- *Deterministic half (Phase 19):* `DispositionEngine._recognize()` fires on three commitment predicates — `"disposition_delta"` (explicit GM/beat-runner signal), `"stress_taken_for"` (+1 trust), `"triumph_for"` (+1 respect).
- *Model-proposed half (Phase 20):* `SocialInterpreter.analyze_event()` uses `propose_social_delta` and `propose_compel` tool calls. Validated deltas return as `DispositionDelta` objects with `causal_event_id` set; the caller applies them via `DispositionEngine.apply_delta()`. The engine remains the sole commit point in both paths.
**Impact:** Disposition engine, `SocialInterpreter`, context assembly, EV considerations (D-004).

## D-012 · Perception propagation fidelity · Open · 2026-06-18
**Question:** How rich should the perception model's sense-propagation be?
**Options:** (a) Thin zone-based — binary open/closed connections, whole-zone audibility, one-hop carry for loud sound, lit/dark line of sight, intra-zone closeness Truths for whisper. (b) Richer — multi-hop sound attenuation, partial occlusion, per-sense connection properties (a curtain blocks sight but not sound), positional gradients within a zone.
**Recommendation:** Start (a) — the model built in phase 3; it satisfies the whisper/noise/line-of-sight success scenarios (CORE §13). Promote toward (b) only where stress-testing shows the coarse model breaks a secrecy or spatial-consistency criterion. The plan flags perception for early stress-testing precisely because this is the load-bearing wall.
**Relates to:** D-002 (fiction-positional; propagation must stay non-metric), D-003 (map fog-of-war could raise the fidelity bar), the perception model and Scene/perception state.
**Impact:** Perception model, scene/perception state, world-state zone graph, every event audience.

## D-013 · Per-POV event ordering vs. global sequence exposure · Resolved · 2026-06-18
**Question:** `ProjectedEvent` exposed the event log's global monotonic `sequence`. A POV could therefore infer that events it is *not* party to occurred — and roughly how many — from the gaps in the sequence numbers it sees. That is a metadata side-channel against POV partitioning (CORE principle 2): a non-audience entity is supposed to see "nothing," but could detect hidden activity. Surfaced by the phase-3 perception stress pass.
**Options:** (a) Keep global `sequence`, accept the leak. (b) Project a per-POV *contiguous* index — ordering preserved, global count hidden. (c) Expose an opaque monotonic ordering token that sorts within a POV without revealing absolute position.
**Decision:** (b), implemented in phase 4. `EventLog.project_for` now sets `ProjectedEvent.sequence` to the event's position in *that POV's* projection (contiguous 0, 1, 2, …); the log's global sequence is unchanged and `id` remains the cross-POV identity. Ordering is preserved and no evidence of hidden events leaks. The phase-3 `xfail` regression test (`test_nonaudience_pov_cannot_infer_hidden_event_count`) is now a normal passing test.
**Rationale:** Cheapest correct fix; preserves ordering; leaks nothing. Resolved in context assembly because that is where projection semantics and belief-store ordering are the subject. Consistent with D-001 (single source, derived on read).
**Relates to:** D-001 (read-time projection), the phase-3 perception model (which surfaced it), phase 4 context assembly (where it was fixed).
**Impact:** `ProjectedEvent`, `event_log.project_for`, context assembly, every belief-store consumer.

## D-014 · Generative scene imagery · Superseded by D-038 · 2026-06-19
**Original question:** Should the interface generate an AI image at each major scene change?
**Superseded:** D-038 is the full image generation architecture spec. D-014's two load-bearing constraints survive intact into D-038: (1) prompt source must be the viewer's authorized belief store, never GM hidden state; (2) images are impressionistic narration — event log and world state always win if contradicted. Everything else in D-014 is absorbed and expanded by D-038.
**Relates to:** D-038 (full spec), CORE §12, channel router / interface.

## D-015 · Configurable seats: human/AI in any role, multi-participant · Open · 2026-06-18
**Question:** Should a session let the human assign which seats (GM, each teammate, NPCs) are human vs AI — including the human as GM with AI players, or several humans on one team with an AI GM?
**Why the architecture is friendly:** the blackboard topology (§4.3) and POV partitioning already make every seat just a POV (belief store) plus a proposal source; the determinism boundary is indifferent to whether a proposal came from a human client or a model agent. CORE §12 already commits that the architecture "must not preclude" multi-human.
**Options:** (a) Keep the fixed shape (one human player; AI GM + AI teammates). (b) Generalize to N seats, each human-or-AI, in any role, set by session config.
**Recommendation:** Target (b), but split the work. The cheap, high-leverage part is to model a role-agnostic **participant/seat** abstraction (POV + proposal source) when building character agents (phase 6) and the orchestrator (phase 7), so "human = the player, AI = everyone else" is never hardcoded and later unwound. Defer the heavy part — multi-client networking, per-seat identity/auth, concurrent-turn arbitration and sync — to the interface phase (11)+. Note: human-as-GM is a useful stress test of the honesty machinery — the deterministic core would hold a *human* GM to canon via the auditor exactly as it does an AI GM.
**Relates to:** CORE §12 (multi-human must-not-preclude), §4.3 blackboard, character agents (phase 6), orchestrator (phase 7), D-006 (NPC handling), interface (phase 11).
**Impact:** A participant/seat abstraction, orchestrator turn routing, the agent layer (agents become optional per seat), interface (multi-client), identity/auth.

## D-016 · Plot-graph ownership: single authority vs. distributed proposal · Resolved · 2026-06-18
**Question:** Who owns the plot graph — a single authority that holds and edits it, or shared persistent state that multiple agents read and propose revisions to, with something arbitrating coherence?
**Context:** Plot is held as a *loose structure* — fronts, factions, clocks, unresolved tensions (standing forces with momentum), not a fixed event sequence (§7.4; already the design). Plot **revision** is a first-class operation: promote a player thread into the standing structure, escalate a faction, retire a stale front, fold an accident into the throughline — but only above the canon line (hidden future is fluid; revealed past is immutable — §7.4 / §6.2 forbidden move). "Retroactively" therefore means re-*interpreting* and connecting, never changing what players were already told.
**Options:** (a) Single authority — the plot-manager holds and edits the plot alone. (b) Distributed proposal + centralized coherence-check — any agent may *propose* a plot revision; one authoritative writer commits it after a coherence-check.
**Recommendation:** (b), realized as the **disposition pattern (D-004 / §7.5) applied to plot**: the **plot-manager is the single authoritative writer**; other agents (GM, character agents, disposition engine) *propose* revisions through it; coherence is enforced by the **canon-ledger boundary** (the phase-2 consistency-check — plot may never contradict canon) plus the **auditor** (phase 8). This mirrors, at the structural level, the felt-agency / latent-authority split D-008 sets moment-to-moment (blackboard, §4.3: agents propose to a mediator, never write shared state directly).
**Risk to weigh:** the hard part is salience, not plumbing. The plot-manager must *evaluate* player input for promotion against an interest/salience threshold (the interest-signal accumulator), not promote everything — or the world bloats into incoherence (everything matters → nothing matters). The "obligation" is to evaluate and let the worthy rise, not to promote all input.
**Relates to:** §4.3 (blackboard), §7.4 (plot-manager), D-004 / §7.5 (the pattern being reused), D-006 (NPC proposal handling), D-008 (same principle, moment-to-moment), the auditor (phase 8). Build deferred to phase 9; ownership shape recorded now.
**Impact:** Plot-manager (sole writer), plot graph store, GM / character agents (propose), auditor (coherence gate), beat-loop divergence handling.

## D-017 · LLM provider strategy: Claude-first vs. provider-agnostic adapter · Resolved · 2026-06-19
**Question:** Should the system design against a single provider (Claude/Anthropic) or include a provider-agnostic LLM adapter layer?
**Options:** (a) Claude-first — build against the Anthropic SDK directly; defer abstraction. (b) Provider-agnostic from the start — define an adapter interface all agents call through, with Claude as the default implementation.
**Decision direction:** (a) for now. Design and build against Claude (Anthropic SDK, tool-use API) as the primary provider. A provider-agnostic adapter is a named future goal. When implemented, it must abstract: message sending, structured output (tool-call formats differ by provider), context window limits, and streaming behavior. The interface should also expose **suggested model defaults per agent role** (cold GM, warm GM, character agents, auditor, etc.) that the user can override — model selection is a user configuration concern, not a hardcoded choice.
**Timing update (2026-06-18, post-phase-7 review):** The "cheapest moment was phase 5" window has passed; phases 5–7 are built Claude-first. The next natural insertion point was before Phase 9 — this window has also now passed (phases 9–20 are built). The current insertion point is Phase 22 (beta hardening). `ModelGateway` IS the provider seam; all callers route through it. A full adapter interface (swappable provider, per-role model routing, structured-output normalization) is Phase 22 work. Do not build the adapter before Phase 22.

**Phase 22 priority note (2026-06-19):** Multi-model routing is **Phase 22 must-ship first**, not a medium-priority refactor. Without per-role model routing, the settings system's model slots (D-041) are cosmetic — all roles hit the same model at the same cost. A 4-seat session running every role on a premium model is unsustainable for any session of meaningful length. Routing unblocks: (1) adjudicator on a reliable structured-output model; (2) character agents and auditor on cheaper/faster models; (3) meaningful cost-per-role telemetry. The context budgeter (D-042) and lorebook v1 (D-043) should be built concurrently or immediately after, but routing comes first because it changes cost structure and thus determines whether D-042 budget policies are calibrated against realistic costs.
**Current coupling:** `AdjudicatorGM`, `NarratorGM`, `CharacterAgent`, `Auditor`, `SocialInterpreter` all receive `ModelGateway` and call `gw.call(role, model=..., ...)`. `ModelGateway.call()` forwards to `client.messages.create`. The seam is there; generalization is deferred.
**Hardest normalization problem:** The `AdjudicatorGM`'s correctness guarantee depends on Anthropic's forced tool-call mechanism. Not all providers offer this. Any adapter layer needs an explicit policy for providers that can't guarantee structured output — schema repair, retry loops, or validation fallbacks. This is the non-trivial part; don't assume provider APIs are interchangeable at this level.
**Relates to:** D-007 (tool-use mechanism is currently Claude-specific), D-005 (cost/latency budget), phases 9–11 (remaining agent construction).
**Impact:** All agent components, LLM call sites, model configuration, cost/latency budget.

## D-018 · Auditor failure policy: tiered failure handling · Resolved · 2026-06-18
**Question:** What happens when the Auditor finds a violation during the beat loop?
**Decision:** Tiered failure handling with three severity levels:
- **Critical** (mechanics integrity, secrecy boundary violation, canon contradiction of revealed facts, world-state integrity, persistence failure): abort the current beat; all uncommitted changes (narration event not yet written to the log) are not written; a blocking `audit_block` event is logged to the GM's audience only; `BeatResult` signals the abort. Note that declared facts committed at step 6 are already in the append-only log and are not rolled back — "uncommitted" means changes not yet written at the time the violation is detected. Correction via override is the recovery path.
- **Non-critical** (API timeout, schema validation failure, tool-call parse error, transient provider error): retry up to a configurable limit; on exhaustion, degrade gracefully (skip the failing check, log a `audit_warning` event to GM audience); play continues. No beat abort.
- **Advisory** (low-confidence semantic notes, stylistic observations, non-canon-threatening imprecisions): logged as `audit_advisory` events visible to GM only; play continues without interruption.
**Rationale:** Hard blocking on all violations would disrupt live play; never blocking would let critical errors accumulate silently. The tiered approach preserves integrity for the cases that matter (secrecy, canon, mechanics) while keeping the table running through model hiccups and subjective observations.
**Relates to:** §7.6 (auditor), D-008 (override as correction path), D-019 (semantic check severity), phase 8.
**Impact:** `auditor.py` (`AuditTier` enum, `AuditFlag`, `AuditResult`, `Auditor`), `BeatRunner` (step 7 integration, beat-abort path), `BeatResult` (`audit_flags`, `beat_aborted` fields).

## D-019 · Semantic consistency policy: advisory vs. blocking · Resolved · 2026-06-18
**Question:** Should the Auditor's semantic narration check block commits, or operate in an advisory capacity?
**Decision:** Semantic auditing is **enabled by default** and treated as **advisory** by default — semantic findings do not block commit. Exception: a semantic finding escalates to **critical/blocking** only when all three conditions hold simultaneously: (1) the model's confidence is very high, (2) the finding directly threatens revealed canon (a committed, player-visible fact), and (3) there is no logged transition, causation event, or override that would explain the change. Structural contradictions (canon ledger conflicts detected deterministically) remain unconditionally blocking regardless of this policy.
**Rationale:** Semantic checks using a model are inherently probabilistic. Blocking on every low-confidence finding would make the table fragile and the GM's job harder. Advisory-by-default with a high-confidence/revealed-canon escalation path gives the system teeth where it matters without becoming adversarial for normal creative prose. The GM always has the override path.
**Relates to:** §7.6 (auditor), D-018 (failure tiers), D-007 (narrator never receives hidden state, which limits the class of semantic contradictions possible), phase 8.
**Impact:** `auditor.py` (semantic check with confidence threshold and escalation logic), `BeatRunner` (post-narration semantic pass).

## D-020 · Phase 9 plot scope: runtime management vs. autonomous generation · Resolved · 2026-06-18
**Question:** Does Phase 9 include autonomous generation of a complete campaign plot graph from scratch?
**Decision:** Phase 9 **manages and advances a prepared, structured campaign graph during live play**. It does not generate one from scratch. The graph may be human-authored or AI-assisted during a setup/campaign-creation workflow, but that workflow is explicitly outside Phase 9 scope and belongs to a later, separate feature. Phase 9 assumes the graph exists on session open and focuses entirely on: divergence detection (a fixture was destroyed or blocked), fixture re-binding (function → new available fixture), thread promotion (high-interest unplanned threads promoted into standing structure), and interest signal accumulation during play.
**Rationale:** Autonomous campaign generation is a distinct creative problem with its own coherence requirements, EV considerations, and quality bar. Conflating it with runtime management would bloat Phase 9 and risk under-building both. Separating them keeps Phase 9 tractable and the campaign-creation workflow designable on its own terms.
**Relates to:** §7.4 (plot-manager), D-016 (plot-graph ownership, sole-writer pattern), phase 9.
**Impact:** `plot_graph.py` (accepts authored graph as input), `PlotManager` (runtime only), campaign-creation workflow (explicitly deferred).

## D-021 · Scene-mode companion gating: every-seat-every-turn vs. mode-driven activation · Resolved · 2026-06-18
**Question:** Should `run_round` activate every present AI companion every turn, or should the orchestrator gate companion calls based on the type of scene?
**Context:** The current `run_round` implementation gives every present seat a full beat (proposal → adjudication → narration). With one human player and two AI companions, a full round already costs ~8 model calls. In quiet exploration or dialogue scenes, most companion calls will produce low-value "I watch" proposals, burning budget for nothing useful. In combat, every seat genuinely needs a turn.
**Options:** (a) Every present seat, every round (current). (b) Explicit scene modes — the orchestrator uses deterministic triggers to decide which companions are invited to act on a given beat. (c) Agent bidding — companions signal intent and the orchestrator arbitrates (D-005 option (b); higher cost).
**Recommendation:** (b), building on the director-picks-next pattern already in D-005. Define a small set of scene modes (quiet, dialogue, tactical, combat, downtime, high-drama) and map them to companion activation rules — e.g. combat activates all present seats, quiet exploration activates at most one companion when a deterministic trigger fires (threat, relationship relevance, assigned role, player request, recent silence). Mode changes are deterministic state transitions, not model calls. Agent bidding (c) deferred until a cheap "should I act?" gate model exists and cost/latency budget is measured.
**Decision:** Option (b) implemented in Phase 16. `SceneMode` enum (quiet/dialogue/tactical/combat/downtime/high-drama) and `SceneCadence` class added to `orchestrator.py`. `BeatRunner.run_round` accepts an optional `scene_cadence` parameter; when present, AI companion seats are filtered through `SceneCadence.select_companions` (using `Orchestrator.sorted_by_spotlight` for least-recently-acted priority) before the round loop begins. Gated companions are removed from `remaining` and receive zero model calls. Human seats (those present in `player_proposals` but not in `agents`) are never gated. Always-active companions are always included first and count toward the mode limit. Mode transitions are pure state changes (no model calls). Agent bidding (c) remains deferred.
**Relates to:** D-005 (spotlight/bidding), the orchestrator (phase 7), character agents (phase 6), D-017 (cost/latency budget).
**Impact:** `orchestrator.py` (`SceneMode`, `SceneCadence`, `Orchestrator.sorted_by_spotlight`), `beat.py` (`run_round` `scene_cadence` param + filter logic). 46 tests in `tests/test_phase16_cadence.py`; 572 total.

## D-023 · Atomic event/state transactions · Resolved · 2026-06-18
**Question:** The SQLiteEventLog and SQLiteWorldState write to the same SQLite connection but in separate calls, creating a window where event-log and world-state can diverge on partial failure.
**Decision:** Use a shared-connection SQLite `BEGIN`/`COMMIT` per beat so all durable writes in one beat (event-log appends, world-state mutations, later plot-graph updates) land atomically or not at all. `SQLiteEventLog` will expose a `transaction()` context manager; `SQLiteWorldState` will participate via a shared deferred-commit flag on the connection, so intermediate `_save()` calls within the transaction suppress their own `commit()` until the context manager exits. If the beat aborts, the `ROLLBACK` covers both stores. In-memory `EventLog._events` is also snapshot-and-restored on rollback so the in-memory and SQLite states stay consistent.
**Implementation timing:** Phase 9 — deferred until Phase 9 adds the plot-graph SQLite table, at which point a three-way atomic write (event-log + world-state + plot-graph) makes the investment clearly worth the scope. Implementing it now against only two writers would require re-doing the work when plot-graph is added.
**Relates to:** `persistence.py` (`SQLiteEventLog`, `SQLiteWorldState`, `open_session`), Phase 9 (plot-graph persistence), D-009 (single source).
**Impact:** `persistence.py` (`transaction()` context manager, shared deferred-commit flag), `BeatRunner.run()` (wraps body in `log.transaction()` when log is a `SQLiteEventLog`), Phase 9 session DB schema.

## D-023 (formerly Open) · now Resolved — see above.

## D-024 · Epistemic commitment types · Resolved · 2026-06-18
**Question:** The current `SQLiteEventLog` and `SQLiteWorldState` write to the same SQLite connection but in separate calls. If the event-log write succeeds and the world-state update fails (or vice versa), the log and state diverge. Is this acceptable, or must every beat's durable writes be a single atomic transaction?
**Why it matters:** Divergence means the canonical "one source of truth" promise breaks at the persistence layer — a read after a partial failure would produce a world state inconsistent with its event history. This gets harder to fix as Phase 9 adds plot-graph state to the same session DB.
**Options:** (a) Accept the current split writes; treat divergence as a recovery concern (re-derive world state from event log on next open). (b) Wrap every beat's event-log append + world-state mutation in a single SQLite transaction using a shared connection + `BEGIN`/`COMMIT`, so either all durable changes land or none do. (c) Store world state as a materialized projection over the event log (no separate write at all) — the append is the only durable write; world state is derived on read.
**Recommendation:** (b) for Phase 9 while the session DB schema is still simple. Option (c) is architecturally cleanest and consistent with D-001/D-009 (read-time derivation), but derives world state on every read — acceptable only with the lazy-cache escape hatch from D-009. Record as open now; resolve at the start of Phase 9 before adding plot-graph writes.
**Relates to:** `persistence.py` (`SQLiteEventLog`, `SQLiteWorldState`, `open_session`), D-009 (event log as single source), D-001 (read-time projection), Phase 9 (adds plot-graph state to the session DB).
**Impact:** `persistence.py` (shared connection / transaction wrapping), `open_session`, potentially `WorldState` derivation model, Phase 9 DB schema.

## D-024 · Epistemic commitment types · Resolved · 2026-06-18
**Question:** Every `Commitment` object is currently treated as objective world state. An NPC claiming "the duke finances the cult" produces an identical data structure to the engine confirming "the door is open." Should commitments carry an epistemic type that distinguishes fact from claim, observation, belief, theory, and rumor?
**Why it matters:** Phase 9's plot manager must reason about what is established truth vs. what a faction believes vs. what a player suspects. Without epistemic typing, the plot manager cannot distinguish "the captain is a cultist" (objective sealed hidden fact) from "Mira suspects the captain" (a character belief) — both would look like canon entries. The belief store will also silently treat NPC assertions as confirmed world state, which feeds omniscience by the back door.
**Epistemic types under consideration:**
  - `fact` — objective committed world state (current behavior; engine-confirmed)
  - `observation` — a character perceived something (via the perception model)
  - `claim` — someone asserted or said something (NPC/player speech)
  - `belief` — a character currently believes something (may be wrong)
  - `theory` — a player or character suspects/infers something
  - `rumor` — unverified socially transmitted claim
  - `secret` — objective state not yet revealed (currently expressed via `revealed=False`)
**Decision:** Option (b) — `epistemic_type: str = "fact"` added to `Commitment` (backward-compatible; existing code defaults to `"fact"`). Valid types: `"fact"`, `"claim"`, `"observation"` (D-024); `"belief"` and `"theory"` deferred as derived annotations in the belief-store projection layer, not commitment schema types. `canon_ledger()` now filters to `revealed=True AND epistemic_type=="fact"` only. `CommitPipeline.check()` skips the consistency check for non-fact commitments — a claim can assert anything without violating the canon ledger. `committed_facts()` returns all types for inspection. `Fact` dataclass carries `epistemic_type` from its originating commitment. Persistence layer (`_commitment_from_dict`) round-trips the field.
**Implemented:** `events.py` (`EPISTEMIC_TYPES`, `Commitment.epistemic_type` field + validation + `to_dict`), `access.py` (`Fact.epistemic_type`, `committed_facts`, `canon_ledger`, `CommitPipeline.check`), `persistence.py` (`_commitment_from_dict`). 207 tests pass.
**Relates to:** `events.py` (`Commitment`), `access.py` (`canon_ledger`, `committed_facts`), Phase 9 (plot manager distinguishes sealed facts from claims/observations), the auditor (semantic check relevance of claims vs. facts), Phase 10 (disposition engine social tracks).
**Impact:** `Commitment` schema, `CommitPipeline.check`, `canon_ledger` filter, `Fact` dataclass, persistence round-trip, adjudicator (should set `epistemic_type="claim"` for NPC speech).

## D-025 · Effect executor and consequence palette · Resolved · 2026-06-18
**Question:** The beat loop currently produces a resolution band (Triumph / Success / Cost / Setback) but has no structured mechanism for translating that band into typed world-state operations. The adjudicator commits `declared_facts` (untyped `{subject, predicate, value}` triples) after the roll — which means (1) consequence types like clock advancement, stress, access creation, and condition changes are not distinct operations, and (2) the consequence palette (what *could* happen on a cost/setback) is not established before the roll.
**Two related sub-questions:**
  - **(A) Effect executor:** Should outcome operations be typed (`advance_clock`, `create_truth`, `change_truth`, `set_condition`, `apply_stress`, `apply_scar`, `change_resource`, `create_access`, `expire_truth`, `trigger_front`) rather than raw subject/predicate/value triples?
  - **(B) Consequence palette:** Should the adjudicator declare the plausible consequence space *before* the roll, rather than choosing consequences only after the band is known?
**Why they are linked:** A typed effect executor makes the consequence palette enforceable — the palette is a set of allowed typed operations; the post-roll outcome picks from it. Without typing, the palette is descriptive only and easily bypassed.
**Decision:** Option (c) — `ResolutionPlan` before the roll + `EffectExecutor` after. Design:
- **`ResolutionPlan`** (adjudicator output, pre-roll): fixes `skill`, `tn`, `action_domain` tag (feeds D-026 clock triggers), `exposure`, `declared_facts`, and a `consequence_palette` mapping each band (Cost, Setback) to a bounded list of typed operations. Triumph gets a separate `triumph_effects` list for extended-Effect operations. `ResolutionPlan` is validated against current world state at resolution time, not declaration time, to handle stale plans in multi-actor rounds.
- **Typed effect operations:** `advance_clock`, `apply_stress`, `apply_scar`, `change_resource`, `create_truth`, `change_truth`, `expire_truth`, `create_access`, `create_seam`, `move_entity`, `trigger_front`. The `EffectExecutor` validates each operation against current canon before applying; the narrator receives only the approved player-safe result.
- **Narrator receives:** band name + applied effect summaries (player-safe), never the raw consequence palette or adjudicator reasoning (consistent with B.18 fix).
**Implementation timing:** Phase 9 rules engine expansion. Incorporated as a Phase 9 deliverable.
**Relates to:** `gm.py` (`_ADJUDICATE_TOOL`, `StakesDecision`), `rules.py` (`RulesEngine`), `beat.py`, D-026 (`action_domain` is the clock-trigger signal), D-007.
**Impact:** `_ADJUDICATE_TOOL` schema (palette + domain fields), `StakesDecision` → `ResolutionPlan`, `RulesEngine` (EffectExecutor), `BeatRunner.run` (pre-roll plan step, executor step), narrator input.

## D-026 · Clock trigger and domain policy · Resolved · 2026-06-18
**Question:** `WorldSimulator.advance()` currently ticks every clock by its `step` on every call (once per beat). FABLE explicitly says not every clock advances every scene — time must meaningfully advance in that clock's domain. A guard-suspicion clock and a ritual-countdown clock should not both tick on every player action.
**Why it matters:** If all clocks advance every beat, pressure becomes arbitrary and preparation feels meaningless. A well-scoped clock is a promise to the table: "this threat moves when *this* kind of action happens." Blanket-per-beat advancement breaks that promise.
**Trigger types under consideration:** `beat` (every action beat, current behavior), `exchange` (every full round of the active seats), `scene_transition`, `breather`, `downtime`, `specific_event_type` (e.g. only when a `front_advance` or `dice_roll` with a specific tag occurs), `manual` (GM-only explicit advance).
**Options:** (a) Keep per-beat blanket advancement; rely on the adjudicator to vary step size. (b) Add a `trigger` field and a `domain` label to each clock; `WorldSimulator.advance(trigger)` advances only clocks whose trigger matches the current event type. (c) Replace `WorldSimulator.advance` with an event-listener model: clocks subscribe to event types and fire their own advancement rules when a matching event is appended.
**Decision:** Option (b). Clock schema gains: `domain` (label; informational, shown in GM context), `trigger_types` (set of trigger tags that advance this clock), `advance_policy` (`"per_trigger"` default, or `"per_exchange"` / `"manual"`), `landing_truth` (the Truth that becomes fact when the clock fills), `front_owner` (entity/faction notified by plot manager when fired), `active` (bool; inactive clocks never advance), `addressed_by` (set of entity IDs actively working against this clock). `WorldSimulator.advance(trigger)` receives a trigger tag from `BeatRunner`; only clocks whose `trigger_types` contains that tag advance. The trigger tag comes from `ResolutionPlan.action_domain` (D-025) so the two decisions are implemented together. `trigger` defaults to `"beat"` and clocks without `trigger_types` default to `{"beat"}` so existing tests pass unchanged.
**Implementation timing:** Phase 9 `WorldSimulator` expansion. Incorporated as a Phase 9 deliverable alongside D-025.
**Relates to:** `gm.py` (`WorldSimulator`), `world_state.py` (clock schema), `beat.py`, D-025 (`action_domain` is the trigger signal), Phase 9 (front-firing, plot-manager clock integration).
**Impact:** `WorldSimulator.advance(trigger)` signature, clock schema (new fields), `BeatRunner.run` (passes trigger from `ResolutionPlan`), `run_round` (exchange-level trigger tag).

## D-022 · Operational telemetry: separate store vs. event log · Resolved · 2026-06-18
**Question:** Where does operational telemetry live — provider, model, role, input/output/cached tokens, cost, latency, retry count, schema-validation result, whether a response was accepted/repaired/discarded?
**Why it cannot go in the event log:** The event log feeds belief projections. Telemetry that enters the log would flow into every agent's context. It is operational data, not fiction, and must be completely invisible to all model roles.
**Options:** (a) In-process metrics object (simple dict/dataclass, reset per session). (b) Separate SQLite table in the same session DB, written alongside but never read by `project_for` or `CommitPipeline`. (c) External observability sink (structured log file, Prometheus, etc.).
**Decision (Phase 14):** Option (a) for now — `TelemetrySink` is a plain in-process list of `CallRecord` dataclasses, accumulated by `ModelGateway.call()`. It starts clean each session. The isolation contract is structural: `TelemetrySink` has no reference to `EventLog`, `CommitPipeline`, or `ContextAssembler`. Option (b) (SQLite persistence) remains available as a zero-coupling upgrade — add a second writer that INSERT-only into a separate `telemetry` table with no join to the event or world-state tables. Option (c) can layer on top. The critical constraint is met: `project_for`, `CommitPipeline`, and `ContextAssembler` have zero access path to telemetry.
**Files changed:** `provider.py` (new: `ModelGateway`, `TelemetrySink`, `CallRecord`); `gm.py`, `character_agent.py`, `auditor.py` (callers accept `ModelGateway`); `__init__.py` (exports). 26 new tests in `tests/test_phase14_gateway.py`.
**Relates to:** D-017 (provider adapter — still open), the event log (must not receive it), context assembly (must not see it).

## D-033 · Audience preservation delivery contract · Resolved · 2026-06-18
**Question:** Channel and target from a Proposal were discarded in `run_with_agent()` before reaching `run()`. The narration event at step 9 was always emitted as `channel="public"` to all world entities — a secrecy-boundary failure: whisper proposals produced public narration.
**Decision:** `DeliveryScope` (frozen dataclass) is computed once in `run()` from `channel` and `target`, validated by `_resolve_delivery()`, and threaded into the step-9 `log.append()` call. No downstream component may reconstruct or widen the audience. OOC actions bypass all fiction at beat entry (no adjudicator, no narrator, no commits, no clock tick). Whisper target is validated against `world.entities` at scope-resolution time, before any model call. Narrator context for public beats is filtered to public-channel events only (`_narrator_context(store, "public")`), preventing actor-private events from flowing into prose that all present participants see.
**Root cause:** `run_with_agent()` extracted only `proposal.intent` into a plain string; `run()` accepted only `(actor, action: str)`; step 9 hardcoded `channel="public"` and `audience=list(world.entities) + [gm]`.
**Files changed:** `beat.py` (`DeliveryScope`, `_resolve_delivery`, `_narrator_context`, `run()` signature, `run_with_agent`, `run_round`), `__init__.py` (exports `DeliveryScope`).
**Tests added:** `tests/test_audience_preservation.py` — 28 tests covering invariants 1–8 from e.md §1.
**Relates to:** D-010 (proposals carry channel/target through the buffer), D-001 (belief-store projection — non-audience entities receive nothing), D-007 (narrator receives only delivery-safe context), D-027 (action lifecycle — OOC bypass is the Cancelled exit for out-of-character beats), D-028 (whispers are the enforcement point for knowledge-sharing).
**Impact:** `beat.py` (all three run methods), `__init__.py`; no change to event schema, access, or persistence layers.

---

## D-027 · Action lifecycle states · Resolved · 2026-06-19
**Question:** Should actions carry explicit named backend-owned lifecycle states, or is implicit per-beat processing sufficient?
**Decision:** Option (b) — explicit backend-owned states. The backend owns all state transitions. The client displays only; it never infers or advances lifecycle state from event content, timing, or client-side logic.

**State set:**
```
draft → submitted → validating → pending_player_choice → adjudicating → rolling
     → applying_effects → auditing → narrating → committed
     (exits: cancelled · aborted · failed)
```

- `pending_player_choice` — the load-bearing interactive state: Trade selection (Aggressive/Measured/Guarded), compel accept/refuse, any mid-beat choice requiring player input. Client must block the composer and show the choice UI. Backend waits for the player's selection before advancing.
- `validating` and `auditing` are both backend-internal; the client may collapse them to a single "processing" indicator, but keeping them distinct backend-side is required because the auditor can abort at `auditing` where the validator does not.
- `cancelled` — action withdrawn by the actor before `committed` (was `submitted` or `pending_player_choice`). Not a D-031 correction.
- `aborted` — beat-loop abort (post-audit block, D-018 CRITICAL tier). Committed facts at step 6 persist; narration does not.
- `failed` — non-recoverable infrastructure failure (e.g. `ModelCallError` exhausted retries) after steps that are unrollable.

**Client contract:** A fictional event is not shown as committed until the backend emits a `committed` state transition. No client-side optimistic commit. The backend echoes the pre-roll composer state on any `cancelled` or `aborted` exit so the composer can reset cleanly.

**Relates to:** D-010 (proposal buffer), D-028 (withdrawal before `committed` is `cancelled`, not D-031), D-031 (correction applies only after `committed`), orchestrator (phase 7), channel router (display gated on state), Phase 21.
**Impact:** `ActionLifecycleState` enum on `Proposal`/action object; beat-loop step ordering; channel router; orchestrator; client composer gating.

---

## D-028 · Knowledge-sharing transfer mechanisms · Resolved · 2026-06-19
**Question:** How does knowledge transfer between characters, and how does the client handle it?
**Decision:** Knowledge moves only through logged, authorized events. There is no automatic merge and no client-side fact transfer between views. The client is a renderer — it displays the belief store the backend sends for each POV; it never synthesizes or promotes facts from another character's view.

**Authorized transfer mechanisms** (each produces a logged event):
- `channel="whisper"` speech (overheardable per the perception model)
- `channel="public"` speech (present-scene audience)
- `share_briefing` action event (explicit deliberate knowledge transfer — e.g. "Mira tells the group what she saw")
- `object_shown` event (a physical object or document shown to specific audience)
- `observed_action` (the acting character performs something visible — perception model generates `may_have_perceived`)
- Perception-derived overhear (`may_have_perceived` from `derive_overhears`)

**Epistemic constraint (mandatory):** All knowledge transferred via any of the above enters the receiver's belief store as `epistemic_type="claim"` from the sharing character. Never `"fact"`. Confirming a claim to `"fact"` requires independent engine-confirmed evidence. The warm GM may narrate a catch-up scene during downtime/breather transitions, but the mechanical transfer is still an explicit event — the narration does not bypass the log.

**Client contract:** The client never transfers facts between POV views. Each character's authorized belief store is the only source for that character's display. Cross-POV information reaches a viewer only when the backend has committed a transfer event to that viewer's audience.

**Relates to:** D-001 (POV partitioning), D-024 (claim vs fact epistemic type), D-007 (warm GM narrates but does not auto-promote), D-029 (roll results follow same claim mechanism), perception model (phase 3), D-032 (claim displays as "Claimed" label, not "Confirmed"), Phase 21.
**Impact:** `share_briefing` and `object_shown` event types added to event schema; channel router routes each to correct audience with `epistemic_type="claim"`; client renders claims distinctly (D-032).

---

## D-029 · Roll visibility and secret-check policy · Resolved · 2026-06-19
**Question:** Who sees what parts of a dice event?
**Decision:** Roll visibility is a `visibility` field on the `dice_roll` event, using the same event audience / `project_for` mechanism as all other events. No separate policy.

**Visibility values:**
- `table` — all present-scene participants see full roll details (skill, pool, dice[], result, TN, band). Default for player-initiated rolls.
- `roller_only` — only the acting character (and GM) sees mechanical details; others see only any observable fiction the warm GM narrates.
- `gm_only` — cold GM sees the result; warm GM and all players see nothing from the mechanical roll. Default for GM passive/secret checks. The observable consequence (if any) reaches players only through narrated fiction, not the roll event.
- `revealed` — transition state: was `gm_only`, GM has explicitly surfaced it. The `revealed` transition is a structural event that the backend emits; the client does not infer it from narration.

**Auditor contract:** A `gm_only` outcome that the warm GM withholds is not a narration contradiction. The auditor must not flag this case. The warm GM must not receive `gm_only` roll events in its context (D-007 cold/warm split enforced).

**Client contract:** The client renders full roll details only for events where `visibility` is `table` or `revealed` and the player is in the event audience. For `roller_only`, the player sees details only for their own character's rolls. `gm_only` events are never in any player's projection.

**Relates to:** D-013 (per-POV projection applies here), D-007 (warm GM never receives `gm_only` results), D-019 (auditor does not flag withheld `gm_only` outcomes), Phase 21 render contract.
**Impact:** `dice_roll` event schema (`visibility` field, default `table`); `project_for` filters by audience; cold GM context includes `gm_only`; player belief store receives only `table`/`roller_only` (if roller) / `revealed`.

---

## D-030 · Fictional time model and time-advance triggers · Resolved · 2026-06-19
**Question:** How does the engine track narrative time, and how does the client learn the current time context?
**Decision:** Minimal backend-owned time anchor. No calendar simulation in Phase 21. API latency and player typing speed never advance fictional time — only explicit backend events do.

**Time anchor fields** (backend-owned; carried in session state and emitted on `scene_transition` structural events):
- `scene_id` — UUID, changes on each backend-declared scene transition. This is the "major scene transition" trigger for D-038 image generation — backend-declared, never client-inferred.
- `beat_index` — monotonic integer within the current scene; resets to 0 on scene transition.
- `scene_phase` — current `SceneMode` from Phase 16 (quiet/dialogue/tactical/combat/downtime/high-drama). Reuses the existing enum; no new type required.
- `prose_time_label` — optional GM-authored string ("morning of the third day"); aesthetic only, no mechanical weight.
- `elapsed_category` — one of: BEAT, EXCHANGE, SCENE, TRAVEL, BREATHER, DOWNTIME. Maps to D-026 clock `trigger_types`. Set by the backend on `scene_transition`; used by `BeatRunner` to tag clock advancement.

**`scene_transition` structural event:** `type="scene_transition"`, `author="rules-engine"`. Carries `scene_id`, `scene_phase`, `elapsed_category`, optional `prose_time_label`. Audience: GM + plot-manager + orchestrator. Not fiction; not narrated prose. The plot-manager and spotlight controller respond to this event deterministically.

**Client contract:** The client never declares a scene transition. It reads `scene_id` from the backend event stream. If `scene_id` changes, the client updates its display state (scene header, imagery trigger). The client does not infer a scene boundary from event content, timing, or roll results.

**Relates to:** D-026 (SCENE/BREATHER/EXCHANGE as valid `elapsed_category` values → clock `trigger_types`), D-016 (plot-manager listens for `scene_transition`), D-021 (`scene_phase` is the existing `SceneMode`), D-038 (`scene_id` change is the image generation trigger), Phase 21.
**Impact:** `scene_transition` event type; `WorldState` carries `scene_id`, `beat_index`, `scene_phase`, `prose_time_label`; `BeatRunner` passes `elapsed_category` to `WorldSimulator.advance()`; plot-manager and orchestrator listen for `scene_transition`; client reads `scene_id`.

---

## D-031 · Retcon, correction, and session-fork policy · Resolved · 2026-06-19
**Question:** How are committed errors and agreed narrative revisions handled without breaking the append-only log?
**Decision:** Corrections are explicit logged events. History is never silently rewritten. The render layer marks corrected/superseded entries; it does not omit them.

**Situation handling:**

| Situation | Mechanism |
| --- | --- |
| Unsubmitted draft | Edit freely — no log entry, no policy |
| Submitted, unresolved action | D-027 `cancelled` state — not a D-031 correction |
| Committed typo / mechanical error | Append `correction` event; `derived_from` references the corrected event ID |
| Agreed narrative revision (table consensus) | Append `retcon` event; `derived_from` references affected events; `authorized_by` must include the human player |
| GM-only revision without player concurrence | D-008 override path — not a retcon |
| Major branch / timeline fork | Deferred beyond Phase 21 |

**Append-only invariant:** `correction` and `retcon` events are additions to the log. Nothing is deleted, edited in place, or hidden. The original event remains in the log with its original content.

**Render contract:** `render_event()` must handle `correction` and `retcon` events. When rendering a corrected/retconned event, emit a superseded marker (e.g. a ~~strikethrough~~ indicator or explicit label). Do not silently omit corrected entries from the transcript. The D-032 label `Corrected/Superseded` maps to this state.

**Auditor contract:** The auditor does not re-flag an event that has a `correction` or `retcon` event in its `derived_from` chain. The correction is the resolution; re-flagging would be noise.

**`retcon` authorization:** A retcon must carry `authorized_by` including the human player's entity ID (D-008 backstop). A GM-only revision without player concurrence is logged as an `override` event, not a `retcon`.

**Relates to:** D-008 (override vs retcon distinction), D-027 (unresolved actions use `cancelled`, not correction), D-018 (auditor ignores corrected events), D-032 (corrected entries display as `Corrected/Superseded`), Phase 21 render contract.
**Impact:** `correction` and `retcon` event types added to schema; `render_event()` emits superseded marker; auditor skips re-flagging of corrected events; `authorized_by` field on `retcon` events.

---

## D-032 · Epistemic certainty in player-facing presentation · Resolved · 2026-06-19
**Question:** How are epistemic distinctions (fact vs. claim vs. observation vs. theory) surfaced in player-facing views?
**Decision:** Option (c) — structured labels in tracking views (backend-emitted) plus a narration contract for the warm GM. The client displays labels; it never computes epistemic certainty from content.

**Six player-facing certainty labels** (backend-emitted alongside the commitment):

| Label | Source | `epistemic_type` |
| --- | --- | --- |
| `Confirmed` | Engine-committed world state | `"fact"` |
| `Claimed` | NPC/character assertion; knowledge shared via D-028 mechanisms | `"claim"` |
| `Observed` | Character perceived via perception model | `"observation"` |
| `Suspected` | Character inference or theory (see below) | `"theory"` |
| `Unknown` | GM-annotated Case File template slot with no evidence yet (see below) | — |
| `Corrected/Superseded` | Entry has a `correction` or `retcon` event in the log | D-031 |

**`"theory"` epistemic type:** Added as a valid `epistemic_type` value in Phase 21 (D-024 deferred it as a future annotation; it is now scheduled). A character inference or explicit suspicion is committed with `epistemic_type="theory"`. Not automatically promoted to `"fact"` without independent engine evidence.

**`Unknown` sourcing rule:** "Unknown" is not a client inference from the absence of evidence — that path is an omniscience leak (absence of evidence in the client view could itself be information). "Unknown" comes only from a GM-annotated Case File template slot — a structural event marking that a named placeholder has no current evidence. The client renders it only when the backend has explicitly emitted the unknown marker.

**Narration contract (warm GM):** Confirmed facts → declarative voice ("The door is locked."). Claims → attribute the speaker ("Sera claims the key opens it."). Observations → perceptual hedges ("The door appears locked."). Theories → express character inference ("Veil suspects the lock is trapped."). The auditor flags narration of a `"claim"` in declarative confirmed-fact voice as an advisory semantic finding (D-019).

**Client contract:** The client renders the label the backend emits. It does not flatten claims or observations into `Confirmed`. It does not infer epistemic status from prose voice or the absence of a commitment.

**Case File annotation:** Case File categories (Known Truths, Clues, Open Questions, Promises & Debts, etc.) are a separate field from `epistemic_type`; both coexist on the same commitment. The backend annotates both; the client renders both.

**Relates to:** D-024 (`epistemic_type` data model; `"theory"` added in Phase 21), D-007 (warm GM narration contract), D-019 (auditor advisory flag for epistemic mismatch), D-028 (transferred knowledge is `"claim"`), D-031 (`Corrected/Superseded` label), D-038 (image prompts use facts + observations only, not claims or theories), Phase 21.
**Impact:** `"theory"` added to `EPISTEMIC_TYPES`; backend emits certainty label alongside commitments; Case File schema carries both label and category; warm GM prompt includes phrasing guide; auditor flags claim-as-fact in advisory tier.

---

## MVP Implementation Defaults

These are implementation defaults used until a decision is formally resolved. They are not final design resolutions unless moved into `Resolved` with an updated decision record.

- **D-001:** *Resolved* — read-time projection + optional cache; no per-agent write-time materialization.
- **D-002:** *Resolved* — fiction-positional: position as Truths within the zone graph, no grid and no formal band system. Proximity is qualitative, feeding Ledger Position / Ground.
- **D-003:** Treat routine positioning queries as free OOC clarification for MVP; later support IC assessment for exploration-heavy scenes.
- **D-004:** *Resolved* — couple disposition through Edge/Bonds, never a passive modifier and never a separate currency. Defer building it to phase 10, after the rules engine's Edge/Bond/compel surfaces and the EV audit exist.
- **D-005:** Start with director-picks-next spotlight. Prototype agent bidding only after a cost/latency budget exists.
- **D-006:** Let the GM puppet walk-on NPCs for MVP; promote recurring NPCs later.
- **D-007:** *Resolved* — hard cold/warm split: cold GM commits via tool use (no prose); warm GM narrates via text only (no commits). No extraction pass. Implementation target: phase 5. Provider: Claude for now (see D-017).
- **D-008:** *Resolved* — AI GM holds override authority, human is co-authority/backstop; override is the reserved exception, normal authority exercised via Add/Causation and plot-bending. Mechanism (logged override + reason) built in phase 2.
- **D-009:** *Resolved* — canon ledger is a pure fold over the event log; no separate store. Lazy per-POV cache is the approved performance escape hatch if needed; it is never an authoritative writer.
- **D-012:** Thin zone-based propagation — binary open/closed connections, whole-zone audibility, one-hop loud carry, lit/dark line of sight, closeness Truths for whisper. *(Built in phase 3; stress-tested. Overhears degrade to a vague hint (fail-safe under-disclosure); richer attenuation/occlusion and "fully overheard content" deferred.)*
- **D-013:** *Resolved* — per-POV contiguous index in `project_for` (option (b)); the global-`sequence` side-channel is closed.
- **D-027:** *Resolved* — backend-owned lifecycle state machine; client reads state, never writes it. See D-027 for full state table.
- **D-028:** *Resolved* — all transferred knowledge enters as `"claim"`; client never transfers facts; knowledge moves only through logged authorized events.
- **D-029:** *Resolved* — four roll-visibility values (`table`, `roller_only`, `gm_only`, `revealed`); `gm_only` never reaches client or warm GM unless revealed.
- **D-030:** *Resolved* — minimal time anchor: `scene_id` + `beat_index` + `scene_phase` + `prose_time_label` + `elapsed_category`; `scene_transition` event on `scene_id` change; client is receiver only.
- **D-031:** *Resolved* — `correction` and `retcon` event types; log remains append-only; `retcon` requires human player authorization.
- **D-032:** *Resolved* — six backend-emitted certainty labels; client renders only; `"theory"` epistemic type added in Phase 21; `Unknown` from GM template slots only.

---

## Resolved

- **D-002** · Spatial model → fiction-positional (position as Truths in the zone graph; no grid, no formal band system) · 2026-06-17.
- **D-004** · Disposition→mechanics coupling → through FABLE's native Edge/Bonds; no passive modifier, no separate "Strings" currency · 2026-06-17.
- **D-010** · Proposal/action queue → transient, non-authoritative buffer (not events on the log) · 2026-06-17.
- **D-013** · Per-POV event ordering → per-POV contiguous index in `project_for`; global-`sequence` side-channel closed · 2026-06-18.
- **D-001** · Belief store → read-time projection + optional cache; no write-time fan-out · 2026-06-18.
- **D-007** · Fact-extraction → hard cold/warm split; cold GM uses tool-use for structured commits, warm GM produces prose only; no extraction pass · 2026-06-18.
- **D-009** · Canon ledger → pure fold over event log; lazy per-POV cache approved as performance escape hatch, never an authoritative writer · 2026-06-18.
- **D-008** · Override authority → AI GM holds it (human co-authority/backstop); override is the reserved exception, authority normally latent via Add/Causation + plot-bending · 2026-06-18.
- **D-018** · Auditor failure policy → tiered (CRITICAL/NON_CRITICAL/ADVISORY) · 2026-06-18.
- **D-019** · Semantic consistency policy → advisory by default; escalates to CRITICAL at high confidence + revealed canon + no logged transition/override · 2026-06-18.
- **D-020** · Phase 9 plot scope → runtime management only; autonomous generation is out of Phase 9 scope · 2026-06-18.
- **D-023** · Atomic transactions → shared-connection SQLite BEGIN/COMMIT per beat; implement in Phase 9 when plot-graph adds a third writer · 2026-06-18.
- **D-024** · Epistemic commitment types → `epistemic_type` field on `Commitment` ("fact"/"claim"/"observation"); only facts enter canon ledger; implemented · 2026-06-18.
- **D-025** · Effect executor + consequence palette → `ResolutionPlan` pre-roll + typed `EffectExecutor` post-roll; Phase 9 deliverable alongside D-026 · 2026-06-18.
- **D-026** · Clock trigger policy → clock schema gains domain/trigger_types/advance_policy/landing_truth/front_owner/active/addressed_by; `WorldSimulator.advance(trigger)` advances only matching clocks; Phase 9 deliverable · 2026-06-18.
- **D-016** · Plot-graph ownership → PlotManager is the sole authoritative writer; other agents propose revisions through it; coherence enforced by canon-ledger boundary; implemented in Phase 9 · 2026-06-18.
- **D-023** (implemented) · `SQLiteEventLog.transaction()` context manager; shared `_tx_active` flag; in-memory snapshot-and-restore on rollback; WorldState reloads from rolled-back DB via back-reference wired in `open_session` · 2026-06-18.
- **D-026** (implemented) · `WorldSimulator.advance(trigger="beat")`; clocks filtered by `trigger_types`/`active`; clocks without `trigger_types` default to `{"beat"}` · 2026-06-18.
- **D-022** · Operational telemetry → in-process `TelemetrySink` (option a); zero coupling to fictional state; `ModelGateway` is the sole writer; SQLite persistence (option b) available as a drop-in upgrade; implemented Phase 14 · 2026-06-18.
- **D-037** · Multi-effect palette atomicity → option (b): explicit `atomic_group` on dependent effects; independence is the default; whole-palette atomicity (c) rejected as too coarse. Implementation deferred to Phase 22 (property tests). `schemas/campaign.schema.json` reserves `atomic_group` for palette effect specs · 2026-06-18.
- **D-011** (fully resolved) · Disposition-delta recognition → deterministic rule table (Phase 19) + model-proposed `SocialInterpreter` (Phase 20); engine remains sole commit point; `resolve_compel()` always applies `GainEdge(1)` on accept · 2026-06-19.
- **D-033** · Audience preservation → delivery contract: audience field is set once at event creation and never mutated; `render_event()` refuses to filter; routers enforce diff; full 28-test suite · 2026-06-18.
- **D-021** · Scene-mode companion gating → `SceneCadence.select_companions()` with always-active + spotlight priority; gated companion = zero model calls · 2026-06-18.
- **D-027** · Action lifecycle states → backend-owned state machine: `draft → submitted → validating → pending_player_choice → adjudicating → rolling → applying_effects → auditing → narrating → committed`; exits: `cancelled / aborted / failed`; client reads state, never writes it · 2026-06-19.
- **D-028** · Knowledge transfer mechanisms → knowledge moves only through logged authorized events (whisper, public statement, share/briefing, shown object, observed action, perception-derived overhear); all transferred knowledge enters as `epistemic_type="claim"`, never `"fact"`; client never transfers facts between views · 2026-06-19.
- **D-029** · Roll visibility → four values: `table` (default player roll), `roller_only`, `gm_only` (default GM/NPC roll), `revealed`; warm GM never receives `gm_only`; client never receives `gm_only` unless explicitly `revealed` · 2026-06-19.
- **D-030** · Fictional time model → minimal backend time anchor: `scene_id` (UUID), `beat_index`, `scene_phase` (= `SceneMode`), `prose_time_label`, `elapsed_category`; `scene_transition` structural event on `scene_id` change; client never declares scene transitions · 2026-06-19.
- **D-031** · Retcon/correction policy → `correction` and `retcon` event types; append-only log preserved; `render_event()` emits superseded markers; `retcon` requires human player in `authorized_by` · 2026-06-19.
- **D-032** · Epistemic labels → six player-facing labels: `Confirmed` (fact), `Claimed` (claim), `Observed` (observation), `Suspected` (theory, added Phase 21), `Unknown` (GM-annotated template slot only), `Corrected/Superseded` (D-031 event); backend emits label; client never computes it; warm GM phrasing contract enforced · 2026-06-19.
- **D-039** · Voice/TTS → manual click-to-play; off by default; per-speaker voice IDs in `settings/voice.json`; API key in env only; cached per event-id+voice-id hash; post-Phase-21 track; no game-state coupling · 2026-06-19.
- **D-040** · Campaign generation pipeline → `CampaignCompiler` → validation → repair/retry → `CampaignPackage`; raw input never in GM context; both auto-generate and from-prompt paths; deferred to Campaign-Authoring Studio post-v1; Phase 21 loads pre-built packages only · 2026-06-19.
- **D-041** · Settings system → layered JSON (code defaults → `settings/models.json` → `settings/campaigns/{campaign_id}.json`); GUI shows campaign-aware character agent slots derived from roster; all essential models have defaults; API keys in env only (never in files); per-setting Reset button; file path shown with open-in-editor button · 2026-06-19.
- **D-017** · LLM provider strategy → `ProviderAdapter` ABC + `AnthropicAdapter` in `provider.py`; per-role model resolution in `ModelGateway._resolve_model()` (settings → kwarg → registry default); `ToolOutputError` for malformed tool responses; `AdjudicatorGM` 2-attempt retry; `BeatRunner` aborts cleanly on `ToolOutputError`. Anthropic-only for now; adapter interface enables future providers · 2026-06-19.
- **D-042** · Context budget management → `budgeter.py`: `ContextBudgetPolicy`, `ContextBudgeter`, `TokenEstimator`, `BudgetCheckResult`; per-role defaults (6 roles); `from_settings` classmethod; event windows wired into `BeatRunner._events_summary` / `_narrator_context` calls and `CharacterAgent.propose()`; `CostCeilingStatus` + `TelemetrySink.ceiling_status()` for per-session cost ceiling (advisory-only default). `SettingsRegistry.DEFAULTS` expanded with 12 budget keys. `CONTEXT_EVENT_WINDOW` kept as backward-compat fallback · 2026-06-19.
- **D-043** · Lorebook v1 → `lorebook.py`: `LoreEntry` (frozen; `audience_permits()`), `LoreDeck` (audience-gated collection), `LoreAssembler` (keyword match against entitled corpus; `max_entries`; `lore_context_block()`). Audience gate fires before keyword match — `gm_only` entries never injected into player context regardless of corpus content (constraint 4). `ContextAssembler.lore_for()` opt-in. `CampaignPackage.lore_entries` + `lore_deck()`. `lorebook_injection_window` setting. Option A (keyword match); (B)/(C) deferred · 2026-06-19.

**Open — Phase 22:**
- (all D-017, D-042, D-043 items resolved; remaining Phase 22 work is golden transcripts, replay/fuzz tests, property tests for `EffectExecutor` atomic groups (D-037), save-format migration, security review)

**Open — deferred / ongoing:**
- **D-003** · Positioning queries → free OOC clarification for MVP; IC assessment for exploration-heavy scenes later.
- **D-005** · Spotlight → director-picks-next for now; agent bidding after cost/latency budget exists.
- **D-006** · NPC management → GM puppets walk-ons; manager/promotion for recurring NPCs.
- **D-012** · Perception fidelity → thin zone-based model built; richer propagation deferred.
- **D-034** · Opening model → extend `MaintainedTruth` with optional `group`/`effect_text` (recommendation A).
- **D-038** · Image generation → post-Phase-21; full spec in decision body. Portrait policy decided: generate once, store artifact, never auto-regenerate per scene.

## D-035 · Beat step-5 pre-transaction event design · Settled · 2026-06-18
**Question:** `BeatRunner.run()` calls `resolve_check()` at step 5 before entering `with self._log.transaction():` at step 6. Dice-roll and resolution events are therefore committed outside the beat transaction and cannot be rolled back if the post-narration audit blocks the beat. Is this a gap or an intentional design choice?
**Decision:** Intentional. Dice and resolution events at step 5 represent a mechanical outcome that has already occurred — the dice were rolled, the TN was compared, a band was established. These are "attempted action" records, not fiction. Rolling back a dice event would claim the roll never happened, which is incorrect. When a post-narration audit blocks a beat: the step-6 fact commits and step-9 narration event are rolled back (they are fiction that flows from the resolution); the step-5 dice and resolution events remain (they are mechanical truth that the roll occurred). The aborted beat's `BeatResult` carries `beat_aborted=True` so callers know the fiction did not commit, even though the mechanical record did.
**Not a gap:** If the dice roll was rolled and resolved, the mechanical record should persist. What aborts is the fictional consequence, not the physical fact of the roll.
**Relates to:** D-023 (beat transaction scope), `BeatRunner.run()` step-5 vs. step-6 ordering, Phase 22 (replay tests should account for orphaned dice events in aborted beats).
**Impact:** No code change. Document here to prevent future refactors from moving `resolve_check()` inside the transaction without reconsidering the intent.

---

## D-038 · Image generation architecture · Open · 2026-06-19

**Scope:** Post-Phase-21 rendering layer. No implementation before Phase 22 or explicit instruction.

**Decided constraints (all non-negotiable):**

1. **Non-authority.** Images are presentation only. `ImageArtifact.non_authoritative = True` on every record. If an image contradicts the event log or world state, the event log and world state win. Regeneration never changes game state.

2. **Prompt source.** `ImagePromptAssembler` builds prompts exclusively from the viewer's authorized belief store / render projection — committed `epistemic_type="fact"` entries and entitled world state only. Forbidden prompt sources: hidden plot graph, unaudienced events, whispers not in audience, secret identities, private NPC interiors, GM adjudicator output, unrevealed map locations. Same fog-of-war constraint as belief stores. Principle 2 (POV partitioning) applies fully.

3. **Style separation.** Subject/context prompt and style instructions are separate strings throughout; they are concatenated only at the final API call. Style instructions come from the style profile (a user-editable config file), never from game state and never invented by code or prompts. Style instructions are aesthetic direction only — they must not contain character names, location names, or any game-state facts.

4. **Style profile.** Stored at `settings/style_profile.json` (or equivalent config location — format TBD). One required field: `style_instructions: str`. Optional: `version: str` for artifact provenance. The project owner supplies and edits this manually. The engine never generates or modifies it. Editable without code changes.

5. **Map invariant.** Generated images are used only for aesthetics on maps. Known locations, labels, routes, current entity position, fog of war, and unrevealed areas must come from deterministic FABLE state and be rendered/overlaid by the UI. No game-truth may be derived from a generated map image.

6. **Caching policy.** Generate asynchronously. Portraits cached per character until manually refreshed. Scene images generated only on major scene transitions. Cache key includes `source_snapshot_hash` (hash of the belief-store snapshot) so a changed scene invalidates cached images without overwriting artifacts from prior snapshots.

7. **User visual mode.** Configurable: `off` (no image calls), `cheap` (fast model for all), `premium` (premium model where appropriate). `off` must produce zero API calls and zero cost.

8. **Telemetry.** Image generation telemetry records go to `TelemetrySink` — never the event log. Same isolation contract as `ModelGateway` (D-022).

**Planned components (see COMPONENTS.md for full specs):**
- `ImageGenerationGateway` — async image API seam; holds model profiles.
- `ImagePromptAssembler` — builds `(subject_prompt, style_prompt)` from entitled context.
- `ImageArtifactStore` / `ImageArtifact` — stores generated files + provenance metadata.
- Style profile — config file, not a code component.

**Recommended model routing (pending consistency testing — not locked):**

| Profile | Recommended candidates | Notes |
|---|---|---|
| `cheap_scene` | Imagen 4 Fast, Qwen-class hosted | Routine scene transitions; minimize latency and cost |
| `premium_scene` | Imagen 4, Imagen 4 Ultra, FLUX Kontext Pro, GPT-image high | Explicit player upgrade, major reveals |
| `portrait` | FLUX Kontext, GPT-image, Imagen 4 | Consistency across sessions is the key criterion — **choice requires testing** |
| `map_background` | Any fast model | Aesthetic layer only; deterministic rendering overlaid on top |
| `text_graphic` | Ideogram, Recraft | Labeled artifacts, symbolic posters, in-world text-heavy items |

**Portrait generation policy (decided constraint):** Character portraits are generated **once per character** — at character creation or first-render — and stored as artifacts. They are **not regenerated per scene, per session, or per session-open**. Face consistency across sessions depends on the stored artifact, not on model consistency. The style profile controls aesthetics; it does not control identity. A user or GM may manually trigger a portrait refresh via an explicit UI action, but the engine never auto-triggers portrait regeneration. This is the only viable path to cross-session face consistency without a dedicated identity-preservation model; do not build per-scene portrait generation.

**Open questions:**
- Which model wins for character portrait consistency within a single generation? (Requires controlled consistency testing before locking the model recommendation in D-038.)
- Style profile file format: JSON, TOML, or YAML? Location relative to session/campaign or global user config?
- Deterministic map rendering architecture: SVG/Canvas/third-party lib? How do FABLE zone positions map to visual coordinates for overlay?
- Definition of "major scene transition" as a cache trigger: zone transition only, or also explicit GM scene declaration events, downtime transitions?
- Cache invalidation: should a new committed fact in the same scene force regeneration, or only zone/scene transitions?
- Multi-viewer cache: if two characters have different belief stores in the same scene, do they get separate image generations?

**Does not break any CORE principle:** Images are below the determinism boundary. Principle 1 (determinism owns truth) — satisfied: images carry `non_authoritative=True` and never feed world state. Principle 2 (POV partitioning) — satisfied: `ImagePromptAssembler` is gated by the viewer's entitled projection. Principle 4 (honesty enforceable) — satisfied: images are impressionistic; the event log is the authority if they diverge. Principle 5 (fidelity tiering) — satisfied: visual fidelity is a user-selectable mode orthogonal to game-state fidelity.

**Timing:** Post-Phase-21. Do not implement in Phase 22 unless Phase 21 is complete and stable. Do not let image generation planning pull implementation forward.

**Supersedes:** D-014 (absorbs and expands its two load-bearing constraints).
**Relates to:** D-022 (telemetry isolation), D-032 (epistemic types — only `fact` commitments enter image prompts), CORE §12 (graphics non-goal softened to v1.x feature), COMPONENTS.md image generation layer.
**Impact:** `settings/style_profile.json`, `image.py` (new module), `ImageArtifactStore` SQLite table, interface/channel router (trigger image generation, display artifacts), `TelemetrySink` (receives image telemetry).

---

## D-039 · Voice / TTS design and policy · Resolved · 2026-06-19

**Question:** What role, if any, should voice / TTS play in FABLE? An earlier design attempted TTS as a runtime narration subsystem; that was explicitly removed from Phase 21 scope. Is there a design that preserves "text is the only required medium" while permitting optional audio?

**Decision:** Voice is a **post-Phase-21 presentation-layer track**. Manual click-to-play only. Off by default. No automatic narration playback. No voice input. No game-state coupling.

**Decided design (locked for the post-Phase-21 track):**

- Each rendered text bubble in the interface may display a small audio button.
- Clicking the button generates (or replays cached) speech for that specific bubble.
- No audio plays automatically; the player controls all playback.
- Each named speaker (gm, named NPCs, player character) has a configured `voice_id` and `model_id`.
- Generated audio is cached per rendered message (cache key: event ID + voice_id hash). Repeated clicks do not re-bill.
- TTS failure degrades silently to text; text is always the source of truth.
- Voice is disabled by default. The user opts in via settings.

**Settings shape** (`settings/voice.json` — not part of campaign package or session DB):

```json
{
  "voice": {
    "enabled": false,
    "provider": "elevenlabs",
    "api_key_env": "ELEVENLABS_API_KEY",
    "default_model": "eleven_multilingual_v2",
    "voices": {
      "gm":     { "voice_id": "...", "model_id": "..." },
      "player": { "voice_id": "...", "model_id": "..." }
    }
  }
}
```

**API key policy:** API key is read from the environment variable named by `api_key_env`. It must never be written to the session DB, campaign package, or any save file. Voice IDs and model IDs may be stored in `settings/voice.json` or campaign package (they are not secrets).

**Authority constraints (non-negotiable):**
- Voice artifacts are presentation only; `non_authoritative=True` on every generated audio artifact.
- Voice generation never reads hidden plot, unaudienced events, or any data the viewer is not entitled to.
- No voice component holds a reference to `EventLog`, `CommitPipeline`, `WorldState`, or `EffectExecutor`.
- No game-state component depends on voice code.

**Implementation timing:** Post-Phase-21 track. Do not implement during Phase 21 or Phase 22. Phase 21's explicit voice policy ("Voice is not in scope") stands unchanged. When this track is opened, start from `settings/voice.json` + `VoiceGateway` + `VoiceArtifactCache`; do not attempt to retrofit into the beat loop or event log.

**Planned components:** `VoiceGateway` (thin ElevenLabs API wrapper; caches by event-id+voice-id hash), `VoiceArtifactCache` (maps event ID → local audio file path), `settings/voice.json` (per-speaker voice IDs; not a secret store).

**Relates to:** D-038 (image generation — same post-Phase-21 track, same `non_authoritative` constraint), IMPLEMENTATION_PLAN.md post-v1 tracks.
**Impact:** New `voice.py` module and `settings/voice.json` config; no changes to event log, world state, beat loop, or any deterministic component.

---

## D-040 · Campaign generation pipeline · Resolved (deferred to Campaign-Authoring Studio) · 2026-06-19

**Question:** How should new campaigns be created for users who don't have a pre-built `CampaignPackage`? What is the generation pipeline for auto-generate and generate-from-prompt? What is the boundary between raw user input and GM runtime context?

**Decision:** Campaign generation is the **Campaign-Authoring Studio post-v1 track**. Both generation paths (auto-generate, generate-from-prompt) use a `CampaignCompiler` model component that produces a validated `CampaignPackage`. Raw user input never becomes GM runtime context directly.

**Phase 21 impact:** The Phase 21 home screen's "New Campaign" flow loads a pre-built `CampaignPackage` only. No generation UI in Phase 21.

**Decided pipeline (for the Campaign-Authoring Studio track):**

```
Raw user prompt / file / minimal choices
    ↓
CampaignCompiler model call
    ↓
Structured CampaignPackage draft (JSON)
    ↓
Validation against campaign.schema.json
    ↓
Repair / retry (up to N attempts) if invalid
    ↓
Saved CampaignPackage
    ↓
attach_campaign() / open_session() as normal
```

**Two entry modes (both reach the same CampaignPackage):**
- **Auto-generate:** user provides minimal choices (genre, tone, a sentence or two). Compiler produces a complete campaign from defaults/settings.
- **Generate from prompt/file:** user uploads arbitrary text. Compiler extracts, normalizes, fills missing required fields, validates.

**Key invariants (non-negotiable):**
- Raw upload is source material for the compiler only. It must never be placed directly in GM context, narrator context, or any player-facing surface.
- CampaignPackage output must pass schema validation before `attach_campaign()` will accept it. Invalid packages are rejected, not silently used.
- Hidden/GM-private fields (`hidden_nodes`, `gm_context`, GM-only secrets) route to plot-manager and GM-private stores only — same access control as hand-authored campaigns.
- Campaign generation must produce FABLE structures (JSON), not free prose. The compiler's output is a `CampaignPackage`, not a narrative text.
- Voice and image style notes in the generated package are advisory; they do not override `settings/voice.json` or `settings/style_profile.json`.

**Required campaign fields for generated campaigns** (minimum for the package to be usable):

| Field | Required | Notes |
| --- | --- | --- |
| `title` | Yes | |
| `player_intro` | Yes | Player-facing premise |
| `gm_context` | Yes | GM-private premise and secrets |
| `starting_scene` | Yes | First scene definition |
| `starting_location` | Yes | First zone/location |
| `initial_visible_truths` | Yes | Committed-on-open facts |
| `initial_hidden_truths` | Yes | GM-private facts |
| `fronts` | Yes | At least one active Front |
| `clocks` | Yes | At least one active clock |
| `npcs` | Yes | Core NPCs |
| `hooks` | Yes | Initial plot hooks |
| `tone_boundaries` | Yes | Safety / tone constraints |
| `hidden_nodes` | Yes | Plot graph hidden structure |
| Character portraits/images | Optional | Advisory; deferred to D-038 |
| Map style | Optional | Advisory; deferred to D-038 |
| Voice assignments | Optional | Advisory; deferred to D-039 |

**Planned components:** `CampaignCompiler` (model component — structured-output call producing `CampaignPackage` draft), `CampaignCompilerGateway` (thin model wrapper with repair/retry loop, schema validation, max-N-attempts circuit breaker). `campaign.schema.json` will need the `tone_boundaries` and `initial_hidden_truths` fields added when this track is opened.

**Relates to:** `CampaignPackage` / `load_campaign` / `campaign.schema.json` (Phase 17), `attach_campaign()` (Phase 17), D-038 (image style notes), D-039 (voice assignments), IMPLEMENTATION_PLAN.md Campaign-Authoring Studio post-v1 track.
**Impact (deferred):** New `compiler.py` module; `campaign.schema.json` additions; Phase 21 home screen "New Campaign" flow loads packages only.

---

## D-041 · Settings system design · Resolved · 2026-06-19

**Question:** How should the FABLE Table Engine expose configurable settings — model choices, API keys, character agent slots — in a way that is both GUI-friendly and directly editable, campaign-aware, and safe with respect to secrets?

**Decision:** Layered JSON settings with a GUI editor that shows campaign-aware slots, exposes the file path for manual editing, and offers per-setting reset-to-default. API keys are stored in the environment only — never in settings files.

**Settings hierarchy (lowest → highest priority):**
1. **Code defaults** — `SettingsRegistry` bakes in a default for every essential setting; the system is always in a valid state with zero user configuration.
2. **`settings/models.json`** — user-level overrides; persists across sessions and campaigns.
3. **`settings/campaigns/{campaign_id}.json`** — per-campaign overrides; applied only when that campaign is loaded. Created on first per-campaign override; absent means "fall through to user level."

**Essential settings with defaults:**

| Setting key | Default model ID | Notes |
| --- | --- | --- |
| `gm_adjudicator_model` | `claude-opus-4-8` | Cold GM; structured tool-use output |
| `gm_narrator_model` | `claude-opus-4-8` | Warm GM; prose narration |
| `gm_world_simulator_model` | `claude-opus-4-8` | Clock/front advances |
| `auditor_model` | `claude-haiku-4-5-20251001` | Pre/post-beat checks; latency-sensitive |
| `social_interpreter_model` | `claude-sonnet-4-6` | Disposition delta recognition |
| `character_agent_default_model` | `claude-opus-4-8` | Default if no per-character override |
| `character_agent_{entity_id}_model` | (inherits default) | One slot per teammate in the loaded campaign |

**Character agent slots are campaign-aware:** When a campaign is loaded, the settings GUI reads the campaign roster and renders one model-picker row per character agent seat. The slot key is `character_agent_{entity_id}_model`. Seats are derived from the running campaign; the GUI does not show empty generic slots.

**Voice API key policy:** The ElevenLabs API key (and any other third-party API key) is **never stored in a settings file**. The settings JSON holds only the env-var name (e.g., `"voice_api_key_env": "ELEVENLABS_API_KEY"`). The GUI shows the env-var name and a status indicator (set / not set); it does not display or accept the key value itself.

**GUI contract:**
- Every essential setting has a visible default value displayed as placeholder text when no override is active.
- Each setting row has a **Reset** button (or reset icon) that clears the per-campaign or user-level override and reverts to the next layer down (per-campaign → user level → code default).
- The settings panel displays the **full path** to the active settings file (user-level and campaign-level, if applicable) and offers a button to **open in the system editor** (or copy path to clipboard on platforms where shell-open is unavailable).
- Character agent slot rows are generated dynamically from the campaign roster. Adding a character to the campaign package adds a slot; removing one removes it. No stale "character_3" row when only two characters exist.
- Voice API key row shows env-var name, status indicator, and a note that the key must be set in the environment — no text field for the key itself.

**Non-goals for Phase 21 settings:**
- No settings migration / schema versioning for the settings files themselves (that is a Phase 22 concern alongside DB migration).
- No per-setting history or audit trail.
- No cloud sync or multi-user settings merge.

**Relates to:** D-039 (voice API key policy), D-040 (campaign roster drives agent slots), Session management / `SessionManager` (campaign_id determines which campaign settings file to load), Phase 21 interface.
**Impact:** New `settings.py` module (`SettingsRegistry`, `SettingsManager`, `load_settings`, `reset_setting`); `settings/models.json` and `settings/campaigns/{campaign_id}.json` file layout; Phase 21 settings panel in the play interface; COMPONENTS.md settings system section.

---

## D-036 · In-memory EventLog rollback contract · Settled · 2026-06-18
**Question:** `EventLog.transaction()` is a no-op (yields without snapshot or restore). `BeatRunner` always wraps beat steps 6–9 in `with self._log.transaction():` and raises `_BeatAborted` to signal rollback. For the in-memory backend, no rollback actually occurs — fact commits and event appends inside the block persist even on `_BeatAborted`. Is this a correctness problem?
**Decision:** By design — with an explicit scope constraint. The in-memory `EventLog` is test infrastructure, not a production backend. It does not provide D-023 atomicity and is not required to. Any test that verifies rollback behavior (e.g., committed facts disappear on post-audit block) must use `SQLiteEventLog` via `open_session`. Tests using the in-memory backend may use `_BeatAborted` to signal abort, but they must not assert on rolled-back state — the state will still contain the pre-abort writes. The in-memory comment in `beat.py` ("behaviour is unchanged from the pre-Phase-10 code") is the documented contract.
**Consequence:** The two backends have different atomicity semantics. This is acceptable because: (1) the SQLite backend is the only production-grade backend; (2) correctness tests for rollback are already written against SQLite (see `test_phase10_session.py`); (3) implementing snapshot/restore in the in-memory backend would require threading snapshot logic through every `append()` and every sub-system write, significantly complicating an otherwise simple test tool. If this divergence ever causes a real test-correctness problem, revisit by implementing a `SnapshotEventLog` specifically for rollback tests.
**Relates to:** D-023 (SQLite atomicity — the in-memory backend is exempt), `BeatRunner._BeatAborted`, `tests/test_phase10_session.py` (rollback tests use SQLite), Phase 22 (beta hardening — any golden transcript tests that involve aborted beats should use SQLite).
**Impact:** No code change. Document here so future engineers do not treat the in-memory no-op as a bug to fix.

---

## D-037 · Multi-effect palette atomicity · Resolved · 2026-06-18
**Question:** `EffectExecutor.apply_all()` applies typed effects independently and continues past rejections. If a consequence palette contains multiple effects (e.g. `ApplyStress` + `MoveEntity` + `ExpireTruth`) and the `MoveEntity` is rejected, the stress is still applied. Is per-effect independence correct, or should some palette effects be grouped as atomic units (all succeed or all skip)?
**Context:** The Phase 13 consequence palette (`triumph_effects`, `consequence_palette["cost"]`, etc.) is assembled by the adjudicator and represents the intended fictional consequence of a roll band. Partial application — where some effects land and others don't — creates a coherent-looking world state that contradicts what the adjudicator intended. Example: `ExpireTruth("enemy.concealed")` succeeds but the follow-up `CreateTruth("enemy.flanked")` fails; the enemy is now revealed but not flanked, which may be internally inconsistent fiction.
**Decision:** Option (b). Effects are independent by default — most palettes have independent entries. The problem is narrow: certain mechanical combos (reveal + reposition, expire + create replacement truth) have intrinsic dependency. Explicit `atomic_group` declarations on dependent pairs solve this without coupling all effects. Option (c) is too coarse — a failed `ChangeResource` (resource already maxed) would block a legitimate `ApplyStress`.
**Implementation:** `atomic_group: str | None = None` will be added to the `TypedEffect` base class and all typed effect dataclasses. `EffectExecutor.apply_all()` will group effects by `atomic_group`, apply each group as a unit (if any effect in the group fails, all are skipped; no effects from that group land). Effects with `atomic_group=None` remain independent. **Implementation deferred to Phase 22** — the executor behavior and property tests both land there. Phase 17's `schemas/campaign.schema.json` reserves `atomic_group` as a future field in palette effect specs.
**Relates to:** `EffectExecutor.apply_all()` (`effects.py`), Phase 13 consequence palette, D-025 (palette design), Phase 22 (property tests for partial application).
**Impact (deferred to Phase 22):** `TypedEffect` base class (`atomic_group` field), `EffectExecutor.apply_all()` (group-aware apply loop), `schemas/campaign.schema.json` (`atomic_group` in effect specs).

---

## D-043 · Lorebook / world-info: injection architecture and audience-gate mechanism · Resolved · 2026-06-19

**Question:** When a lorebook/world-info system is added in Phase 22, how should entries be retrieved and injected into role contexts? SillyTavern-style keyword triggers on raw event content are unsafe: the trigger can fire from content the receiving POV was not in the audience of, injecting facts that POV is not entitled to know.

**Why it matters:** If a lorebook entry about a secret faction is triggered by a keyword in an NPC's dialogue (visible to GM only), and the trigger fires for the player's context too (because the keyword appears somewhere in the event stream), the player's prompt receives lorebook content outside their entitled belief projection. This is an audience-leakage vector structurally identical to the D-013 sequence-number side-channel.

**Decided constraints (non-negotiable regardless of option chosen):**
1. Lorebook entries are **background/setting context only** — never current-state authority. Event log, world state, canon ledger, disposition graph, and plot graph override lorebook entries on any conflict.
2. Entries carry an **audience class** (`all`, `gm_only`, `player_{id}`) assigned at authoring time.
3. Retrieval and injection happen **inside `ContextAssembler`** — never at the gateway, never client-side, and never keyed from raw event content the requesting POV cannot see at content level.
4. Entry injection for a POV is driven by what **that POV's entitled belief projection contains** — not by raw event content, global search, or any data outside the POV's authorized view.
5. A `gm_only` entry is never injected into any player context, regardless of keyword match.
6. **D-042 (context budgeter) is a hard prerequisite.** Lorebook injection increases prompt size; it must not be wired in before the budgeter can account for the additional tokens.

**Options:**
- **(A) Keyword match against POV belief projection (Phase 22 v1 recommendation):** an entry fires when its keywords appear in the entitled event text or committed fact labels of that POV's projection only. Deterministic, auditable, no API calls.
- **(B) Semantic retrieval against POV belief store:** vector similarity over the N most relevant entries, filtered by audience class before any embedding comparison. Better relevance; requires an embedding model and a vector store. Natural upgrade from (A).
- **(C) GM-curated explicit injection:** entries are tagged with `scene_ids` or plot-graph node IDs; the GM or plot manager activates entries by tag, not via keyword trigger. A complementary override mechanism, not a replacement for (A).

**Recommendation:** (A) for Phase 22 v1. Keyword match is deterministic, audience-safe, and adds no API calls. Audience class gate fires before any content assembly. (C) is a useful complement for entries the GM wants always-present in a given scene. (B) is a Phase 23+ upgrade; defer until (A) proves insufficient for relevance.

**Relates to:** D-001 (lorebook injection is a read-time projection-layer operation), D-042 (hard prerequisite — budgeter must partially exist before lorebook is wired in), D-038 (image prompt source is the same audience-filtered projection lorebooks are filtered by), `ContextAssembler`, Phase 22.

**Impact (deferred to Phase 22, after D-042 partial):** New `lorebook.py` module (`LoreEntry`, `LoreDeck`, `LoreAssembler`); `ContextAssembler` gains an optional `LoreAssembler` collaborator (disabled when absent; lorebook injection is opt-in); `settings/models.json` schema gains `lorebook_injection_window`; `CampaignPackage` gains `lore_entries` field with per-entry `audience_class`.

---

## D-042 · Context budget management: where and how to enforce token limits · Open · 2026-06-19

**Question:** Prompts sent to each role (adjudicator, narrator, character agents, social interpreter, auditor, plot-manager) can grow unbounded as event history accumulates. Where should the token budget be enforced, how should limits be applied per role, and how should the engine behave when a context is near or over budget?

**Why it matters:** Without a budget policy, long sessions silently approach model context limits, causing latency spikes, cost overruns, or hard API failures. The limit must be applied *before* the prompt is fully assembled — not at the gateway, where only the assembled string is visible. Dropping events at the gateway is too late; the assembler must know which events to include or summarize.

**Architectural constraint (confirmed):** `ContextBudgeter` belongs at **context-assembly time**, not between `ContextAssembler` and `ModelGateway`. Correct data flow: `belief store → ContextBudgeter → prompt strings → ModelGateway → model`. The gateway sees only the assembled prompt; it cannot choose which events to drop. Any enforcement that lives only at the gateway is post-hoc and incomplete.

**`limit=12` note:** The current `_events_summary` and `_narrator_context` functions in `beat.py` use `CONTEXT_EVENT_WINDOW = 12` (module-level constant as of this decision) as a hard recent-event window. This constant is a budget placeholder, not a full budget policy. Phase 22 replaces it with per-role `ContextBudgetPolicy` entries loaded from `SettingsManager`.

**Options:**
- **(A) Per-role hard token cap via preflight estimation**: before assembling the prompt, call `count_tokens` on each section candidate; drop/summarize older events until the assembled prompt fits within a per-role cap. Accurate but adds one API call per prompt.
- **(B) Per-role event-window heuristic**: each role has a configured max-event count (recent-window) plus a soft cap on summary text. No preflight API call. Fast and predictable; may over- or under-shoot actual token count.
- **(C) Hybrid**: recent-window heuristic as primary gate (no extra API call for routine turns); preflight `count_tokens` call only when the estimated token count (word-count proxy) is within 20 % of the per-role cap. Balances accuracy and latency.

**Recommendation:** (C). Preflight estimation is the right tool but adding it on every call adds measurable latency. The hybrid approach spends the preflight call only when the heuristic signals proximity to the limit. Per-role caps are explicit in the settings system so they can be tuned per deployment.

**Per-role budget policies (Phase 22 defaults):**

| Role | Recommended max tokens | Required-always sections | Event window |
|---|---|---|---|
| `gm_adjudicator` | 40 000 | World state, canon, scene | Recent 20 |
| `gm_narrator` | 20 000 | Outcome, committed effects | Recent 8 |
| `character_agent` | 12 000 | Sheet, persona | Recent 12 |
| `social_interpreter` | 8 000 | Dialogue events only | Recent 6 |
| `auditor` | 16 000 | Beat record, palette | Recent 10 |
| `plot_manager` | 24 000 | Full plot graph | Recent 15 |

**Context quality check (advisory):** After trimming, check: (1) required-always sections survived; (2) at least one event is present for roles that require context; (3) the assembled prompt is below cap. If checks fail, emit an `AuditFlag(tier=WARNING)` rather than silently sending a degraded prompt.

**Cost ceiling:** `TelemetrySink` already receives per-call cost data. Phase 22 adds a per-session cost ceiling: when cumulative cost exceeds the cap, the engine emits an advisory log event and the interface surfaces a warning. Hard cutoff is opt-in (default: advisory only).

**Relates to:** `ContextAssembler` (belief store projection), `ModelGateway` (call site), `TelemetrySink` (cost tracking), `SettingsManager` (per-role cap configuration), D-041 (settings hierarchy — budget policies live in `settings/models.json`), Phase 22 (implementation target).
**Impact (deferred to Phase 22):** New `budgeter.py` module (`ContextBudgeter`, `ContextBudgetPolicy`, `TokenEstimator`); `ContextAssembler` gains a `ContextBudgeter` collaborator; `SettingsRegistry` gains six per-role cap defaults; `settings/models.json` schema gains budget entries.

---

## D-034 · Opening model: extended MaintainedTruth vs. separate entity · Open · 2026-06-18
**Question:** The GUI mockup (v4) surfaces an OPENINGS panel in the Scene tab, with entries carrying a `group` (Position / Opening / Leverage — FABLE's Ledger categories, §10), `text` (what the fiction established), and `effect_text` (what acting on it can achieve mechanically). These have the same lifecycle as `MaintainedTruth` (created when fiction establishes them; expired when acted upon or when the opportunity closes), but the current `MaintainedTruth` schema has no `group` or `effect_text` field.
**Why it matters:** If Openings are left as a frontend convention with no backend model, Phase 21's interface cannot derive them from world state. If they're shoehorned into `maintained_truths` without schema change, the group/effect information is lost. The decision must be made before Phase 17 (campaign schema) encodes Openings in the plot graph.
**Options:**
- **(A) Extend `MaintainedTruth`**: add optional `group: str | None` (Ledger category: Position, Opening, Leverage, or None for unclassified) and `effect_text: str | None` (mechanical consequence if acted on). `CreateMaintainedTruth` effect gains the same two optional fields. The Scene tab projection filters maintained truths by non-None group to populate OPENINGS.
- **(B) Separate `WorldState.openings: dict[str, Opening]`**: a dedicated `Opening` dataclass (key, text, group, effect_text, lapse_condition). Two new effect types: `CreateOpening` and `CloseOpening`. Schema is clean but adds a third dict alongside `maintained_truths` and `clocks`.
- **(C) Pure fact convention**: Openings are committed canonical facts using a conventional `predicate` namespace (e.g. `predicate="ledger_opening"`), `value` carrying group + text + effect as structured data. No new WorldState field; projection filters canon by predicate prefix. Stays inside the existing event log fold.
**Recommendation:** (A). Openings are ontologically maintained truths — facts about what is currently possible in the fiction, held until acted upon or until the situation changes. The lifecycle is identical; only the presentation metadata differs. Adding two optional fields to `MaintainedTruth` and `CreateMaintainedTruth` is the least invasive approach and keeps Openings inside the existing effect executor pipeline. Option C requires the frontend to parse structured values out of a fact's `value` field — fragile. Option B introduces a separate dict for what is semantically the same concept.
**Risk:** If Openings later need game-mechanical coupling beyond expire/lapse (e.g. spending an Opening grants a Ledger step), a separate entity may prove cleaner. Revisit at Phase 17 if mechanical coupling is needed.
**Relates to:** `effects.py` (`CreateMaintainedTruth`), `world_state.py` (`MaintainedTruth`), Phase 17 (campaign schema), Phase 21 (Scene tab projection).
**Impact:** `MaintainedTruth` schema (`group`, `effect_text` fields), `CreateMaintainedTruth` effect (same optional fields), `WorldState.set_maintained_truth`, persistence layer, Scene tab Opening projection.

---

## D-044 · TN table enforcement: deterministic lookup vs. adjudicator-asserted · Open · 2026-06-19

**Question:** FABLE v6 §6 specifies a fixed TN table (base 8, routine 10, demanding 12, extreme 13, heroic 14; contested = 10+Skill). Currently the adjudicator LLM asserts a TN value in its tool call and the rules engine accepts it without validation. Should `RulesEngine` enforce the legal TN set independently of the model?

**Why it matters:** The determinism boundary (CORE §1, principle 1) says "Dice, rules, and world state are code-owned." TN is a rule, so the rules engine — not the model — should be authoritative. A model that hallucinates TN=7 currently produces a valid roll result. If TN is code-enforced, the model's output is validated and any out-of-set value triggers an audit flag rather than silently producing an incorrect resolution.

**Options:**
- **(A) Enforce in RulesEngine:** Add `LEGAL_TNS = {8, 10, 12, 13, 14}` and a contested formula to `rules.py`. `AdjudicatorGM.evaluate()` returns a `ResolutionPlan.tn`; `BeatRunner` validates it before calling `resolve_check()`. Invalid TN → `AuditFlag(CRITICAL)` + beat abort.
- **(B) Enforce in auditor:** Leave `RulesEngine` accepting any TN; add a pre-commit auditor hook that validates TN against the legal set. Lighter change to beat.py; auditor already has the advisory infrastructure.
- **(C) Defer:** Accept current behavior (adjudicator-asserted TN) as "good enough" for v1. Model prompts already specify the legal TN table; hallucinated TNs are rare and correctable via the D-031 retcon path.

**Recommendation:** (A) for v1.1, (C) for Phase 22 v1. The exit gate for Phase 22 is "a player can run a complete text-only session" — not "rules are fully code-enforced." TN validation is a correctness improvement, not a runtime stability requirement. Adding it now risks scope creep; defer to v1.1 once the basic session flow is stable.

**Status note:** Explicitly deferred to post-Phase-22 / v1.1. This decision remains Open so it is not forgotten. Record in the v1.1 worklog when addressed.

**Relates to:** CORE §1 (determinism boundary), `rules.py` (`RulesEngine.resolve_check`), `gm.py` (`ResolutionPlan.tn`), `beat.py` (pre-roll TN validation), D-027 (lifecycle state — an invalid TN would produce an `aborted` state).

---

## D-045 · CreateSeam typed effect and Seam validation · Open · 2026-06-19

**Question:** FABLE v6 §15 defines a Seam as a vulnerability marker on an entity or location that enables a terminal consequence when conditions are met. The consequence palette (D-025) currently supports `apply_stress`, `apply_scar`, `create_truth`, etc., but has no `create_seam` or `trigger_seam` effect type. Should these be added in Phase 22 or deferred?

**Why it matters:** Without `CreateSeam`, the full Cost/Setback/Exposure consequence chain cannot reach terminal outcomes. Sessions can still run to conclusion via stress overflow → scar, but the Seam narrative structure (explicit vulnerability → triggered consequence) is unavailable. This is a completeness gap, not a runtime failure.

**Decision (deferred):** Post-Phase-22. The Seam mechanic requires coordinated work across `effects.py` (new effect types), `world_state.py` (seam tracking), `plot_graph.py` (seam-tied plot nodes), and the consequence palette schema. This is a Phase 23 feature. Deferring does not prevent Phase 22 from shipping — the current stress/scar path provides terminal consequences.

**Relates to:** D-025 (consequence palette), `effects.py`, `world_state.py`, Phase 23 planning.

---

## D-046 · Recovery clocks: recovery_for field and lapse behavior · Open · 2026-06-19

**Question:** FABLE v6 §12 specifies recovery clocks — clocks that, when they fire, lapse a named Maintained Truth (e.g. "wound healing" clock expires the "hero.bleeding" truth on completion). The current `Clock` schema in `world_state.py` has no `recovery_for` field; `WorldSimulator.advance()` fires `front_advance` events but does not call `expire_maintained_truth()` automatically on clock completion.

**Decision (deferred):** Post-Phase-22. Adding `recovery_for: str | None` to the `Clock` schema and wiring `WorldSimulator.advance()` to call `EffectExecutor.apply(ExpireMaintainedTruth(...))` on a full clock is a contained, testable change — but it touches the persistence layer (SQLite clock schema), the simulator, and effect typing. Deferring avoids a schema migration in Phase 22 and keeps the Phase 22 migration registry lean. Target: Phase 23 alongside CreateSeam.

**Relates to:** `world_state.py` (Clock dataclass), `persistence.py` (SQLite clock schema), `effects.py` (`ExpireMaintainedTruth`), `gm.py` (`WorldSimulator.advance`), Phase 23.

---

## D-047 · Cost register mechanics: Ground / Trace / Relational · Open · 2026-06-19

**Question:** FABLE v6 §7 defines three cost registers — Ground (positional cost: movement, cover), Trace (exposure cost: stealth, noise), Relational (social cost: trust, reputation). These have no typed effects (`ApplyCostRegister` or equivalent) in the current `effects.py`. Is a generic typed effect needed in v1?

**Why it matters:** Without typed cost-register effects, palette entries can only apply stress and scars as mechanical consequences. Ground/Trace/Relational costs must be narrated by the GM rather than applied deterministically, which breaks the determinism boundary for this class of consequence.

**Decision (deferred):** Post-Phase-22. A minimal implementation would be a generic `ApplyCostRegister(register: str, entity_id: str, description: str)` that logs the cost as a commitment. However, without a cost-register ledger in `WorldState` and a corresponding projection, this would be a write-only side effect with no read surface. Building it correctly requires the full Ledger model (§10). Deferring to Phase 23 alongside Seams and recovery clocks, where the Ledger can be designed holistically.

**Relates to:** `effects.py`, `world_state.py` (Ledger model), `character_sheet.py` (Ground/Trace/Relational tracks), FABLE v6 §7/§10, Phase 23.

---

## D-048 · Post-v1 FABLE mechanics: Prep Rounds, Volatile overlay, Advancement, Opposition classes · Resolved (deferred) · 2026-06-19

**Question (consolidated):** Four FABLE v6 mechanics have no implementation: Prep Rounds (§18), Volatile overlay (§20), Advancement (§21), and Opposition classes (§19). Should any be addressed in Phase 22?

**Decision:** All four are deferred to post-v1 tracks, for the following reasons:

- **Prep Rounds (§18):** Requires orchestrator round-type discrimination (prep vs. live vs. recovery). Current `Orchestrator` supports one round type. Deferring does not prevent play — scenes simply cannot have a declared prep phase. Post-v1 addition to the orchestrator.

- **Volatile overlay (§20):** Requires a `volatile: bool` flag on `SceneMode` and TN/Exposure adjustment in `BeatRunner.run()` before the adjudicator call. Minor implementation but touched enough invariants (TN floor, Top-Exit block) to warrant a standalone change. Post-v1.

- **Advancement (§21):** CORE §1 invariant 17: advancement must be causal (triggered by demonstrated play, not declared). Without a demonstrated-event tracker, advancement cannot be implemented correctly. Post-v1 design track — must not be retrofitted as a GM-declared effect.

- **Opposition classes (§19):** Obstacle / Minor / Significant / Front are currently adjudicator-managed prose distinctions. Formalizing them requires a structured opposition registry in `world_state.py`. Useful for telemetry and encounter tracking; not required for session correctness. Post-v1.

**Relates to:** `orchestrator.py`, `beat.py`, `world_state.py`, `character_sheet.py`, FABLE v6 §18–21.
