# Архитектура parkinson

> Концептуально вдохновлено [LLM Knowledge Base от Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
> Этот документ — **источник правды** для clean-room реализации всех скриптов. При написании кода обращайтесь к этому файлу, а не к репозиториям-предшественникам.

## Компиляторная аналогия

```
daily/          = source code    (разговоры пользователя — исходный материал)
LLM             = compiler       (извлекает и организует знание)
knowledge/      = executable     (структурированная, запрашиваемая база)
lint            = test suite     (health checks консистентности)
queries         = runtime        (использование знания)
```

Пользователь не организует знание руками. Он разговаривает с AI-ассистентом, а LLM делает синтез, cross-referencing и обслуживание.

---

## Слои

### Layer 1: `data/daily/` — Conversation Logs (immutable)

Дневные логи captcha того, что произошло в AI-сессиях. Это «сырой материал» — append-only, никогда не редактируется после факта.

```
data/daily/
├── 2026-04-01.md
├── 2026-04-02.md
└── ...
```

Формат:

```markdown
# Daily Log: YYYY-MM-DD

## Sessions

### Session (HH:MM) — Brief Title

**Context:** что делал пользователь.

**Key Exchanges:**
- Пользователь спросил X, ассистент объяснил Y
- Решили использовать Z, потому что…
- Обнаружили что W не работает когда…

**Decisions Made:**
- Выбрали библиотеку X вместо Y потому что…

**Lessons Learned:**
- Всегда X перед Y чтобы избежать…

**Action Items:**
- [ ] Вернуться к X
```

Header сессии содержит тег проекта (canonical-имя) в суффиксе — `— WorkHarmony`. Это нужно для tiered-фильтрации в SessionStart и для роутинга concept-статей.

### Layer 2: `data/knowledge/` — скомпилированное знание (LLM-owned)

LLM владеет этой директорией полностью. Человек читает, но редко редактирует напрямую.

```
data/knowledge/
├── index.md            # Master catalog — каждая статья с одно-строчной сводкой
├── log.md              # Append-only chronological build log
├── concepts/           # Атомарные знание-статьи
├── connections/        # Кросс-каттинг инсайты, связывающие 2+ концепта
├── qa/                 # Filed ответы на запросы (compounding knowledge)
└── instincts/          # Поведенческие паттерны (trigger → action)
```

### Layer 3: `data/wiki/` — внешние источники (manual ingest)

Опциональный параллельный слой для заметок из внешних статей/README/фреймворков. Заполняется вручную через ingest-workflow. См. «Разделение слоёв» ниже.

### Layer 4: `docs/architecture.ru.md` (этот файл)

Спецификация, по которой LLM компилирует и обслуживает базу. «Compiler specification».

---

## Разделение слоёв knowledge/ vs wiki/

**Жёсткое правило.** Один факт живёт ровно в одном слое.

- `wiki/` — знание из **внешних источников** (`raw/`). Каждая страница имеет `sources:` в frontmatter. Ingest — вручную.
- `knowledge/` — знание из **собственных разговоров** (`daily/`). Автокомпиляция через `compile.py`.
- Граница по **происхождению** (откуда пришёл факт), не по теме. План, родившийся в разговоре, — в `knowledge/`. Статья про тот же план — в `wiki/`.
- Пересечения — через `[[wiki-ссылки]]`, но страница существует только в одном слое.

---

## Multi-project поддержка

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
    "notes": "Кросс-проектные или без привязки"
  }
}
```

### Detection

`detect_project(cwd)` в `utils_projects.py`:
1. `CLAUDE_PROJECT_DIR` env var — если задана.
2. `git rev-parse --show-toplevel` от cwd.
3. `git remote get-url origin` — если есть, `id = sha256(remote)[:12]` (portable между машинами).
4. Иначе `id = sha256(project_root)[:12]`.
5. Если ничего — возвращает stub с `id = "shared"`.

### Auto-registration

При первом detect — `ensure_project_registered(project)` атомарно добавляет stub в `projects.json`:

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

Lock через `fcntl.flock` на `projects.lock`, re-read внутри lock для защиты от race condition. Fast-path без lock, если запись уже есть.

### Tiered SessionStart rendering

SessionStart хук выдаёт контекст в четырёх ярусах:

1. **Today + Current Project** — заголовок.
2. **Knowledge: Current + Shared** — полные строки `index.md` для статей, у которых `projects:` пересекается с aliases текущего проекта или содержит `shared`/`all`.
3. **Knowledge: Other Projects (заголовки, читай по запросу)** — компактные `- [[slug]] — summary (Projects)` для остальных.
4. **Instincts** (ALL, без фильтра — паттерны портируемы).
5. **Wiki Index** — всегда, topic-agnostic.
6. **Recent Daily Log** — отфильтрованный по проекту.

---

## Instincts pipeline

Отдельная под-система памяти для **поведенческих** паттернов (trigger → action), в отличие от концептуального знания в `concepts/`.

### Capture: observations.jsonl

PreToolUse/PostToolUse хуки пишут каждое tool-событие в `observations/observations.jsonl`:

```json
{"ts":"2026-04-16T09:14:25Z","ts_ms":1776330865716,"session_id":"...","project":"MyProject","event":"pre","tool":"Grep","input_summary":"path=... pattern=...","tool_call_num":16}
```

Хуки НЕ записывают тело tool-output (может быть большим) — только `isError` флаг для PostToolUse. Секреты в input_summary автоматически scrub-аются через `scrub_secrets`.

Ротация: при превышении `PARKINSON_OBSERVATIONS_MAX_MB` (10 МБ default) — архивация в `observations/archive/observations-<ts>.jsonl.gz`.

### Synthesize: `synthesize_instincts.py`

Вызывается из SessionEnd (после `flush.py`). Читает последние `PARKINSON_INSTINCT_WINDOW_H` часов из `observations.jsonl`, передаёт в Claude Agent SDK (Haiku — дёшево) с промптом:

```
Проанализируй наблюдения работы пользователя с Claude Code и выдели до 5
атомарных поведенческих паттернов (instincts). Каждый — один trigger → одно action.

Формат — YAML-блок в ```yaml``` fence:
  id: short-kebab-case-id
  trigger: "когда/в каких условиях"
  action: "что делать"
  domain: category
  confidence: 0.3
  evidence: "краткое обоснование"

КРИТИЧЕСКИЙ дедуп: ниже каталог УЖЕ существующих инстинктов. Если новый
паттерн совпадает (близкий trigger И близкий action) — ОБЯЗАТЕЛЬНО
переиспользуй его `id`. Это инкрементирует confidence вместо дубля.
```

### Storage: `knowledge/instincts/*.md`

Каждый instinct — отдельный файл с frontmatter:

```yaml
---
id: cli-discovery-before-use
type: instinct
trigger: перед использованием нового CLI-пакета
action: "последовательно: npm view → --help → subcommand --help → sample run"
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

- Confidence: 0.3 при первом обнаружении, +0.1 при каждом повторе (max 0.9).
- Min observations для synthesis: `PARKINSON_INSTINCT_MIN_OBS` (20 default).
- CLI: `scripts/instincts.py list / show <id> / prune --below 0.4`.

### Cluster (merge близких)

`cluster_instincts.py` — offline-утилита. Группирует instincts с близкими `trigger` по embedding-similarity (опционально) или по heuristic, предлагает merge-кандидатов. Ручное подтверждение.

---

## Статические файлы

### `knowledge/index.md`

Таблица всех статей. LLM читает её **первой** при любом query, затем выбирает нужные статьи для полного чтения.

```markdown
# Knowledge Base Index

| Article | Summary | Projects | Compiled From | Updated |
|---------|---------|----------|---------------|---------|
| [[concepts/supabase-auth]] | Row-level security patterns | shared | daily/2026-04-02.md | 2026-04-02 |
| [[concepts/rxflow-shared-nc]] | One Flow = one NC rule | Prosebya-iOS | daily/2026-04-15.md | 2026-04-15 |
```

Колонка `Projects` — поддержка multi-project scope. `shared` / `all` / `<canonical>` / `<alias>`.

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

## Article Formats

### Concept (`knowledge/concepts/`)

```markdown
---
title: "Concept Name"
aliases: [alt-name]
tags: [domain, topic]
projects: [shared]            # или [canonical-name], или [shared, other]
sources:
  - "daily/2026-04-01.md"
created: 2026-04-01
updated: 2026-04-03
---

# Concept Name

[2-4 предложения ядра]

## Key Points
- [самодостаточные буллеты]

## Details
[энциклопедический текст]

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
[что связывает]

## Key Insight
[не-очевидная связь]

## Evidence
[специфичные примеры]
```

### Q&A (`knowledge/qa/`)

```markdown
---
title: "Q: вопрос"
question: "точный текст"
consulted:
  - "concepts/article-1"
filed: 2026-04-05
---

# Q: вопрос

## Answer
[ответ с [[wikilinks]]]

## Sources Consulted
- [[concepts/article-1]] — был нужен потому что…
```

### Instinct (`knowledge/instincts/`)

См. раздел Instincts выше.

---

## Core Operations

### 1. Compile (daily/ → knowledge/)

Когда обрабатывается дневной лог:

1. Прочитать daily-log.
2. Прочитать `knowledge/index.md` для понимания текущего состояния.
3. Прочитать существующие статьи, которые могут нуждаться в обновлении.
4. Для каждого найденного знания:
   - Если существующая concept-статья покрывает тему — UPDATE, добавить daily как источник.
   - Иначе CREATE новую в `concepts/`.
5. Если лог выявил не-очевидную связь между 2+ концептами — CREATE `connections/`.
6. UPDATE `knowledge/index.md`.
7. APPEND в `knowledge/log.md`.

Важно:
- Один daily-log может затронуть 3-10 статей.
- Предпочитать UPDATE над near-duplicate CREATE.
- Obsidian-style `[[wikilinks]]` с полными relative-путями от `knowledge/`.
- Энциклопедический стиль, factual, self-contained.
- Каждая статья — YAML frontmatter обязательно.
- Каждая статья линкует обратно на свои daily-источники.
- Инкрементально: `scripts/state.json` хранит SHA-256 hashes daily-логов.
- `permission_mode="acceptEdits"` в Agent SDK — LLM пишет файлы напрямую.

### 2. Query (индекс-guided retrieval)

1. Прочитать `knowledge/index.md`.
2. По вопросу выбрать 3-10 релевантных статей.
3. Прочитать в полном объёме.
4. Синтезировать ответ с `[[wikilink]]` цитатами.
5. Если `--file-back` — создать `knowledge/qa/` статью + update index.md + log.md.

**Почему без RAG:** на масштабе 50-500 статей LLM, читающий структурированный индекс, выигрывает у cosine similarity. LLM понимает *что* ты спрашиваешь; embeddings ищут similar words. При ~2000+ статей добавить hybrid RAG.

### 3. Lint (7 health checks)

| Check | Type | Catches |
|-------|------|---------|
| Broken links | Structural | `[[wikilinks]]` на несуществующие статьи |
| Orphan pages | Structural | Статьи с нулём inbound-линков |
| Orphan sources | Structural | Daily-логи, которые ещё не компилировались |
| Stale articles | Structural | Source-log изменился после compile |
| Missing backlinks | Structural | A → B, но B не → A |
| Sparse articles | Structural | Меньше 200 слов |
| Contradictions | LLM | Конфликтующие утверждения (требует judgment) |

CLI: `lint.py` (все), `lint.py --structural-only` (без API, free). Reports в `data/reports/lint-YYYY-MM-DD.md`.

---

## Hook System

Пять хуков в `hooks/`, конфигурятся в `~/.claude/settings.json`:

### `session-start.py` (SessionStart)

- Pure local I/O, no API calls, <1s.
- Reads `data/knowledge/index.md` + последний daily-log + `data/knowledge/instincts/*.md` + `data/wiki/index.md`.
- Детектит проект, auto-registers если новый.
- Tiered output (см. «Multi-project»).
- Output JSON: `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`.
- Max context: 20 000 chars.

### `session-end.py` (SessionEnd)

- stdin JSON: `session_id`, `transcript_path`, `cwd`, `source`.
- Extract conversation context (last ~30 turns, ~15 000 chars) в temp `.md` файл.
- Detect project + auto-register, пишет sidecar `.project.json` рядом с context-файлом.
- Spawn `flush.py` как **detached** background (macOS: `start_new_session=True`; Windows: `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`).
- Spawn `synthesize_instincts.py` (опционально, дешевле с Haiku).
- Spawn `agentshield_run.py` (throttled 6h).
- Recursion guard: `CLAUDE_INVOKED_BY` env var → exit 0.

### `pre-compact.py` (PreCompact)

- Та же архитектура, что session-end.
- Срабатывает перед auto-compact.
- Guard против empty `transcript_path` (Claude Code bug #13668).
- Нужен для длинных сессий: без неё intermediate-контекст теряется в summarization до SessionEnd.

### `pre-tool-use.py` (PreToolUse)

- stdin JSON per tool call.
- Append в `observations/observations.jsonl` с `event=pre`, `tool`, `input_summary` (первые ~500 chars аргументов, secrets scrubbed).
- Exit <2s. Не вызывает API.

### `post-tool-use.py` (PostToolUse)

- stdin JSON с `tool_response`.
- Append в `observations/observations.jsonl` с `event=post`, `success`, `error` (если есть, truncated to 160 chars).
- Не пишет тело ответа (может быть большим).
- Exit <5s.

---

## Background: flush.py

Спавнится хуками SessionEnd/PreCompact как detached процесс.

1. Set `CLAUDE_INVOKED_BY=memory_flush` (guard против recursive hook).
2. Читает pre-extracted context из temp `.md`.
3. Skip если пусто или если та же session_id flash-ился <`PARKINSON_FLUSH_COOLDOWN_SEC` назад (dedup через `scripts/last-flush.json`).
4. Загружает sidecar `.project.json` для routing статьи в правильный scope.
5. Calls Agent SDK `query()` с `allowed_tools=[]`, `max_turns=2`.
6. LLM решает, что worth saving — структурированные bullets или `FLUSH_OK` (если контекст не представляет ценности).
7. Appends result в `data/daily/YYYY-MM-DD.md` под header `### Session/Memory Flush (HH:MM) — <Canonical>`.
8. Cleanup temp files.
9. **End-of-day auto-compile:** если сейчас после 18:00 local time и сегодняшний daily изменился с последней компиляции (SHA comparison против `state.json`) — spawn detached `compile.py`.

JSONL transcript format:

```python
entry = json.loads(line)
msg = entry.get("message", {})
role = msg.get("role", "")          # "user" | "assistant"
content = msg.get("content", "")    # str | List[Block]
```

Content блоки: `{"type": "text", "text": "..."}` словари.

---

## State tracking

`scripts/state.json`:
- `ingested`: `{<daily-name>: {"hash": "...", "compiled_at": "...", "cost": ...}}`
- `query_count`: int
- `last_lint`: ISO timestamp
- `total_cost`: float

`scripts/last-flush.json`: `{<session_id>: <ts_epoch>}` для dedup. Gitignored.

---

## Costs (рефенсные, не договор)

| Operation | Cost |
|-----------|------|
| Compile one daily log | $0.45-0.65 |
| Query (no file-back) | ~$0.15-0.25 |
| Query (with file-back) | ~$0.25-0.40 |
| Full lint (contradictions) | ~$0.15-0.25 |
| Structural lint only | $0.00 |
| Memory flush (per session) | ~$0.02-0.05 |
| Instinct synthesis (Haiku) | ~$0.005-0.02 |

Персональное использование Claude Agent SDK входит в подписку Max/Team/Enterprise — дополнительных API-credits не требуется.

---

## Scaling out

При ~2000+ статей или ~2M+ tokens индекс перестаёт влезать в контекст. Тогда — hybrid RAG (keyword + semantic) как retrieval layer перед LLM. См. рекомендацию Карпати `qmd` от Tobi Lutke для search at scale.
