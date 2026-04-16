#!/usr/bin/env bash
# parkinson — bootstrap installer for macOS/Linux.
#
# Idempotent: re-running never overwrites existing data or settings.
# Creates data directories, copies templates, and prints hook-registration
# instructions.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

echo "parkinson installer — repo root: $REPO_ROOT"
echo ""

# ── 1. Guard: uv must be installed ────────────────────────────────────

if ! command -v uv >/dev/null 2>&1; then
    cat <<'EOF'
ERROR: `uv` is not installed or not on PATH.

Install with:
    curl -LsSf https://astral.sh/uv/install.sh | sh

Then re-run this installer.
EOF
    exit 1
fi
echo "✓ uv found: $(uv --version)"

# ── 2. Sync dependencies ──────────────────────────────────────────────

echo ""
echo "Syncing dependencies (uv sync)..."
uv sync --quiet
echo "✓ Dependencies installed in .venv/"

# ── 3. Resolve DATA_DIR ───────────────────────────────────────────────

DATA_DIR="${PARKINSON_DATA_DIR:-}"
if [ -z "$DATA_DIR" ] && [ -f "$REPO_ROOT/.parkinson-data-dir" ]; then
    DATA_DIR="$(head -n 1 "$REPO_ROOT/.parkinson-data-dir" | tr -d '[:space:]')"
fi
if [ -z "$DATA_DIR" ]; then
    DATA_DIR="$REPO_ROOT/data"
fi
# Expand ~
DATA_DIR="${DATA_DIR/#\~/$HOME}"

echo ""
echo "Data root: $DATA_DIR"

# ── 4. Create directory tree ──────────────────────────────────────────

mkdir -p \
    "$DATA_DIR/daily" \
    "$DATA_DIR/knowledge/concepts" \
    "$DATA_DIR/knowledge/connections" \
    "$DATA_DIR/knowledge/qa" \
    "$DATA_DIR/knowledge/instincts" \
    "$DATA_DIR/wiki" \
    "$DATA_DIR/raw/assets" \
    "$DATA_DIR/reports/agentshield" \
    "$REPO_ROOT/observations/archive" \
    "$REPO_ROOT/state/tool-counts"
echo "✓ Data directories created"

# ── 5. Copy templates (non-destructive, only if missing) ──────────────

copy_if_missing() {
    local src="$1"
    local dst="$2"
    if [ ! -f "$dst" ]; then
        cp "$src" "$dst"
        echo "  + $dst"
    fi
}

copy_if_missing "$REPO_ROOT/templates/projects.json"       "$DATA_DIR/projects.json"
copy_if_missing "$REPO_ROOT/templates/knowledge-index.md"  "$DATA_DIR/knowledge/index.md"
copy_if_missing "$REPO_ROOT/templates/knowledge-log.md"    "$DATA_DIR/knowledge/log.md"

echo "✓ Templates copied (missing files only)"

# ── 6. Hook registration ──────────────────────────────────────────────

SETTINGS_FILE="$HOME/.claude/settings.json"
TEMPLATE="$REPO_ROOT/examples/.claude/settings.json"

echo ""
if [ ! -f "$SETTINGS_FILE" ]; then
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    # Substitute placeholder with absolute repo path
    sed "s|__REPO_ROOT__|$REPO_ROOT|g" "$TEMPLATE" > "$SETTINGS_FILE"
    echo "✓ Created $SETTINGS_FILE with hooks wired to $REPO_ROOT"
else
    echo "ℹ $SETTINGS_FILE already exists — not overwriting."
    echo ""
    echo "  To add parkinson hooks, merge $TEMPLATE into it."
    echo "  Quick merge with jq (replace __REPO_ROOT__ first):"
    echo ""
    echo "    TMP=\$(mktemp)"
    echo "    sed 's|__REPO_ROOT__|$REPO_ROOT|g' $TEMPLATE > \$TMP"
    echo "    jq -s '.[0] * .[1]' $SETTINGS_FILE \$TMP > \${TMP}2"
    echo "    mv \${TMP}2 $SETTINGS_FILE && rm \$TMP"
    echo ""
    echo "  Or open both files and copy the \`hooks\` section manually."
fi

# ── 7. (Optional) parkinson-aware snippet for ~/.claude/CLAUDE.md ─────

CLAUDE_MD="$HOME/.claude/CLAUDE.md"
SNIPPET_MARKER="<!-- BEGIN: parkinson-instructions -->"

if [[ "${LANG:-}" == ru* ]] || [[ "${LC_ALL:-}" == ru* ]]; then
    SNIPPET="$REPO_ROOT/templates/global-claude-md-snippet.ru.md"
else
    SNIPPET="$REPO_ROOT/templates/global-claude-md-snippet.md"
fi

echo ""
if [ -f "$CLAUDE_MD" ] && grep -qF "$SNIPPET_MARKER" "$CLAUDE_MD"; then
    echo "✓ Parkinson snippet already present in $CLAUDE_MD"
elif [ ! -t 0 ]; then
    echo "ℹ Non-interactive shell — skipping CLAUDE.md prompt."
    echo "  To add parkinson-aware instructions later:"
    echo "    sed -e 's|__DATA_DIR__|$DATA_DIR|g' -e 's|__REPO_ROOT__|$REPO_ROOT|g' $SNIPPET >> $CLAUDE_MD"
else
    echo "Optional: append parkinson-aware instructions to $CLAUDE_MD"
    echo "  (helps Claude scan the SessionStart inject before answering 'what is X?')."
    echo ""
    echo "Snippet preview:"
    sed -e "s|__DATA_DIR__|$DATA_DIR|g" -e "s|__REPO_ROOT__|$REPO_ROOT|g" "$SNIPPET" | sed 's/^/  | /'
    echo ""
    read -r -p "Append now? [y/N] " reply
    case "$reply" in
        [yY]|[yY][eE][sS])
            mkdir -p "$(dirname "$CLAUDE_MD")"
            if [ -f "$CLAUDE_MD" ] && [ -s "$CLAUDE_MD" ]; then
                printf "\n" >> "$CLAUDE_MD"
            fi
            sed -e "s|__DATA_DIR__|$DATA_DIR|g" -e "s|__REPO_ROOT__|$REPO_ROOT|g" "$SNIPPET" >> "$CLAUDE_MD"
            echo "✓ Appended to $CLAUDE_MD"
            ;;
        *)
            echo "ℹ Skipped. Manually copy from $SNIPPET when ready."
            ;;
    esac
fi

# ── 8. Smoke check ────────────────────────────────────────────────────

echo ""
echo "Smoke check — resolved paths:"
uv run --quiet python scripts/config.py --print | head -12 | sed 's/^/  /'

# ── 9. Next steps ─────────────────────────────────────────────────────

cat <<EOF

Setup complete.

Next steps:
  1. (optional) cp .env.example .env  and adjust PARKINSON_* variables.
  2. Open Claude Code in any project — SessionStart hook will fire.
  3. After a few sessions: uv run python scripts/lint.py --structural-only
  4. Compile: uv run python scripts/compile.py

Docs: README.ru.md, docs/install.ru.md, docs/architecture.ru.md
EOF
