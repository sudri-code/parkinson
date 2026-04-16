#!/usr/bin/env python3
"""
bootstrap.py — cross-platform installer for parkinson (Windows + fallback).

Mirrors install.sh: guards uv presence, runs `uv sync`, creates data
directories, copies templates non-destructively, wires hooks into
~/.claude/settings.json with __REPO_ROOT__ substitution.

Usage:
    python bootstrap.py

All operations are idempotent — re-running never overwrites existing data
or settings.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def _uv_check() -> None:
    if shutil.which("uv") is None:
        sys.stderr.write(
            "ERROR: `uv` not found on PATH.\n"
            "Install: https://docs.astral.sh/uv/\n"
        )
        sys.exit(1)


def _uv_sync() -> None:
    print("Syncing dependencies (uv sync)...")
    subprocess.run(
        ["uv", "sync", "--quiet"],
        cwd=str(REPO_ROOT),
        check=True,
    )
    print("✓ Dependencies installed in .venv/")


def _resolve_data_dir() -> Path:
    env = os.environ.get("PARKINSON_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    pointer = REPO_ROOT / ".parkinson-data-dir"
    if pointer.is_file():
        value = pointer.read_text(encoding="utf-8").strip()
        if value:
            return Path(value).expanduser().resolve()
    return REPO_ROOT / "data"


def _create_dirs(data_dir: Path) -> None:
    for sub in [
        data_dir / "daily",
        data_dir / "knowledge" / "concepts",
        data_dir / "knowledge" / "connections",
        data_dir / "knowledge" / "qa",
        data_dir / "knowledge" / "instincts",
        data_dir / "wiki",
        data_dir / "raw" / "assets",
        data_dir / "reports" / "agentshield",
        REPO_ROOT / "observations" / "archive",
        REPO_ROOT / "state" / "tool-counts",
    ]:
        sub.mkdir(parents=True, exist_ok=True)
    print("✓ Data directories created")


def _copy_if_missing(src: Path, dst: Path) -> None:
    if not dst.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        print(f"  + {dst}")


def _copy_templates(data_dir: Path) -> None:
    tpl = REPO_ROOT / "templates"
    _copy_if_missing(tpl / "projects.json", data_dir / "projects.json")
    _copy_if_missing(tpl / "knowledge-index.md", data_dir / "knowledge" / "index.md")
    _copy_if_missing(tpl / "knowledge-log.md", data_dir / "knowledge" / "log.md")
    print("✓ Templates copied (missing files only)")


def _wire_hooks() -> None:
    template = REPO_ROOT / "examples" / ".claude" / "settings.json"
    settings = Path.home() / ".claude" / "settings.json"

    if not template.is_file():
        print(f"WARN: template missing at {template}")
        return

    content = template.read_text(encoding="utf-8").replace("__REPO_ROOT__", str(REPO_ROOT))

    if not settings.is_file():
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(content, encoding="utf-8")
        print(f"✓ Created {settings} with hooks wired to {REPO_ROOT}")
        return

    print(f"ℹ {settings} already exists — not overwriting.")
    print()
    print(f"  To add parkinson hooks, merge entries from:")
    print(f"    {template}")
    print(f"  (after substituting __REPO_ROOT__ → {REPO_ROOT}).")
    print()
    print("  Or apply programmatically:")
    print(f"    python -c \"import json, pathlib, os;"
          f" a=json.loads(pathlib.Path(r'{settings}').read_text());"
          f" b=json.loads(pathlib.Path(r'{template}').read_text().replace('__REPO_ROOT__', r'{REPO_ROOT}'));"
          f" a.setdefault('hooks', {{}}).update(b.get('hooks', {{}}));"
          f" pathlib.Path(r'{settings}').write_text(json.dumps(a, indent=2))\"")


def _offer_claude_md_snippet() -> None:
    """Optionally append parkinson-aware instructions to ~/.claude/CLAUDE.md.

    Idempotent via the `<!-- BEGIN: parkinson-instructions -->` marker.
    Skipped silently in non-interactive shells.
    """
    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    marker = "<!-- BEGIN: parkinson-instructions -->"

    locale = (os.environ.get("LANG") or os.environ.get("LC_ALL") or "").lower()
    name = "global-claude-md-snippet.ru.md" if locale.startswith("ru") else "global-claude-md-snippet.md"
    snippet = REPO_ROOT / "templates" / name

    if not snippet.is_file():
        print(f"WARN: snippet template missing at {snippet}")
        return

    print()
    if claude_md.is_file() and marker in claude_md.read_text(encoding="utf-8"):
        print(f"✓ Parkinson snippet already present in {claude_md}")
        return

    if not sys.stdin.isatty():
        print("ℹ Non-interactive shell — skipping CLAUDE.md prompt.")
        print(f"  To add parkinson-aware instructions later, append the contents of:")
        print(f"    {snippet}")
        print(f"  to:")
        print(f"    {claude_md}")
        return

    print(f"Optional: append parkinson-aware instructions to {claude_md}")
    print("  (helps Claude scan the SessionStart inject before answering 'what is X?').")
    print()
    print("Snippet preview:")
    for line in snippet.read_text(encoding="utf-8").splitlines():
        print(f"  | {line}")
    print()

    try:
        reply = input("Append now? [y/N] ").strip().lower()
    except EOFError:
        reply = ""

    if reply in ("y", "yes"):
        claude_md.parent.mkdir(parents=True, exist_ok=True)
        existing = claude_md.read_text(encoding="utf-8") if claude_md.is_file() else ""
        sep = "\n" if existing and not existing.endswith("\n") else ""
        claude_md.write_text(existing + sep + snippet.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"✓ Appended to {claude_md}")
    else:
        print(f"ℹ Skipped. Manually copy from {snippet} when ready.")


def _smoke_check() -> None:
    print()
    print("Smoke check — resolved paths:")
    try:
        result = subprocess.run(
            ["uv", "run", "--quiet", "python", "scripts/config.py", "--print"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines()[:12]:
            print(f"  {line}")
    except Exception as exc:
        print(f"  (smoke check failed: {exc})")


def _next_steps() -> None:
    print()
    print("Setup complete.")
    print()
    print("Next steps:")
    print("  1. (optional) cp .env.example .env  and adjust PARKINSON_* variables.")
    print("  2. Open Claude Code in any project — SessionStart hook will fire.")
    print("  3. After a few sessions: uv run python scripts/lint.py --structural-only")
    print("  4. Compile: uv run python scripts/compile.py")
    print()
    print("Docs: README.ru.md, docs/install.ru.md, docs/architecture.ru.md")


def main() -> int:
    print(f"parkinson installer — repo root: {REPO_ROOT}")
    print()
    _uv_check()
    print(f"✓ uv found")
    _uv_sync()
    data_dir = _resolve_data_dir()
    print()
    print(f"Data root: {data_dir}")
    _create_dirs(data_dir)
    _copy_templates(data_dir)
    _wire_hooks()
    _offer_claude_md_snippet()
    _smoke_check()
    _next_steps()
    return 0


if __name__ == "__main__":
    sys.exit(main())
