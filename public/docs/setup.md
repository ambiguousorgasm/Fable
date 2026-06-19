# Setup

## Prerequisites

- Python 3.11 or higher
- An Anthropic API key for live sessions — get one at [console.anthropic.com](https://console.anthropic.com/)

The current live model provider is Anthropic. The engine has a provider-adapter boundary and per-role model routing, but non-Anthropic provider adapters are not implemented yet.

## Install

```sh
git clone <repo-url> fable-table-engine
cd fable-table-engine
bash scripts/setup.sh
```

Or manually:

```sh
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

## Environment variables

Copy the example file and supply your API key:

```sh
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=your-key-here
```

The engine reads `ANTHROPIC_API_KEY` from the environment at runtime. The `.env` file is never committed.

## Verify installation

```sh
./.venv/bin/python -m pytest -q
```

All tests should pass without a live API key — tests mock all model calls.

## Start a text session

After adding `ANTHROPIC_API_KEY` to `.env`, run:

```sh
./.venv/bin/fable-play
```

At the home screen, use:

```text
new
```

to start a blank session, or:

```text
resume 1
```

to resume the first saved session.

## Configuration

The engine ships with built-in defaults for every setting. Zero configuration is needed to run tests.

For live sessions, model selection and per-role configuration live in `settings/`. Override any setting by creating the relevant JSON file:

**`settings/models.json`** — applies to all campaigns:

```json
{
  "gm_adjudicator_model":        "claude-opus-4-8",
  "gm_narrator_model":           "claude-opus-4-8",
  "gm_world_simulator_model":    "claude-opus-4-8",
  "character_agent_default_model": "claude-opus-4-8",
  "auditor_model":               "claude-haiku-4-5-20251001",
  "social_interpreter_model":    "claude-sonnet-4-6"
}
```

**`settings/campaigns/<campaign_id>.json`** — per-campaign overrides (same keys).

Available keys and their defaults are in `src/fable_table_engine/settings.py` → `SettingsRegistry.DEFAULTS`.

## Context and cost limits

Per-role token caps and event windows are also configurable via `settings/models.json`. Default keys:

```
gm_adjudicator_max_tokens      gm_adjudicator_event_window
gm_narrator_max_tokens         gm_narrator_event_window
character_agent_max_tokens     character_agent_event_window
auditor_max_tokens             auditor_event_window
social_interpreter_max_tokens  social_interpreter_event_window
plot_manager_max_tokens        plot_manager_event_window
```

Cost ceiling (advisory by default):

```json
{ "session_cost_ceiling_usd": "5.00" }
```

When cumulative session cost exceeds the ceiling, `PlayInterface.render_status()` shows a warning.
