"""Synthesize behavioural instincts from observations.jsonl.

Reads the last INSTINCT_SYNTHESIS_WINDOW_HOURS of observations, asks
Claude (via Agent SDK) to extract atomic instincts, then upserts them
as markdown files in knowledge/instincts/. On repeat observation the
confidence grows by +0.1 (max 0.9); first observation starts at 0.3.

Invoked sequentially from session-end.py after flush.py. Must not block
indefinitely — timeouts handled by the hook wrapper.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["CLAUDE_INVOKED_BY"] = "instinct_synth"

SCRIPTS_DIR = Path(__file__).resolve().parent
INSTALL_DIR = SCRIPTS_DIR.parent
LOG_FILE = SCRIPTS_DIR / "flush.log"

sys.path.insert(0, str(SCRIPTS_DIR))

from config import (  # noqa: E402
    INSTINCT_SYNTHESIS_MIN_OBSERVATIONS,
    INSTINCT_SYNTHESIS_WINDOW_HOURS,
    INSTINCTS_DIR,
    OBSERVATIONS_FILE,
    today_iso,
)
from utils import slugify  # noqa: E402

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [instincts] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_MAX_OBS_IN_PROMPT = 200
_PROMPT = """Проанализируй наблюдения работы пользователя с Claude Code и выдели до 5 атомарных поведенческих паттернов (instincts). Каждый instinct — один trigger → одно action.

Формат — YAML-блок в ```yaml``` fence:

```yaml
id: short-kebab-case-id
trigger: "когда/в каких условиях"
action: "что делать"
domain: category (например: yaml-frontmatter, git-workflow, python-imports, error-handling)
confidence: 0.3
evidence: "краткое обоснование из наблюдений"
```

КРИТИЧЕСКОЕ правило дедупа: ниже приведён каталог УЖЕ существующих инстинктов. Если новый паттерн по сути совпадает с одним из них (близкий trigger И близкий action), ОБЯЗАТЕЛЬНО переиспользуй его `id` — это инкрементирует confidence вместо создания дубля. Новый id вводи ТОЛЬКО если паттерна действительно нет в каталоге. Язык, формулировка, domain-label — не повод считать паттерн новым.

## Существующие инстинкты (каталог для дедупа)

{existing_catalog}

Только существенные, повторяющиеся паттерны. Если не хватает сигнала — верни ровно `NO_PATTERNS`.

Не используй tools. Выдай ответ простым текстом.

## Наблюдения

{observations}
"""


def load_recent_observations(hours: int) -> list[dict]:
    if not OBSERVATIONS_FILE.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out: list[dict] = []
    with open(OBSERVATIONS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_str = entry.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts >= cutoff:
                out.append(entry)
    return out


def format_for_prompt(obs: list[dict]) -> str:
    tail = obs[-_MAX_OBS_IN_PROMPT:]
    lines: list[str] = []
    for o in tail:
        ev = o.get("event", "")
        tool = o.get("tool", "-")
        sid = (o.get("session_id") or "?")[:8]
        project = o.get("project") or "-"
        if ev == "pre":
            summary = (o.get("input_summary") or "")[:140]
            lines.append(f"[{sid}/{project}] PRE {tool}: {summary}")
        elif ev == "post":
            if not o.get("success", True):
                err = (o.get("error") or "error")[:80]
                lines.append(f"[{sid}/{project}] POST {tool}: ERR {err}")
    return "\n".join(lines)


def _parse_simple_yaml(text: str) -> dict:
    out: dict = {}
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip("'\"")
        if not key or not val:
            continue
        if key == "confidence":
            try:
                out[key] = float(val)
            except ValueError:
                out[key] = 0.3
        else:
            out[key] = val
    return out


def load_existing_catalog() -> str:
    if not INSTINCTS_DIR.exists():
        return "(каталог пуст)"
    lines: list[str] = []
    for md in sorted(INSTINCTS_DIR.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not m:
            continue
        fm = _parse_simple_yaml(m.group(1))
        iid = fm.get("id") or md.stem
        trig = (fm.get("trigger", "") or "").replace("\n", " ")
        act = (fm.get("action", "") or "").replace("\n", " ")
        lines.append(f"- id: {iid}\n  trigger: {trig}\n  action: {act}")
    return "\n".join(lines) if lines else "(каталог пуст)"


async def run_synthesis(obs: list[dict]) -> str:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        TextBlock,
        query,
    )

    prompt = _PROMPT.format(
        observations=format_for_prompt(obs),
        existing_catalog=load_existing_catalog(),
    )
    response = ""
    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(allowed_tools=[], max_turns=2),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text
    except Exception as e:
        logging.error("Synthesis SDK error: %s\n%s", e, traceback.format_exc())
    return response


def parse_yaml_blocks(text: str) -> list[dict]:
    blocks = re.findall(r"```ya?ml\s*\n(.*?)\n```", text, re.DOTALL)
    if not blocks:
        return []
    result: list[dict] = []
    for raw in blocks:
        parsed = _parse_simple_yaml(raw)
        if parsed.get("id") and parsed.get("trigger") and parsed.get("action"):
            result.append(parsed)
    return result


def _render_frontmatter(fm: dict) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            quoted = [f'"{x}"' if "," in str(x) else str(x) for x in v]
            lines.append(f"{k}: [{', '.join(quoted)}]")
        elif isinstance(v, (int, float)) and k == "confidence":
            lines.append(f"{k}: {v}")
        else:
            sval = str(v)
            if any(c in sval for c in [":", "#", "[", "]"]):
                sval = f'"{sval}"'
            lines.append(f"{k}: {sval}")
    lines.append("---")
    return "\n".join(lines)


def upsert_instinct(inst: dict, projects: list[str]) -> tuple[Path, bool]:
    INSTINCTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = slugify(inst["id"])[:60] or slugify(inst["trigger"])[:60] or "unnamed"
    path = INSTINCTS_DIR / f"{slug}.md"
    today = today_iso()
    evidence_note = inst.get("evidence", "observed in session")

    is_new = not path.exists()
    existing_fm: dict = {}
    body_tail = ""

    if not is_new:
        content = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n?", content, re.DOTALL)
        if m:
            existing_fm = _parse_simple_yaml(m.group(1))
            body_tail = content[m.end():]

    if is_new:
        fm = {
            "id": slug,
            "type": "instinct",
            "trigger": inst["trigger"],
            "action": inst["action"],
            "domain": inst.get("domain", "general"),
            "confidence": round(float(inst.get("confidence", 0.3)), 2),
            "projects": projects,
            "source": "session-observation",
            "evidence_count": 1,
            "created": today,
            "last_seen": today,
            "updated": today,
        }
        body = (
            f"# {slug.replace('-', ' ').title()}\n\n"
            f"## Action\n\n{inst['action']}\n\n"
            f"## Trigger\n\n{inst['trigger']}\n\n"
            f"## Evidence\n\n- {today}: {evidence_note}\n"
        )
        content = _render_frontmatter(fm) + "\n" + body
    else:
        prev_conf = float(existing_fm.get("confidence", 0.3))
        new_conf = min(0.9, prev_conf + 0.1)
        prev_count = int(float(existing_fm.get("evidence_count", 1)))
        fm = {
            "id": slug,
            "type": "instinct",
            "trigger": inst["trigger"],
            "action": inst["action"],
            "domain": inst.get("domain", existing_fm.get("domain", "general")),
            "confidence": round(new_conf, 2),
            "projects": projects,
            "source": existing_fm.get("source", "session-observation"),
            "evidence_count": prev_count + 1,
            "created": existing_fm.get("created", today),
            "last_seen": today,
            "updated": today,
        }
        evidence_line = f"- {today}: {evidence_note}"
        if evidence_line not in body_tail:
            body_tail = body_tail.rstrip() + f"\n{evidence_line}\n"
        content = _render_frontmatter(fm) + "\n" + body_tail

    path.write_text(content, encoding="utf-8")
    return path, is_new


def dominant_projects(obs: list[dict]) -> list[str]:
    """Instincts are behavioural patterns of the user, portable across projects."""
    return ["shared"]


def main() -> None:
    obs = load_recent_observations(INSTINCT_SYNTHESIS_WINDOW_HOURS)
    if len(obs) < INSTINCT_SYNTHESIS_MIN_OBSERVATIONS:
        logging.info(
            "Skip: %d observations (min %d) in last %dh",
            len(obs), INSTINCT_SYNTHESIS_MIN_OBSERVATIONS, INSTINCT_SYNTHESIS_WINDOW_HOURS,
        )
        return

    logging.info("Synthesizing from %d observations", len(obs))
    response = asyncio.run(run_synthesis(obs))

    if not response.strip() or "NO_PATTERNS" in response.upper():
        logging.info("No patterns detected (resp_len=%d)", len(response))
        return

    instincts = parse_yaml_blocks(response)
    if not instincts:
        logging.warning("No parsable instincts in response (resp_len=%d)", len(response))
        return

    projects = dominant_projects(obs)
    created, updated = 0, 0
    for inst in instincts:
        try:
            _, is_new = upsert_instinct(inst, projects)
            if is_new:
                created += 1
            else:
                updated += 1
        except Exception as e:
            logging.error("Upsert failed for id=%s: %s", inst.get("id"), e)

    logging.info("Instincts: %d created, %d updated", created, updated)


if __name__ == "__main__":
    main()
