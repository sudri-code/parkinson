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

---

## Ingest-setup: Obsidian Web Clipper + Local Images Plus (опционально)

Слой `data/wiki/` в parkinson предназначен для знания из внешних источников (статьи, READMEs, документация). Чтобы складывать туда веб-страницы прямо из браузера в markdown-формате — используйте **Obsidian Web Clipper** и **Local Images Plus**.

### 1. Открыть `data/` как Obsidian vault

Оба инструмента работают через Obsidian. Откройте папку `data/` (или то, что у вас в `PARKINSON_DATA_DIR`) как vault:

1. Скачать Obsidian: [obsidian.md](https://obsidian.md) (бесплатно для личного использования).
2. Open folder as vault → выбрать `<repo>/data/` (или ваш `PARKINSON_DATA_DIR`).

В vault'е появятся ваши `daily/`, `knowledge/`, `wiki/` — Obsidian понимает `[[wiki-ссылки]]` нативно, даёт graph view и backlinks.

### 2. Obsidian Web Clipper

Официальный browser-extension от Obsidian: сохраняет веб-страницы в vault как markdown-файлы с frontmatter.

**Установка:**

1. Открыть [obsidian.md/clipper](https://obsidian.md/clipper).
2. Установить extension для своего браузера (Chrome, Safari, Firefox, Edge — все поддерживаются).
3. В настройках extension:
   - **Vault:** выбрать тот же vault, что открыли в п. 1.
   - **Default folder:** `raw/` — все клипы будут падать туда.
   - **Template:** базовый или кастомный. Рекомендуемые поля в frontmatter:
     ```yaml
     ---
     title: "{{title}}"
     source: "{{url}}"
     author: "{{author}}"
     published: "{{published}}"
     tags: [clipped]
     created: "{{date}}"
     ---
     ```

**Использование:**

Open the browser extension → клик «Save to Obsidian» на любой странице → markdown-файл появится в `data/raw/`.

После клипа — запустите обычный wiki ingest-workflow (вручную через LLM):
- прочитать файл из `raw/`
- создать страницу типа `source` в `data/wiki/`
- обновить `data/wiki/index.md` и `data/wiki/log.md`

См. `docs/conventions.ru.md` — раздел «Ingest» для деталей workflow.

### 3. Local Images Plus

Community-плагин Obsidian: автоматически скачивает все внешние изображения (`![alt](https://...)`) в локальную папку vault'а. Нужен потому что Web Clipper сохраняет изображения как ссылки на CDN — при потере интернета или при удалении страницы-источника они пропадут.

**Установка:**

1. В Obsidian: **Settings → Community plugins → Turn on community plugins** (первый раз потребуется подтвердить — это нормально, plugin open-source).
2. **Browse** → поиск «Local Images Plus» → **Install** → **Enable**.
3. В настройках плагина:
   - **Media storage directory:** `raw/assets/` — все изображения будут падать туда.
   - **Apply to newly added files:** ON — автоматически для новых клипов.
   - **Recursive:** можно однократно прогнать на существующих `raw/*.md`.

**Проверка:**

Сохраните любую веб-страницу через Web Clipper → подождите ~5-10 сек (Local Images Plus работает по триггеру file-modified) → изображения в `data/raw/assets/`, ссылки в markdown переписаны на локальные.

### 4. Итоговый flow

```
Браузер → Web Clipper → data/raw/<slug>.md
                      → Local Images Plus → data/raw/assets/<images>
                      → (вручную) LLM ingest → data/wiki/<slug>.md (type: source)
                      → обновить data/wiki/index.md + log.md
```

Папки `data/raw/` и `data/raw/assets/` создаются install-скриптом автоматически. Если у вас старая установка без этих папок — создайте вручную:

```bash
mkdir -p "$PARKINSON_DATA_DIR/raw/assets"
```
