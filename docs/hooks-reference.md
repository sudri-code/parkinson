# Hooks reference

parkinson uses **five hooks** registered in `~/.claude/settings.json`.

## Overview

| Hook | Trigger | Calls API | Timeout |
|------|---------|-----------|---------|
| `SessionStart` | start of every session | no | 15 s |
| `PreCompact` | before auto-compaction | no (spawns in background) | 10 s |
| `SessionEnd` | end of a session | no (spawns in background) | 10 s |
| `PreToolUse` | before every tool call | no | 2 s |
| `PostToolUse` | after every tool call | no | 5 s |

All hooks do pure local I/O in their synchronous body — heavy work (LLM calls) is delegated to background processes (`flush.py`, `synthesize_instincts.py`, `agentshield_run.py`).

## `session-start.py`

**When:** Claude Code begins a session (new or resumed).

**Input (stdin JSON):** `{session_id, cwd, source}`.

**What it does:**
1. Detects the current project (`utils_projects.detect_project`).
2. Auto-registers the project if new (`ensure_project_registered`).
3. Reads `data/knowledge/index.md`, classifies rows by scope (`current` / `shared` / `other`).
4. Reads `data/knowledge/instincts/*.md` (all, unfiltered).
5. Reads `data/wiki/index.md` (if present).
6. Reads the latest `data/daily/YYYY-MM-DD.md`, filters sections by project.
7. Assembles tiered context (up to 20 000 chars).

**Output (stdout JSON):**

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "## Today\n...\n## Current Project\n...\n## Knowledge: Current + Shared\n...\n"
  }
}
```

## `session-end.py`

**When:** a session closes or the user exits.

**Input:** `{session_id, transcript_path, cwd, source}`.

**What it does:**
1. Parses the JSONL transcript, extracts the last ~30 turns as markdown (~15 000 chars).
2. Writes the context to `scripts/session-flush-<session_id>-<ts>.md`.
3. Detects the project, writes sidecar `session-flush-<session_id>-<ts>.project.json`.
4. Spawns detached processes:
   - `flush.py <context_file> <session_id>` — the LLM extracts knowledge into the daily log.
   - `synthesize_instincts.py` — Haiku extracts patterns.
   - `agentshield_run.py` — security scan (throttled 6 h).

All spawns are fully detached (they survive the hook's exit).

**Recursion guard:** if the `CLAUDE_INVOKED_BY` env var is set, the hook exits 0 immediately (protects against the `flush.py → Agent SDK → Claude Code → SessionEnd → flush.py` loop).

## `pre-compact.py`

**When:** Claude Code is about to auto-compact the context (when the window fills up).

**Input:** `{session_id, transcript_path, cwd}`.

**What it does:** same as `session-end.py` — but important: guards against an empty `transcript_path` (known Claude Code bug #13668). Runs with `MIN_TURNS_TO_FLUSH=5` (higher than SessionEnd=1) because pre-compact can fire more often.

**Why we need it:** a long session can auto-compact several times before closing. Without `pre-compact.py`, intermediate context is lost to summarisation before SessionEnd ever fires.

## `pre-tool-use.py`

**When:** before every tool call (Read, Edit, Bash, …).

**Input:** `{session_id, tool_name, tool_input, cwd, tool_call_num}`.

**What it does:**
1. Detects the project (cheap, light caching).
2. Appends to `observations/observations.jsonl`:

```json
{
  "ts": "2026-04-16T09:14:25Z",
  "ts_ms": 1776330865716,
  "session_id": "...",
  "project": "MyProject",
  "event": "pre",
  "tool": "Grep",
  "input_summary": "path=... pattern=...",
  "tool_call_num": 16
}
```

`input_summary` — first ~500 chars of the tool args, secrets scrubbed via `scrub_secrets`.

**Timeout:** 2 s (must stay fast — tool calls are blocked until it returns).

## `post-tool-use.py`

**When:** after every tool call.

**Input:** `{session_id, tool_name, tool_response, cwd, tool_call_num}`.

**What it does:** appends to `observations.jsonl` with `event=post`, classifies success/failure:

```json
{
  "ts": "...",
  "event": "post",
  "success": true | false,
  "error": "<truncated to 160 chars>" | null,
  ...
}
```

**Does NOT write the response body** — it can be very big. Only the success flag is needed.

**Timeout:** 5 s.

## Config in `settings.json`

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "uv run --directory /path/to/parkinson python /path/to/parkinson/hooks/session-start.py",
        "timeout": 15
      }]
    }],
    "PreCompact": [...],
    "SessionEnd": [...],
    "PreToolUse": [...],
    "PostToolUse": [...]
  }
}
```

An empty `matcher` catches all events. For selective matchers see [Claude Code docs](https://docs.claude.com/en/docs/claude-code/hooks).

## Debug / disable

- Logs: `scripts/flush.log` (all hooks log there via `logging`).
- To disable a specific hook — remove its block from `settings.json`.
- To temporarily disable observations — `PARKINSON_DISABLE_OBSERVATIONS=1` env (check `pre-tool-use.py` for the guard).

## Recursion protection

All background scripts (`flush.py`, `compile.py`, `synthesize_instincts.py`) set `CLAUDE_INVOKED_BY=<name>` before calling the Claude Agent SDK. Every hook checks this env var in the first line of its main. Without this you get an infinite hook loop.
