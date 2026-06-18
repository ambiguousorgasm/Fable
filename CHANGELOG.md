# Changelog

Append-only history of meaningful changes to the design and the build. Newest first. Each entry: date, what changed, and *why*. Reference decision IDs (`D-00x`) and components where relevant. Per the change protocol (`00_README.md`), every component or architecture change lands an entry here.

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
- **Minimal rules engine** (`rules.py`): the cold adjudicator slice — `resolve_check` rolls 3d6+Skill vs TN via the dice service, reads the FABLE band (`fable_engine.md` §5), and logs a `resolution` event linked to its dice event via `derived_from`. Deliberately excludes Exposure/Effect/Trade/Ledger/Clocks/Edge (later phases).
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

## 2026-06-17 — Integrate the FABLE ruleset (`fable_engine.md`, Engine Schema v4)

The ruleset doc was added to the repo; integrated it as canon for the rules-engine component *without implementing any of it* (phase 1 remains a minimal rules-engine interface, not FABLE's math).

- Registered `fable_engine.md` in the `00_README.md` file map and referenced it from CORE §3 (rules engine), §8 (character sheet), the appendix, and the `COMPONENTS.md` rules-engine and character-sheet entries. It is authoritative for *rules mechanics*; CORE stays authoritative for *architecture*. *Why:* it was an orphan — referenced by nothing — exactly the map-drift the change protocol exists to catch.
- Reconciled dead terminology: "**stance(s)**" (from an older FABLE draft) is not a v4 surface; replaced its references in CORE §3/§8/appendix and `COMPONENTS.md` (×2), and rebuilt `schemas/character_sheet.schema.json` to the actual anatomy (Concept · Skills 0–4 · Traits · Bonds · Drive · Question · Gear · Stress · Scars · Edge). The closest live analog to the old "stance" is the **Trade** (§9).
- Anchored the **stakes gate** (CORE §3/§7.2/beat-loop step 4) to its mechanical definition: FABLE's **Exit Check** + the *no-empty-rolls* rule (`fable_engine.md` §11, §5).
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

- Initialized a dedicated git repository at the project root (`git init -b main`). *Why:* the scaffold was previously untracked inside the `/home/audrey` repo, which made the project `.gitignore` inert, the CHANGELOG/commit-based change protocol moot, and any branch/PR workflow impossible. The project is now its own versioned repo.
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
