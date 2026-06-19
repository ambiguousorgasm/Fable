# FABLE Table Engine

An AI-facilitated tabletop RPG engine for one human player. Runs a complete session with an AI Game Master, AI teammates, deterministic rules and world state, differential information, and per-character channels — entirely through Python and an Anthropic API key.

**Code owns truth; models own voice.** Dice, rules, world state, and the event log are deterministic Python. Language models produce narration, proposals, and judgment under ambiguity — but they never decide outcomes and never see information they are not entitled to.

## Quick setup

```sh
git clone <repo-url> fable-table-engine
cd fable-table-engine
bash scripts/setup.sh
```

The setup script checks Python 3.11+, creates `.venv`, installs `pip install -e ".[dev]"`, and copies `.env.example` to `.env`. Then add your Anthropic API key to `.env`.

### Manual setup

```sh
python3 -m venv .venv           # requires Python >= 3.11
./.venv/bin/pip install -e ".[dev]"
cp .env.example .env            # add ANTHROPIC_API_KEY
```

## Run the tests

```sh
./.venv/bin/python -m pytest -q
```

All tests mock model calls — no API key required to run the suite.

## Current status

The deterministic substrate, event log, access model, perception model, context assembly, GM split, character agents, orchestrator, auditor, plot manager, persistence layer, save migration, context budgeting, cost telemetry, and lorebook injection are built and tested.

The current public build is a late text-only beta candidate. It is intended for developer review and early testing, not polished end-user play.

## Secrets policy

- `.env` and `.env.*` are git-ignored and must never be committed.
- `secrets/`, credential files, API keys, and private tokens must never be committed.
- Campaign uploads, generated transcripts, and runtime databases are data files — keep them out of version control.

## Key source directories

```
src/fable_table_engine/     Core engine (Python package)
tests/                      Full test suite
schemas/                    JSON schemas for events, world state, campaigns
static/                     Reference materials (rules PDF)
scripts/                    Dev tooling (setup, public tree builder)
public/                     Public-facing README and docs
```

## Documentation

- `public/docs/setup.md` — detailed setup and configuration
- `public/docs/architecture.md` — system design overview
