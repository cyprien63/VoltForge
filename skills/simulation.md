# Moteur de simulation

Le solveur est indépendant de Qt et utilise l'analyse nodale modifiée (MNA).
Les sources de tension ajoutent des inconnues de branche ; résistances,
interrupteurs, instruments et modèles compagnons sont stampés dans `A·x=b`.
En DC, les condensateurs sont ouverts et les inductances sont remplacées par
leur résistance de fil. En transitoire, C et L utilisent Euler implicite.

Convention des résultats : `u = V(p)-V(n)`, `i` circule de p vers n et
`p = u*i`. `SimulationEngine` gère une session interactive (style Scratch) :
`start_play(duration, loop)` démarre la lecture, `advance(dt)` avance
l'horloge, `pause_play()`/`resume_play()` et `stop_play()` la contrôlent.
Pendant la session, `recompute()` réapplique immédiatement les interactions
de l'utilisateur (interrupteurs, curseurs, tension) sans avancer l'horloge et
en conservant l'état dynamique ; les valeurs réglées en lecture restent en
place après l'arrêt. Conserver les mutations typées via
`Component.set_prop()` et tester les nouveaux composants en DC et en session.

Ajouter des composants dans `core/components.py`, compléter leur estampillage
dans `core/solver.py`, et vérifier sérialisation, affichage et édition des
propriétés.

Les composants `Thermistor` (modèle bêta NTC) et `Photoresistor` (résistance
statique selon l'éclairement) sont des résistances commandées par leurs
paramètres d'environnement. `Heater`, `Speaker` et `Buzzer` sont des charges
résistives DC simplifiées ; ne pas présenter leur simulation comme un modèle
thermique ou acoustique.
