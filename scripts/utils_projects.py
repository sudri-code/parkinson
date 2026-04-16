"""
utils_projects.py — project-scope registry + secret scrubbing helpers.

This module is a mix of:
  [AS]  Original code authored for parkinson by the copyright holder:
        detect_project, ensure_project_registered, _projects_registry_lock,
        load_projects_registry, resolve_project_aliases,
        extract_projects_field, article_matches_project,
        parse_daily_section_projects.

  [ECC] Fragments adapted from affaan-m/everything-claude-code (MIT):
        scrub_secrets, write_atomic_json.
        Each block is delimited by explicit attribution comments.

See NOTICE for full licence text.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from config import (
    CONCEPTS_DIR,
    CONNECTIONS_DIR,
    DATA_DIR,
    KNOWLEDGE_DIR,
    PROJECTS_REGISTRY_FILE,
    QA_DIR,
)


# ╔═══════════════════════════════════════════════════════════════════╗
# ║  [ECC] Adapted from everything-claude-code (MIT)                   ║
# ║  Source: https://github.com/affaan-m/everything-claude-code        ║
# ║  Original author: Affaan Mustafa. MIT License — see NOTICE.        ║
# ╚═══════════════════════════════════════════════════════════════════╝


def write_atomic_json(path: Path, payload: dict | list) -> None:
    """Atomically write JSON via tempfile + os.replace.

    [ECC] Adapted from everything-claude-code `detect-project.sh`.
    Prevents torn writes on crash.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.tmp.",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization|credentials?|auth)"
    r"""(["'\s:=]+)"""
    r"([A-Za-z]+\s+)?"
    r"([A-Za-z0-9_\-/.+=]{8,})"
)


def scrub_secrets(text: str) -> str:
    """Redact common key=value secret patterns.

    [ECC] Adapted from everything-claude-code `observe.sh` SECRET_RE.
    Handles api_key, token, secret, password, authorization, credentials,
    auth — with optional auth scheme (Bearer/Basic) before the token.
    """
    if not text:
        return text
    return _SECRET_RE.sub(
        lambda m: m.group(1) + m.group(2) + (m.group(3) or "") + "[REDACTED]",
        text,
    )


# ╔═══════════════════════════════════════════════════════════════════╗
# ║  [AS] Original parkinson code — project-scope registry.            ║
# ╚═══════════════════════════════════════════════════════════════════╝


# ── Registry I/O ──────────────────────────────────────────────────────


def load_projects_registry() -> dict:
    """Load projects.json, return {} if missing or malformed."""
    if not PROJECTS_REGISTRY_FILE.exists():
        return {}
    try:
        return json.loads(PROJECTS_REGISTRY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


@contextlib.contextmanager
def _projects_registry_lock():
    """Advisory flock on sidecar lockfile to serialize registry writes."""
    PROJECTS_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = PROJECTS_REGISTRY_FILE.with_suffix(".lock")
    with open(lock_path, "w", encoding="utf-8") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


# ── Git-based project identity ────────────────────────────────────────


def _git(cwd: str | Path, *args: str) -> str | None:
    """Run a git command, return stripped stdout or None on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


_CREDS_RE = re.compile(r"://[^@/]+@")


def _strip_credentials(url: str) -> str:
    """Strip inline creds from https://user:pass@host/... URLs."""
    return _CREDS_RE.sub("://", url)


def _project_id(hash_input: str) -> str:
    """SHA-256 hex prefix (12 chars) of the hash input."""
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:12]


def _canonical_from_name(name: str) -> str:
    """Default canonical: capitalize first letter, preserve the rest."""
    if not name:
        return name
    return name[0].upper() + name[1:]


def detect_project(cwd: str | Path | None = None) -> dict:
    """Detect the current project context (read-only).

    Resolution order:
      1. CLAUDE_PROJECT_DIR env var.
      2. `git rev-parse --show-toplevel` from cwd.
      3. `git remote get-url origin` — id = sha256(remote)[:12].
      4. Otherwise id = sha256(project_root)[:12].
      5. Fallback: id == "shared".
    """
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    project_root: str | None = None
    source = "fallback"

    if env_dir and Path(env_dir).is_dir():
        project_root = env_dir
        source = "env"
    elif cwd:
        cwd_path = Path(cwd).expanduser()
        if cwd_path.is_dir():
            git_root = _git(cwd_path, "rev-parse", "--show-toplevel")
            if git_root:
                project_root = git_root
                source = "git-toplevel"
            else:
                project_root = str(cwd_path)
                source = "cwd"

    if not project_root:
        return {
            "id": "shared",
            "name": "shared",
            "canonical": "Shared",
            "root": None,
            "remote": None,
            "source": "fallback",
        }

    name = Path(project_root).name

    remote = _git(project_root, "remote", "get-url", "origin")
    if remote:
        remote = _strip_credentials(remote)
        pid = _project_id(remote)
        if source != "env":
            source = "git-remote"
    else:
        pid = _project_id(project_root)

    registry = load_projects_registry()
    entry = registry.get(pid, {})
    canonical = entry.get("canonical") or entry.get("name") or name

    return {
        "id": pid,
        "name": name,
        "canonical": canonical,
        "root": project_root,
        "remote": remote,
        "source": source,
    }


def ensure_project_registered(project: dict) -> dict:
    """Add a stub entry to projects.json if unknown. Idempotent.

    Fast path: if id already in registry, returns without writing.
    New entry fields: id, name, canonical (capitalized), aliases, root,
    remote, auto_registered date, notes. Existing entries are never
    overwritten. Mutates `project["canonical"]` to match registry so
    the first session sees consistent naming.
    """
    pid = project.get("id")
    if not pid or pid == "shared":
        return project

    registry = load_projects_registry()
    if pid in registry:
        existing = registry[pid]
        project["canonical"] = (
            existing.get("canonical") or project.get("canonical")
        )
        return project

    name = project.get("name") or "unknown"
    stub = {
        "id": pid,
        "name": name,
        "canonical": _canonical_from_name(name),
        "aliases": [name.lower()],
        "root": project.get("root"),
        "remote": project.get("remote"),
        "auto_registered": datetime.now(timezone.utc)
        .astimezone()
        .strftime("%Y-%m-%d"),
        "notes": (
            "Auto-registered on first detection — "
            "edit canonical/aliases/notes to customize."
        ),
    }

    with _projects_registry_lock():
        registry = load_projects_registry()  # re-read inside lock
        if pid in registry:
            existing = registry[pid]
            project["canonical"] = (
                existing.get("canonical") or project.get("canonical")
            )
            return project
        registry[pid] = stub
        write_atomic_json(PROJECTS_REGISTRY_FILE, registry)

    project["canonical"] = stub["canonical"]
    return project


# ── Alias resolution ──────────────────────────────────────────────────


def resolve_project_aliases(identifier: str) -> set[str]:
    """Return full alias set for any canonical/name/alias identifier.

    Unknown identifier → {identifier_lower} (so filtering doesn't match
    nothing silently).
    """
    ident_lower = identifier.lower()
    registry = load_projects_registry()
    for entry in registry.values():
        names = {
            str(entry.get("canonical", "")).lower(),
            str(entry.get("name", "")).lower(),
        } | {str(a).lower() for a in entry.get("aliases", [])}
        names.discard("")
        if ident_lower in names:
            names.add(ident_lower)
            return names
    return {ident_lower}


# ── Article projects-field parsing ────────────────────────────────────


_PROJECTS_FIELD_RE = re.compile(r"^projects:\s*\[([^\]]*)\]", re.MULTILINE)


def extract_projects_field(article_content: str) -> list[str] | None:
    """Return `projects: [...]` list from frontmatter, or None if missing."""
    if not article_content.startswith("---"):
        return None
    end = article_content.find("---", 3)
    if end == -1:
        return None
    frontmatter = article_content[3:end]
    m = _PROJECTS_FIELD_RE.search(frontmatter)
    if not m:
        return None
    raw = m.group(1).strip()
    if not raw:
        return []
    return [v.strip().strip("'\"") for v in raw.split(",")]


def article_matches_project(
    article_content: str, project_aliases: set[str]
) -> bool:
    """True if article's projects intersect aliases, or projects absent,
    or projects contains 'shared'/'all'.
    """
    projects = extract_projects_field(article_content)
    if projects is None:
        return True
    lower = {p.lower() for p in projects}
    if not lower or "shared" in lower or "all" in lower:
        return True
    aliases_lower = {a.lower() for a in project_aliases}
    return bool(lower & aliases_lower)


def read_all_articles_for_project(project_filter: set[str] | None = None) -> str:
    """Concat index + filtered articles for LLM context consumption."""
    parts: list[str] = []
    from config import INDEX_FILE  # lazy to avoid circular concerns

    if INDEX_FILE.is_file():
        parts.append(f"## INDEX\n\n{INDEX_FILE.read_text(encoding='utf-8')}")
    for subdir in (CONCEPTS_DIR, CONNECTIONS_DIR, QA_DIR):
        if not subdir.is_dir():
            continue
        for md in sorted(subdir.glob("*.md")):
            content = md.read_text(encoding="utf-8")
            if project_filter and not article_matches_project(content, project_filter):
                continue
            rel = md.relative_to(KNOWLEDGE_DIR)
            parts.append(f"## {rel}\n\n{content}")
    return "\n\n---\n\n".join(parts)


# ── Daily log section → project parsing ───────────────────────────────

_DAILY_HEADER_RE = re.compile(r"^###\s+(.+?)\s*$")
_TAG_SUFFIX_RE = re.compile(r"—\s*([A-Za-z0-9_\-.]+)\s*(?:\(|$)")


def parse_daily_section_projects(daily_path: Path) -> dict[str, str]:
    """Parse a daily log, return {section_header: canonical_project}."""
    if not daily_path.exists():
        return {}
    registry = load_projects_registry()
    alias_to_canonical: dict[str, str] = {}
    for entry in registry.values():
        canonical = entry.get("canonical")
        if not canonical:
            continue
        alias_to_canonical[canonical.lower()] = canonical
        for alias in entry.get("aliases", []):
            alias_to_canonical[alias.lower()] = canonical
        name = entry.get("name")
        if name:
            alias_to_canonical[name.lower()] = canonical

    out: dict[str, str] = {}
    for raw_line in daily_path.read_text(encoding="utf-8").splitlines():
        m = _DAILY_HEADER_RE.match(raw_line)
        if not m:
            continue
        header = m.group(1)
        tag_match = _TAG_SUFFIX_RE.search(header)
        if not tag_match:
            continue
        tag = tag_match.group(1)
        canonical = alias_to_canonical.get(tag.lower(), tag)
        out[header] = canonical
    return out


def projects_in_daily(daily_path: Path) -> list[str]:
    """Sorted unique canonical project names referenced in a daily log."""
    sections = parse_daily_section_projects(daily_path)
    return sorted({p for p in sections.values() if p})
