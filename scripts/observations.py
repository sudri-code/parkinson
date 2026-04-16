"""Append-only observations log used by PreToolUse/PostToolUse hooks.

Captures minimal summaries of every tool invocation for later instinct
synthesis. Secrets are scrubbed before writing. The file rotates when it
exceeds OBSERVATIONS_MAX_SIZE_MB.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from config import (
    OBSERVATIONS_ARCHIVE_DIR,
    OBSERVATIONS_DIR,
    OBSERVATIONS_FILE,
    OBSERVATIONS_MAX_SIZE_MB,
)
from utils_projects import scrub_secrets


_MAX_SUMMARY_CHARS = 500


def _summarize_input(tool: str, tool_input: dict) -> str:
    """Reduce tool_input to a short human-readable summary (scrubbed)."""
    if not isinstance(tool_input, dict):
        return scrub_secrets(str(tool_input))[:_MAX_SUMMARY_CHARS]

    key_order = [
        "file_path", "path", "command", "pattern", "url", "query",
        "old_string", "new_string", "prompt", "description", "content",
    ]
    parts: list[str] = []
    for k in key_order:
        if k in tool_input:
            val = tool_input[k]
            if isinstance(val, str):
                parts.append(f"{k}={val[:120]}")
            elif isinstance(val, (int, float, bool)):
                parts.append(f"{k}={val}")
            elif isinstance(val, list):
                parts.append(f"{k}=[{len(val)} items]")

    for k, v in tool_input.items():
        if k in key_order:
            continue
        if isinstance(v, (str, int, float, bool)):
            parts.append(f"{k}={str(v)[:60]}")

    summary = " ".join(parts)[:_MAX_SUMMARY_CHARS]
    return scrub_secrets(summary)


def _rotate_if_needed() -> None:
    if not OBSERVATIONS_FILE.exists():
        return
    size_mb = OBSERVATIONS_FILE.stat().st_size / (1024 * 1024)
    if size_mb < OBSERVATIONS_MAX_SIZE_MB:
        return
    OBSERVATIONS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d-%H%M")
    archive_path = OBSERVATIONS_ARCHIVE_DIR / f"{ts}.jsonl"
    shutil.move(str(OBSERVATIONS_FILE), str(archive_path))


def append_observation(entry: dict) -> None:
    """Append a single JSON record to observations.jsonl.

    Caller is responsible for populating `ts`, `event`, `tool`, etc.
    This function handles rotation, directory creation, and atomic write.
    Errors are swallowed — the tool must not block on observation failures.
    """
    try:
        OBSERVATIONS_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed()
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with open(OBSERVATIONS_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def now_ts() -> str:
    """Current UTC timestamp in compact ISO form."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def now_epoch_ms() -> int:
    return int(time.time() * 1000)
