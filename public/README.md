# FABLE Table Engine

A text-first AI tabletop RPG engine for one human player, an AI Game Master, and optional AI companion characters.

**Code owns truth; models own voice.** Models may propose, narrate, and roleplay, but deterministic code owns rules, dice, state, visibility, persistence, and canon.

## Built systems

- Append-only event log
- Deterministic dice and rules substrate
- Audience and visibility filtering (differential knowledge)
- Per-character belief and context projection
- Cold adjudicator / warm narrator split
- Character agents with per-POV context
- Orchestrator and scene cadence
- Auditor (pre-commit and post-narration)
- Typed effect executor
- Campaign package loading
- Plot graph and disposition systems
- Text play interface
- Settings and per-role model routing
- Context budgeting and cost tracking
- Lorebook and world-info injection
- Save/resume with automatic schema migration
- Golden transcript regression tests

## Current status

Core systems are complete through Phase 22 (release hardening). Remaining work is replay/property tests, security review, portability checks, and playtesting. Not yet stable for production use.

## Requirements

- Python 3.11 or higher
- An Anthropic API key for live sessions

The current live model provider is Anthropic. The engine has a provider-adapter boundary and per-role model routing, but non-Anthropic provider adapters are not implemented yet.

## Quick setup

```sh
git clone <repo-url> fable-table-engine
cd fable-table-engine
bash scripts/setup.sh
```

Or manually:

```sh
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
cp .env.example .env
```

Then add your `ANTHROPIC_API_KEY` to `.env`.

## Run the tests

```sh
./.venv/bin/python -m pytest -q
```

All tests use mocked model calls. No API key is required to run the suite.

## Run a text session

After setup, add your Anthropic API key to `.env`, then run:

```sh
./.venv/bin/fable-play
```

The current runner supports one human player, new/resumed SQLite sessions, text input, `/save`, `/history`, `/status`, `/settings`, and `/quit`.

## Documentation

- [`docs/setup.md`](docs/setup.md) — detailed setup and configuration
- [`docs/architecture.md`](docs/architecture.md) — system design overview

## Key source directories

```
src/fable_table_engine/     Core engine (Python package)
tests/                      Full test suite
schemas/                    JSON schemas for events, world state, campaigns
static/                     Reference materials
```

## FABLE rules

The engine implements the FABLE tabletop ruleset. A reference copy of the rules is in `static/fable_rules.pdf`.

## License

See repository for license information.
