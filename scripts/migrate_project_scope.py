"""
One-off migration: backfill `projects: [...]` into existing concept/connection/qa
articles by deriving project from `sources:` (daily logs).

Dry-run by default. Use --apply to actually write files.

Usage:
    uv run python scripts/migrate_project_scope.py           # dry-run report
    uv run python scripts/migrate_project_scope.py --apply   # write changes
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from config import CONCEPTS_DIR, DAILY_DIR, KNOWLEDGE_DIR  # noqa: E402
from utils import extract_wikilinks, list_wiki_articles  # noqa: E402
from utils_projects import (  # noqa: E402
    extract_projects_field,
    load_projects_registry,
    projects_in_daily,
)


def parse_sources(frontmatter: str) -> list[str]:
    """Extract source file paths from YAML frontmatter (inline or block list)."""
    sources: list[str] = []
    in_sources = False

    for raw in frontmatter.splitlines():
        if raw.startswith("sources:"):
            after = raw.split(":", 1)[1].strip()
            if after.startswith("["):
                for s in re.findall(r"""['"]?([^,\[\]'"]+)['"]?""", after):
                    s = s.strip()
                    if s and s != "":
                        sources.append(s)
                in_sources = False
            else:
                in_sources = True
            continue

        if in_sources:
            stripped = raw.strip()
            if stripped.startswith("- "):
                s = stripped[2:].strip().strip("'\"")
                if s:
                    sources.append(s)
            elif raw and not raw.startswith(" ") and not raw.startswith("\t"):
                in_sources = False

    return sources


def resolve_sources_to_projects(sources: list[str]) -> list[str]:
    found: set[str] = set()
    for src in sources:
        if not src.startswith("daily/"):
            continue
        daily_path = DAILY_DIR / Path(src).name
        if not daily_path.exists():
            continue
        for proj in projects_in_daily(daily_path):
            found.add(proj)
    return sorted(found)


def _alias_lookup() -> dict[str, str]:
    registry = load_projects_registry()
    lookup: dict[str, str] = {}
    for entry in registry.values():
        canonical = entry.get("canonical")
        if not canonical or canonical == "Shared":
            continue
        lookup[canonical.lower()] = canonical
        name = entry.get("name")
        if name:
            lookup[name.lower()] = canonical
        for alias in entry.get("aliases", []):
            lookup[str(alias).lower()] = canonical
    return lookup


def narrow_projects_by_body(body: str, candidates: list[str]) -> list[str]:
    if len(candidates) <= 1:
        return candidates
    lookup = _alias_lookup()
    body_lower = body.lower()
    mentioned: set[str] = set()
    for alias_lc, canonical in lookup.items():
        if canonical not in candidates:
            continue
        if re.search(r"\b" + re.escape(alias_lc) + r"\b", body_lower):
            mentioned.add(canonical)
    if mentioned:
        return sorted(mentioned)
    return candidates


def inject_projects_field(content: str, projects: list[str]) -> str:
    if not content.startswith("---"):
        return content
    end = content.find("\n---", 3)
    if end == -1:
        return content

    frontmatter = content[:end]
    body = content[end:]

    lines = frontmatter.split("\n")
    lines = [ln for ln in lines if not re.match(r"^projects:\s*", ln)]

    projects_line = "projects: [" + ", ".join(projects) + "]"
    lines.append(projects_line)

    return "\n".join(lines) + body


def _derive_for_article(
    article: Path, concept_projects_map: dict[str, list[str]]
) -> tuple[list[str], list[str] | None, str | None]:
    content = article.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return ([], None, None)
    end = content.find("\n---", 3)
    if end == -1:
        return ([], None, None)
    frontmatter = content[3:end]

    existing = extract_projects_field(content)
    sources = parse_sources(frontmatter)
    derived = resolve_sources_to_projects(sources)

    body = content[end + len("\n---"):]

    inherited: list[str] = []
    seen_inh: set[str] = set()
    for link in extract_wikilinks(body):
        if link.startswith("daily/"):
            continue
        slug = link.split("|")[0]
        for p in concept_projects_map.get(slug, []):
            if p.lower() not in seen_inh and p.lower() != "shared":
                seen_inh.add(p.lower())
                inherited.append(p)

    if inherited:
        derived = inherited
    else:
        derived = narrow_projects_by_body(body, derived)

    union: list[str] = []
    seen: set[str] = set()
    for p in (existing or []) + derived:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            union.append(p)
    return (union, existing, content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill projects: field into wiki articles")
    parser.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    parser.add_argument(
        "--default",
        default="shared",
        help="Project to assign when sources yield no known project (default: shared)",
    )
    args = parser.parse_args()

    articles = list_wiki_articles()
    concepts = [a for a in articles if a.is_relative_to(CONCEPTS_DIR)]
    others = [a for a in articles if not a.is_relative_to(CONCEPTS_DIR)]

    concept_projects_map: dict[str, list[str]] = {}
    changes: list[tuple[Path, list[str], list[str] | None]] = []

    def process(article: Path) -> None:
        union, existing, content = _derive_for_article(article, concept_projects_map)
        if content is None:
            return
        if not union:
            union = [args.default]

        existing_lower = sorted(p.lower() for p in (existing or []))
        union_lower = sorted(p.lower() for p in union)
        if existing is not None and existing_lower == union_lower:
            return

        changes.append((article, union, existing))
        if args.apply:
            new_content = inject_projects_field(content, union)
            article.write_text(new_content, encoding="utf-8")

        rel = article.relative_to(KNOWLEDGE_DIR).with_suffix("")
        concept_projects_map[str(rel).replace("\\", "/")] = union

    for article in concepts:
        process(article)
    for article in others:
        process(article)

    print(f"Articles scanned: {len(articles)}")
    print(f"Articles {'migrated' if args.apply else 'to migrate'}: {len(changes)}")
    for path, new_projects, old_projects in changes:
        rel = path.relative_to(KNOWLEDGE_DIR)
        arrow = f"{old_projects} → {new_projects}" if old_projects is not None else f"(none) → {new_projects}"
        print(f"  {rel}: {arrow}")

    if not args.apply and changes:
        print("\n(Dry-run. Use --apply to write changes.)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
