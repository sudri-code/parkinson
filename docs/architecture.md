# parkinson architecture

> Conceptually inspired by Andrej Karpathy's [LLM Knowledge Base](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
> This document is the **source of truth** for the clean-room implementation of every script. When writing code, refer to this file — not to predecessor repositories.

## The compiler analogy

```
daily/          = source code    (user conversations — the raw material)
LLM             = compiler       (extracts and organises knowledge)
knowledge/      = executable     (structured, queryable base)
lint            = test suite     (consistency health checks)
queries         = runtime        (using the knowledge)
```

The user does not organise knowledge by hand. They talk to the AI assistant; the LLM takes care of synthesis, cross-referencing, and maintenance.

---

## Layers

### Layer 1: `data/daily/` — conversation logs (immutable)

Daily logs capture what happened during AI sessions. These are the "raw material" — append-only, never edited after the fact.

```
data/daily/
├── 2026-04-01.md
├── 2026-04-02.md
└── ...
```

Format:

```markdown
# Daily Log: YYYY-MM-DD

## Sessions

### Session (HH:MM) — Brief Title

**Context:** what the user was working on.

**Key Exchanges:**
- User asked X, assistant explained Y
- Decided to use Z because…
- Discovered that W fails when…

**Decisions Made:**
- Chose library X over Y because…

**Lessons Learned:**
- Always X before Y to avoid…

**Action Items:**
- [ ] Revisit X
```

The session header carries a project tag (canonical name) as a suffix — `— WorkHarmony`. This is used for tiered filtering in SessionStart and for routing concept articles.

### Layer 2: `data/knowledge/` — compiled knowledge (LLM-owned)

The LLM owns this directory fully. Humans read, rarely edit directly.

```
data/knowledge/
├── index.md            # Master catalog — one row per article
├── log.md              # Append-only chronological build log
├── concepts/           # Atomic knowledge articles
├── connections/        # Cross-cutting insights linking 2+ concepts
├── qa/                 # Filed query answers (compounding knowledge)
└── instincts/          # Behavioural patterns (trigger → action)
```

### Layer 3: `data/wiki/` — external sources (manual ingest)

Optional parallel layer for notes from external articles / READMEs / frameworks. Populated by hand through the ingest workflow. See "Layer separation" below.

### Layer 4: `docs/architecture.md` (this file)

The specification by which the LLM compiles and maintains the base — the "compiler specification".

---

## Layer separation: `knowledge/` vs `wiki/`

**Hard rule.** One fact lives in exactly one layer.

- `wiki/` — knowledge from **external sources** (`raw/`). Each page has a `sources:` field in frontmatter. Ingest is manual.
- `knowledge/` — knowledge from **your own conversations** (`daily/`). Auto-compiled via `compile.py`.
- The boundary is by **origin** (where the fact came from), not by topic. A plan born in conversation lives in `knowledge/`; an article about the same plan lives in `wiki/`.
- Overlaps go through `[[wiki-links]]`, but the page exists only in one layer.

---

## Multi-project support

`data/projects.json` — registry:

```json
{
  "<id>": {
    "id": "<id>",
    "name": "<short>",
    "canonical": "<Human Readable>",
    "aliases": ["alias1", "alias2"],
    "root": "/path/to/project",
    "remote": "git@github.com:...",
    "notes": "..."
  },
  "shared": {
    "id": "shared",
    "canonical": "Shared",
    "notes": "Cross-project or no-affiliation entries"
  }
}
```

### Detection

`detect_project(cwd)` in `utils_projects.py`:
1. `CLAUDE_PROJECT_DIR` env var — if set.
2. `git rev-parse --show-toplevel` from cwd.
3. `git remote get-url origin` — if present, `id = sha256(remote)[:12]` (portable across machines).
4. Otherwise `id = sha256(project_root)[:12]`.
5. If nothing — returns a stub with `id = "shared"`.

### Auto-registration

On first detection, `ensure_project_registered(project)` atomically adds a stub to `projects.json`:

```json
{
  "id": "...",
  "name": "...",
  "canonical": "<Capitalize(name)>",
  "aliases": ["<name.lower()>"],
  "root": "...",
  "remote": "...",
  "auto_registered": "YYYY-MM-DD",
  "notes": "Auto-registered on first detection — edit canonical/aliases/notes to customize."
}
```

Lock via `fcntl.flock` on `projects.lock`, re-read inside lock to avoid race conditions. Fast path without the lock if the entry already exists.

### Tiered SessionStart rendering

The SessionStart hook produces context in four tiers:

1. **Today + Current Project** — header.
2. **Knowledge: Current + Shared** — full `index.md` rows for articles whose `projects:` field intersects the current project's aliases or contains `shared`/`all`.
3. **Knowledge: Other Projects (titles only, read on demand)** — compact `- [[slug]] — summary (Projects)` lines for the rest.
4. **Instincts** (ALL, unfiltered — patterns are portable).
5. **Wiki Index** — always shown, topic-agnostic.
6. **Recent Daily Log** — filtered by project.

---

## Instincts pipeline

A separate memory sub-system for **behavioural** patterns (trigger → action), distinct from the conceptual knowledge in `concepts/`.

### Capture: `observations.jsonl`

PreToolUse / PostToolUse hooks write every tool event to `observations/observations.jsonl`:

```json
{"ts":"2026-04-16T09:14:25Z","ts_ms":1776330865716,"session_id":"...","project":"MyProject","event":"pre","tool":"Grep","input_summary":"path=... pattern=...","tool_call_num":16}
```

Hooks do NOT record the tool-output body (can be large) — only the `isError` flag for PostToolUse. Secrets in `input_summary` are scrubbed through `scrub_secrets`.

Rotation: when the file exceeds `PARKINSON_OBSERVATIONS_MAX_MB` (10 MB default), it is archived to `observations/archive/observations-<ts>.jsonl.gz`.

### Synthesis: `synthesize_instincts.py`

Invoked from SessionEnd (after `flush.py`). Reads the last `PARKINSON_INSTINCT_WINDOW_H` hours from `observations.jsonl`, passes them to the Claude Agent SDK (Haiku — cheap) with the prompt:

```
Analyse the user's Claude Code tool observations and extract up to 5
atomic behavioural patterns (instincts). Each is one trigger → one action.

Format — YAML block in ```yaml``` fence:
  id: short-kebab-case-id
  trigger: "when / in what condition"
  action: "what to do"
  domain: category
  confidence: 0.3
  evidence: "short justification"

CRITICAL dedup: below is the catalogue of EXISTING instincts. If a new
pattern matches an existing one (close trigger AND close action) you
MUST reuse its `id`. This increments confidence instead of creating a
duplicate.
```

### Storage: `knowledge/instincts/*.md`

Each instinct is its own file with frontmatter:

```yaml
---
id: cli-discovery-before-use
type: instinct
trigger: before using a new CLI package
action: "sequentially: npm view → --help → subcommand --help → sample run"
domain: cli-discovery
confidence: 0.9
projects: [shared, MyProject]
source: session-observation
evidence_count: 4
created: 2026-04-16
last_seen: 2026-04-16
updated: 2026-04-16
---
```

- Confidence: 0.3 on first detection, +0.1 on every repeat (max 0.9).
- Minimum observations for synthesis: `PARKINSON_INSTINCT_MIN_OBS` (20 default).
- CLI: `scripts/instincts.py list / show <id> / prune --below 0.4`.

### Cluster (merge close ones)

`cluster_instincts.py` — offline utility. Groups instincts with close `trigger` values by embedding similarity (optional) or by heuristic, proposes merge candidates. Manual confirmation required.

---

## Static files

### `knowledge/index.md`

Table of every article. The LLM reads this **first** for any query, then picks a subset to read in full.

```markdown
# Knowledge Base Index

| Article | Summary | Projects | Compiled From | Updated |
|---------|---------|----------|---------------|---------|
| [[concepts/supabase-auth]] | Row-level security patterns | shared | daily/2026-04-02.md | 2026-04-02 |
| [[concepts/rxflow-shared-nc]] | One Flow = one NC rule | Prosebya-iOS | daily/2026-04-15.md | 2026-04-15 |
```

The `Projects` column supports multi-project scope: `shared` / `all` / `<canonical>` / `<alias>`.

### `knowledge/log.md`

Append-only chronological record.

```markdown
# Build Log

## [2026-04-01T14:30:00] compile | Daily Log 2026-04-01
- Source: daily/2026-04-01.md
- Articles created: [[concepts/nextjs-project-structure]]
- Articles updated: (none)

## [2026-04-02T09:00:00] query | "How do I handle auth redirects?"
- Consulted: [[concepts/supabase-auth]]
- Filed to: [[qa/auth-redirect-handling]]
```

---

## Article formats

### Concept (`knowledge/concepts/`)

```markdown
---
title: "Concept Name"
aliases: [alt-name]
tags: [domain, topic]
projects: [shared]            # or [canonical-name], or [shared, other]
sources:
  - "daily/2026-04-01.md"
created: 2026-04-01
updated: 2026-04-03
---

# Concept Name

[2–4 sentence core explanation]

## Key Points
- [self-contained bullets]

## Details
[encyclopedic prose]

## Related Concepts
- [[concepts/related]]

## Sources
- [[daily/2026-04-01.md]]
```

### Connection (`knowledge/connections/`)

```markdown
---
title: "Connection: X and Y"
connects:
  - "concepts/concept-x"
  - "concepts/concept-y"
projects: [shared]
sources:
  - "daily/2026-04-04.md"
created: 2026-04-04
updated: 2026-04-04
---

# Connection: X and Y

## The Connection
[what links them]

## Key Insight
[the non-obvious connection]

## Evidence
[specific examples]
```

### Q&A (`knowledge/qa/`)

```markdown
---
title: "Q: question"
question: "exact text"
consulted:
  - "concepts/article-1"
filed: 2026-04-05
---

# Q: question

## Answer
[answer with [[wikilinks]]]

## Sources Consulted
- [[concepts/article-1]] — needed because…
```

### Instinct (`knowledge/instincts/`)

See the Instincts section above.

---

## Core operations

### 1. Compile (daily/ → knowledge/)

When processing a daily log:

1. Read the daily log.
2. Read `knowledge/index.md` to understand the current state.
3. Read existing articles that might need updating.
4. For each piece of knowledge found:
   - If an existing concept article covers the topic — UPDATE it (add the daily as a source).
   - Otherwise CREATE a new one in `concepts/`.
5. If the log reveals a non-obvious link between 2+ concepts — CREATE a `connections/` article.
6. UPDATE `knowledge/index.md`.
7. APPEND to `knowledge/log.md`.

Important:
- A single daily log can touch 3–10 articles.
- Prefer UPDATE over near-duplicate CREATE.
- Obsidian-style `[[wikilinks]]` with full relative paths from `knowledge/`.
- Encyclopedic style: factual, self-contained.
- Every article must have YAML frontmatter.
- Every article links back to its daily sources.
- Incremental: `scripts/state.json` stores SHA-256 hashes of daily logs.
- `permission_mode="acceptEdits"` in the Agent SDK — the LLM writes files directly.

### 2. Query (index-guided retrieval)

1. Read `knowledge/index.md`.
2. For the question, pick 3–10 relevant articles.
3. Read them in full.
4. Synthesise an answer with `[[wikilink]]` citations.
5. If `--file-back` — create a `knowledge/qa/` article + update index.md + log.md.

**Why no RAG:** at 50–500 articles, an LLM reading a structured index outperforms cosine similarity. The LLM understands *what* you are asking; embeddings merely find similar words. Add hybrid RAG around 2 000+ articles.

### 3. Lint (7 health checks)

| Check | Type | Catches |
|-------|------|---------|
| Broken links | Structural | `[[wikilinks]]` to non-existent articles |
| Orphan pages | Structural | Articles with zero inbound links |
| Orphan sources | Structural | Daily logs not yet compiled |
| Stale articles | Structural | Source log changed after compilation |
| Missing backlinks | Structural | A → B, but B ↛ A |
| Sparse articles | Structural | Under 200 words |
| Contradictions | LLM | Conflicting claims (requires judgment) |

CLI: `lint.py` (all), `lint.py --structural-only` (no API, free). Reports in `data/reports/lint-YYYY-MM-DD.md`.

---

## Hook system

Five hooks in `hooks/`, configured in `~/.claude/settings.json`:

### `session-start.py` (SessionStart)

- Pure local I/O, no API calls, <1 s.
- Reads `data/knowledge/index.md` + latest daily log + `data/knowledge/instincts/*.md` + `data/wiki/index.md`.
- Detects project, auto-registers if new.
- Tiered output (see "Multi-project support").
- Output JSON: `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`.
- Max context: 20 000 chars.

### `session-end.py` (SessionEnd)

- stdin JSON: `session_id`, `transcript_path`, `cwd`, `source`.
- Extracts conversation context (last ~30 turns, ~15 000 chars) into a temp `.md` file.
- Detects project + auto-registers, writes sidecar `.project.json` alongside the context file.
- Spawns `flush.py` as a **detached** background process (macOS: `start_new_session=True`; Windows: `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`).
- Spawns `synthesize_instincts.py` (optional, cheap on Haiku).
- Spawns `agentshield_run.py` (throttled, 6 h).
- Recursion guard: `CLAUDE_INVOKED_BY` env var → exit 0.

### `pre-compact.py` (PreCompact)

- Same architecture as `session-end.py`.
- Fires before auto-compaction.
- Guards against empty `transcript_path` (Claude Code bug #13668).
- Required for long sessions: without it, intermediate context is lost to summarisation before SessionEnd fires.

### `pre-tool-use.py` (PreToolUse)

- stdin JSON per tool call.
- Appends to `observations/observations.jsonl` with `event=pre`, `tool`, `input_summary` (first ~500 chars of args, secrets scrubbed).
- Must exit in under 2 s. No API calls.

### `post-tool-use.py` (PostToolUse)

- stdin JSON with `tool_response`.
- Appends to `observations/observations.jsonl` with `event=post`, `success`, `error` (if any, truncated to 160 chars).
- Does NOT write the response body (can be large).
- Must exit in under 5 s.

---

## Background: `flush.py`

Spawned by SessionEnd / PreCompact hooks as a detached process.

1. Sets `CLAUDE_INVOKED_BY=memory_flush` (guard against recursive hook firing).
2. Reads pre-extracted context from the temp `.md`.
3. Skips if empty or if the same `session_id` was flushed <`PARKINSON_FLUSH_COOLDOWN_SEC` ago (dedup via `scripts/last-flush.json`).
4. Loads sidecar `.project.json` for routing the article into the correct scope.
5. Calls Agent SDK `query()` with `allowed_tools=[]`, `max_turns=2`.
6. The LLM decides what is worth saving — structured bullets or `FLUSH_OK` if the context is not worth keeping.
7. Appends the result to `data/daily/YYYY-MM-DD.md` under a header `### Session/Memory Flush (HH:MM) — <Canonical>`.
8. Cleans up temp files.
9. **End-of-day auto-compile:** if local time is past 18:00 and today's daily has changed since its last compilation (SHA comparison against `state.json`) — spawns detached `compile.py`.

JSONL transcript format:

```python
entry = json.loads(line)
msg = entry.get("message", {})
role = msg.get("role", "")          # "user" | "assistant"
content = msg.get("content", "")    # str | List[Block]
```

Content blocks: `{"type": "text", "text": "..."}` dicts.

---

## State tracking

`scripts/state.json`:
- `ingested`: `{<daily-name>: {"hash": "...", "compiled_at": "...", "cost": ...}}`
- `query_count`: int
- `last_lint`: ISO timestamp
- `total_cost`: float

`scripts/last-flush.json`: `{<session_id>: <ts_epoch>}` for dedup. Gitignored.

---

## Costs (reference figures, not a contract)

| Operation | Cost |
|-----------|------|
| Compile one daily log | $0.45–0.65 |
| Query (no file-back) | ~$0.15–0.25 |
| Query (with file-back) | ~$0.25–0.40 |
| Full lint (with contradictions) | ~$0.15–0.25 |
| Structural lint only | $0.00 |
| Memory flush (per session) | ~$0.02–0.05 |
| Instinct synthesis (Haiku) | ~$0.005–0.02 |

Personal use of the Claude Agent SDK is included in Max / Team / Enterprise subscriptions — no separate API credits required.

---

## Scaling out

At ~2 000+ articles or ~2 M+ tokens the index no longer fits in the context window. At that point — add hybrid RAG (keyword + semantic) as a retrieval layer before the LLM. See Karpathy's recommendation of `qmd` by Tobi Lutke for search at scale.
