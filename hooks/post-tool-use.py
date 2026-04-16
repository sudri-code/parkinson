"""PostToolUse hook — append tool completion to observations.jsonl.

Records success/failure, but NOT tool output body (can be large).
Must exit in <5s.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

if os.environ.get("CLAUDE_INVOKED_BY"):
    sys.exit(0)

INSTALL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = INSTALL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from observations import append_observation, now_epoch_ms, now_ts
    from utils_projects import detect_project
except ImportError:
    sys.exit(0)


def _parse_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            fixed = re.sub(r'(?<!\\)\\(?!["\\])', r'\\\\', raw)
            return json.loads(fixed)
    except (json.JSONDecodeError, ValueError, EOFError):
        return {}


def _classify_result(hook: dict) -> tuple[bool, str | None]:
    response = hook.get("tool_response") or hook.get("response") or {}
    if isinstance(response, dict):
        if response.get("isError") or response.get("error"):
            err = str(response.get("error") or "tool_error")
            return False, err[:160]
        return True, None
    return True, None


def main() -> None:
    hook = _parse_stdin()
    session_id = hook.get("session_id") or "unknown"
    tool = hook.get("tool_name") or hook.get("tool") or "unknown"
    cwd = hook.get("cwd") or os.getcwd()

    success, error = _classify_result(hook)

    try:
        project = detect_project(cwd)
        project_canonical = project.get("canonical") if project else None
    except Exception:
        project_canonical = None

    entry = {
        "ts": now_ts(),
        "ts_ms": now_epoch_ms(),
        "session_id": session_id,
        "project": project_canonical,
        "event": "post",
        "tool": tool,
        "success": success,
    }
    if error:
        entry["error"] = error
    append_observation(entry)


if __name__ == "__main__":
    main()
