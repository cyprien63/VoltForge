# Export GIF

`export_gif(engine, canvas, filename, duration, fps, progress)` enregistre une
session de lecture : `start_play()` démarre une session fraîche, puis chaque
image est capturée à intervalle `1/fps` d'horloge simulée et `stop_play()`
termine la session dans un bloc `finally`, y compris quand le rendu ou
l'écriture du fichier échoue. Le nombre d'images est `ceil(duration * fps)`
(au moins 2) ; les durées d'image somment à la durée demandée.

Chaque image est rendue depuis le même canevas que l'export statique afin de
préserver couleurs, mesures et états. Le rappel `progress(current, total)` est
invoqué après chaque image : s'il traite les événements Qt, l'utilisateur peut
interagir avec le canevas pendant la capture — interrupteurs et curseurs sont
alors enregistrés dans le GIF. L'interface doit désactiver les commandes de
session pendant l'export pour que le timer de lecture ne pilote pas le moteur
en parallèle.
