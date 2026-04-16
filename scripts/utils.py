"""
utils.py — base helpers for parkinson scripts.

Clean-room implementation written from scratch against the specification
in docs/architecture.ru.md. No source code from coleam00/claude-memory-compiler
was consulted during authorship.

Co-authored with Anthropic's Claude Code under the direction and review
of the copyright holder. See docs/clean-room-provenance.md.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path

from config import (
    CONCEPTS_DIR,
    CONNECTIONS_DIR,
    INDEX_FILE,
    INSTINCTS_DIR,
    KNOWLEDGE_DIR,
    LOG_LEVEL,
    QA_DIR,
)


# ── Slug / naming ─────────────────────────────────────────────────────

_SLUG_NON_WORD = re.compile(r"[^\w\s-]")
_SLUG_SPACES = re.compile(r"[\s_]+")
_SLUG_REPEAT = re.compile(r"-+")


def slugify(text: str) -> str:
    """Convert free text to a filename-safe, lowercase, hyphen-joined slug."""
    lowered = text.lower().strip()
    cleaned = _SLUG_NON_WORD.sub("", lowered)
    dashed = _SLUG_SPACES.sub("-", cleaned)
    collapsed = _SLUG_REPEAT.sub("-", dashed)
    return collapsed.strip("-")


# ── Hashing ───────────────────────────────────────────────────────────


def file_hash(path: Path) -> str:
    """Short SHA-256 hex prefix of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def text_hash(text: str) -> str:
    """Short SHA-256 hex prefix of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── Atomic text write ─────────────────────────────────────────────────


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically via tempfile + os.replace to prevent torn writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.tmp.",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ── Frontmatter parsing (minimal YAML subset) ─────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_KV_RE = re.compile(r"^([A-Za-z_][\w\-]*)\s*:\s*(.*)$")
_LIST_INLINE_RE = re.compile(r"^\[(.*)\]$")


def _parse_scalar(raw: str) -> str | list[str] | None:
    value = raw.strip()
    if value == "":
        return ""
    inline_list = _LIST_INLINE_RE.match(value)
    if inline_list:
        inner = inline_list.group(1).strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in inner.split(",")]
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def read_frontmatter(text: str) -> dict[str, str | list[str]]:
    """Parse top YAML frontmatter into a flat dict.

    Supports scalar values, inline lists `[a, b, c]`, and dash-prefixed
    multi-line lists. No nested structures. Missing frontmatter → empty dict.
    """
    if not text.startswith("---"):
        return {}
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    result: dict[str, str | list[str]] = {}
    current_key: str | None = None
    current_list: list[str] | None = None
    for raw_line in match.group(1).splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if current_list is not None and raw_line.lstrip().startswith("- "):
            current_list.append(raw_line.lstrip()[2:].strip().strip("'\""))
            continue
        if current_list is not None:
            # list block ended
            if current_key is not None:
                result[current_key] = current_list
            current_list = None
            current_key = None
        kv = _KV_RE.match(raw_line)
        if not kv:
            continue
        key, raw_value = kv.group(1), kv.group(2)
        if raw_value.strip() == "":
            # block-list start
            current_key = key
            current_list = []
            continue
        parsed = _parse_scalar(raw_value)
        if parsed is not None:
            result[key] = parsed  # type: ignore[assignment]
    if current_list is not None and current_key is not None:
        result[current_key] = current_list
    return result


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict, body without frontmatter)."""
    fm = read_frontmatter(text)
    if not fm:
        return {}, text
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return fm, text
    body_start = match.end()
    return fm, text[body_start:].lstrip("\n")


# ── Wikilinks ─────────────────────────────────────────────────────────

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def extract_wikilinks(content: str) -> list[str]:
    """Return all [[wikilink]] targets (without aliases, without brackets)."""
    out: list[str] = []
    for raw in _WIKILINK_RE.findall(content):
        out.append(raw.split("|", 1)[0].strip())
    return out


def wiki_article_exists(link: str) -> bool:
    """True if a wikilink target resolves to a file under knowledge/."""
    return (KNOWLEDGE_DIR / f"{link}.md").is_file()


def list_wiki_articles() -> list[Path]:
    """Return every compiled article file under knowledge/{concepts,connections,qa}."""
    articles: list[Path] = []
    for subdir in (CONCEPTS_DIR, CONNECTIONS_DIR, QA_DIR):
        if subdir.is_dir():
            articles.extend(sorted(subdir.glob("*.md")))
    return articles


def list_instinct_files() -> list[Path]:
    """Return every instinct markdown file."""
    if not INSTINCTS_DIR.is_dir():
        return []
    return sorted(INSTINCTS_DIR.glob("*.md"))


# ── Index helpers ─────────────────────────────────────────────────────


def read_index() -> str:
    """Read knowledge/index.md or return a minimal header if missing."""
    if INDEX_FILE.is_file():
        return INDEX_FILE.read_text(encoding="utf-8")
    return (
        "# Knowledge Base Index\n\n"
        "| Article | Summary | Projects | Compiled From | Updated |\n"
        "|---------|---------|----------|---------------|---------|\n"
    )


def count_inbound_links(target: str, exclude: Path | None = None) -> int:
    """Count other articles linking to the given wikilink target."""
    count = 0
    needle = f"[[{target}]]"
    for article in list_wiki_articles():
        if exclude is not None and article == exclude:
            continue
        try:
            content = article.read_text(encoding="utf-8")
        except OSError:
            continue
        if needle in content:
            count += 1
    return count


# ── Logging ───────────────────────────────────────────────────────────


def setup_logger(name: str, log_file: Path | None = None) -> logging.Logger:
    """Configure and return a named logger with PARKINSON_LOG_LEVEL."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logger.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(str(log_file), encoding="utf-8")
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


# ── Word count ────────────────────────────────────────────────────────


def body_word_count(text: str) -> int:
    """Count words in body (excluding YAML frontmatter)."""
    _, body = split_frontmatter(text)
    return len(body.split())
