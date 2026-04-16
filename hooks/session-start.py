"""
SessionStart hook — injects the knowledge base context into every conversation.

Tiered output so memory is usable cross-project, not just accumulated:
  1. Today + Current Project header
  2. Knowledge: Current + Shared (full index rows) — the relevant slice
  3. Knowledge: Other Projects (titles only) — awareness that it exists
  4. Instincts (ALL, no project filter) — behavioural patterns are portable
  5. Wiki Index (external sources) — always shown, topic-agnostic
  6. Recent Daily Log (filtered to current project)

Clean-room skeleton: stdin parsing, context assembly, and tiered rendering
were written from scratch against docs/architecture.ru.md §Hook System.
Business logic (ensure_project_registered, _classify_row, instincts
rendering) is ported from the author's own prior work.

Co-authored with Anthropic's Claude Code under the direction and review
of the copyright holder. See docs/clean-room-provenance.md.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

INSTALL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = INSTALL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from config import DAILY_DIR, DATA_DIR, INDEX_FILE, INSTINCTS_DIR, KNOWLEDGE_DIR, WIKI_INDEX_FILE
    from utils_projects import (
        article_matches_project,
        detect_project,
        ensure_project_registered,
        extract_projects_field,
        load_projects_registry,
    )
except ImportError:
    sys.exit(0)


MAX_CONTEXT_CHARS = 20_000
MAX_LOG_LINES = 30
MAX_OTHER_PROJECT_ROWS = 40
MIN_INSTINCT_CONFIDENCE = 0.5


# ── stdin parsing ─────────────────────────────────────────────────────


def _read_hook_cwd() -> str | None:
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return None
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    cwd = data.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else None


_RESOLVED_CWD: str | None = None
_CWD_RESOLVED = False


def resolve_cwd() -> str:
    global _RESOLVED_CWD, _CWD_RESOLVED
    if not _CWD_RESOLVED:
        _RESOLVED_CWD = _read_hook_cwd() or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        _CWD_RESOLVED = True
    return _RESOLVED_CWD or os.getcwd()


def detect_current_project() -> dict | None:
    cwd = resolve_cwd()
    try:
        project = detect_project(cwd)
    except Exception:
        return None
    try:
        ensure_project_registered(project)
    except Exception:
        pass
    return project


def _is_inside_vault(cwd: str) -> bool:
    try:
        Path(cwd).resolve().relative_to(DATA_DIR.resolve())
        return True
    except ValueError:
        return False


# ── Daily filter helpers ──────────────────────────────────────────────

_SESSION_TAG_RE = re.compile(r"—\s*([A-Za-z0-9_\-.]+)\s*$")


def _header_project(line: str) -> str | None:
    stripped = line.rstrip()
    m = _SESSION_TAG_RE.search(stripped)
    if m:
        return m.group(1)
    legacy = re.search(r"—\s*([A-Za-z0-9_\-.]+)\s*\(", stripped)
    if legacy:
        return legacy.group(1)
    return None


def _project_matches(header_project: str | None, aliases: set[str]) -> bool:
    if header_project is None:
        return True
    hp_lower = header_project.lower()
    if hp_lower in {"shared", "all"}:
        return True
    return hp_lower in aliases


def _aliases_for(project: dict) -> set[str]:
    aliases = {
        str(project.get("canonical", "")).lower(),
        str(project.get("name", "")).lower(),
    }
    try:
        registry = load_projects_registry()
        entry = registry.get(project.get("id"))
    except Exception:
        entry = None
    if entry:
        for a in entry.get("aliases", []):
            aliases.add(str(a).lower())
    aliases.discard("")
    return aliases


# ── Row scope classification ──────────────────────────────────────────

_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _row_projects(line: str) -> list[str] | None:
    m = _LINK_RE.search(line)
    if not m:
        return None
    slug = m.group(1).split("|")[0]
    article_path = KNOWLEDGE_DIR / f"{slug}.md"
    if not article_path.exists():
        return None
    text = article_path.read_text(encoding="utf-8")
    return extract_projects_field(text)


def _classify_row(line: str, aliases: set[str]) -> str:
    projects = _row_projects(line)
    if projects is None:
        return "shared"
    values = {p.lower() for p in projects}
    values.discard("")
    if not values or "shared" in values or "all" in values:
        return "shared"
    if values & aliases:
        return "current"
    return "other"


def _compact_row(line: str) -> str:
    """Render an index.md row as `- [[link]] — summary _(projects)_`.

    Drops the verbose `Compiled From` and `Updated` columns — they bloat
    SessionStart inject without helping retrieval.
    """
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) < 2:
        return line
    link = cells[0]
    summary = cells[1]
    projects = cells[2] if len(cells) > 2 else ""
    proj_suffix = f" _({projects})_" if projects and projects not in ("-", "shared") else ""
    return f"- {link} — {summary}{proj_suffix}"


def split_index_by_scope(
    index_content: str, aliases: set[str]
) -> tuple[list[str], list[str]]:
    current_block: list[str] = []
    other_brief: list[str] = []

    for raw_line in index_content.splitlines():
        line = raw_line.rstrip()
        if not line.startswith("|") or "[[" not in line:
            continue
        scope = _classify_row(line, aliases) if aliases else "shared"
        compact = _compact_row(line)
        if scope in ("current", "shared"):
            current_block.append(compact)
        else:
            other_brief.append(f"  {compact}")
    return current_block, other_brief


# ── Instincts section ─────────────────────────────────────────────────

_INSTINCT_FM_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def _parse_fm_line(line: str) -> tuple[str, str] | None:
    if ":" not in line or line.lstrip().startswith("#"):
        return None
    key, _, val = line.partition(":")
    return key.strip(), val.strip().strip("'\"")


def _read_instincts() -> list[dict]:
    if not INSTINCTS_DIR.exists():
        return []
    result: list[dict] = []
    for md in sorted(INSTINCTS_DIR.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        m = _INSTINCT_FM_RE.match(text)
        if not m:
            continue
        fm: dict = {}
        for line in m.group(1).splitlines():
            kv = _parse_fm_line(line)
            if kv:
                fm[kv[0]] = kv[1]
        result.append(fm)
    return result


def instincts_section() -> str:
    instincts = _read_instincts()
    if not instincts:
        return "_(пока пусто — накапливаются из tool-событий текущих сессий)_"

    lines = [
        "| Trigger | Action | Domain | Conf | Last Seen |",
        "|---------|--------|--------|------|-----------|",
    ]

    def sort_key(x):
        try:
            conf = float(x.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0
        return (-conf, x.get("last_seen", ""))

    rendered = 0
    for inst in sorted(instincts, key=sort_key):
        try:
            conf_value = float(inst.get("confidence", 0))
        except (TypeError, ValueError):
            conf_value = 0.0
        if conf_value < MIN_INSTINCT_CONFIDENCE:
            continue
        trigger = (inst.get("trigger", "-") or "-")[:60]
        action = (inst.get("action", "-") or "-")[:60]
        domain = (inst.get("domain", "-") or "-")[:18]
        conf = inst.get("confidence", "?")
        last = inst.get("last_seen", "-")
        lines.append(f"| {trigger} | {action} | {domain} | {conf} | {last} |")
        rendered += 1
    if rendered == 0:
        return f"_(нет instincts с confidence >= {MIN_INSTINCT_CONFIDENCE})_"
    return "\n".join(lines)


# ── Daily log ─────────────────────────────────────────────────────────


def _filter_daily_by_project(lines: list[str], aliases: set[str]) -> list[str]:
    result: list[str] = []
    keep = True
    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            keep = True
            result.append(line)
            continue
        if line.startswith("### "):
            keep = _project_matches(_header_project(line), aliases)
            if keep:
                result.append(line)
            continue
        if keep:
            result.append(line)
    return result


def get_recent_log(aliases: set[str] | None) -> str:
    today = datetime.now(timezone.utc).astimezone()
    for offset in range(2):
        date = today - timedelta(days=offset)
        log_path = DAILY_DIR / f"{date.strftime('%Y-%m-%d')}.md"
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            if aliases:
                lines = _filter_daily_by_project(lines, aliases)
            recent = lines[-MAX_LOG_LINES:] if len(lines) > MAX_LOG_LINES else lines
            return "\n".join(recent)
    return "(no recent daily log)"


# ── Wiki section ──────────────────────────────────────────────────────


def wiki_index_section(full: bool) -> str:
    if not WIKI_INDEX_FILE.exists():
        return "_(wiki/index.md отсутствует — внешний ingest ещё не начинался)_"
    text = WIKI_INDEX_FILE.read_text(encoding="utf-8")
    if full:
        lines = text.splitlines()
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
        stripped = [ln for ln in lines if ln.strip()]
        return "\n".join(stripped)[:6000]
    page_count = sum(1 for ln in text.splitlines() if ln.strip().startswith("- [["))
    rel = WIKI_INDEX_FILE.relative_to(DATA_DIR.parent) if WIKI_INDEX_FILE.is_relative_to(DATA_DIR.parent) else WIKI_INDEX_FILE
    return f"_({page_count} страниц во `{rel}` — открой через `Read` при необходимости)_"


# ── Context assembly ──────────────────────────────────────────────────


def build_context() -> str:
    parts: list[str] = []
    today = datetime.now(timezone.utc).astimezone()
    parts.append(f"## Today\n{today.strftime('%d.%m.%Y (%A)')}")

    project = detect_current_project()
    if project and project.get("id") != "shared":
        aliases = _aliases_for(project)
        parts.append(
            f"## Current Project\n\n**{project['canonical']}** "
            f"(id: `{project['id']}`)"
        )
    else:
        aliases = set()
        parts.append(
            "## Current Project\n\n*(вне зарегистрированного проекта — "
            "доступен shared scope + awareness других)*"
        )

    if INDEX_FILE.exists():
        index_content = INDEX_FILE.read_text(encoding="utf-8")
        current_block, other_brief = split_index_by_scope(index_content, aliases)
        parts.append("## Knowledge: Current + Shared\n\n" + "\n".join(current_block))
        if other_brief:
            other_capped = other_brief[:MAX_OTHER_PROJECT_ROWS]
            tail = ""
            if len(other_brief) > MAX_OTHER_PROJECT_ROWS:
                tail = (
                    f"\n  _(+ ещё {len(other_brief) - MAX_OTHER_PROJECT_ROWS} — "
                    "см. `knowledge/index.md`)_"
                )
            parts.append(
                "## Knowledge: Other Projects (заголовки, читай по запросу)\n\n"
                + "\n".join(other_capped) + tail
            )
    else:
        parts.append("## Knowledge: Current + Shared\n\n(empty — no articles compiled yet)")

    parts.append("## Instincts (поведенческие паттерны, глобально)\n\n" + instincts_section())
    parts.append(
        "## Wiki (внешние источники)\n\n"
        + wiki_index_section(full=_is_inside_vault(resolve_cwd()))
    )

    recent_log = get_recent_log(aliases if aliases else None)
    parts.append(f"## Recent Daily Log\n\n{recent_log}")

    context = "\n\n---\n\n".join(parts)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n...(truncated)"
    return context


def main():
    context = build_context()
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
