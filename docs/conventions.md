# Content conventions

Content language: whatever suits your personal vault. Technical terms and product names are kept in their original form (e.g. "dependency injection", "goroutine", "React").

## Vault layout

```
data/
├── daily/        — conversation auto-compiler (Claude Code hooks → flush.py). Immutable.
├── knowledge/    — pages compiled from daily/ (compile.py). Do not edit by hand.
│   ├── index.md       catalogue of all knowledge pages
│   ├── log.md         append-only build log
│   ├── concepts/      atomic concepts
│   ├── connections/   links between 2+ concepts
│   ├── qa/            filed query answers
│   └── instincts/     behavioural patterns (trigger → action)
├── wiki/         — pages from external sources (manual ingest). Optional.
├── raw/          — source materials (articles, notes, images). Immutable.
├── reports/      — lint reports, agentshield scans. Gitignored.
└── projects.json — project registry (canonical + aliases)
```

## Layer separation

One of the two core rules of the system.

- `wiki/` — external sources (`raw/`). Every page has a `sources:` field in frontmatter. Ingest is manual.
- `knowledge/` — your own conversations (`daily/`). Auto-compilation via `compile.py`; do not edit by hand.
- **One fact — one layer.** Overlaps go through `[[wiki-links]]`, but the page lives in exactly one place.
- The boundary is by origin, not by topic.

## Frontmatter for wiki pages

```yaml
---
title: Page title
type: concept | entity | source | comparison | analysis
tags: [tag1, tag2]
sources: [source-file-name.md]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

### Wiki page types

- **source** — summary of one source: key ideas, quotes, assessment.
- **concept** — technology / concept page (e.g. "Event Sourcing", "SOLID"): definition, applications, links.
- **entity** — entity page: tool, library, language, company, person.
- **comparison** — comparison of two or more entities / approaches.
- **analysis** — author's synthesis of multiple sources.

## Links

- Obsidian-style: `[[file-name]]` or `[[file-name|display text]]`.
- Wiki pages without a path (Obsidian resolves by name).
- Raw files with a full path: `[[raw/article.md]]`.
- Knowledge articles with a relative path from `knowledge/`: `[[concepts/supabase-auth]]`.
- **No literal placeholders.** Syntax examples like `foo`, `slug`, or `file-name` inside double-brackets break lint (`broken_link`). Describe the syntax in prose or inside backticks without the `[[…]]` wrapper.
- **Bidirectional `## Related Concepts`.** If article A links to B, article B must link back to A (lint: `missing_backlink`). Exception — a hub concept with 4+ peripheral inbound links: remove the weak forward link in the source instead of adding a weak reciprocal.
- **Body ≥200 words** for concepts and connections (lint: `sparse_article`). If content is shorter, UPDATE an existing article rather than CREATE a new one.

## Images

`![[raw/assets/filename.png]]`. When ingesting a source that contains images, mention them and inspect them separately if needed.

## Workflow

### Ingest (external source)

1. Read the source from `raw/`.
2. Discuss key points.
3. Create a `source`-type page in `wiki/`.
4. Update / create related `concept` / `entity` pages.
5. Update `wiki/index.md`.
6. Add an entry to `wiki/log.md`.

### Query

1. Read `knowledge/index.md` (master).
2. Read the selected pages.
3. Synthesise an answer with `[[links]]`.
4. If the answer is valuable — offer to save as `qa/`, `analysis`, or `comparison`.

### Lint

Check for:
- Contradictions between pages.
- Stale claims.
- Orphan pages (no incoming links).
- Mentioned but not created concepts.
- Gaps in data.

## Rules

- Never modify files in `raw/`.
- wiki → only from external sources. knowledge → only from conversations. Do not duplicate.
- `index.md` and `log.md` — in `knowledge/` (auto) and optionally in `wiki/` (manual).
- When updating a page, update `updated` in frontmatter.
- `log.md` is append-only, format: `## [YYYY-MM-DD] type | description`.
- Wiki file names in Latin, kebab-case (`event-sourcing.md`, `golang.md`).
