"""
compile.py — compile daily logs into knowledge articles.

Clean-room implementation written from scratch against the specification
in docs/architecture.ru.md §Compile. No source code from
coleam00/claude-memory-compiler was consulted during authorship.

Co-authored with Anthropic's Claude Code under the direction and review
of the copyright holder. See docs/clean-room-provenance.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config import (
    DAILY_DIR,
    INSTALL_DIR,
    KNOWLEDGE_DIR,
    LOG_FILE,
    STATE_FILE,
    now_iso,
)
from utils import (
    atomic_write_text,
    extract_message_text,
    file_hash,
    setup_logger,
)
from utils_projects import write_atomic_json


SPEC_PATH = INSTALL_DIR / "docs" / "architecture.ru.md"
CONVENTIONS_PATH = INSTALL_DIR / "docs" / "conventions.ru.md"


# ── State ─────────────────────────────────────────────────────────────


def _load_state() -> dict:
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "ingested": {},
        "query_count": 0,
        "last_lint": None,
        "total_cost": 0.0,
    }


def _save_state(state: dict) -> None:
    write_atomic_json(STATE_FILE, state)


# ── Enumeration ───────────────────────────────────────────────────────


def _pending_dailies(state: dict, force_all: bool) -> list[Path]:
    if not DAILY_DIR.is_dir():
        return []
    ingested = state.get("ingested", {}) or {}
    pending: list[Path] = []
    for daily in sorted(DAILY_DIR.glob("*.md")):
        if force_all:
            pending.append(daily)
            continue
        record = ingested.get(daily.name)
        if not isinstance(record, dict):
            pending.append(daily)
            continue
        if record.get("hash") != file_hash(daily):
            pending.append(daily)
    return pending


# ── Prompt ────────────────────────────────────────────────────────────


def _build_prompt(daily_path: Path) -> str:
    spec = SPEC_PATH.read_text(encoding="utf-8") if SPEC_PATH.is_file() else ""
    conventions = (
        CONVENTIONS_PATH.read_text(encoding="utf-8") if CONVENTIONS_PATH.is_file() else ""
    )
    daily = daily_path.read_text(encoding="utf-8")
    rel_daily = daily_path.relative_to(daily_path.parent.parent)
    return (
        "Ты — компилятор персональной базы знаний. Прочитай дневной лог "
        f"ниже (`{rel_daily}`) и извлеки из него атомарные знания в "
        "виде concept/connection/qa статей.\n\n"
        "Правила:\n"
        "1. Сначала прочитай `knowledge/index.md`.\n"
        "2. Если тема уже покрыта существующей статьёй — UPDATE её "
        "(добавь daily как источник в frontmatter, расширь Details).\n"
        "3. Если тема новая — CREATE `concepts/<slug>.md`.\n"
        "4. Если лог раскрывает не-очевидную связь 2+ концептов — "
        "CREATE `connections/<slug>.md`.\n"
        "5. Обнови `knowledge/index.md` (таблица). Новые ряды добавляй "
        "СРАЗУ после последнего существующего ряда — БЕЗ пустых строк "
        "между рядами. Пустая строка в GFM-таблице разбивает её на "
        "несколько таблиц (видно в Obsidian).\n"
        "6. Добавь секцию в `knowledge/log.md`.\n"
        "7. Для каждой concept/connection статьи укажи в frontmatter "
        "`projects: [<canonical>]` (канонические имена — из `projects.json`).\n"
        "8. Obsidian-style wiki-ссылки пишутся так: ДВЕ открывающие "
        "квадратные скобки + `concepts/<имя-файла-без-.md>` + ДВЕ "
        "закрывающие. Используй этот синтаксис ТОЛЬКО для реальных "
        "существующих статей. НИКОГДА не вставляй литеральные примеры "
        "синтаксиса в double-brackets — плейсхолдеры вроде `foo`, "
        "`slug`, `wikilinks` ломают lint (broken_link). Если нужно "
        "описать синтаксис в тексте статьи — пиши прозой: «Obsidian-"
        "ссылки в формате двойных квадратных скобок», а не литералом.\n"
        "9. Секция `## Related Concepts` должна быть двусторонней: если "
        "статья A линкует на B, ОБНОВИ B и добавь обратную ссылку на A. "
        "Исключение — hub-концепты (общая инфраструктура), на которые "
        "приходит 4+ peripheral-ссылок: в этом случае не добавляй "
        "weak forward-ссылку в source-article (ссылка через projects-"
        "membership, а не concept-relationship).\n"
        "10. Body статьи ≥200 слов (порог lint). Если контента меньше, "
        "либо UPDATE существующей статьи вместо CREATE, либо расширь "
        "Details подробностями из daily.\n\n"
        "## Спецификация архитектуры\n\n"
        f"{spec}\n\n"
        "## Конвенции\n\n"
        f"{conventions}\n\n"
        "## Дневной лог для компиляции\n\n"
        f"{daily}"
    )


# ── Agent SDK call ────────────────────────────────────────────────────


def _run_agent(prompt: str) -> tuple[bool, str]:
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query as agent_query
    except ImportError:
        return False, "claude_agent_sdk not installed — run `uv sync`."

    try:
        import anyio

        async def _run() -> str:
            os.environ["CLAUDE_INVOKED_BY"] = "compile"
            collected: list[str] = []
            async for message in agent_query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    cwd=str(KNOWLEDGE_DIR.parent),
                    system_prompt={"type": "preset", "preset": "claude_code"},
                    allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
                    permission_mode="acceptEdits",
                    max_turns=30,
                ),
            ):
                text = extract_message_text(message)
                if text:
                    collected.append(text)
            return "".join(collected)

        final = anyio.run(_run)
        return True, final or "(ok)"
    except Exception as exc:
        return False, f"Agent SDK call failed: {exc}"


# ── Log-file append ───────────────────────────────────────────────────


def _append_log(entry: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


# ── Main ──────────────────────────────────────────────────────────────


def compile_one(daily_path: Path, state: dict, dry_run: bool, logger) -> bool:
    logger.info("Compiling %s", daily_path.name)
    if dry_run:
        return True
    prompt = _build_prompt(daily_path)
    ok, result = _run_agent(prompt)
    if not ok:
        logger.error("compile %s failed: %s", daily_path.name, result)
        return False
    h = file_hash(daily_path)
    state.setdefault("ingested", {})[daily_path.name] = {
        "hash": h,
        "compiled_at": now_iso(),
    }
    _save_state(state)
    _append_log(
        f"\n## [{now_iso()}] compile | {daily_path.name}\n"
        f"- Source: daily/{daily_path.name}\n"
    )
    logger.info("OK: %s", daily_path.name)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="parkinson knowledge compiler")
    parser.add_argument(
        "--all", action="store_true",
        help="Force recompile every daily log regardless of state.json.",
    )
    parser.add_argument(
        "--file", type=str, default=None,
        help="Compile a single daily log file (relative or absolute path).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List the plan without calling the Agent SDK.",
    )
    args = parser.parse_args(argv)

    logger = setup_logger("compile")
    state = _load_state()

    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            target = DAILY_DIR / target.name
        if not target.is_file():
            logger.error("File not found: %s", target)
            return 2
        pending = [target]
    else:
        pending = _pending_dailies(state, args.all)

    if not pending:
        print("No pending daily logs. Knowledge base is up to date.")
        return 0

    print(f"Plan: {len(pending)} daily log(s) to compile:")
    for path in pending:
        print(f"  - {path.name}")
    if args.dry_run:
        return 0

    failures = 0
    for path in pending:
        if not compile_one(path, state, dry_run=False, logger=logger):
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
