<!-- BEGIN: parkinson-instructions -->
## Незнакомые термины — сначала SessionStart-инжект

Если пользователь спрашивает «что такое X?» и X похоже на название проекта, репо, тулзы или собственного концепта — **до энциклопедического ответа** просканировать SessionStart `additionalContext`:

1. `Knowledge: Current + Shared` — full rows.
2. `Other Projects` — title + summary; если совпало по названию или summary — открыть статью через `Read` по wikilink-пути из vault (`knowledge/concepts/<slug>.md`).
3. `Wiki` — внешние источники.

Только если ни в одном слое нет совпадения — давать общий ответ.
<!-- END: parkinson-instructions -->
