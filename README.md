# VoltForge

VoltForge est une application de bureau Python/PyQt6 pour dessiner des circuits
électriques, résoudre leur comportement par analyse nodale modifiée (MNA) et
exporter des schémas statiques ou des animations de scénarios.

## Fonctionnalités

- Canevas à grille magnétique : aperçu des composants, fils orthogonaux,
  déplacement, rotation et annotations de tension orientées.
- Générateur, pile, résistance IEC, potentiomètre, interrupteur, condensateur,
  bobine, diode, LED, lampe, moteur, fusible, masse, voltmètre, ampèremètre,
  ohmmètre et composants personnalisés résistifs.
- Pack d'icônes SVG cohérent dans `assets/icons/`, utilisé par la barre
  d'outils unique.
- Résolution DC et transitoire (Euler implicite pour C et L), mesures de
  tension/courant/puissance, alertes de puissance et de courant.
- Projets JSON réouvrables, export PNG/JPEG/SVG/PDF et GIF animé depuis un
  scénario textuel.

## Installation

Python 3.10 ou plus récent est recommandé.

Le moyen le plus simple est d'utiliser le script de démarrage : il crée
automatiquement `.venv` si nécessaire, installe les dépendances, puis lance
l'application. Sur Linux/macOS, rendez-le exécutable si besoin avec
`chmod +x run.sh`. Ne lancez pas l'application avec `sudo`.

## Démarrage

```bash
./run.sh
# Windows : run.bat
```

Choisissez une catégorie dans la barre supérieure pour accéder à ses
composants. **Créer perso…** définit un composant résistif à deux bornes.
L'aperçu suit la souris avant la pose et la touche `R` le tourne par quarts
de tour. En mode **Sélection**, cliquez un composant pour le déplacer ;
utilisez `R` ou **Tourner**, et `Delete` ou **Supprimer** pour l'éditer.
Sélectionnez un fil pour le déplacer, attrapez un de ses ronds d'extrémité
pour le rerouter, ou faites un clic droit pour le supprimer. Le bouton milieu
déplace la vue et la molette règle le zoom. Le double-clic sur un interrupteur
le bascule. Le scénario et l'export GIF sont accessibles dans **Simulation**.

Un exemple de scénario :

```text
loop 0s 3s
fps 15
dt 1ms
t=0s: G1.voltage = 0V ; K1.closed = false
t=0.5s: G1.voltage = 12V
t=1s: K1.closed = true
t=2s: K1.closed = false
```

Dans **Simulation > Scénario**, collez ou chargez le texte, puis lancez la
simulation ou l'export GIF. Le GIF est capturé jusqu'à la fin de la durée
définie (`loop`, ou dernier événement + `tail`).

## Compilation

`./compil.sh` (Windows : `compil.bat`) construit un exécutable avec PyInstaller.

## Architecture

- `core/` : modèles électriques, topologie, parseur de scénario et solveur MNA,
  indépendants de Qt.
- `ui/` : fenêtre principale, canevas, édition et orchestration interactive.
- `exporters/` : export de canevas statique et génération GIF.
- `skills/` : notes de référence pour les extensions du solveur et des exports.
