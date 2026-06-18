# FABLE Table Engine

This repository contains the design and implementation scaffold for the **FABLE Table Engine**: an AI-facilitated tabletop RPG table for one human player, with an AI Game Master, AI teammates, deterministic rules/state, differential information, and per-character channels.

## Start here

- `00_README.md` — project map, precedence rules, and change protocol.
- `FABLE_Table_Engine_Blueprint.md` — CORE architecture and design authority.
- `CLAUDE.md` — Claude Code operating instructions.
- `STATUS.md` — current design-vs-build state.
- `IMPLEMENTATION_PLAN.md` — current milestone and concrete next steps.
- `COMPONENTS.md` — component registry and dependency impact map.
- `DECISIONS.md` — open/resolved design decisions and MVP defaults.
- `CHANGELOG.md` — append-only history of meaningful changes.

## Setup

This project uses a local virtual environment at `./.venv` (mandated by `CLAUDE.md`; do not use global Python for project commands).

```sh
python3 -m venv .venv            # requires Python >= 3.11
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m pytest -q  # phase-1 contracts are skipped until implemented
```

## Current build posture

The design is intentionally architecture-first. The implementation should begin with the deterministic substrate before any agent/UI polish:

1. Event log
2. World-state skeleton
3. Dice service
4. Minimal rules-engine interface
5. Audience/visibility filtering
6. Commit/canon boundary

Do **not** build agent cleverness, TTS, plot management, or UI polish before the deterministic core and access model are testable.

## Claude Code usage

Open this directory in Claude Code and begin by asking it to read `CLAUDE.md`, `00_README.md`, `STATUS.md`, and the CORE blueprint. The project-level Claude Code settings live in `.claude/settings.json`.

## MCP

No live MCP servers are configured by default. Add project-scoped MCP servers only when you know the real tools you want to use. See `docs/MCP_SETUP.md`.
