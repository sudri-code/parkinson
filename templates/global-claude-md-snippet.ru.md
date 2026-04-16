<!-- BEGIN: parkinson-instructions -->
## Персональный LLM-vault: Parkinson

У пользователя есть персональная база знаний в **`__DATA_DIR__`**. Она доступна из любой сессии — не только когда cwd=parkinson.

### Структура vault

```
wiki/          — внешние источники (статьи, README, фреймворки). Ручной ingest из raw/.
wiki/index.md  — каталог wiki по категориям (source/concept/entity/comparison/analysis).

knowledge/concepts/     — концепты из собственных разговоров (compile.py автоматически).
knowledge/connections/  — связи между concepts.
knowledge/instincts/    — поведенческие паттерны (trigger → action), confidence 0.3-0.9.
                          Извлекаются Haiku из __REPO_ROOT__/observations/.
knowledge/index.md      — каталог всего слоя knowledge.
```

### Правило разделения слоёв

- Внешний источник (статья, README) → `wiki/`.
- Разговор → `knowledge/` (concepts/connections через compile, instincts через synthesize).
- Один факт живёт ровно в одном слое; пересечения — через `[[wiki-ссылки]]`.

### Когда заглядывать в vault

- Пользователь задаёт вопрос про свои паттерны работы, привычки, принципы → `knowledge/instincts/`.
- Пользователь ссылается на внешнюю статью или технологию → `wiki/`.
- Вопрос про решение, принятое в другом проекте → `knowledge/concepts/` с `projects: [<name>]`.
- Пользователь говорит «помнишь, мы обсуждали...» → искать в `knowledge/concepts/` + `daily/YYYY-MM-DD.md`.

### Незнакомые термины — сначала SessionStart-инжект

Если пользователь спрашивает «что такое X?» и X похоже на название проекта, репо, тулзы или собственного концепта — **до энциклопедического ответа** просканировать SessionStart `additionalContext`:

1. `Knowledge: Current + Shared` — full rows.
2. `Other Projects` — title + summary; если совпало по названию или summary — открыть статью через `Read` по wikilink-пути из vault (`knowledge/concepts/<slug>.md`).
3. `Wiki` — внешние источники.

Только если ни в одном слое нет совпадения — давать общий ответ.

Читать файлы vault напрямую через `Read`; полный список тем — в двух индексах: `__DATA_DIR__/index.md` (wiki) и `__DATA_DIR__/knowledge/index.md` (knowledge).

### Мульти-проект

В `__DATA_DIR__/projects.json` — registry проектов с canonical-именами и алиасами. `shared` — для фактов без привязки к проекту или кросс-проектных.
<!-- END: parkinson-instructions -->
