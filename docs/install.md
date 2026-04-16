# Installing parkinson

## Requirements

- **Python 3.12+**
- **`uv`** — dependency manager. Install: `curl -LsSf https://astral.sh/uv/install.sh | sh` or see [docs.astral.sh/uv](https://docs.astral.sh/uv/).
- **Claude Code** — installed and configured (`~/.claude/.credentials.json` must exist).
- **Active Claude subscription** (Max / Team / Enterprise) — the Claude Agent SDK is included; no separate API credits needed. Pro subscribers need to supply `ANTHROPIC_API_KEY`.

## Steps

### 1. Clone the repo

```bash
git clone git@github.com:sudri-code/parkinson.git
cd parkinson
```

### 2. Run the installer

**macOS / Linux:**

```bash
./install.sh
```

**Windows:**

```powershell
uv run python bootstrap.py
```

The installer:
- Checks that `uv` is available.
- Runs `uv sync` (downloads dependencies into `.venv/`).
- Resolves `PARKINSON_DATA_DIR` (from env or `<repo_root>/data`).
- Creates empty directories: `daily/`, `knowledge/{concepts,connections,qa,instincts}/`, `wiki/`, `raw/assets/`, `reports/agentshield/`, `observations/archive/`, `state/tool-counts/`.
- Copies templates (only if the target file is missing): `projects.json`, `knowledge/index.md`, `knowledge/log.md`.
- If you have no `~/.claude/settings.json`, copies the full example from `examples/.claude/settings.json` with an absolute repo path substituted for `__REPO_ROOT__`.
- If `~/.claude/settings.json` already exists, does not overwrite — prints a merge command you can run manually (a ready-to-use `jq` snippet).
- **Optionally** (interactive shell only, after explicit `y` confirmation): appends a snippet to `~/.claude/CLAUDE.md` instructing the assistant to scan the SessionStart inject before answering "what is X?". Idempotent via a `<!-- BEGIN: parkinson-instructions -->` marker. Source: `templates/global-claude-md-snippet.ru.md` (if `LANG=ru*`) or `templates/global-claude-md-snippet.md`.
- Runs a smoke check: `uv run python scripts/config.py --print`.

### 3. Merge hooks (if settings already exists)

`install.sh` prints a command like:

```bash
jq -s '.[0] * .[1]' \
  ~/.claude/settings.json \
  "$(pwd)/examples/.claude/settings.json" \
  > /tmp/merged.json && mv /tmp/merged.json ~/.claude/settings.json
```

**Important:** before merging, substitute `__REPO_ROOT__` in the paths inside `examples/.claude/settings.json` with your clone's absolute path (the installer does this via `sed`).

Or do it by hand — open both files and copy the `hooks` section.

### 4. First run

Open Claude Code in any project. The SessionStart hook will fire automatically — in the first session you will see an empty knowledge index (nothing to compile yet).

Work in a session for 10–15 minutes. On exit (or at auto-compaction) the SessionEnd hook spawns `flush.py` in the background. After ~30 seconds:

```bash
ls data/daily/
# a YYYY-MM-DD.md file has appeared
```

### 5. First compilation

After a few sessions — run manually (or wait for the automatic 18:00 run):

```bash
cd /path/to/parkinson
uv run python scripts/compile.py
```

This pipes every new daily through the Agent SDK and generates concept articles in `data/knowledge/concepts/`.

### 6. Health check

```bash
uv run python scripts/lint.py --structural-only    # fast, no API
uv run python scripts/lint.py                      # full run with LLM
```

Reports are saved to `data/reports/lint-YYYY-MM-DD.md`.

## Configuring via `.env`

Copy `.env.example` to `.env` and uncomment what you need:

```bash
cp .env.example .env
${EDITOR:-vi} .env
```

Key variables:
- `PARKINSON_DATA_DIR` — point at an existing vault (e.g. `~/my-knowledge-base` or a cloud-synced path).
- `PARKINSON_TIMEZONE` — for correct auto-compile after 18:00 local time.
- `ANTHROPIC_API_KEY` — if you are on a Pro subscription.

## Verify the install

```bash
cd /path/to/parkinson
uv run python scripts/config.py --print
# Should print:
#   DATA_DIR=<repo_root>/data
#   TIMEZONE=UTC
#   ...
```

## Uninstall

```bash
rm -rf /path/to/parkinson
# Remove the hook entries from ~/.claude/settings.json by hand.
```

Data under `data/` is safe — it lives outside the repo (gitignored).

## Common issues

**"uv: command not found"** — install uv via astral.sh, restart your shell.

**"ImportError: claude_agent_sdk"** — `uv sync` didn't complete. Check Python 3.12+.

**Hooks do not fire in Claude Code** — verify `~/.claude/settings.json` syntax and absolute paths (not `__REPO_ROOT__`).

**"ANTHROPIC_API_KEY not found"** — you are on Pro. Add the key to `.env`.

---

## Ingest setup: Obsidian Web Clipper + Local Images Plus (optional)

The `data/wiki/` layer in parkinson is for knowledge clipped from external sources (articles, READMEs, documentation). To capture web pages directly from your browser as markdown, use **Obsidian Web Clipper** and **Local Images Plus**.

### 1. Open `data/` as an Obsidian vault

Both tools work through Obsidian. Open your `data/` folder (or whatever `PARKINSON_DATA_DIR` points at) as a vault:

1. Download Obsidian: [obsidian.md](https://obsidian.md) (free for personal use).
2. Open folder as vault → select `<repo>/data/` (or your `PARKINSON_DATA_DIR`).

Your `daily/`, `knowledge/`, `wiki/` folders will appear in the vault — Obsidian handles `[[wiki-links]]` natively and gives you graph view + backlinks.

### 2. Obsidian Web Clipper

The official browser extension from Obsidian: saves web pages into your vault as markdown files with frontmatter.

**Install:**

1. Open [obsidian.md/clipper](https://obsidian.md/clipper).
2. Install the extension for your browser (Chrome, Safari, Firefox, Edge — all supported).
3. In the extension settings:
   - **Vault:** pick the same vault you opened in step 1.
   - **Default folder:** `raw/` — all clips land there.
   - **Template:** default or custom. Recommended frontmatter:
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

**Usage:**

Open the browser extension → click "Save to Obsidian" on any page → a markdown file shows up in `data/raw/`.

After the clip — run the normal wiki ingest workflow (manually, via an LLM):
- read the file from `raw/`
- create a `source`-type page in `data/wiki/`
- update `data/wiki/index.md` and `data/wiki/log.md`

See `docs/conventions.md` — "Ingest" section for details.

### 3. Local Images Plus

An Obsidian community plugin that automatically downloads every external image (`![alt](https://...)`) into a local folder inside the vault. Needed because Web Clipper keeps images as CDN links — if the network drops or the source page disappears, the images are gone.

**Install:**

1. In Obsidian: **Settings → Community plugins → Turn on community plugins** (first time you'll have to confirm — fine; the plugin is open-source).
2. **Browse** → search "Local Images Plus" → **Install** → **Enable**.
3. Plugin settings:
   - **Media storage directory:** `raw/assets/` — images land here.
   - **Apply to newly added files:** ON — automatic for new clips.
   - **Recursive:** run once across existing `raw/*.md` if you already have clips.

**Verification:**

Save any web page via Web Clipper → wait ~5–10 s (Local Images Plus fires on file-modified) → images appear in `data/raw/assets/`, markdown links are rewritten to local paths.

### 4. Resulting flow

```
Browser → Web Clipper → data/raw/<slug>.md
                      → Local Images Plus → data/raw/assets/<images>
                      → (manual) LLM ingest → data/wiki/<slug>.md (type: source)
                      → update data/wiki/index.md + log.md
```

`data/raw/` and `data/raw/assets/` are created by the installer automatically. On older installs without them:

```bash
mkdir -p "$PARKINSON_DATA_DIR/raw/assets"
```
