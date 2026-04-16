"""Run AgentShield security scan on ~/.claude, persist report, append
critical alerts to today's daily log.

Throttled to AGENTSHIELD_THROTTLE_HOURS (default 6h) to avoid burning
time on every session close. Called from session-end.py as a detached
process (fire-and-forget).

Installation: npx downloads `ecc-agentshield` on first use (~1 MB).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

os.environ["CLAUDE_INVOKED_BY"] = "agentshield_run"

SCRIPTS_DIR = Path(__file__).resolve().parent
INSTALL_DIR = SCRIPTS_DIR.parent
LOG_FILE = SCRIPTS_DIR / "flush.log"

sys.path.insert(0, str(SCRIPTS_DIR))

from config import (  # noqa: E402
    AGENTSHIELD_REPORTS_DIR,
    AGENTSHIELD_STATE_FILE,
    AGENTSHIELD_THROTTLE_HOURS,
    AGENTSHIELD_TIMEOUT_SEC,
    DAILY_DIR,
)
from utils_projects import write_atomic_json  # noqa: E402

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [agentshield] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

TARGET_PATH = str(Path.home() / ".claude")


def _within_throttle() -> bool:
    if not AGENTSHIELD_STATE_FILE.exists():
        return False
    try:
        state = json.loads(AGENTSHIELD_STATE_FILE.read_text(encoding="utf-8"))
        last = float(state.get("timestamp", 0))
    except (json.JSONDecodeError, OSError, ValueError):
        return False
    return (time.time() - last) < AGENTSHIELD_THROTTLE_HOURS * 3600


def _run_scan() -> dict | None:
    cmd = [
        "npx", "-y", "-p", "ecc-agentshield", "agentshield", "scan",
        "--path", TARGET_PATH,
        "--format", "json",
        "--min-severity", "medium",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=AGENTSHIELD_TIMEOUT_SEC,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logging.error("npx launch failed: %s", e)
        return None
    if result.returncode != 0 and not result.stdout.strip():
        logging.error("scan rc=%d stderr=%s", result.returncode, result.stderr[:300])
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logging.error("scan output not JSON: %s (first 200: %s)", e, result.stdout[:200])
        return None


def _severity_counts(report: dict) -> Counter:
    counts: Counter = Counter()
    for f in report.get("findings", []):
        sev = f.get("severity", "unknown")
        counts[sev] += 1
    return counts


def _append_critical_to_daily(findings: list[dict]) -> None:
    if not findings:
        return
    today = datetime.now(timezone.utc).astimezone()
    log_path = DAILY_DIR / f"{today.strftime('%Y-%m-%d')}.md"
    if not log_path.exists():
        DAILY_DIR.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"# Daily Log: {today.strftime('%Y-%m-%d')}\n\n## Sessions\n\n## Memory Maintenance\n\n",
            encoding="utf-8",
        )
    time_str = today.strftime("%H:%M")
    lines = [f"### AgentShield Alert ({time_str})", ""]
    for f in findings[:10]:
        file_loc = f.get("file", "?")
        line = f.get("line")
        loc = f"{file_loc}:{line}" if line else file_loc
        lines.append(f"- **{f.get('title', 'untitled')}** ({f.get('category', '-')}) — {loc}")
    if len(findings) > 10:
        lines.append(f"- … and {len(findings) - 10} more critical findings")
    lines.append("")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    if _within_throttle():
        logging.info("Throttle: <%dh since last scan", AGENTSHIELD_THROTTLE_HOURS)
        return

    logging.info("Running scan on %s", TARGET_PATH)
    t_start = time.time()
    report = _run_scan()
    duration = time.time() - t_start

    if report is None:
        logging.error("Scan failed after %.1fs", duration)
        return

    findings = report.get("findings", [])
    counts = _severity_counts(report)
    summary = (
        f"AgentShield: {counts.get('critical', 0)} critical, "
        f"{counts.get('high', 0)} high, {counts.get('medium', 0)} medium "
        f"(total={len(findings)}, {duration:.1f}s)"
    )
    logging.info(summary)

    AGENTSHIELD_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts_slug = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    report_path = AGENTSHIELD_REPORTS_DIR / f"agentshield-{ts_slug}.json"
    try:
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logging.error("Failed to write report: %s", e)

    criticals = [f for f in findings if f.get("severity") == "critical"]
    if criticals:
        try:
            _append_critical_to_daily(criticals)
        except Exception as e:
            logging.error("Failed to append critical to daily: %s", e)

    try:
        write_atomic_json(AGENTSHIELD_STATE_FILE, {
            "timestamp": time.time(),
            "duration_sec": round(duration, 2),
            "severity_counts": dict(counts),
            "total_findings": len(findings),
            "report_path": str(report_path),
        })
    except Exception as e:
        logging.error("Failed to update state: %s", e)


if __name__ == "__main__":
    main()
