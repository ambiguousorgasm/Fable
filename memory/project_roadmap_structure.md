---
name: project-roadmap-structure
description: Current phase numbering (Phases 9–22) and what each built phase maps to; adopted 2026-06-18 from uploads/f.md
metadata:
  type: project
---

The original IMPLEMENTATION_PLAN.md Phase 9–11 sequence was replaced 2026-06-18 with a 14-phase stabilization plan (Phases 9–22) from `uploads/f.md`. Full specs (purpose, included components, non-goals, adversarial acceptance tests, exit gates) are in that file.

**Renumbering of old phases:**
- Old Phase 9 (plot-manager, Built) → **Phase 18** (Plot-manager Runtime)
- Old Phase 10 (disposition, Designed) → **Phase 19** (Disposition Graph Core)
- Old Phase 11 (interface, Partial substrate) → **Phase 21** (Production Text-Channel API)

**Phases 1–9: all Built (294 tests)**

**Current milestone: Phase 10 — Atomic Session + Replayable Scene State**
- Gaps: beat loop partial-commit window (facts commit at step 6 before post-narration audit closes); scene state not persisted (defaults permissive on restart — secrecy failure).
- Partial: `SQLiteEventLog.transaction()` exists (D-023).

**Upcoming dependency chain:**
10 → 11 (epistemic commitment) → 12 (typed effect executor) → 13 (FABLE resolution slice) → 14 (provider gateway) → 15 (human-seat adapter) → 16 (scene cadence) → 17 (campaign package) → 18 (plot manager) → 19 (disposition core) → 20 (social interpretation) → 21 (text-channel API) → 22 (beta hardening)

**Why:** The original three-phase tail was too coarse to safely sequence secrecy, persistence, rules, telemetry, and interface work. Each phase in the new plan has one durable outcome, explicit non-goals, and a falsifiable exit gate.

**How to apply:** When selecting the next implementation task, check this order and IMPLEMENTATION_PLAN.md's current milestone. Do not pull Phase N+1 work into Phase N.
