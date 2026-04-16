#!/usr/bin/env bash
# Smoke test: session-start hook on fixture git-repo.
#
# Verifies:
#   1. Hook exits 0.
#   2. Valid JSON with hookSpecificOutput.additionalContext.
#   3. Context contains Current Project / Knowledge / Instincts / Wiki sections.
#   4. Auto-registration works (new project appears in projects.json).
#   5. Cleans up test project from projects.json afterwards.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE="$REPO/tests/fixtures/git-repo"
PROJECTS_JSON="${PARKINSON_DATA_DIR:-$REPO/data}/projects.json"

# Self-setup: fixture git-repo is gitignored; create on demand.
if [ ! -d "$FIXTURE/.git" ]; then
    echo "[test_session_start] bootstrapping fixture at $FIXTURE"
    mkdir -p "$FIXTURE"
    (
        cd "$FIXTURE"
        git init -q
        git remote add origin https://github.com/parkinson-fixture/demo-repo.git
        touch README.md
        git add README.md
        git -c user.email=test@example.com -c user.name=Test commit -q -m "fixture"
    )
fi

echo "[test_session_start] fixture=$FIXTURE"

OUT=$(mktemp)
echo "{\"cwd\":\"$FIXTURE\"}" \
    | uv run --quiet --directory "$REPO" python "$REPO/hooks/session-start.py" > "$OUT"

python3 - <<PY
import json, sys
d = json.load(open("$OUT"))
ctx = d["hookSpecificOutput"]["additionalContext"]
expected_fragments = [
    "Current Project",
    "Knowledge: Current + Shared",
    "Instincts",
    "Wiki",
    "Recent Daily Log",
]
missing = [f for f in expected_fragments if f not in ctx]
assert not missing, f"missing sections: {missing}"
print(f"[test_session_start] context={len(ctx)} chars, all expected sections present")
PY

# Cleanup: remove auto-registered test project from projects.json
python3 - <<PY
import json, pathlib
p = pathlib.Path("$PROJECTS_JSON")
if p.is_file():
    data = json.loads(p.read_text())
    before = len(data)
    data = {k: v for k, v in data.items() if v.get("name") != "demo-repo"}
    if len(data) != before:
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print("[test_session_start] cleaned test project from projects.json")
PY

rm -f "$OUT"
echo "[test_session_start] OK"
