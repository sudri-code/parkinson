# Установка parkinson

## Требования

- **Python 3.12+**
- **`uv`** — менеджер зависимостей. Установка: `curl -LsSf https://astral.sh/uv/install.sh | sh` или [docs.astral.sh/uv](https://docs.astral.sh/uv/).
- **Claude Code** — установлен и настроен (`~/.claude/.credentials.json` должен существовать).
- **Активная подписка Claude** (Max / Team / Enterprise) — Claude Agent SDK включён в подписку, отдельные API-кредиты не нужны. При Pro-подписке потребуется `ANTHROPIC_API_KEY`.

## Шаги

### 1. Клон репозитория

```bash
git clone git@github.com:sudri-code/parkinson.git
cd parkinson
```

### 2. Запуск install-скрипта

**macOS / Linux:**

```bash
./install.sh
```

**Windows:**

```powershell
uv run python bootstrap.py
```

Скрипт:
- Проверяет `uv`.
- Запускает `uv sync` (скачивает зависимости в `.venv/`).
- Определяет `PARKINSON_DATA_DIR` (из env или `<repo_root>/data`).
- Создаёт пустые директории: `daily/`, `knowledge/{concepts,connections,qa,instincts}/`, `reports/agentshield/`, `observations/archive/`, `state/tool-counts/`.
- Копирует шаблоны (только если файлы отсутствуют): `projects.json`, `knowledge/index.md`, `knowledge/log.md`.
- Если у вас нет `~/.claude/settings.json` — копирует полный пример из `examples/.claude/settings.json` с подстановкой абсолютного пути репо вместо `__REPO_ROOT__`.
- Если `~/.claude/settings.json` уже существует — печатает инструкцию для ручного merge (готовую `jq` команду).
- Делает smoke-check: `uv run python scripts/config.py --print`.

### 3. Merge хуков (если settings уже существует)

`install.sh` напечатает подобную команду:

```bash
jq -s '.[0] * .[1]' \
  ~/.claude/settings.json \
  "$(pwd)/examples/.claude/settings.json" \
  > /tmp/merged.json && mv /tmp/merged.json ~/.claude/settings.json
```

**Важно:** перед merge замените `__REPO_ROOT__` в путях `examples/.claude/settings.json` на абсолютный путь вашего клона (install-скрипт делает это автоматически через `sed`).

Можно вручную — открыть оба файла и скопировать `hooks` секцию.

### 4. Первый запуск

Откройте Claude Code в любом проекте. SessionStart хук запустится автоматически — в первую сессию вы увидите пустой knowledge-index (ещё нечего компилировать).

Поработайте в сессии 10-15 минут. По завершении (или при auto-compact) SessionEnd хук запустит `flush.py` в фоне. Через ~30 секунд посмотрите:

```bash
ls data/daily/
# появился файл YYYY-MM-DD.md
```

### 5. Первая компиляция

После нескольких сессий — вручную (или автоматически после 18:00):

```bash
cd /path/to/parkinson
uv run python scripts/compile.py
```

Это прогонит все новые daily через Agent SDK и создаст concept-статьи в `data/knowledge/concepts/`.

### 6. Проверка здоровья

```bash
uv run python scripts/lint.py --structural-only    # быстро, без API
uv run python scripts/lint.py                      # полная проверка с LLM
```

Отчёты сохраняются в `data/reports/lint-YYYY-MM-DD.md`.

## Конфигурация через `.env`

Скопируйте `.env.example` в `.env` и раскомментируйте нужные переменные:

```bash
cp .env.example .env
${EDITOR:-vi} .env
```

Ключевые:
- `PARKINSON_DATA_DIR` — если хотите указать на существующий vault (например, `~/my-knowledge-base` или путь в облачном хранилище).
- `PARKINSON_TIMEZONE` — для корректного auto-compile после 18:00 local time.
- `ANTHROPIC_API_KEY` — если Pro-подписка.

## Проверка установки

```bash
cd /path/to/parkinson
uv run python scripts/config.py --print
# Должно напечатать:
#   DATA_DIR=<repo_root>/data
#   TIMEZONE=UTC
#   ...
```

## Удаление

```bash
rm -rf /path/to/parkinson
# Удалите hooks-записи из ~/.claude/settings.json вручную.
```

Данные в `data/` безопасны — это вне репозитория (gitignored).

## Частые проблемы

**«uv: command not found»** — установите uv через astral.sh, перезапустите shell.

**«ImportError: claude_agent_sdk»** — `uv sync` не прошёл. Проверьте Python 3.12+.

**Хуки не срабатывают в Claude Code** — проверьте `~/.claude/settings.json` синтаксис и абсолютные пути (не `__REPO_ROOT__`).

**«ANTHROPIC_API_KEY not found»** — у вас Pro-подписка. Добавьте ключ в `.env`.
