# parkinson

Персональный компилятор базы знаний для сессий Claude Code.

Хуки захватывают ваши диалоги с AI-ассистентом, Claude Agent SDK извлекает
решения/уроки/паттерны в дневной лог, а LLM-компилятор организует их в
структурированные концепт-статьи с перекрёстными ссылками — которые потом
инжектируются обратно в каждую новую сессию.

---

## Как это работает

```
Разговор → SessionEnd/PreCompact хуки → flush.py извлекает знание
    → data/daily/YYYY-MM-DD.md → compile.py
        → data/knowledge/concepts/, connections/, qa/
            → SessionStart инжектит индекс в следующую сессию → цикл
```

- **Hooks** захватывают разговоры автоматически (конец сессии + safety net
  на pre-compact).
- **flush.py** вызывает Claude Agent SDK чтобы решить, что стоит сохранить,
  и после 18:00 местного времени автоматически запускает компиляцию.
- **compile.py** превращает дневные логи в концепт-статьи с cross-refs.
- **query.py** отвечает на вопросы, используя индекс (без RAG).
- **lint.py** запускает 7 health checks (broken links, orphans,
  противоречия, устаревание).

---

## Особенности

- **Multi-project aware.** `projects.json` registry с canonical-именами
  и алиасами. При первой встрече с новым репо — запись создаётся
  автоматически. SessionStart выдаёт tiered-контекст: `Current + Shared`
  (полные записи), `Other Projects` (только заголовки), `Instincts`
  (глобально), `Wiki` (внешние источники).

- **Instincts pipeline.** PreToolUse/PostToolUse собирают наблюдения
  в `observations.jsonl`, `synthesize_instincts.py` извлекает атомарные
  поведенческие паттерны через Haiku (trigger → action) с confidence
  scoring (0.3 → 0.9 при повторах), дедуп через каталог существующих
  инстинктов в промпте.

- **Два слоя знания.** `wiki/` — ingest внешних источников (вручную),
  `knowledge/` — автокомпиляция из разговоров. Жёсткое правило: один факт
  живёт ровно в одном слое, пересечения — через `[[wiki-ссылки]]`.

- **Security scan.** `agentshield-run.py` периодически сканирует данные
  на утечки secrets (adapted from everything-claude-code, MIT).

---

## Установка

Требования: `uv` ([docs.astral.sh/uv](https://docs.astral.sh/uv/)),
Python 3.12+, активная подписка Claude (Max/Team/Enterprise — SDK входит
в неё), Claude Code.

```bash
git clone git@github.com:sudri-code/parkinson.git
cd parkinson
./install.sh
```

Скрипт сделает `uv sync`, создаст папки `data/`, скопирует шаблоны
(`templates/projects.json` и т.д.). После этого подхвати хуки в своём
`~/.claude/settings.json` — подсказку install.sh напечатает.

Подробнее — в [docs/install.ru.md](docs/install.ru.md).

---

## Конфигурация (env-vars)

Все переменные опциональные, дефолты в `.env.example`. Главная —
`PARKINSON_DATA_DIR` (дефолт `<repo_root>/data`). Если у тебя уже есть
vault в другом месте — укажи в `.env`:

```bash
PARKINSON_DATA_DIR=~/my-knowledge-base
```

Полный список — в `.env.example` и `scripts/config.py`.

---

## Команды

```bash
uv run python scripts/compile.py                       # компиляция новых daily
uv run python scripts/compile.py --dry-run             # план без записи
uv run python scripts/query.py "вопрос"                # ответ по базе
uv run python scripts/query.py "вопрос" --file-back    # + сохранить в qa/
uv run python scripts/lint.py                          # все проверки
uv run python scripts/lint.py --structural-only        # без API
uv run python scripts/instincts.py list                # инстинкты
uv run python scripts/instincts.py show <id>           #   показать
uv run python scripts/instincts.py prune               #   удалить устаревшие
```

---

## Ingest внешних источников (опционально)

Слой `data/wiki/` предназначен для знания из статей и документации. Рекомендуемый браузерный flow:

- **[Obsidian Web Clipper](https://obsidian.md/clipper)** — официальный extension, сохраняет веб-страницы в `data/raw/` как markdown с frontmatter.
- **Local Images Plus** — Obsidian community-плагин, скачивает все внешние изображения в `data/raw/assets/` локально (чтобы клипы оставались читаемы оффлайн).

Установка и настройка — см. [docs/install.ru.md](docs/install.ru.md#ingest-setup-obsidian-web-clipper--local-images-plus-опционально).

---

## Документация

- [docs/architecture.ru.md](docs/architecture.ru.md) — полная спека архитектуры
- [docs/conventions.ru.md](docs/conventions.ru.md) — конвенции страниц
- [docs/install.ru.md](docs/install.ru.md) — установка пошагово (включая ingest-инструменты)
- [docs/hooks-reference.ru.md](docs/hooks-reference.ru.md) — 5 хуков и их triggers
- [docs/clean-room-provenance.md](docs/clean-room-provenance.md) — audit trail

---

## Почему без RAG?

Инсайт Карпати: на персональном масштабе (50-500 статей) LLM, читающий
структурированный `index.md`, выигрывает у vector similarity. LLM
понимает *что* ты спрашиваешь; cosine similarity ищет только похожие
слова. RAG становится необходим примерно с 2000+ статей, когда индекс
перестаёт влезать в контекст.

---

## Лицензия

MIT. См. [LICENSE](LICENSE) и [NOTICE](NOTICE).
