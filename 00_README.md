# FABLE Table Engine — Project Directory

This directory holds the design for the FABLE Table Engine: a system that simulates a live tabletop RPG session with an AI Game Master, AI teammates, and a reactive world, for one human player. This README is the map and the maintenance contract. Read it first.

## What's here

| File | Responsibility | Change rate |
|---|---|---|
| `FABLE_Table_Engine_Blueprint.md` | **CORE.** Authoritative spine: goal, philosophy, the five principles, access model, beat loop, architecture, subsystems, roadmap, success criteria. | Slow / deliberate |
| `COMPONENTS.md` | Authoritative **registry** of every model, service, and store — role, reads, writes, depends-on, and *depended-on-by*. The single place to answer "is this still needed, and what breaks if it goes." | Medium |
| `DECISIONS.md` | Living **decision log** (ADR-lite): open and resolved design forks, with options, recommendation, rationale, date. | Medium |
| `STATUS.md` | **Build tracker**: design-vs-implemented state per component and roadmap phase. Descriptive, not normative. | Fast |
| `CHANGELOG.md` | Append-only **history** of meaningful changes to the design and the build. | Fast (append) |
| `IMPLEMENTATION_PLAN.md` | Converts the CORE roadmap into concrete coding milestones (deliverables, non-goals, acceptance tests). Defines *what to build next*; `STATUS.md` tracks *what is built*. | Medium |
| `README.md` | Standard repo entry point for humans/tools. Delegates to this file for the full map. | Rare |
| `CLAUDE.md` | Claude Code operating contract: required reading, source-of-truth hierarchy, change protocol, implementation priorities, architecture invariants, collaboration stance, Python/safety rules. | Rare |
| `00_README.md` | This file: directory map and the change protocol. | Rare |

The files are split by **change-rate and coupling**, not by topic. CORE is kept whole because its parts are tightly interdependent; the satellites are separated because each changes at a different rate and is loosely coupled to the rest. Subsystem deep-dives (e.g. a dedicated perception-model spec) get their own files under a future `subsystems/` folder *only once their detail outgrows the CORE section* — until then they live in CORE.

**Code and config.** Alongside the design docs: `schemas/` (JSON Schema skeletons for event, world_state, character_sheet — skeletons that track CORE §8, not an independent source of truth), `docs/MCP_SETUP.md` (MCP notes; none configured by default), `src/` and `tests/` (the Python package and its tests), `pyproject.toml`, `.claude/settings.json` (Claude Code permissions), and the standard `.gitignore`, `.env.example`, `.mcp.json`. These follow the build, not the design — code state is tracked in `STATUS.md`.

## Precedence

**Where any file conflicts with CORE, CORE wins** until CORE is consciously revised. Satellites hold *detail and state*; CORE holds *structure and intent*. Never let a satellite silently contradict CORE — reconcile, or revise CORE deliberately and log it.

## Change protocol

Follow this whenever a component (model, service, or store) is **added, removed, or modified**, or whenever the architecture changes. The point is to make "did every file get updated?" a procedure rather than a hope.

1. **`COMPONENTS.md` first.** Add/edit/remove the component's registry entry. Then reconcile every *other* entry's `depended-on-by` and `depends-on` lines — a removed component must vanish from every dependency list, and a new dependency must appear on both sides.
2. **Reconcile CORE.** Update wherever the component appears: the layer architecture (§4), the beat loop (§5), the access matrix (§6.4), the data model (§8), and the roadmap (§10). Use the removed/changed component's `depended-on-by` list as the checklist of what to touch.
3. **Spokes.** If a `subsystems/` file covers it, update that too (and keep its summary in CORE in sync).
4. **`CHANGELOG.md`.** Add a dated entry: what changed, and *why*.
5. **`STATUS.md`.** Update if the build state changed.
6. **`DECISIONS.md`.** If the change resolves an open decision or opens a new one, record it.
7. **Verify precedence.** Re-check that nothing now contradicts CORE.

A change that touches only one file is usually a change that wasn't fully propagated. Removing a model almost always touches CORE §4/§5/§6, `COMPONENTS.md`, and `CHANGELOG.md` at minimum.

## For an AI editor working in this project

Always load CORE and this README. Before reasoning about or changing any component, consult `COMPONENTS.md` for its dependency surface. After any change, walk the change protocol above in order. Treat the `depended-on-by` field as authoritative for impact analysis: if you remove a component, you are responsible for every entry that listed it.
