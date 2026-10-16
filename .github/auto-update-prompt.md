## Consignes

- Lis `CLAUDE.md` et respecte les conventions du projet (le cœur `core/` ne doit pas dépendre de Qt, réutilise les helpers existants).
- Explore le code avant de modifier. Fais des changements ciblés.
- Valide avec `python -m compileall -q core ui exporters` et `python -m unittest discover -s tests`. Corrige ce que tu casses.
- Fais PLUSIEURS petits commits logiques avec des messages clairs au format Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`...). Chaque commit doit expliquer une étape.
- NE crée PAS de pull request. NE pousse PAS (`git push`) : la CI s'en charge.
- Termine par un résumé Markdown concis de ce que tu as changé et pourquoi.
