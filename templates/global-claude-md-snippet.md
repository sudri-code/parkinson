<!-- BEGIN: parkinson-instructions -->
## Unknown terms — check SessionStart inject first

When the user asks "what is X?" and X looks like a project name, repo, tool, or personal concept — **before answering encyclopedically**, scan the SessionStart `additionalContext`:

1. `Knowledge: Current + Shared` — full rows.
2. `Other Projects` — title + summary; on match by name or summary, open the article with `Read` using the wikilink path from the vault (`knowledge/concepts/<slug>.md`).
3. `Wiki` — external sources.

Only if no layer matches — give a general answer.
<!-- END: parkinson-instructions -->
