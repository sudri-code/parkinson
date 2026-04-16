# Smoke tests

Minimal sanity checks: install is correct, hooks fire, lint passes. Not a full test suite — just dev smoke tests.

## Layout

```
tests/
├── fixtures/
│   ├── minimal-transcript.jsonl   — fake SessionEnd transcript
│   └── git-repo/                  — minimal git repo for project detection (created on demand)
├── smoke/
│   ├── test_lint_structural.sh    — lint --structural-only on an empty vault
│   └── test_session_start.sh      — session-start hook on the fixture
└── README.md
```

## Running

```bash
cd /path/to/parkinson
bash tests/smoke/test_lint_structural.sh
bash tests/smoke/test_session_start.sh
```

Both must finish with `[test_*] OK` and exit 0. If they fail — read the stderr message and check:
- `uv sync` completed.
- `./install.sh` has been run (the `data/` tree exists).
- The fixture git-repo exists: `ls tests/fixtures/git-repo/.git` (if not, `test_session_start.sh` will bootstrap it on demand).

## Verification levels

Full verification (`docs/install.md`) has five levels. These smoke scripts cover Level 1 (lint) and Level 2 (session-start hook). Levels 3–5 need Agent SDK calls and real data — run them by hand after installation.
