# Clean-room provenance

Этот файл — audit-trail для заявления «core scripts were written from scratch against the specification in docs/architecture.ru.md without consulting upstream source code from coleam00/claude-memory-compiler».

## Декларация

1. Источник спецификации для всех [CR]-файлов — `docs/architecture.ru.md` и `docs/conventions.ru.md`. Эти документы написаны пользователем (копирайт-холдером репозитория) на основе собственного опыта и знаний.
2. Допустимое использование после завершения [CR]-файла: сверка интерфейсных сигнатур (CLI-флаги, stdin/stdout hook-контракты) — это интерфейсы, не выражение.

## Co-authorship

Код написан пользователем с помощью Anthropic's Claude Code (Opus 4.6). LLM имеет в обучающей выборке публичный код GitHub. Пользователь отдавал приказ и делал review; ассистент не запрашивал и не показывал upstream-код во время реализации.

## [CR]-файлы

| Файл | Checkpoint commit | Implementation commit | Spec reference |
|------|-------------------|----------------------|----------------|
| `scripts/config.py` | TBD | TBD | docs/architecture.ru.md §Env-vars, §Paths |
| `scripts/utils.py` | TBD | TBD | (базовые helpers без спеки) |
| `scripts/lint.py` | TBD | TBD | docs/architecture.ru.md §Lint |
| `scripts/query.py` | TBD | TBD | docs/architecture.ru.md §Query |
| `scripts/compile.py` | TBD | TBD | docs/architecture.ru.md §Compile |
| `scripts/flush.py` | TBD | TBD | docs/architecture.ru.md §flush.py |
| `hooks/session-start.py` (скелет) | TBD | TBD | docs/architecture.ru.md §Hook System |
| `hooks/session-end.py` (скелет) | TBD | TBD | docs/architecture.ru.md §Hook System |
| `hooks/pre-compact.py` (скелет) | TBD | TBD | docs/architecture.ru.md §Hook System |

## Процедура

Для каждого [CR]-файла:

1. `git commit --allow-empty -m "chore(cr): checkpoint before rewriting <file>"` — timestamped anchor.
2. Написать файл полностью, обращаясь только к `docs/architecture.ru.md` и `docs/conventions.ru.md`.
3. Прогнать соответствующий smoke-тест (см. `tests/smoke/`).
4. `git commit -m "feat(cr): <file> implementation complete"`.
5. Обновить таблицу выше с git hashes.

## In-file header для [CR]

Каждый [CR]-файл начинается с:

```python
"""
<name>.py — <purpose>.

Clean-room implementation written from scratch against the specification
in docs/architecture.ru.md. No source code from coleam00/claude-memory-compiler
was consulted during authorship.

Co-authored with Anthropic's Claude Code under the direction and review
of the copyright holder. See docs/clean-room-provenance.md.
"""
```

## ECC fragments ([ECC])

`scripts/utils_projects.py` содержит два фрагмента, адаптированных из
`affaan-m/everything-claude-code` (MIT License):
- `scrub_secrets`
- `write_atomic_json`

Каждый блок обрамлён комментариями с явной MIT-атрибуцией. Полная лицензия воспроизведена в `NOTICE`.
