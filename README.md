# parkinson

Personal knowledge-base compiler for Claude Code sessions.

Hooks capture your AI coding conversations, the Claude Agent SDK extracts
decisions/lessons/patterns into a daily log, and an LLM compiler organizes
those into structured, cross-referenced knowledge articles — injected back
into every future session.

---

## About this repository

This project is conceptually inspired by Andrej Karpathy's
[LLM Knowledge Base](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
and by Cole Medin's
[claude-memory-compiler](https://github.com/coleam00/claude-memory-compiler),
but the core scripts are a from-scratch clean-room implementation written
against the specification in `docs/architecture.ru.md`. No source code from
upstream repositories without a published license was consulted during
authorship. See [NOTICE](NOTICE) for the full attribution statement and
[docs/clean-room-provenance.md](docs/clean-room-provenance.md) for the
audit trail.

Primary documentation is in Russian (`docs/*.ru.md`, `README.ru.md`).
This README provides a short English overview; see
[README.ru.md](README.ru.md) for the full quick-start guide.

---

## Quick start (TL;DR)

```bash
git clone git@github.com:sudri-code/parkinson.git
cd parkinson
./install.sh
# then merge examples/.claude/settings.json into your ~/.claude/settings.json
```

Open Claude Code in any project — SessionStart will inject the (initially
empty) knowledge index; after a conversation, SessionEnd will flush it
into a daily log, and the next `uv run python scripts/compile.py` turns
daily logs into concept articles.

---

## License

MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
