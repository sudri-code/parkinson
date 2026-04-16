# Smoke tests

Минимальные проверки: установка корректна, хуки запускаются, lint проходит. Не полное тестовое покрытие — только dev-sanity.

## Структура

```
tests/
├── fixtures/
│   ├── minimal-transcript.jsonl   — фейковый SessionEnd transcript
│   └── git-repo/                  — минимальный git-репо для project detection
├── smoke/
│   ├── test_lint_structural.sh    — lint --structural-only на пустом vault
│   └── test_session_start.sh      — session-start hook на fixture
└── README.ru.md
```

## Запуск

```bash
cd /path/to/parkinson
bash tests/smoke/test_lint_structural.sh
bash tests/smoke/test_session_start.sh
```

Оба должны завершиться `[test_*] OK` с exit 0. Если падают — см. сообщение stderr и проверьте:
- `uv sync` прошёл
- `./install.sh` был запущен (data/ создан)
- Путь fixture git-repo существует: `ls tests/fixtures/git-repo/.git`

## Verification levels

Полная верификация (`docs/install.ru.md`) включает 5 уровней. Эти smoke-скрипты покрывают Levels 1 (lint) и 2 (session-start hook). Levels 3–5 требуют вызовов Agent SDK и реальных данных — запускаются вручную после установки.
