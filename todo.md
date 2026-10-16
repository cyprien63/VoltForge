# VoltForge — suivi des fonctionnalités

## Fonctionnalités réalisées

- [x] Résolution DC et transitoire des composants pris en charge.
- [x] Modèles dédiés à la pile, au générateur, à la résistance IEC, au
  potentiomètre, à l'interrupteur, au condensateur, à la bobine, à la diode,
  à la LED, à la lampe, au moteur, au fusible, à la masse et aux instruments.
- [x] Allumage visuel de la LED selon son état de conduction et luminosité de la
  lampe selon sa puissance dissipée.
- [x] Création de composants personnalisés résistifs à deux bornes depuis
  l'interface, avec nom, symbole, résistance et sérialisation dans le projet.
- [x] Symboles SVG redessinés pour la palette, avec pile `+ / −`, générateur
  `G`, moteur `M`, voltmètre `V` et résistance rectangulaire IEC.
- [x] Palette regroupée par catégories dans la barre supérieure, sans doublon
  latéral.
- [x] Aperçu avant pose, rotation par `R`, sélection, déplacement et rotation
  des composants ; les fils connectés suivent les bornes.
- [x] Sélection et déplacement d'un fil entier, déplacement de ses extrémités,
  suppression par `Delete` ou menu contextuel.
- [x] Sélection rectangulaire, sélection complète `Ctrl+A`, déplacement et
  suppression groupés des composants et fils.
- [x] Routage orthogonal des fils ; l'outil reste actif et permet de tracer des
  fils successifs depuis le dernier point. Clic droit ou `Échap` termine le
  tracé en cours.
- [x] Normalisation orthogonale des fils après chaque déplacement ou édition,
  ainsi que conversion écran/scène correcte quand le canevas est zoomé.
- [x] Repère circulaire vert au survol d'une borne ou d'un fil ; les extrémités
  s'y accrochent également pendant le dessin et le déplacement.
- [x] Flèche de tension visible au-dessus du schéma, avec aperçu avant pose,
  accrochage aux bornes et nœuds sans marqueurs permanents.
- [x] Bouton explicite pour ouvrir/fermer l'interrupteur sélectionné ; le
  double-clic et le solveur mettent à jour son état électrique.
- [x] Jonctions automatiques aux croisements de fils et aux bornes situées sur
  un segment.
- [x] Nœuds automatiquement nommés A, B, C… avec renommage manuel persistant.
- [x] Flèches de tension nommées automatiquement `Uab`, personnalisables à la
  création et supprimables individuellement ; le trait peut être déplacé
  au-dessus ou au-dessous du circuit et le texte se déplace séparément, sans
  points visibles à ses extrémités.
- [x] Affichage des polarités `+` et `−` sur les bornes des composants.
- [x] Destruction persistante des composants en cas de dépassement de leur
  tension/puissance admissible ou de court-circuit d'un générateur ; bouton
  **Réparer le composant** dans l'inspecteur.
- [x] Calcul et mise en évidence des mailles indépendantes, activables avec
  l'affichage des nœuds depuis le menu **Affichage**.
- [x] Simulation utilisateur sans saisie de code : formulaire de durée,
  cadence, pas de calcul et liste d'événements paramétrés.
- [x] Calculateur de loi d'Ohm pour déterminer U, I, R et P depuis deux valeurs.
- [x] Calcul de résistance série de protection, normalisation E12 et puissance
  minimale conseillée pour préserver le récepteur.
- [x] Zoom à la molette et déplacement de la vue au bouton milieu ou avec
  `Espace` + glisser.
- [x] Thèmes clair et sombre mémorisés entre les sessions.
- [x] Compteurs permanents de nœuds et de mailles ; labels de nœuds dessinés
  au-dessus des composants lorsqu'ils sont activés.
- [x] Sauvegarde au format de projet `.voltforge`, import des anciens JSON et
  confirmation avant fermeture en présence de modifications non enregistrées.
- [x] Export GIF jusqu'au dernier événement du scénario, avec durée totale
  calculée depuis le programme, et restauration de l'état du circuit.
- [x] Tests de régression pour la palette, les symboles, les mouvements, les
  jonctions, la simulation des lampes/LED et l'export GIF.

## Améliorations facultatives

- [ ] Ajouter annuler/rétablir (Undo/Redo).
- [ ] Ajouter des courbes temporelles interactives pour les mesures.
- [ ] Permettre de définir des composants personnalisés à plusieurs broches et
  des sous-circuits, au-delà du modèle résistif à deux bornes.
- [ ] Ajouter un routeur de fils qui évite automatiquement les composants et
  minimise les croisements, avec choix du coude horizontal/vertical.
- [ ] Ajouter un éditeur graphique de symboles et un panneau de réglages
  rapide sans ouvrir les propriétés complètes.
- [ ] Ajouter une bibliothèque de circuits et de sous-circuits réutilisables.
- [ ] Ajouter des analyses AC/fréquentielles, balayage de paramètres et
  estimation de tolérances.
- [ ] Ajouter une légende/export des noms de nœuds, courants et valeurs de
  mesure dans les documents statiques.
- [ ] Ajouter des contrôles de lecture/pause/pas à pas et des signaux
  temporels synchronisés avec la simulation.
- [ ] Ajouter une option pour sélectionner le coude préféré d'un fil, et
  afficher une alerte de collision lorsqu'un tracé traverse un composant.
- [ ] Ajouter un outil « couper / prolonger » un fil.
- [ ] Ajouter des points de jonction déplaçables et des ponts visuels pour
  distinguer les croisements non connectés.
- [ ] Ajouter une comparaison côte à côte des résultats avant/après une
  modification de composant.
- [ ] Ajouter des profils de composants (valeurs normalisées E12/E24,
  puissances nominales et modèles de composants courants).
- [ ] Ajouter des modèles thermiques et des courbes de surcharge dépendant du
  temps, avec refroidissement et réarmement contrôlé des composants.
- [ ] Ajouter des contrôles de vérification du circuit : bornes flottantes,
  boucle sans source, court-circuit et fils qui se chevauchent.
- [ ] Ajouter un mode présentation qui masque la grille et exporte un schéma
  annoté avec nomenclature et tableau des valeurs.
- [ ] Ajouter des raccourcis configurables et une recherche rapide d'outils,
  composants et commandes.
