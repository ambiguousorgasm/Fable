# Changelog

Append-only history of meaningful changes to the design and the build. Newest first. Each entry: date, what changed, and *why*. Reference decision IDs (`D-00x`) and components where relevant. Per the change protocol (`00_README.md`), every component or architecture change lands an entry here.

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
