# parkinson

Personal knowledge-base compiler for Claude Code sessions.

Hooks capture your AI coding conversations, the Claude Agent SDK extracts
decisions, lessons, and patterns into a daily log, and an LLM compiler
organises those into structured, cross-referenced knowledge articles —
injected back into every future session.

**Docs in English** (this file + `docs/*.md`) and **Russian** (`README.ru.md`
+ `docs/*.ru.md`). The Russian version is the primary source; the English
version is a direct translation.

---

## About this repository

Conceptually inspired by Andrej Karpathy's
[LLM Knowledge Base](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
and Cole Medin's
[claude-memory-compiler](https://github.com/coleam00/claude-memory-compiler),
but the core scripts are a from-scratch clean-room implementation written
against the specification in `docs/architecture.md`. No source code from
upstream repositories without a published licence was consulted during
authorship. See [NOTICE](NOTICE) for the full attribution statement and
[docs/clean-room-provenance.md](docs/clean-room-provenance.md) for the
audit trail.

---

## How it works

```
Conversation → SessionEnd / PreCompact hooks → flush.py extracts knowledge
    → data/daily/YYYY-MM-DD.md → compile.py
        → data/knowledge/concepts/, connections/, qa/
            → SessionStart injects the index into the next session → loop
```

- **Hooks** capture conversations automatically (session end + pre-compact
  safety net + per-tool observations for behavioural patterns).
- **flush.py** calls the Claude Agent SDK to decide what is worth saving;
  after 18:00 local time it auto-triggers end-of-day compilation.
- **compile.py** turns daily logs into concept articles with cross-refs.
- **query.py** answers questions using the master index — no RAG.
- **lint.py** runs seven health checks (broken links, orphans,
  contradictions, staleness, and more).

---

## Features

- **Multi-project aware.** `projects.json` holds a registry of canonical
  project names + aliases. Unknown projects are auto-registered on first
  detection. SessionStart produces tiered context: `Current + Shared`
  (full rows), `Other Projects` (titles only), `Instincts` (global),
  `Wiki` (external sources).

- **Instincts pipeline.** `PreToolUse` / `PostToolUse` hooks gather tool
  observations; `synthesize_instincts.py` extracts atomic behavioural
  patterns via Haiku (trigger → action) with confidence scoring
  (0.3 → 0.9 on repeats) and in-prompt deduplication against the
  existing catalogue.

- **Two knowledge layers.** `wiki/` holds clipped external sources (manual
  ingest via Obsidian Web Clipper); `knowledge/` holds auto-compiled
  derivatives of your conversations. Hard rule: one fact lives in exactly
  one layer; cross-layer relationships go through `[[wiki-links]]`.

- **Security scan.** `agentshield_run.py` periodically sweeps the data
  root for secret leakage (adapted from everything-claude-code, MIT).

---

## Quick start

```bash
git clone git@github.com:sudri-code/parkinson.git
cd parkinson
./install.sh
# then merge examples/.claude/settings.json into your ~/.claude/settings.json
```

Full walk-through: [docs/install.md](docs/install.md).

---

## Configuration (env vars)

All variables are optional; defaults are in `.env.example`. The main one
is `PARKINSON_DATA_DIR` (default `<repo_root>/data`). Point it at an
existing vault if you already have one:

```bash
PARKINSON_DATA_DIR=~/my-knowledge-base
```

Full list: [`.env.example`](.env.example), [`scripts/config.py`](scripts/config.py).

---

## Commands

```bash
uv run python scripts/compile.py                       # compile new daily logs
uv run python scripts/compile.py --dry-run             # plan without writing
uv run python scripts/query.py "question"              # answer from the KB
uv run python scripts/query.py "question" --file-back  # + save to qa/
uv run python scripts/lint.py                          # full checks
uv run python scripts/lint.py --structural-only        # no API calls
uv run python scripts/instincts.py list                # list instincts
uv run python scripts/instincts.py show <id>           # show one
uv run python scripts/instincts.py prune               # drop stale
```

---

## Why no RAG?

Karpathy's insight: at personal-vault scale (50–500 articles) an LLM
reading a structured `index.md` outperforms vector similarity. The LLM
understands what you are *asking*; cosine similarity merely finds similar
words. RAG becomes necessary around 2 000+ articles, when the index
exceeds the context window.

---

## Trade-offs

### Pros

- **Index-guided retrieval beats RAG at personal scale.** No embedding
  pipeline, no vector database, no index rebuilds. Retrieval is fully
  auditable — you can see exactly which articles the LLM chose.
- **Filesystem-native.** Every artefact is a plain `.md` file under
  `data/`. Works out of the box with Obsidian (graph view, backlinks,
  search), grep, git, Dropbox/iCloud sync, and any text editor.
- **Hooks-driven, no daemon.** Capture and auto-compile happen in
  response to Claude Code events — no cron job, no background service
  to babysit.
- **Multi-project aware by design.** One vault holds knowledge from all
  your projects without cross-talk. SessionStart only shows rows scoped
  to the current project plus shared; other projects are visible only as
  titles.
- **Behavioural instincts layer.** Tool-usage patterns are extracted and
  scored over time — surfacing personal workflow habits that concept
  articles do not capture.
- **Local-first, privacy-respecting.** Nothing leaves your machine except
  prompts to the Claude API (same as normal Claude Code use). No
  third-party sync, no telemetry, no cloud storage.
- **Low maintenance for most users.** `install.sh` is idempotent;
  auto-registration handles new projects without manual edits;
  compilation runs itself after 18:00.
- **Clean-room attribution.** The public release is licence-safe — core
  scripts are written from scratch against the spec, MIT fragments are
  explicitly attributed.

### Cons

- **Scales only to ~2 000 articles.** Past that the master index
  exceeds the context window; you must add hybrid RAG (keyword +
  semantic) as a retrieval stage.
- **Claude Code-only.** Hooks are specific to Claude Code; Cursor,
  Codex, OpenCode etc. are not supported out of the box (would require
  per-harness adaptors).
- **Requires a Claude subscription or API credits.** The Claude Agent
  SDK is included in Max / Team / Enterprise plans; Pro users need
  `ANTHROPIC_API_KEY` with metered billing.
- **Non-trivial compile cost.** Per-day compilation runs around
  $0.45–0.65 against a growing KB; heavy users can see this compound.
  Flush (~$0.02–0.05 per session) and lint-contradictions
  (~$0.15–0.25) add on top.
- **Python 3.12 + `uv` barrier to entry.** Not a problem for developers;
  non-technical users cannot install it.
- **Terminal + Obsidian only.** No web UI, no mobile app, no team
  collaboration layer. Multi-device sync relies on git / Dropbox / iCloud
  — pick your poison.
- **English ↔ Russian split in LLM prompts.** `synthesize_instincts.py`
  uses Russian prompts by default (aligned with the author's personal
  use). Others can override, but there is no language switch yet.
- **Secret-scrubbing is best-effort.** `scrub_secrets` catches common
  `key=value` patterns, but adversarial inputs in `observations.jsonl`
  could still leak. Review before sharing the `data/` directory.
- **No built-in team mode.** `projects.json` is single-user; merging
  two users' knowledge bases requires manual conflict resolution.
- **Depends on upstream APIs.** Any breaking change in Claude Code hook
  contracts or the Agent SDK streaming API requires patching — no
  abstraction layer shields you.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — full architecture spec
- [`docs/conventions.md`](docs/conventions.md) — page conventions
- [`docs/install.md`](docs/install.md) — step-by-step install (incl. Obsidian Web Clipper)
- [`docs/hooks-reference.md`](docs/hooks-reference.md) — all five hooks and triggers
- [`docs/clean-room-provenance.md`](docs/clean-room-provenance.md) — audit trail
- [Russian version](README.ru.md) · [Russian docs](docs/) (`*.ru.md`)

---

## Licence

MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
