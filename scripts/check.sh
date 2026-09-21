#!/usr/bin/env bash
# The four checks that must pass before a push. CI runs exactly this script.
# pipefail matters: a check piped through anything else must still fail the script.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
