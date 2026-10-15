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
- [x] Jonctions automatiques aux croisements de fils et aux bornes situées sur
  un segment.
- [x] Zoom à la molette et déplacement de la vue au bouton milieu.
- [x] Export GIF jusqu'au dernier événement du scénario, avec durée totale
  calculée depuis le programme, et restauration de l'état du circuit.
- [x] Tests de régression pour la palette, les symboles, les mouvements, les
  jonctions, la simulation des lampes/LED et l'export GIF.

## Améliorations facultatives

- [ ] Ajouter annuler/rétablir (Undo/Redo).
- [ ] Ajouter des courbes temporelles interactives pour les mesures.
- [ ] Permettre de définir des composants personnalisés à plusieurs broches et
  des sous-circuits, au-delà du modèle résistif à deux bornes.
