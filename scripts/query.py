"""
query.py — index-guided retrieval without RAG.

Clean-room implementation written from scratch against the specification
in docs/architecture.ru.md §Query. No source code from
coleam00/claude-memory-compiler was consulted during authorship.

Co-authored with Anthropic's Claude Code under the direction and review
of the copyright holder. See docs/clean-room-provenance.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config import (
    KNOWLEDGE_DIR,
    LOG_FILE,
    QA_DIR,
    now_iso,
    today_iso,
)
from utils import (
    atomic_write_text,
    extract_message_text,
    list_wiki_articles,
    read_index,
    slugify,
)
from utils_projects import resolve_project_aliases


EMPTY_INDEX_NOTICE = "The knowledge base is empty. Run `compile.py` after a few sessions."


def _bundle_knowledge(project: str | None) -> tuple[str, int]:
    """Return (context string, article count) scoped to project aliases."""
    parts: list[str] = [f"## INDEX\n\n{read_index()}"]
    aliases: set[str] | None = None
    if project:
        aliases = resolve_project_aliases(project)

    count = 0
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        if aliases is not None:
            from utils_projects import article_matches_project
            if not article_matches_project(content, aliases):
                continue
        rel = article.relative_to(KNOWLEDGE_DIR)
        parts.append(f"## {rel}\n\n{content}")
        count += 1
    return "\n\n---\n\n".join(parts), count


def _call_agent(question: str, bundle: str) -> str:
    """Call Agent SDK with the knowledge bundle and return the answer text."""
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query as agent_query
    except ImportError:
        return (
            "[error] claude_agent_sdk not installed — run `uv sync`."
        )

    prompt = (
        "Ты отвечаешь на вопрос пользователя, опираясь только на "
        "предоставленную базу знаний. Сначала прочитай INDEX (master "
        "catalog), выбери 3-10 релевантных статей, затем прочитай "
        "полный текст выбранных статей ниже. Отвечай с цитатами в "
        "формате Obsidian-wikilinks [[concepts/foo]]. Если база знаний "
        "пустая или в ней нет ответа — скажи об этом прямо.\n\n"
        "НЕ используй tools. Верни plain markdown.\n\n"
        f"## Вопрос\n\n{question}\n\n## База знаний\n\n{bundle}\n"
    )

    try:
        import anyio

        async def _run() -> str:
            collected: list[str] = []
            os.environ.setdefault("CLAUDE_INVOKED_BY", "query")
            async for message in agent_query(
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
            return "".join(collected).strip() or "(empty response)"

        return anyio.run(_run)
    except Exception as exc:
        return f"[error] Agent SDK call failed: {exc}"


def _file_back_qa(question: str, answer: str) -> Path:
    """Persist the answer as a qa/ article and append to log.md."""
    QA_DIR.mkdir(parents=True, exist_ok=True)
    slug = slugify(question)[:80] or f"q-{datetime.now().strftime('%H%M%S')}"
    path = QA_DIR / f"{slug}.md"
    body = (
        "---\n"
        f"title: \"Q: {question}\"\n"
        f"question: \"{question.replace(chr(34), chr(39))}\"\n"
        f"filed: {today_iso()}\n"
        f"created: {today_iso()}\n"
        f"updated: {today_iso()}\n"
        "projects: [shared]\n"
        "---\n\n"
        f"# Q: {question}\n\n"
        "## Answer\n\n"
        f"{answer}\n"
    )
    atomic_write_text(path, body)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(
            f"\n## [{now_iso()}] query | {question}\n"
            f"- Filed to: [[qa/{slug}]]\n"
        )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="parkinson knowledge-base query")
    parser.add_argument("question", help="Question to ask")
    parser.add_argument(
        "--file-back", action="store_true",
        help="Save answer as a qa/ article and update index/log.",
    )
    parser.add_argument(
        "--project", default=None,
        help="Restrict to articles tagged with this project / alias.",
    )
    args = parser.parse_args(argv)

    bundle, count = _bundle_knowledge(args.project)
    if count == 0:
        print(EMPTY_INDEX_NOTICE)
        return 0

    answer = _call_agent(args.question, bundle)
    print(answer)
    if args.file_back:
        path = _file_back_qa(args.question, answer)
        print(f"\n---\nSaved to {path.relative_to(KNOWLEDGE_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
