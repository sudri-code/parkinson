"""
flush.py — extract key decisions/lessons from a session transcript into daily/YYYY-MM-DD.md.

Clean-room implementation written from scratch against the specification
in docs/architecture.ru.md §flush.py. No source code from
coleam00/claude-memory-compiler was consulted during authorship.

Co-authored with Anthropic's Claude Code under the direction and review
of the copyright holder. See docs/clean-room-provenance.md.

Invoked as a detached background process by SessionEnd / PreCompact hooks:
    uv run --directory <repo> python scripts/flush.py <context_file> <session_id>

`<context_file>` is a markdown-ish dump of recent conversation turns that
the hook extracted in-process. `<session_id>` is the Claude Code session
identifier (used for flush de-duplication).

Sidecar: `<context_file>.project.json` holds detect_project() output and
is used to tag the daily-log section with the correct canonical project.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Recursion guard: when Agent SDK calls fire hooks, those hooks must no-op.
os.environ["CLAUDE_INVOKED_BY"] = "memory_flush"

from config import (
    COMPILE_AFTER_HOUR,
    DAILY_DIR,
    FLUSH_GLOBAL_COOLDOWN_SEC,
    FLUSH_MAX_CONTEXT_CHARS,
    INSTALL_DIR,
    LAST_FLUSH_FILE,
    SCRIPTS_DIR as _SCRIPTS_DIR,
    STATE_FILE,
    now_local,
    today_iso,
)
from utils import atomic_write_text, extract_message_text, file_hash, setup_logger
from utils_projects import scrub_secrets, write_atomic_json


LOGGER = setup_logger("flush", _SCRIPTS_DIR / "flush.log")


# ── De-duplication state ──────────────────────────────────────────────


def _load_last_flush() -> dict:
    if not LAST_FLUSH_FILE.is_file():
        return {}
    try:
        return json.loads(LAST_FLUSH_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_last_flush(data: dict) -> None:
    write_atomic_json(LAST_FLUSH_FILE, data)


def _within_cooldown(session_id: str) -> bool:
    last = _load_last_flush()
    prev = last.get(session_id)
    if not prev:
        return False
    try:
        return (time.time() - float(prev)) < FLUSH_GLOBAL_COOLDOWN_SEC
    except (TypeError, ValueError):
        return False


def _remember_flush(session_id: str) -> None:
    data = _load_last_flush()
    data[session_id] = time.time()
    _save_last_flush(data)


# ── Sidecar ───────────────────────────────────────────────────────────


def _load_sidecar(context_file: Path) -> dict:
    sidecar = context_file.with_suffix(".project.json")
    if not sidecar.is_file():
        return {}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# ── Agent SDK call ────────────────────────────────────────────────────


_FLUSH_PROMPT = """Ты получаешь дамп последних ходов разговора пользователя с AI-ассистентом.
Извлеки из него то, что стоит сохранить в долговременную память: решения,
уроки, неочевидные детали, action items. Игнорируй small-talk, неудавшиеся
эксперименты без выводов, повторы.

Формат ответа — markdown-секции с bullet-пунктами. Если сохранять нечего
(разговор пустой, либо без существенных результатов) — верни ровно строку
`FLUSH_OK` и больше ничего. Не используй tools, не пиши файлы.

Скелет (используй те секции, которые уместны):

**Context:** одно предложение что делал пользователь.

**Decisions Made:**
- ...

**Lessons Learned:**
- ...

**Key Exchanges:**
- ...

**Action Items:**
- [ ] ...

## Разговор

{context}
"""


def _call_agent(context: str) -> str | None:
    """Return extracted section body, or None if FLUSH_OK/failed."""
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query as agent_query
    except ImportError:
        LOGGER.error("claude_agent_sdk unavailable — cannot flush")
        return None

    prompt = _FLUSH_PROMPT.format(context=context[:FLUSH_MAX_CONTEXT_CHARS])

    try:
        import anyio

        async def _run() -> str:
            collected: list[str] = []
            async for message in agent_query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    cwd=str(INSTALL_DIR),
                    system_prompt={"type": "preset", "preset": "claude_code"},
                    allowed_tools=[],
                    max_turns=2,
                ),
            ):
                text = extract_message_text(message)
                if text:
                    collected.append(text)
            return "".join(collected).strip()

        raw = anyio.run(_run)
        stripped = raw.strip()
        if not stripped:
            LOGGER.info("Agent returned empty response (no AssistantMessage text blocks)")
            return None
        if stripped == "FLUSH_OK":
            LOGGER.info("Agent explicitly returned FLUSH_OK")
            return None
        return raw
    except Exception as exc:
        LOGGER.error("Agent SDK call failed: %s", exc)
        return None


# ── Daily-log append ──────────────────────────────────────────────────


def _append_daily_section(body: str, canonical: str) -> Path:
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    daily_path = DAILY_DIR / f"{today_iso()}.md"
    now = now_local()
    header_time = now.strftime("%H:%M")
    section = (
        f"\n### Session ({header_time}) — {canonical}\n\n"
        f"{body}\n"
    )
    if not daily_path.exists():
        content = (
            f"# Daily Log: {today_iso()}\n\n"
            "## Sessions\n"
            f"{section}"
        )
        atomic_write_text(daily_path, content)
    else:
        with open(daily_path, "a", encoding="utf-8") as f:
            f.write(section)
    return daily_path


# ── End-of-day auto-compile trigger ───────────────────────────────────


def _load_state() -> dict:
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"ingested": {}}


def _should_autocompile(daily_path: Path) -> bool:
    if now_local().hour < COMPILE_AFTER_HOUR:
        return False
    if not daily_path.is_file():
        return False
    state = _load_state()
    record = state.get("ingested", {}).get(daily_path.name)
    current_hash = file_hash(daily_path)
    if not isinstance(record, dict):
        return True
    return record.get("hash") != current_hash


def _spawn_compile() -> None:
    try:
        subprocess.Popen(
            [
                "uv", "run", "--directory", str(INSTALL_DIR),
                "python", str(_SCRIPTS_DIR / "compile.py"),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        LOGGER.info("Spawned end-of-day compile.py")
    except Exception as exc:
        LOGGER.error("Failed to spawn compile.py: %s", exc)


# ── Main ──────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        sys.stderr.write("Usage: flush.py <context_file> <session_id>\n")
        return 2
    context_file = Path(argv[1])
    session_id = argv[2]

    if not context_file.is_file():
        LOGGER.error("Context file missing: %s", context_file)
        return 1

    if _within_cooldown(session_id):
        LOGGER.info("SKIP: %s within cooldown", session_id)
        try:
            context_file.unlink(missing_ok=True)
            context_file.with_suffix(".project.json").unlink(missing_ok=True)
        except OSError:
            pass
        return 0

    context = context_file.read_text(encoding="utf-8")
    context = scrub_secrets(context)
    if not context.strip():
        LOGGER.info("SKIP: empty context")
        return 0

    sidecar = _load_sidecar(context_file)
    canonical = sidecar.get("canonical") or "Shared"

    body = _call_agent(context)
    if body is None:
        LOGGER.info("Agent returned FLUSH_OK or failed — nothing to write")
    else:
        daily_path = _append_daily_section(body, canonical)
        LOGGER.info("Appended %d chars to %s", len(body), daily_path.name)
        _remember_flush(session_id)
        if _should_autocompile(daily_path):
            _spawn_compile()

    # Cleanup
    try:
        context_file.unlink(missing_ok=True)
        context_file.with_suffix(".project.json").unlink(missing_ok=True)
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
