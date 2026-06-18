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

## D-002 · Spatial model: abstract range bands vs. coordinates/grid · Open · 2026-06-17
**Question:** How is position/distance represented in world state?
**Options:** (a) Abstract range bands (close/near/far). (b) Coordinates or a grid.
**Recommendation:** Match FABLE's native spatial abstraction; the architecture is agnostic. Decide once FABLE's positioning rules are fixed.
**Ruleset note (2026-06-17, `fable_engine.md` v4):** FABLE has *no* grid or coordinates. Position is fictional — surfaced mechanically only through the Ledger **Position** category (§10) and the **Ground** cost register (§7), and persisted as **Truths** (§12). This favors (a), or something looser than formal range bands. Still Open pending confirmation; note the perception model (phase 3) and distance queries (scenario B) must then work against fictional/Truth-based position, not metric distance — the "100 ft to the tower" example becomes a committed Truth, not a coordinate.
**Impact:** World state, rules engine, perception model, distance-query handling.

## D-003 · Positioning queries: free OOC read vs. in-character assessment · Open · 2026-06-17
**Question:** Is "how far am I from X?" a free clarification, or an in-character action? And is the map itself fogged?
**Options:** (a) Free OOC read, no fiction cost. (b) IC assessment that costs a beat and enables map fog-of-war (unscouted distances unknown).
**Recommendation:** Lean (a) for routine play; consider (b) selectively for exploration-heavy scenes where not-knowing is the point.
**Impact:** Adjudicator, perception model, world state (map visibility).

## D-004 · Disposition→mechanics coupling: passive modifier vs. Strings · Open · 2026-06-17
**Question:** How does disposition affect mechanics, if at all?
**Options:** (a) Always-on passive modifier on cooperation/social rolls. (b) Strings — a spendable relational resource for one-time, legible effects.
**Recommendation:** (b) Strings. A passive modifier corrupts EV and incentivizes approval-farming. Whatever is chosen must pass the FABLE EV audit before going live.
**Ruleset note (2026-06-17, `fable_engine.md` v4):** FABLE already has a spendable relational-leverage economy — **Edge** (capped at 3, §13) plus **Bonds** as Held Truths (§12). Invariant 18 and the §22 Mode rule explicitly reject new resolution subsystems ("express it through the core surfaces or reject it as subsystem growth"). So a *separate* "Strings" mechanic likely violates the ruleset's own anti-bloat invariant; disposition should probably couple by routing **through** Edge/Bonds (e.g. disposition state gates Bond invocation, compels, or Edge gain) rather than adding a new currency. This reframes option (b) rather than discarding it. Still Open; user call. **Knock-on:** if accepted, update CORE §3/§7.5 where "Strings" is named as the preferred coupling, and the phase-10 STATUS note.
**Impact:** Disposition graph, rules engine, economy/EV balance.

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
- **D-002:** Use abstract range bands for the MVP unless the FABLE rules implementation demands coordinates.
- **D-003:** Treat routine positioning queries as free OOC clarification for MVP; later support IC assessment for exploration-heavy scenes.
- **D-004:** Do not implement passive disposition modifiers. If mechanics are needed, prototype spendable Strings only after the core EV audit exists.
- **D-005:** Start with director-picks-next spotlight. Prototype agent bidding only after a cost/latency budget exists.
- **D-006:** Let the GM puppet walk-on NPCs for MVP; promote recurring NPCs later.
- **D-007:** Start with GM-emitted structured commitment blocks for reliability; later prototype post-hoc extraction.
- **D-008:** Do not allow unstructured overrides in MVP. If an override is needed, require an explicit logged override event with author and reason.
- **D-009:** Implement the canon ledger as a view over committed-and-disclosed events unless performance requires materialization.

---

## Resolved

- **D-010** · Proposal/action queue → transient, non-authoritative buffer (not events on the log) · 2026-06-17.
