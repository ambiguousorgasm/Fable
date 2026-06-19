# FABLE Table Engine

A text-based AI-facilitated tabletop RPG engine for one human player. Runs a complete session with an AI Game Master, AI teammates, deterministic rules and world state, differential information, and per-character channels — entirely through Python and an Anthropic API key.

## What it does

**Code owns truth; models own voice.**

- **Deterministic core.** Dice rolls, rules resolution, world state mutations, and the event log are handled by plain Python — not language models. Models never decide outcomes.
- **Differential knowledge.** Each participant (player, AI GM, AI teammates) sees only the events and facts they are entitled to. Secrets are enforced structurally, not by asking models to "pretend not to know."
- **Split GM.** The adjudicator (cold) decides what is at stake and emits structured outcomes. The narrator (warm) writes prose — and never sees the dice.
- **Append-only event log.** Every action, dice roll, adjudication, committed fact, and narration is logged. World state and belief stores are derived views over the log.
- **Persistent sessions.** Sessions save to SQLite and resume across restarts with automatic schema migration.
- **Cost-bounded.** Per-role context windows, token estimation, and per-session cost ceilings are built in.

## Requirements

- Python 3.11 or higher
- An [Anthropic API key](https://console.anthropic.com/)

## Quick setup

```sh
git clone <repo-url> fable-table-engine
cd fable-table-engine
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
cp .env.example .env          # then add your ANTHROPIC_API_KEY
```

## Run the tests

```sh
./.venv/bin/python -m pytest -q
```

All tests should pass.

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
