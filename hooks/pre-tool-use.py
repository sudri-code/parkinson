"""PreToolUse hook — strategic-compact counter + observations append.

Two responsibilities per invocation:
1. Increment the session-local tool-call counter; emit a stderr hint
   on COMPACT_THRESHOLD and every COMPACT_INTERVAL beyond it.
2. Append a pre-event record to observations.jsonl for later instinct
   synthesis.

Must exit in <5s — tool execution is blocked until we return.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Recursion guard — we were spawned by Agent SDK (flush.py), don't re-observe.
if os.environ.get("CLAUDE_INVOKED_BY"):
    sys.exit(0)

INSTALL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = INSTALL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from config import (
        COMPACT_INTERVAL,
        COMPACT_THRESHOLD,
        TOOL_COUNT_STATE_DIR,
    )
    from observations import (
        _summarize_input,
        append_observation,
        now_epoch_ms,
        now_ts,
    )
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


def _bump_counter(session_id: str) -> int:
    TOOL_COUNT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    counter_file = TOOL_COUNT_STATE_DIR / f"{session_id}.json"
    count = 0
    if counter_file.exists():
        try:
            count = json.loads(counter_file.read_text(encoding="utf-8")).get("count", 0)
        except (json.JSONDecodeError, OSError):
            count = 0
    count += 1
    try:
        counter_file.write_text(json.dumps({"count": count}), encoding="utf-8")
    except OSError:
        pass
    return count


def _maybe_suggest_compact(count: int) -> None:
    if count == COMPACT_THRESHOLD:
        print(
            f"[StrategicCompact] {COMPACT_THRESHOLD} tool calls reached — "
            f"consider /compact if transitioning phases",
            file=sys.stderr,
        )
    elif count > COMPACT_THRESHOLD and (count - COMPACT_THRESHOLD) % COMPACT_INTERVAL == 0:
        print(
            f"[StrategicCompact] {count} tool calls — "
            f"good checkpoint for /compact if context is stale",
            file=sys.stderr,
        )


def main() -> None:
    hook = _parse_stdin()
    session_id = hook.get("session_id") or "unknown"
    tool = hook.get("tool_name") or hook.get("tool") or "unknown"
    tool_input = hook.get("tool_input") or hook.get("input") or {}
    cwd = hook.get("cwd") or os.getcwd()

    count = _bump_counter(session_id)
    _maybe_suggest_compact(count)

    try:
        project = detect_project(cwd)
        project_canonical = project.get("canonical") if project else None
    except Exception:
        project_canonical = None

    append_observation({
        "ts": now_ts(),
        "ts_ms": now_epoch_ms(),
        "session_id": session_id,
        "project": project_canonical,
        "event": "pre",
        "tool": tool,
        "input_summary": _summarize_input(tool, tool_input) if isinstance(tool_input, dict) else "",
        "tool_call_num": count,
    })


if __name__ == "__main__":
    main()
