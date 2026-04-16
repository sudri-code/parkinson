#!/usr/bin/env bash
# Smoke test: structural lint on empty/real vault returns exit 0.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

echo "[test_lint_structural] DATA_DIR=${PARKINSON_DATA_DIR:-$REPO/data}"

uv run --quiet python scripts/lint.py --structural-only
echo "[test_lint_structural] OK"
