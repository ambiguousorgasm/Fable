# Design Decision Log

Living record of design forks — open and resolved. Authoritative for decision *status*; CORE §11 carries only an index of what is open. Each decision has a stable ID so other files and the changelog can reference it.

**Format:** `ID · Title · Status (Open / Resolved / Superseded) · Date.` Then: the question, the options, the recommendation/decision, rationale, and any downstream impact.

When a decision is resolved, change its status and date, record the choice, and walk the change protocol (`00_README.md`) — a resolution usually changes CORE and `COMPONENTS.md`.

---

## D-001 · Belief store: read-time projection vs. write-time materialization · Open · 2026-06-17
**Question:** Is each agent's belief store derived on read by filtering the event log, or materialized per-agent at write time?
**Options:** (a) Read-time projection from the single log, cached. (b) Write-time fan-out into per-agent stores.
**Recommendation:** (a) read-time + cache. One source of truth, no desync; caching recovers the speed. Two materialized stores drifting apart reintroduces omniscience-style bugs by the back door.
**Impact if changed:** Context assembly, event-log schema, caching layer.

## D-002 · Spatial model · Resolved · 2026-06-17
**Question:** How is position/distance represented in world state?
**Options:** (a) Abstract range bands (close/near/far). (b) Coordinates or a grid. (c) Fiction-positional — position as Truths, no measured space.
**Decision:** (c) Fiction-positional, following FABLE's native abstraction. Position is a fictional fact persisted as **Truths** (`fable_engine.md` §12) within the scene/zone graph; there is no coordinate grid (rejects (b)) and no formal range-band system (looser than (a)). Proximity surfaces mechanically only through the Ledger **Position** category (§10) and the **Ground** cost register (§7); coarse qualitative tags (adjacent / near / far) are descriptive adjudication aids, not measured quantities. A distance the GM states in fiction ("a hundred feet off") is committed as a relational Truth and enforced by Truth-consistency + logged traversal, not by arithmetic.
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
- **Bonds** (Held Truths, `fable_engine.md` §12) are the mechanical *handles*: a relationship surfaces as a Bond the actor may **Lean** on (Edge, §13) or that pays a **Ledger** step where it *changes* baseline (§10). **Edge** (cap 3) is the spend currency.
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

## D-007 · Fact-extraction: post-hoc pass vs. GM-emitted structured block · Open · 2026-06-17
**Question:** How are declared facts lifted into structured commitments?
**Options:** (a) A structured-output extraction pass over the GM's free prose. (b) The GM emits a structured commitment block alongside its prose.
**Trade-off:** (a) keeps the GM's output natural but adds a parsing step and its failure modes; (b) is more reliable to commit but constrains GM output format.
**Recommendation:** Undecided — prototype both; this is a high-leverage early decision (see CORE §7.3).
**Impact:** Fact-extraction pipeline, GM output contract, auditor reliability.

## D-008 · Override authority · Resolved · 2026-06-18
**Question:** Who may invoke a deliberate override of committed state, and how is it surfaced and logged?
**Decision:** The **AI GM holds authoring and override authority** over world-state and consequence; the **human player is the co-authority and backstop** (final say, table-safety) and may also override. Every override remains an explicit logged `override` event with author and reason, which the auditor reads as intentional fiat (mechanism unchanged from phase 2).
The substance is *when*, not just *who*. Override is the **reserved exception**, not the working tool. The GM's authority is **latent**: in normal play it is exercised through the other two legal modes — Add by fiat and Change via causation (§6.2) — and through plot-bending (§7.4), so player choices meet friction, consequence, and adjacent hooks rather than veto. Overt override is reserved for genuine coherence-breaks and table-safety. Default stance is "yes-and / yes-but," and every "yes-but" must leave a **mechanical mark** in deterministic state (a clock ticks, a front advances, a Truth or Edge changes) so consequence is real, not narrated away.
**Rationale:** Delivers high felt agency with coherence held by latent structural authority. Most of what reads as "GM authority" is not the override path at all — it is Add + Causation — so the forbidden move (silent contradiction) is never approached in normal play. Aligns with §7.4 (agency sovereign over plot; never negate to protect a script) and principle 4 (honesty enforceable).
**Design intent → future criteria:** two properties should become testable success criteria (CORE §13) once the GM/plot phases make them measurable — (1) overt redirections trend toward ~zero per session (divergence absorbed via causation/re-bind, not veto); (2) every "yes-but" commits a mechanical consequence. Recorded here; added to §13 when measurable.
**Relates to:** §6.2 (legal modes), §7.4 (plot-manager), D-016 (the same latent-authority split at the structural level), the auditor (phase 8), D-007 (still open).
**Impact:** GM agent behavior/prompts, auditor, the override protocol (`COMPONENTS.md`), plot-manager.

## D-009 · Canon ledger: separate store vs. view over events · Open · 2026-06-17
**Question:** Is the canon ledger a distinct store, or a query over committed-and-disclosed events?
**Options:** (a) Separate materialized store. (b) A view over the event log.
**Recommendation:** Lean (b) for single-source-of-truth, consistent with D-001's reasoning; materialize only if performance demands.
**Impact:** Canon ledger, fact-extraction, auditor.

## D-010 · Proposal/action queue: transient buffer vs. events on the log · Resolved · 2026-06-17
**Question:** Where do agents' proposed actions live between proposal (beat-loop step 3) and commit (steps 6–9) — on the append-only event log, or in a separate buffer?
**Options:** (a) Uncommitted events on the event log, marked `proposed`. (b) A distinct transient, non-authoritative proposal buffer the mediator drains each beat.
**Decision:** (b). Proposals are candidates, not truth. Putting them on the authoritative log pollutes "the log is historical truth" and risks un-audienced proposals entering belief projections — an omniscience leak by the back door. A proposal becomes an event only once resolved and committed, at which point its audience is computed.
**Rationale:** Consistent with D-001/D-009's single-authoritative-source stance and with principles 1 (determinism boundary) and 2/3 (POV partitioning / blackboard).
**Impact:** Blackboard topology (CORE §4.3), beat loop (§5 steps 3/9), data model (§8), orchestrator, the `COMPONENTS.md` action-queue entry.

## D-011 · Disposition-delta recognition: deterministic rules vs. model-proposed · Open · 2026-06-17
**Question:** The disposition engine is the authoritative writer of event-linked deltas — but how is it decided *which* logged event triggers *which* delta on *which* axis?
**Options:** (a) A deterministic rule table over engine-legible events (redirected damage → +trust, etc.). (b) A model proposes deltas from ambiguous social/fictional cues, which the engine commits as event-linked changes. (c) Both, split by whether the trigger is mechanically legible.
**Recommendation:** Lean (c) — deterministic rules for engine-legible triggers; model-proposed deltas for purely social cues, always committed through the engine so every delta stays auditable and event-linked. Defer until the disposition system (phase 10) is built.
**Impact:** Disposition engine, rules engine, context assembly, EV considerations (relates to D-004).

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

## D-014 · Generative scene imagery · Open · 2026-06-18
**Question:** Should the interface generate an AI image at each major scene change to set scene and tone (no mechanical/tracking role)?
**Options:** (a) Text + voice only (the CORE §12 v1 non-goal as written). (b) An impressionistic per-scene image generated via API at scene transitions, mood-setting only.
**Recommendation:** Defer to the interface phase (11) — it is pure downstream rendering and touches no authoritative state. If adopted, two constraints are load-bearing: (1) build the image prompt from the *player's* belief store / canon, never GM hidden state, or the picture leaks secrets through the back door (principle 2); (2) treat the image as narration — keep it impressionistic and seeded from committed scene facts so it can't silently contradict canon (e.g. depict a different guard count) (principle 4). Needs a definition of "major scene change" (zone/scene transition, or an explicit GM scene declaration) and a per-image cost/latency budget. Softens the §12 "no graphics in v1" non-goal → a v1.x feature, not v1.
**Relates to:** CORE §12 (graphics non-goal), channel router / interface + TTS, D-005 (cost/latency budget).
**Impact:** Interface / channel router; an image-generation service; scene-change detection.

## D-015 · Configurable seats: human/AI in any role, multi-participant · Open · 2026-06-18
**Question:** Should a session let the human assign which seats (GM, each teammate, NPCs) are human vs AI — including the human as GM with AI players, or several humans on one team with an AI GM?
**Why the architecture is friendly:** the blackboard topology (§4.3) and POV partitioning already make every seat just a POV (belief store) plus a proposal source; the determinism boundary is indifferent to whether a proposal came from a human client or a model agent. CORE §12 already commits that the architecture "must not preclude" multi-human.
**Options:** (a) Keep the fixed shape (one human player; AI GM + AI teammates). (b) Generalize to N seats, each human-or-AI, in any role, set by session config.
**Recommendation:** Target (b), but split the work. The cheap, high-leverage part is to model a role-agnostic **participant/seat** abstraction (POV + proposal source) when building character agents (phase 6) and the orchestrator (phase 7), so "human = the player, AI = everyone else" is never hardcoded and later unwound. Defer the heavy part — multi-client networking, per-seat identity/auth, concurrent-turn arbitration and sync — to the interface phase (11)+. Note: human-as-GM is a useful stress test of the honesty machinery — the deterministic core would hold a *human* GM to canon via the auditor exactly as it does an AI GM.
**Relates to:** CORE §12 (multi-human must-not-preclude), §4.3 blackboard, character agents (phase 6), orchestrator (phase 7), D-006 (NPC handling), interface (phase 11).
**Impact:** A participant/seat abstraction, orchestrator turn routing, the agent layer (agents become optional per seat), interface (multi-client), identity/auth.

## D-016 · Plot-graph ownership: single authority vs. distributed proposal · Open · 2026-06-18
**Question:** Who owns the plot graph — a single authority that holds and edits it, or shared persistent state that multiple agents read and propose revisions to, with something arbitrating coherence?
**Context:** Plot is held as a *loose structure* — fronts, factions, clocks, unresolved tensions (standing forces with momentum), not a fixed event sequence (§7.4; already the design). Plot **revision** is a first-class operation: promote a player thread into the standing structure, escalate a faction, retire a stale front, fold an accident into the throughline — but only above the canon line (hidden future is fluid; revealed past is immutable — §7.4 / §6.2 forbidden move). "Retroactively" therefore means re-*interpreting* and connecting, never changing what players were already told.
**Options:** (a) Single authority — the plot-manager holds and edits the plot alone. (b) Distributed proposal + centralized coherence-check — any agent may *propose* a plot revision; one authoritative writer commits it after a coherence-check.
**Recommendation:** (b), realized as the **disposition pattern (D-004 / §7.5) applied to plot**: the **plot-manager is the single authoritative writer**; other agents (GM, character agents, disposition engine) *propose* revisions through it; coherence is enforced by the **canon-ledger boundary** (the phase-2 consistency-check — plot may never contradict canon) plus the **auditor** (phase 8). This mirrors, at the structural level, the felt-agency / latent-authority split D-008 sets moment-to-moment (blackboard, §4.3: agents propose to a mediator, never write shared state directly).
**Risk to weigh:** the hard part is salience, not plumbing. The plot-manager must *evaluate* player input for promotion against an interest/salience threshold (the interest-signal accumulator), not promote everything — or the world bloats into incoherence (everything matters → nothing matters). The "obligation" is to evaluate and let the worthy rise, not to promote all input.
**Relates to:** §4.3 (blackboard), §7.4 (plot-manager), D-004 / §7.5 (the pattern being reused), D-006 (NPC proposal handling), D-008 (same principle, moment-to-moment), the auditor (phase 8). Build deferred to phase 9; ownership shape recorded now.
**Impact:** Plot-manager (sole writer), plot graph store, GM / character agents (propose), auditor (coherence gate), beat-loop divergence handling.

## MVP Implementation Defaults

These are implementation defaults used until a decision is formally resolved. They are not final design resolutions unless moved into `Resolved` with an updated decision record.

- **D-001:** Implement belief stores as read-time projections from the event log, with optional cache.
- **D-002:** *Resolved* — fiction-positional: position as Truths within the zone graph, no grid and no formal band system. Proximity is qualitative, feeding Ledger Position / Ground.
- **D-003:** Treat routine positioning queries as free OOC clarification for MVP; later support IC assessment for exploration-heavy scenes.
- **D-004:** *Resolved* — couple disposition through Edge/Bonds, never a passive modifier and never a separate currency. Defer building it to phase 10, after the rules engine's Edge/Bond/compel surfaces and the EV audit exist.
- **D-005:** Start with director-picks-next spotlight. Prototype agent bidding only after a cost/latency budget exists.
- **D-006:** Let the GM puppet walk-on NPCs for MVP; promote recurring NPCs later.
- **D-007:** Start with GM-emitted structured commitment blocks for reliability; later prototype post-hoc extraction. *(Exercised in phase 2: `CommitPipeline.commit` takes structured `Commitment`s directly; no prose-extraction pass exists yet.)*
- **D-008:** *Resolved* — AI GM holds override authority, human is co-authority/backstop; override is the reserved exception, normal authority exercised via Add/Causation and plot-bending. Mechanism (logged override + reason) built in phase 2.
- **D-009:** Implement the canon ledger as a view over committed-and-disclosed events unless performance requires materialization. *(Exercised in phase 2: `canon_ledger()` is a pure fold over the log, not a materialized store.)*
- **D-012:** Thin zone-based propagation — binary open/closed connections, whole-zone audibility, one-hop loud carry, lit/dark line of sight, closeness Truths for whisper. *(Built in phase 3; stress-tested. Overhears degrade to a vague hint (fail-safe under-disclosure); richer attenuation/occlusion and "fully overheard content" deferred.)*
- **D-013:** *Resolved* — per-POV contiguous index in `project_for` (option (b)); the global-`sequence` side-channel is closed.

---

## Resolved

- **D-002** · Spatial model → fiction-positional (position as Truths in the zone graph; no grid, no formal band system) · 2026-06-17.
- **D-004** · Disposition→mechanics coupling → through FABLE's native Edge/Bonds; no passive modifier, no separate "Strings" currency · 2026-06-17.
- **D-010** · Proposal/action queue → transient, non-authoritative buffer (not events on the log) · 2026-06-17.
- **D-013** · Per-POV event ordering → per-POV contiguous index in `project_for`; global-`sequence` side-channel closed · 2026-06-18.
- **D-008** · Override authority → AI GM holds it (human co-authority/backstop); override is the reserved exception, authority normally latent via Add/Causation + plot-bending · 2026-06-18.
