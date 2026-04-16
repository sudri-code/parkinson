"""Cluster near-duplicate instincts in data/knowledge/instincts/ and merge them.

Haiku groups semantically equivalent instincts (same underlying pattern
with different wording/slugs). For each cluster we pick the highest-
confidence file as canonical, merge frontmatter (max confidence, sum
evidence_count, union projects, earliest created, latest last_seen),
append de-duplicated evidence lines, then delete the other files.

Dry-run by default. Pass --apply to actually write/delete.

    uv run python scripts/cluster_instincts.py
    uv run python scripts/cluster_instincts.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("CLAUDE_INVOKED_BY", "instinct_cluster")

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from config import INSTINCTS_DIR, today_iso  # noqa: E402


_CLUSTER_PROMPT = """Ты консолидируешь поведенческие инстинкты пользователя Claude Code. На вход — список файлов-инстинктов (id + trigger + action + domain). Сгруппируй файлы, описывающие один и тот же паттерн разными словами, в кластеры.

Правила:
- В один кластер попадают только инстинкты с одинаковой сутью (trigger близок по смыслу И action близок по смыслу). Язык (ru/en), формулировка, domain-label — не повод разделять.
- Не объединяй разные паттерны, даже если они похожи по словам.
- canonical_id — id самого ёмкого/точного варианта в кластере (тот, который останется).
- Кластер из одного элемента возвращать НЕ нужно — выведи только те, где реально 2+ дубля.
- merged_trigger / merged_action — наилучшая объединённая формулировка (можно взять из canonical или улучшить). Язык — русский, если большинство исходных на русском.
- merged_domain — один устоявшийся snake-case ярлык для кластера.

Верни строго JSON, без комментариев и текста вокруг:

{
  "clusters": [
    {
      "canonical_id": "slug",
      "duplicate_ids": ["slug-a", "slug-b"],
      "merged_trigger": "...",
      "merged_action": "...",
      "merged_domain": "..."
    }
  ]
}

Если дублей нет — верни {"clusters": []}.

## Инстинкты

{catalog}
"""


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not m:
        return {}, text
    out: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            out[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        else:
            out[key] = val.strip("'\"")
    return out, text[m.end():]


def _render_frontmatter(fm: dict) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            quoted = [f'"{x}"' if "," in str(x) else str(x) for x in v]
            lines.append(f"{k}: [{', '.join(quoted)}]")
        elif isinstance(v, (int, float)) and k == "confidence":
            lines.append(f"{k}: {v}")
        else:
            s = str(v)
            if any(c in s for c in [":", "#", "[", "]"]):
                s = f'"{s}"'
            lines.append(f"{k}: {s}")
    lines.append("---")
    return "\n".join(lines)


def _load_all() -> list[tuple[Path, dict, str]]:
    out: list[tuple[Path, dict, str]] = []
    if not INSTINCTS_DIR.exists():
        return out
    for md in sorted(INSTINCTS_DIR.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)
        if fm:
            out.append((md, fm, body))
    return out


def _catalog_lines(items: list[tuple[Path, dict, str]]) -> str:
    parts: list[str] = []
    for _, fm, _ in items:
        iid = fm.get("id", "?")
        trig = (fm.get("trigger", "") or "").replace("\n", " ")
        act = (fm.get("action", "") or "").replace("\n", " ")
        dom = fm.get("domain", "-")
        parts.append(f"- id: {iid}\n  trigger: {trig}\n  action: {act}\n  domain: {dom}")
    return "\n".join(parts)


async def _call_haiku(catalog: str) -> str:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        TextBlock,
        query,
    )

    prompt = _CLUSTER_PROMPT.replace("{catalog}", catalog)
    response = ""
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            allowed_tools=[],
            max_turns=2,
            model="claude-haiku-4-5-20251001",
        ),
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    response += block.text
    return response


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in LLM response")
    return json.loads(m.group(0))


def _merge_evidence_bodies(bodies: list[str]) -> str:
    seen: set[str] = set()
    merged: list[str] = []
    for body in bodies:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") and stripped not in seen:
                seen.add(stripped)
                merged.append(stripped)
    return "\n".join(merged)


def _min_date(values: list[str]) -> str:
    v = [x for x in values if x]
    return min(v) if v else today_iso()


def _max_date(values: list[str]) -> str:
    v = [x for x in values if x]
    return max(v) if v else today_iso()


def _to_float(x, default: float = 0.3) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _to_int(x, default: int = 1) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


def _apply_cluster(
    cluster: dict,
    by_id: dict[str, tuple[Path, dict, str]],
    apply: bool,
) -> tuple[int, list[str]]:
    canonical_id = cluster.get("canonical_id")
    dup_ids = [d for d in cluster.get("duplicate_ids", []) if d != canonical_id]
    all_ids = [canonical_id] + dup_ids

    missing = [i for i in all_ids if i not in by_id]
    if missing:
        return 0, [f"  [skip] unknown ids in cluster: {missing}"]
    if len(all_ids) < 2:
        return 0, [f"  [skip] {canonical_id}: cluster <2"]

    members = [by_id[i] for i in all_ids]
    frontmatters = [fm for _, fm, _ in members]
    bodies = [body for _, _, body in members]

    merged_conf = max(_to_float(fm.get("confidence")) for fm in frontmatters)
    merged_count = sum(_to_int(fm.get("evidence_count")) for fm in frontmatters)
    projects: list[str] = []
    for fm in frontmatters:
        for p in fm.get("projects", []) or []:
            if p and p not in projects:
                projects.append(p)
    if not projects:
        projects = ["shared"]
    created = _min_date([str(fm.get("created", "")) for fm in frontmatters])
    last_seen = _max_date([str(fm.get("last_seen", "")) for fm in frontmatters])

    canonical_path, canonical_fm, _ = by_id[canonical_id]

    new_fm = {
        "id": canonical_id,
        "type": "instinct",
        "trigger": cluster.get("merged_trigger") or canonical_fm.get("trigger", ""),
        "action": cluster.get("merged_action") or canonical_fm.get("action", ""),
        "domain": cluster.get("merged_domain") or canonical_fm.get("domain", "general"),
        "confidence": round(merged_conf, 2),
        "projects": projects,
        "source": canonical_fm.get("source", "session-observation"),
        "evidence_count": merged_count,
        "created": created,
        "last_seen": last_seen,
        "updated": today_iso(),
    }

    evidence_body = _merge_evidence_bodies(bodies)
    title = canonical_id.replace("-", " ").title()
    body = (
        f"# {title}\n\n"
        f"## Action\n\n{new_fm['action']}\n\n"
        f"## Trigger\n\n{new_fm['trigger']}\n\n"
        f"## Evidence\n\n{evidence_body}\n"
    )
    new_content = _render_frontmatter(new_fm) + "\n" + body

    logs = [
        f"  canonical: {canonical_id}  (conf {new_fm['confidence']}, count {merged_count})",
        f"    drop: {', '.join(dup_ids)}",
    ]

    if apply:
        canonical_path.write_text(new_content, encoding="utf-8")
        for dup_id in dup_ids:
            dup_path, _, _ = by_id[dup_id]
            if dup_path != canonical_path and dup_path.exists():
                dup_path.unlink()

    return len(dup_ids), logs


def main() -> int:
    ap = argparse.ArgumentParser(prog="cluster-instincts")
    ap.add_argument("--apply", action="store_true", help="actually merge and delete files")
    args = ap.parse_args()

    items = _load_all()
    if len(items) < 2:
        print(f"(only {len(items)} instincts — nothing to cluster)")
        return 0

    by_id: dict[str, tuple[Path, dict, str]] = {}
    for path, fm, body in items:
        iid = fm.get("id") or path.stem
        by_id[iid] = (path, fm, body)

    catalog = _catalog_lines(items)
    print(f"[{'APPLY' if args.apply else 'DRY-RUN'}] asking Haiku to cluster {len(items)} instincts…")
    raw = asyncio.run(_call_haiku(catalog))
    if not raw.strip():
        print("LLM returned empty response.", file=sys.stderr)
        return 1

    try:
        data = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Failed to parse LLM response: {e}", file=sys.stderr)
        print("--- raw response ---", file=sys.stderr)
        print(raw, file=sys.stderr)
        return 1

    clusters = [c for c in data.get("clusters", []) if len(c.get("duplicate_ids", [])) >= 2]
    if not clusters:
        print("(no clusters of 2+)")
        return 0

    print(f"\nFound {len(clusters)} cluster(s):\n")
    removed_total = 0
    for idx, cluster in enumerate(clusters, 1):
        print(f"cluster #{idx} — domain: {cluster.get('merged_domain', '-')}")
        print(f"  trigger: {cluster.get('merged_trigger', '-')}")
        print(f"  action:  {cluster.get('merged_action', '-')}")
        removed, logs = _apply_cluster(cluster, by_id, args.apply)
        removed_total += removed
        for line in logs:
            print(line)
        print()

    remaining = len(items) - removed_total
    verb = "Removed" if args.apply else "Would remove"
    print(f"{verb} {removed_total} file(s). Instincts: {len(items)} → {remaining}.")
    if not args.apply:
        print("Re-run with --apply to commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
