"""CLI for managing the instinct store (data/knowledge/instincts/).

Commands:
  list [--project X] [--min-confidence 0.5] [--domain Y]
  show <id>
  prune [--apply]   (dry-run by default; drops confidence<0.3 or last_seen>30d)
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from config import INSTINCTS_DIR  # noqa: E402


def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    out: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip("'\"")
        if val.startswith("[") and val.endswith("]"):
            out[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        else:
            out[key] = val
    return out


def _load_all() -> list[tuple[Path, dict]]:
    if not INSTINCTS_DIR.exists():
        return []
    result: list[tuple[Path, dict]] = []
    for md in sorted(INSTINCTS_DIR.glob("*.md")):
        fm = _parse_frontmatter(md.read_text(encoding="utf-8"))
        if fm:
            result.append((md, fm))
    return result


def cmd_list(args) -> int:
    rows = _load_all()
    if not rows:
        print("(no instincts)")
        return 0

    filtered: list[tuple[Path, dict]] = []
    for path, fm in rows:
        if args.project:
            projects_lower = {p.lower() for p in fm.get("projects", [])}
            if args.project.lower() not in projects_lower and "shared" not in projects_lower:
                continue
        if args.domain and fm.get("domain", "").lower() != args.domain.lower():
            continue
        try:
            conf = float(fm.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0
        if conf < args.min_confidence:
            continue
        filtered.append((path, fm))

    if not filtered:
        print("(no matches)")
        return 0

    print(f"{'ID':<35} {'Conf':<5} {'Count':<5} {'Domain':<18} {'Last Seen':<12} Projects")
    print("-" * 110)
    for path, fm in sorted(filtered, key=lambda r: -float(r[1].get("confidence", 0))):
        pid = fm.get("id", path.stem)[:34]
        conf = fm.get("confidence", "?")
        count = fm.get("evidence_count", "?")
        domain = (fm.get("domain", "-") or "-")[:17]
        last = fm.get("last_seen", "-")
        projects = ",".join(fm.get("projects", []) or [])[:40]
        print(f"{pid:<35} {str(conf):<5} {str(count):<5} {domain:<18} {last:<12} {projects}")
    return 0


def cmd_show(args) -> int:
    slug = args.id
    path = INSTINCTS_DIR / f"{slug}.md"
    if not path.exists():
        matches = list(INSTINCTS_DIR.glob(f"{slug}*.md"))
        if not matches:
            print(f"Not found: {slug}", file=sys.stderr)
            return 1
        path = matches[0]
    print(path.read_text(encoding="utf-8"))
    return 0


_STALE_DAYS = 30


def cmd_prune(args) -> int:
    today = datetime.now(timezone.utc).astimezone()
    cutoff = today - timedelta(days=_STALE_DAYS)

    to_remove: list[tuple[Path, str]] = []
    for path, fm in _load_all():
        try:
            conf = float(fm.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0
        last = fm.get("last_seen", "")
        reason = None
        if conf < 0.3:
            reason = f"confidence={conf:.2f}<0.3"
        else:
            try:
                last_dt = datetime.fromisoformat(last).replace(tzinfo=timezone.utc)
                if last_dt < cutoff:
                    reason = f"last_seen={last} >{_STALE_DAYS}d ago"
            except ValueError:
                pass
        if reason:
            to_remove.append((path, reason))

    if not to_remove:
        print("(nothing to prune)")
        return 0

    print(f"{'[APPLY]' if args.apply else '[DRY-RUN]'} {len(to_remove)} instincts to prune:")
    for path, reason in to_remove:
        print(f"  {path.name}  — {reason}")
        if args.apply:
            path.unlink()

    if not args.apply:
        print("\nRe-run with --apply to actually delete.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="instincts")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list instincts")
    p_list.add_argument("--project")
    p_list.add_argument("--domain")
    p_list.add_argument("--min-confidence", type=float, default=0.0)
    p_list.set_defaults(fn=cmd_list)

    p_show = sub.add_parser("show", help="show one instinct")
    p_show.add_argument("id")
    p_show.set_defaults(fn=cmd_show)

    p_prune = sub.add_parser("prune", help="remove low-confidence/stale (dry-run)")
    p_prune.add_argument("--apply", action="store_true")
    p_prune.set_defaults(fn=cmd_prune)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
