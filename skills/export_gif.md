# Export GIF

L'interface recueille la durée, la cadence, le pas de calcul et les changements
de paramètres avec des champs et des listes, sans exposer le langage de
scénario. Elle convertit ces réglages en événements que `parse_scenario()`
analyse avant le démarrage de `SimulationEngine.begin_transient()`. L'export
avance d'un pas de simulation par intervalle d'image. Chaque image est rendue
depuis le même canevas que l'export statique afin de préserver couleurs,
mesures et états.

La capture va jusqu'à `ScenarioProgram.end`; le nombre d'images et la durée
sont déterminés par `fps`, `loop`, les événements et `tail`. Restaurer les
valeurs originales dans un bloc `finally`, y compris quand le rendu ou
l'écriture du fichier échoue. Les erreurs de syntaxe doivent être présentées
à l'utilisateur avant le démarrage.
