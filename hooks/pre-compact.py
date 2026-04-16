"""
PreCompact hook — captures conversation transcript before auto-compaction.

Guards against empty transcript_path (Claude Code bug #13668). Fires
before Claude Code auto-compacts the context window; without this
intermediate context is lost to summarization before SessionEnd runs.

Clean-room skeleton written against docs/architecture.ru.md §Hook System.
Project detection and spawn-chain composition ported from the author's
prior work.

Co-authored with Anthropic's Claude Code under the direction and review
of the copyright holder.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if os.environ.get("CLAUDE_INVOKED_BY"):
    sys.exit(0)

INSTALL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = INSTALL_DIR / "scripts"
STATE_DIR = SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from utils_projects import (
        detect_project,
        ensure_project_registered,
        write_atomic_json,
    )
except ImportError:
    detect_project = None  # type: ignore
    ensure_project_registered = None  # type: ignore
    write_atomic_json = None  # type: ignore

logging.basicConfig(
    filename=str(SCRIPTS_DIR / "flush.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [pre-compact] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

MAX_TURNS = 30
MAX_CONTEXT_CHARS = 15_000
MIN_TURNS_TO_FLUSH = 5


def extract_conversation_context(transcript_path: Path) -> tuple[str, int]:
    turns: list[str] = []
    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg = entry.get("message", {})
            if isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")
            else:
                role = entry.get("role", "")
                content = entry.get("content", "")

            if role not in ("user", "assistant"):
                continue

            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                content = "\n".join(parts)

            if isinstance(content, str) and content.strip():
                label = "User" if role == "user" else "Assistant"
                turns.append(f"**{label}:** {content.strip()}\n")

    recent = turns[-MAX_TURNS:]
    context = "\n".join(recent)

    if len(context) > MAX_CONTEXT_CHARS:
        context = context[-MAX_CONTEXT_CHARS:]
        boundary = context.find("\n**")
        if boundary > 0:
            context = context[boundary + 1:]

    return context, len(recent)


def main() -> None:
    try:
        raw = sys.stdin.read()
        try:
            hook_input: dict = json.loads(raw)
        except json.JSONDecodeError:
            fixed = re.sub(r'(?<!\\)\\(?!["\\])', r'\\\\', raw)
            hook_input = json.loads(fixed)
    except (json.JSONDecodeError, ValueError, EOFError) as e:
        logging.error("Failed to parse stdin: %s", e)
        return

    session_id = hook_input.get("session_id", "unknown")
    transcript_path_str = hook_input.get("transcript_path", "")

    logging.info("PreCompact fired: session=%s", session_id)

    if not transcript_path_str or not isinstance(transcript_path_str, str):
        logging.info("SKIP: no transcript path (bug #13668?)")
        return

    transcript_path = Path(transcript_path_str)
    if not transcript_path.exists():
        logging.info("SKIP: transcript missing: %s", transcript_path_str)
        return

    try:
        context, turn_count = extract_conversation_context(transcript_path)
    except Exception as e:
        logging.error("Context extraction failed: %s", e)
        return

    if not context.strip():
        logging.info("SKIP: empty context")
        return

    if turn_count < MIN_TURNS_TO_FLUSH:
        logging.info("SKIP: only %d turns (min %d)", turn_count, MIN_TURNS_TO_FLUSH)
        return

    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    context_file = STATE_DIR / f"flush-context-{session_id}-{timestamp}.md"
    context_file.write_text(context, encoding="utf-8")

    if detect_project is not None and write_atomic_json is not None:
        try:
            cwd = hook_input.get("cwd") or os.getcwd()
            project = detect_project(cwd)
            if ensure_project_registered is not None:
                try:
                    ensure_project_registered(project)
                except Exception as reg_err:
                    logging.error("Project auto-register failed: %s", reg_err)
            project["detected_at"] = (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            )
            sidecar = context_file.with_suffix(".project.json")
            write_atomic_json(sidecar, project)
            logging.info("Project: %s (source=%s)", project["canonical"], project["source"])
        except Exception as e:
            logging.error("Project detection failed: %s", e)

    flush_script = SCRIPTS_DIR / "flush.py"
    cmd = [
        "uv", "run", "--directory", str(INSTALL_DIR),
        "python", str(flush_script),
        str(context_file), session_id,
    ]

    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            start_new_session=sys.platform != "win32",
        )
        logging.info("Spawned flush.py (%d turns, %d chars)", turn_count, len(context))
    except Exception as e:
        logging.error("Failed to spawn flush.py: %s", e)


if __name__ == "__main__":
    main()
