"""
config.py — env-var resolution + path constants for parkinson.

Clean-room implementation written from scratch against the specification
in docs/architecture.ru.md. No source code from coleam00/claude-memory-compiler
was consulted during authorship.

Co-authored with Anthropic's Claude Code under the direction and review
of the copyright holder. See docs/clean-room-provenance.md.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore[assignment]


# ── Repo root + .env ──────────────────────────────────────────────────

SCRIPTS_DIR = Path(__file__).resolve().parent
INSTALL_DIR = SCRIPTS_DIR.parent
HOOKS_DIR = INSTALL_DIR / "hooks"
TEMPLATES_DIR = INSTALL_DIR / "templates"

if load_dotenv is not None:
    load_dotenv(INSTALL_DIR / ".env", override=False)


# ── Data root resolution ──────────────────────────────────────────────


def _resolve_data_dir() -> Path:
    """Resolve DATA_DIR via env var → pointer file → default repo-relative."""
    env = os.environ.get("PARKINSON_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    pointer = INSTALL_DIR / ".parkinson-data-dir"
    if pointer.is_file():
        value = pointer.read_text(encoding="utf-8").strip()
        if value:
            return Path(value).expanduser().resolve()
    return INSTALL_DIR / "data"


DATA_DIR = _resolve_data_dir()


# ── Directory structure ───────────────────────────────────────────────

DAILY_DIR = DATA_DIR / "daily"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
CONCEPTS_DIR = KNOWLEDGE_DIR / "concepts"
CONNECTIONS_DIR = KNOWLEDGE_DIR / "connections"
QA_DIR = KNOWLEDGE_DIR / "qa"
INSTINCTS_DIR = KNOWLEDGE_DIR / "instincts"

WIKI_DIR = DATA_DIR / "wiki"
RAW_DIR = DATA_DIR / "raw"

REPORTS_DIR = DATA_DIR / "reports"
AGENTSHIELD_REPORTS_DIR = REPORTS_DIR / "agentshield"

OBSERVATIONS_DIR = INSTALL_DIR / "observations"
OBSERVATIONS_FILE = OBSERVATIONS_DIR / "observations.jsonl"
OBSERVATIONS_ARCHIVE_DIR = OBSERVATIONS_DIR / "archive"

STATE_DIR = INSTALL_DIR / "state"
TOOL_COUNT_STATE_DIR = STATE_DIR / "tool-counts"


# ── Files ─────────────────────────────────────────────────────────────

INDEX_FILE = KNOWLEDGE_DIR / "index.md"
LOG_FILE = KNOWLEDGE_DIR / "log.md"
WIKI_INDEX_FILE = DATA_DIR / "index.md"
PROJECTS_REGISTRY_FILE = DATA_DIR / "projects.json"

STATE_FILE = SCRIPTS_DIR / "state.json"
LAST_FLUSH_FILE = SCRIPTS_DIR / "last-flush.json"
AGENTSHIELD_STATE_FILE = STATE_DIR / "last-agentshield.json"


# ── Tunable numeric constants (env-overridable) ───────────────────────


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


COMPACT_THRESHOLD = _env_int("PARKINSON_COMPACT_THRESHOLD", 50)
COMPACT_INTERVAL = _env_int("PARKINSON_COMPACT_INTERVAL", 25)

FLUSH_MAX_CONTEXT_CHARS = _env_int("PARKINSON_FLUSH_MAX_CONTEXT_CHARS", 150_000)
FLUSH_GLOBAL_COOLDOWN_SEC = _env_int("PARKINSON_FLUSH_COOLDOWN_SEC", 30)

OBSERVATIONS_MAX_SIZE_MB = _env_int("PARKINSON_OBSERVATIONS_MAX_MB", 10)

AGENTSHIELD_THROTTLE_HOURS = _env_int("PARKINSON_AGENTSHIELD_THROTTLE_H", 6)
AGENTSHIELD_TIMEOUT_SEC = _env_int("PARKINSON_AGENTSHIELD_TIMEOUT_S", 60)

# fnmatch-style globs applied to finding paths relative to the scan root
# (~/.claude). Matches are dropped before summary/daily reporting.
# Marketplace agent docs contain illustrative "bad pattern" snippets that
# trigger false positives (e.g. `const password = "admin123"` in
# security-reviewer.md's vulnerability catalogue).
AGENTSHIELD_IGNORE_GLOBS = tuple(
    p.strip()
    for p in os.environ.get(
        "PARKINSON_AGENTSHIELD_IGNORE",
        "plugins/marketplaces/*",
    ).split(":")
    if p.strip()
)

INSTINCT_SYNTHESIS_MIN_OBSERVATIONS = _env_int("PARKINSON_INSTINCT_MIN_OBS", 20)
INSTINCT_SYNTHESIS_WINDOW_HOURS = _env_int("PARKINSON_INSTINCT_WINDOW_H", 24)

COMPILE_AFTER_HOUR = _env_int("PARKINSON_COMPILE_AFTER_HOUR", 18)

LOG_LEVEL = os.environ.get("PARKINSON_LOG_LEVEL", "INFO").upper()
TIMEZONE = os.environ.get("PARKINSON_TIMEZONE", "").strip()


# ── Time helpers ──────────────────────────────────────────────────────


def _tz():
    if not TIMEZONE or ZoneInfo is None:
        return None
    try:
        return ZoneInfo(TIMEZONE)
    except Exception:
        return None


def now_local() -> datetime:
    """Timezone-aware current datetime, honouring PARKINSON_TIMEZONE."""
    tz = _tz()
    return datetime.now(tz) if tz else datetime.now()


def now_iso() -> str:
    """ISO 8601 timestamp with seconds precision."""
    return now_local().isoformat(timespec="seconds")


def today_iso() -> str:
    """Current date as YYYY-MM-DD in the configured timezone."""
    return now_local().strftime("%Y-%m-%d")


def today_display() -> str:
    """Current date as DD.MM.YYYY (European display format)."""
    return now_local().strftime("%d.%m.%Y")


# ── CLI (sanity check) ────────────────────────────────────────────────


def _print_config() -> None:
    entries = [
        ("INSTALL_DIR", INSTALL_DIR),
        ("DATA_DIR", DATA_DIR),
        ("DAILY_DIR", DAILY_DIR),
        ("KNOWLEDGE_DIR", KNOWLEDGE_DIR),
        ("CONCEPTS_DIR", CONCEPTS_DIR),
        ("CONNECTIONS_DIR", CONNECTIONS_DIR),
        ("QA_DIR", QA_DIR),
        ("INSTINCTS_DIR", INSTINCTS_DIR),
        ("WIKI_DIR", WIKI_DIR),
        ("INDEX_FILE", INDEX_FILE),
        ("LOG_FILE", LOG_FILE),
        ("WIKI_INDEX_FILE", WIKI_INDEX_FILE),
        ("PROJECTS_REGISTRY_FILE", PROJECTS_REGISTRY_FILE),
        ("OBSERVATIONS_FILE", OBSERVATIONS_FILE),
        ("STATE_FILE", STATE_FILE),
        ("TIMEZONE", TIMEZONE),
        ("COMPACT_THRESHOLD", COMPACT_THRESHOLD),
        ("FLUSH_MAX_CONTEXT_CHARS", FLUSH_MAX_CONTEXT_CHARS),
        ("INSTINCT_SYNTHESIS_WINDOW_HOURS", INSTINCT_SYNTHESIS_WINDOW_HOURS),
        ("LOG_LEVEL", LOG_LEVEL),
        ("now_iso()", now_iso()),
        ("today_iso()", today_iso()),
    ]
    width = max(len(name) for name, _ in entries)
    for name, value in entries:
        print(f"{name.ljust(width)} = {value}")


if __name__ == "__main__":
    if "--print" in sys.argv[1:]:
        _print_config()
        sys.exit(0)
    sys.stderr.write("Usage: python scripts/config.py --print\n")
    sys.exit(2)
