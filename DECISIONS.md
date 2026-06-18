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

## D-008 · Override authority · Open · 2026-06-17
**Question:** Who may invoke a deliberate override of committed state, and how is it surfaced and logged?
**Options:** A human director; the GM agent itself; a separate meta-agent — and in each case, how the log marks it intentional so the auditor reads fiat, not bug.
**Recommendation:** Undecided. At minimum, every override is logged as intentional with an author; the auditor keys off that flag.
**Impact:** Auditor, event-log schema, GM authority model.

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

## MVP Implementation Defaults

These are implementation defaults used until a decision is formally resolved. They are not final design resolutions unless moved into `Resolved` with an updated decision record.

- **D-001:** Implement belief stores as read-time projections from the event log, with optional cache.
- **D-002:** *Resolved* — fiction-positional: position as Truths within the zone graph, no grid and no formal band system. Proximity is qualitative, feeding Ledger Position / Ground.
- **D-003:** Treat routine positioning queries as free OOC clarification for MVP; later support IC assessment for exploration-heavy scenes.
- **D-004:** *Resolved* — couple disposition through Edge/Bonds, never a passive modifier and never a separate currency. Defer building it to phase 10, after the rules engine's Edge/Bond/compel surfaces and the EV audit exist.
- **D-005:** Start with director-picks-next spotlight. Prototype agent bidding only after a cost/latency budget exists.
- **D-006:** Let the GM puppet walk-on NPCs for MVP; promote recurring NPCs later.
- **D-007:** Start with GM-emitted structured commitment blocks for reliability; later prototype post-hoc extraction.
- **D-008:** Do not allow unstructured overrides in MVP. If an override is needed, require an explicit logged override event with author and reason.
- **D-009:** Implement the canon ledger as a view over committed-and-disclosed events unless performance requires materialization.

---

## Resolved

- **D-002** · Spatial model → fiction-positional (position as Truths in the zone graph; no grid, no formal band system) · 2026-06-17.
- **D-004** · Disposition→mechanics coupling → through FABLE's native Edge/Bonds; no passive modifier, no separate "Strings" currency · 2026-06-17.
- **D-010** · Proposal/action queue → transient, non-authoritative buffer (not events on the log) · 2026-06-17.
