# Hooks reference

parkinson использует **5 хуков** Claude Code, регистрирующихся в `~/.claude/settings.json`.

## Обзор

| Hook | Триггер | Вызывает API | Таймаут |
|------|---------|--------------|---------|
| `SessionStart` | начало каждой сессии | нет | 15s |
| `PreCompact` | перед auto-compact контекста | нет (спавн в фоне) | 10s |
| `SessionEnd` | окончание сессии | нет (спавн в фоне) | 10s |
| `PreToolUse` | перед каждым вызовом tool | нет | 2s |
| `PostToolUse` | после каждого вызова tool | нет | 5s |

Все хуки pure local I/O в синхронной части — тяжёлые операции (LLM-вызовы) делегируются фоновым процессам (`flush.py`, `synthesize_instincts.py`, `agentshield_run.py`).

## `session-start.py`

**Когда:** Claude Code начинает сессию (новую или возобновлённую).

**Вход (stdin JSON):** `{session_id, cwd, source}`.

**Что делает:**
1. Детектит текущий проект (`utils_projects.detect_project`).
2. Auto-registers если проект новый (`ensure_project_registered`).
3. Читает `data/knowledge/index.md`, классифицирует строки по scope (`current` / `shared` / `other`).
4. Читает `data/knowledge/instincts/*.md` (все, без фильтра).
5. Читает `data/wiki/index.md` (если существует).
6. Читает последний `data/daily/YYYY-MM-DD.md`, фильтрует секции по проекту.
7. Собирает tiered-контекст (макс 20 000 chars).

**Выход (stdout JSON):**

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "## Today\n...\n## Current Project\n...\n## Knowledge: Current + Shared\n...\n"
  }
}
```

## `session-end.py`

**Когда:** сессия закрывается или пользователь выходит.

**Вход:** `{session_id, transcript_path, cwd, source}`.

**Что делает:**
1. Парсит JSONL-транскрипт, извлекает последние ~30 ходов как markdown (~15 000 chars).
2. Пишет контекст в `scripts/session-flush-<session_id>-<ts>.md`.
3. Детектит проект, пишет sidecar `session-flush-<session_id>-<ts>.project.json`.
4. Спавнит детач-процессы:
   - `flush.py <context_file> <session_id>` — LLM извлекает знание в daily.
   - `synthesize_instincts.py` — Haiku извлекает паттерны.
   - `agentshield_run.py` — security scan (throttled 6h).

Все спавны — полностью отсоединённые (переживают exit хука).

**Recursion guard:** если `CLAUDE_INVOKED_BY` env var установлена — хук exit 0 мгновенно (защита от `flush.py → Agent SDK → Claude Code → SessionEnd → flush.py` петли).

## `pre-compact.py`

**Когда:** Claude Code собирается auto-compact'нуть контекст (при переполнении window).

**Вход:** `{session_id, transcript_path, cwd}`.

**Что делает:** то же, что `session-end.py` — но важно: guard против пустого `transcript_path` (known Claude Code bug #13668). Запускается с `MIN_TURNS_TO_FLUSH=5` (выше чем у SessionEnd=1), потому что pre-compact может срабатывать чаще.

**Зачем нужно:** в длинной сессии может быть несколько auto-compact до закрытия. Без `pre-compact.py` intermediate-контекст теряется в summarization, не доходя до SessionEnd.

## `pre-tool-use.py`

**Когда:** перед каждым вызовом tool (Read, Edit, Bash, …).

**Вход:** `{session_id, tool_name, tool_input, cwd, tool_call_num}`.

**Что делает:**
1. Детектит проект (cheap, лёгкое кэширование).
2. Append в `observations/observations.jsonl`:

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

`input_summary` — первые ~500 chars аргументов tool, secrets scrubbed через `scrub_secrets`.

**Таймаут:** 2s (должен быть быстрым, чтобы не блокировать вызовы).

## `post-tool-use.py`

**Когда:** после каждого вызова tool.

**Вход:** `{session_id, tool_name, tool_response, cwd, tool_call_num}`.

**Что делает:** append в `observations.jsonl` с `event=post`, классифицирует успех/ошибку:

```json
{
  "ts": "...",
  "event": "post",
  "success": true | false,
  "error": "<truncated to 160 chars>" | null,
  ...
}
```

**Не пишет тело tool-response** — оно может быть очень большим. Нужен только флаг успеха.

**Таймаут:** 5s.

## Конфигурация в settings.json

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

Пустой `matcher` — ловит все события. Для selective matcher см. [Claude Code docs](https://docs.claude.com/en/docs/claude-code/hooks).

## Debug / отключение

- Логи: `scripts/flush.log` (все хуки пишут туда через `logging`).
- Отключить конкретный хук — удалить его блок из `settings.json`.
- Временно disable всех observations — `PARKINSON_DISABLE_OBSERVATIONS=1` env (проверьте `pre-tool-use.py` на наличие guard).

## Recursion protection

Все фоновые скрипты (`flush.py`, `compile.py`, `synthesize_instincts.py`) ставят `CLAUDE_INVOKED_BY=<name>` перед вызовом Claude Agent SDK. Все хуки проверяют эту env var в первой строке main-а. Без этого получим бесконечный хук-loop.
