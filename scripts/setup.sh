#!/usr/bin/env bash
# setup.sh — bootstrap the FABLE Table Engine development environment
set -euo pipefail

REQUIRED_MAJOR=3
REQUIRED_MINOR=11

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()    { printf '\033[0;34m[setup]\033[0m %s\n' "$*"; }
success() { printf '\033[0;32m[setup]\033[0m %s\n' "$*"; }
warn()    { printf '\033[0;33m[setup]\033[0m %s\n' "$*"; }
die()     { printf '\033[0;31m[setup]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Check Python version
# ---------------------------------------------------------------------------

info "Checking Python version..."

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        VERSION=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        MAJOR=$(echo "$VERSION" | cut -d. -f1)
        MINOR=$(echo "$VERSION" | cut -d. -f2)
        if [ "${MAJOR:-0}" -gt "$REQUIRED_MAJOR" ] || \
           { [ "${MAJOR:-0}" -eq "$REQUIRED_MAJOR" ] && [ "${MINOR:-0}" -ge "$REQUIRED_MINOR" ]; }; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    die "Python ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+ is required. Install it from https://python.org/downloads/ and retry."
fi

PYTHON_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
success "Found Python $PYTHON_VERSION ($PYTHON)"

# ---------------------------------------------------------------------------
# 2. Create .venv if missing
# ---------------------------------------------------------------------------

VENV=".venv"

if [ -d "$VENV" ]; then
    info "Virtual environment already exists at $VENV — skipping creation."
else
    info "Creating virtual environment at $VENV..."
    "$PYTHON" -m venv "$VENV"
    success "Virtual environment created."
fi

# ---------------------------------------------------------------------------
# 3. Install package and dev dependencies
# ---------------------------------------------------------------------------

info "Installing fable-table-engine[dev]..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install -e ".[dev]"
success "Package installed."

# ---------------------------------------------------------------------------
# 4. Environment file
# ---------------------------------------------------------------------------

if [ -f ".env" ]; then
    info ".env already exists — skipping copy."
else
    if [ -f ".env.example" ]; then
        cp .env.example .env
        warn ".env created from .env.example. Open it and set ANTHROPIC_API_KEY before running live sessions."
    else
        warn ".env.example not found. Create .env manually with ANTHROPIC_API_KEY=<your-key>."
    fi
fi

# ---------------------------------------------------------------------------
# 5. Next steps
# ---------------------------------------------------------------------------

echo ""
success "Setup complete."
echo ""
echo "  Next steps:"
echo ""
echo "    # Run the test suite (no API key required):"
echo "    ./.venv/bin/python -m pytest -q"
echo ""
echo "    # Edit .env and add your Anthropic API key for live sessions:"
echo "    \$EDITOR .env"
echo ""
echo "    # Start a playtest session:"
echo "    ./.venv/bin/python -c 'from fable_table_engine import PlaytestSession; print(\"Engine ready.\")'"
echo ""
