## Consignes

- Lis `CLAUDE.md` et respecte les conventions du projet (le cœur `core/` ne doit pas dépendre de Qt, réutilise les helpers existants).
- Explore le code avant de modifier. Fais des changements ciblés.
- Valide avec `python -m compileall -q core ui exporters` et `python -m unittest discover -s tests`. Corrige ce que tu casses.
- Fais PLUSIEURS petits commits logiques avec des messages clairs au format Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`...). Chaque commit doit expliquer une étape.
- NE crée PAS de pull request. NE pousse PAS (`git push`) : la CI s'en charge.

## Résumé final (obligatoire)

La CI reprend ce résumé pour écrire la description de la PR : sans lui, la PR est vide.

- Quand tout est fait et validé, écris le fichier `.github/auto-update-summary.md`
  (Markdown en français, 30 lignes maximum, sans titre de niveau 1).
- Structure attendue (libellés en gras, puces dessous) :
  - `**Fait**` — puces courtes et concrètes, groupées par thème, une action par puce
    (fichier ou écran concerné quand c'est utile) ;
  - `**Pourquoi**` — le problème réglé et la raison, 2 à 5 puces ;
  - `**Validation**` — commandes exécutées et résultat (`compileall`, tests) ;
  - `**Limites**` — seulement s'il en reste (facultatif).
- Écris pour un humain qui relit la PR : pas de jargon d'outil, pas de copie de logs,
  pas de codes d'échappement, pas d'emojis.
- NE JAMAIS `git add` ni committer ce fichier : la CI le lit puis le supprime.
- Termine aussi ta réponse par ce même résumé (secours si le fichier manque).
