"""
lint.py — seven health checks for the knowledge base.

Clean-room implementation written from scratch against the specification
in docs/architecture.ru.md §Lint. No source code from
coleam00/claude-memory-compiler was consulted during authorship.

Co-authored with Anthropic's Claude Code under the direction and review
of the copyright holder. See docs/clean-room-provenance.md.

Checks:
    1. broken_links        — [[wikilinks]] pointing at non-existent articles
    2. orphan_pages        — articles with zero inbound links
    3. orphan_sources      — daily logs not yet compiled
    4. stale_articles      — source log changed since compile
    5. missing_backlinks   — A links B but B does not link back
    6. sparse_articles     — body under 200 words
    7. contradictions      — LLM-judged conflicting claims (skipped with --structural-only)

Bonus (project-scope aware):
    * projects_missing     — article has no `projects:` frontmatter field
    * unknown_project_alias — alias not in projects.json registry
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config import (
    DAILY_DIR,
    INDEX_FILE,
    KNOWLEDGE_DIR,
    REPORTS_DIR,
    STATE_FILE,
    now_iso,
    today_iso,
)
from utils import (
    body_word_count,
    extract_message_text,
    extract_wikilinks,
    file_hash,
    list_wiki_articles,
    read_index,
    split_frontmatter,
    wiki_article_exists,
)
from utils_projects import (
    extract_projects_field,
    load_projects_registry,
)


SPARSE_MIN_WORDS = 200


# ── Issue dataclass substitute ────────────────────────────────────────


def _issue(severity: str, check: str, file: str, detail: str) -> dict:
    return {
        "severity": severity,
        "check": check,
        "file": file,
        "detail": detail,
    }


# ── State access ──────────────────────────────────────────────────────


def _load_state() -> dict:
    if not STATE_FILE.is_file():
        return {"ingested": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"ingested": {}}


# ── 1. Broken wikilinks ───────────────────────────────────────────────


def check_broken_links() -> list[dict]:
    issues: list[dict] = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(KNOWLEDGE_DIR)
        for link in extract_wikilinks(content):
            if link.startswith("daily/"):
                daily_path = DAILY_DIR / f"{link.split('/', 1)[1]}"
                if not daily_path.is_file():
                    issues.append(_issue(
                        "error", "broken_link", str(rel),
                        f"Daily source [[{link}]] does not exist",
                    ))
                continue
            if not wiki_article_exists(link):
                issues.append(_issue(
                    "error", "broken_link", str(rel),
                    f"Wikilink [[{link}]] points to a non-existent article",
                ))
    return issues


# ── 2. Orphan pages ───────────────────────────────────────────────────


def check_orphan_pages() -> list[dict]:
    """Articles that no other article links to."""
    articles = list_wiki_articles()
    link_targets: dict[str, int] = {}
    for article in articles:
        content = article.read_text(encoding="utf-8")
        for link in extract_wikilinks(content):
            link_targets[link] = link_targets.get(link, 0) + 1
    issues: list[dict] = []
    for article in articles:
        rel = article.relative_to(KNOWLEDGE_DIR)
        slug = str(rel).removesuffix(".md")
        if link_targets.get(slug, 0) == 0:
            issues.append(_issue(
                "warning", "orphan_page", str(rel),
                "No other article links to this one",
            ))
    return issues


# ── 3. Orphan sources ─────────────────────────────────────────────────


def check_orphan_sources() -> list[dict]:
    """Daily logs that have never been compiled."""
    if not DAILY_DIR.is_dir():
        return []
    state = _load_state()
    ingested = state.get("ingested", {})
    issues: list[dict] = []
    for daily in sorted(DAILY_DIR.glob("*.md")):
        if daily.name not in ingested:
            issues.append(_issue(
                "suggestion", "orphan_source", f"daily/{daily.name}",
                "Daily log has not been compiled into knowledge yet",
            ))
    return issues


# ── 4. Stale articles ─────────────────────────────────────────────────


def check_stale_articles() -> list[dict]:
    """Source daily log changed since article was last compiled."""
    state = _load_state()
    ingested = state.get("ingested", {})
    issues: list[dict] = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        fm, _ = split_frontmatter(content)
        sources = fm.get("sources") or []
        if isinstance(sources, str):
            sources = [sources]
        rel = article.relative_to(KNOWLEDGE_DIR)
        for source in sources:
            if not isinstance(source, str) or not source.startswith("daily/"):
                continue
            daily_name = source.split("/", 1)[1].removesuffix(".md") + ".md"
            daily_path = DAILY_DIR / daily_name
            if not daily_path.is_file():
                continue
            current_hash = file_hash(daily_path)
            recorded = ingested.get(daily_name, {})
            recorded_hash = (
                recorded.get("hash") if isinstance(recorded, dict) else None
            )
            if recorded_hash and recorded_hash != current_hash:
                issues.append(_issue(
                    "warning", "stale_article", str(rel),
                    f"Source {source} changed since last compile",
                ))
                break
    return issues


# ── 5. Missing backlinks ──────────────────────────────────────────────


def check_missing_backlinks() -> list[dict]:
    """If A links to B via Related Concepts, B should link back."""
    articles = list_wiki_articles()
    outgoing: dict[str, set[str]] = {}
    for article in articles:
        content = article.read_text(encoding="utf-8")
        slug = str(article.relative_to(KNOWLEDGE_DIR)).removesuffix(".md")
        outgoing[slug] = set(extract_wikilinks(content))

    issues: list[dict] = []
    for src, targets in outgoing.items():
        for target in targets:
            if target.startswith("daily/"):
                continue
            if target not in outgoing:
                continue  # broken link — caught by check #1
            if src not in outgoing[target]:
                issues.append(_issue(
                    "suggestion", "missing_backlink", f"{target}.md",
                    f"Target linked from [[{src}]] but does not link back",
                ))
    return issues


# ── 6. Sparse articles ────────────────────────────────────────────────


def check_sparse_articles() -> list[dict]:
    issues: list[dict] = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        words = body_word_count(content)
        rel = article.relative_to(KNOWLEDGE_DIR)
        if words < SPARSE_MIN_WORDS:
            issues.append(_issue(
                "suggestion", "sparse_article", str(rel),
                f"Body has only {words} words (threshold {SPARSE_MIN_WORDS})",
            ))
    return issues


# ── Bonus: projects-field checks ──────────────────────────────────────


def check_projects_missing() -> list[dict]:
    issues: list[dict] = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        if extract_projects_field(content) is None:
            rel = article.relative_to(KNOWLEDGE_DIR)
            issues.append(_issue(
                "warning", "projects_missing", str(rel),
                "Missing `projects:` frontmatter — treated as unscoped",
            ))
    return issues


def check_unknown_project_aliases() -> list[dict]:
    registry = load_projects_registry()
    known = {"shared", "all"}
    for entry in registry.values():
        for key in ("canonical", "name"):
            v = entry.get(key)
            if v:
                known.add(str(v).lower())
        for alias in entry.get("aliases", []):
            known.add(str(alias).lower())

    issues: list[dict] = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        projects = extract_projects_field(content)
        if not projects:
            continue
        unknown = [p for p in projects if p.lower() not in known]
        if unknown:
            rel = article.relative_to(KNOWLEDGE_DIR)
            issues.append(_issue(
                "suggestion", "unknown_project_alias", str(rel),
                f"Unknown project alias(es): {unknown}",
            ))
    return issues


# ── 7. Contradictions (LLM) ───────────────────────────────────────────


def check_contradictions() -> list[dict]:
    """LLM-judged contradictions across articles.

    Uses Claude Agent SDK with the full knowledge base as context. Skip with
    --structural-only.
    """
    articles = list_wiki_articles()
    if len(articles) < 2:
        return []

    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except ImportError:
        return [_issue(
            "warning", "contradictions", "(infra)",
            "claude_agent_sdk not available — run `uv sync` or use --structural-only",
        )]

    bundled = []
    for article in articles:
        rel = article.relative_to(KNOWLEDGE_DIR)
        bundled.append(f"## {rel}\n\n{article.read_text(encoding='utf-8')}")
    context = "\n\n---\n\n".join(bundled)

    prompt = (
        "Проанализируй следующие статьи базы знаний и найди прямые "
        "противоречия между утверждениями в разных статьях. "
        "Ответ строго в виде JSON-массива объектов с полями "
        "{file: str, detail: str}. Если противоречий нет — пустой массив `[]`. "
        "Не используй tools, отвечай plain JSON.\n\n"
        f"{context}"
    )

    try:
        import anyio

        async def _run() -> list[dict]:
            collected: list[str] = []
            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    cwd=str(KNOWLEDGE_DIR),
                    system_prompt={"type": "preset", "preset": "claude_code"},
                    allowed_tools=[],
                    max_turns=1,
                ),
            ):
                text = extract_message_text(message)
                if text:
                    collected.append(text)
            raw = "".join(collected).strip()
            start = raw.find("[")
            end = raw.rfind("]")
            if start == -1 or end == -1:
                return []
            try:
                parsed = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return []
            out: list[dict] = []
            for item in parsed:
                if isinstance(item, dict):
                    out.append(_issue(
                        "warning", "contradiction",
                        str(item.get("file", "?")),
                        str(item.get("detail", "conflicting claim")),
                    ))
            return out

        return anyio.run(_run)
    except Exception as exc:
        return [_issue(
            "warning", "contradictions", "(infra)",
            f"LLM check failed: {exc}",
        )]


# ── Report rendering ──────────────────────────────────────────────────


def format_report(issues: list[dict]) -> str:
    if not issues:
        return "# Lint Report\n\n**0 issues.** Knowledge base is healthy.\n"
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    suggestions = [i for i in issues if i["severity"] == "suggestion"]

    lines = [f"# Lint Report — {now_iso()}", ""]
    lines.append(
        f"**{len(errors)} errors, {len(warnings)} warnings, {len(suggestions)} suggestions.**"
    )
    lines.append("")

    for label, group in (
        ("Errors", errors),
        ("Warnings", warnings),
        ("Suggestions", suggestions),
    ):
        if not group:
            continue
        lines.append(f"## {label}")
        lines.append("")
        for item in group:
            lines.append(f"- **{item['check']}** · `{item['file']}` — {item['detail']}")
        lines.append("")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────


def run_all(structural_only: bool) -> list[dict]:
    issues: list[dict] = []
    issues += check_broken_links()
    issues += check_orphan_pages()
    issues += check_orphan_sources()
    issues += check_stale_articles()
    issues += check_missing_backlinks()
    issues += check_sparse_articles()
    issues += check_projects_missing()
    issues += check_unknown_project_aliases()
    if not structural_only:
        issues += check_contradictions()
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="parkinson health checks")
    parser.add_argument(
        "--structural-only", action="store_true",
        help="Skip LLM-based contradictions check (free, no API calls).",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save report to data/reports/lint-YYYY-MM-DD.md",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of markdown to stdout.",
    )
    args = parser.parse_args(argv)

    issues = run_all(structural_only=args.structural_only)

    if args.json:
        print(json.dumps({"issues": issues, "count": len(issues)}, indent=2, ensure_ascii=False))
    else:
        report = format_report(issues)
        print(report)
        if args.save:
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            out = REPORTS_DIR / f"lint-{today_iso()}.md"
            out.write_text(report, encoding="utf-8")

    errors = sum(1 for i in issues if i["severity"] == "error")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
