<!-- BEGIN: parkinson-instructions -->
## Personal LLM vault: Parkinson

The user has a personal knowledge base at **`__DATA_DIR__`**. It is available from any session — not just when cwd=parkinson.

### Vault layout

```
wiki/          — external sources (articles, README, frameworks). Manual ingest from raw/.
wiki/index.md  — wiki catalog by category (source/concept/entity/comparison/analysis).

knowledge/concepts/     — concepts from the user's own conversations (compile.py, automated).
knowledge/connections/  — links between concepts.
knowledge/instincts/    — behavioural patterns (trigger → action), confidence 0.3-0.9.
                          Extracted by Haiku from __REPO_ROOT__/observations/.
knowledge/index.md      — catalog for the whole knowledge layer.
```

### Layer separation rule

- External source (article, README) → `wiki/`.
- Conversation → `knowledge/` (concepts/connections via compile, instincts via synthesize).
- A single fact lives in exactly one layer; cross-references go through `[[wiki-links]]`.

### When to consult the vault

- User asks about their own work patterns, habits, principles → `knowledge/instincts/`.
- User references an external article or technology → `wiki/`.
- Question about a decision made in another project → `knowledge/concepts/` with `projects: [<name>]`.
- User says "remember, we discussed..." → look in `knowledge/concepts/` + `daily/YYYY-MM-DD.md`.

### Unknown terms — check SessionStart inject first

When the user asks "what is X?" and X looks like a project name, repo, tool, or personal concept — **before answering encyclopedically**, scan the SessionStart `additionalContext`:

1. `Knowledge: Current + Shared` — full rows.
2. `Other Projects` — title + summary; on match by name or summary, open the article with `Read` using the wikilink path from the vault (`knowledge/concepts/<slug>.md`).
3. `Wiki` — external sources.

Only if no layer matches — give a general answer.

Read vault files directly via `Read`; the full topic list lives in two indexes: `__DATA_DIR__/index.md` (wiki) and `__DATA_DIR__/knowledge/index.md` (knowledge).

### Multi-project

`__DATA_DIR__/projects.json` is the project registry with canonical names and aliases. `shared` — for facts not tied to any single project or cross-project.
<!-- END: parkinson-instructions -->
