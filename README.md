# VoltForge

VoltForge est une application de bureau Python/PyQt6 pour dessiner des circuits
électriques, résoudre leur comportement par analyse nodale modifiée (MNA) et
exporter des schémas statiques ou des animations de scénarios.

## Fonctionnalités

- Canevas à grille magnétique : aperçu des composants, fils orthogonaux,
  tracé de fils en continu, déplacement, rotation et annotations de tension
  orientées.
- Repérage automatique A, B, C… des nœuds, renommage manuel, visualisation
  des nœuds et mise en évidence des mailles indépendantes.
- Générateur, pile, résistance IEC, potentiomètre, interrupteur, condensateur,
  bobine, diode, LED, lampe, moteur, fusible, masse, voltmètre, ampèremètre,
  ohmmètre et composants personnalisés résistifs.
- Pack d'icônes SVG cohérent dans `assets/icons/`, utilisé par la barre
  d'outils unique.
- Résolution DC et transitoire (Euler implicite pour C et L), mesures de
  tension/courant/puissance, alertes de puissance et de courant.
- Projets JSON réouvrables, export PNG/JPEG/SVG/PDF et GIF animé à partir
  d'une séquence de paramètres configurée dans l'interface.

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
déplace la vue et la molette règle le zoom ; les déplacements respectent
également le niveau de zoom. Dans l'outil **Fil**, un repère vert apparaît à
proximité d'une borne ou d'un fil pour indiquer l'accrochage. Le double-clic
sur un interrupteur ou son bouton dans le panneau de propriétés le bascule.
Pour tracer plusieurs fils à la suite, gardez l'outil **Fil**
sélectionné et cliquez les points du trajet ; le clic droit ou `Échap` termine
le tracé courant. Dans **Affichage**, activez les lettres de nœuds ou les
indicateurs de mailles. Faites un clic droit près d'un nœud pour lui donner un
nom personnalisé. Les flèches de tension reçoivent automatiquement un nom
comme `Uab` ; l'aperçu indique leur orientation avant la pose, et leur trait
reste visible au-dessus du circuit. Elles sont sélectionnables, renommables
lors de leur création et supprimables avec `Delete`.

Le menu **Simulation > Configurer / lancer** permet de choisir une durée, la
cadence d'images et le pas de calcul, puis d'ajouter des changements de
paramètres horodatés avec des formulaires. Le même réglage sert à lancer la
simulation ou à exporter un GIF, sans écrire de scénario. Le **Calculateur loi
d'Ohm** déduit U, I, R et P à partir de deux valeurs saisies.

## Compilation

`./compil.sh` (Windows : `compil.bat`) construit un exécutable avec PyInstaller.

## Architecture

- `core/` : modèles électriques, topologie, parseur de scénario et solveur MNA,
  indépendants de Qt.
- `ui/` : fenêtre principale, canevas, édition et orchestration interactive.
- `exporters/` : export de canevas statique et génération GIF.
- `skills/` : notes de référence pour les extensions du solveur et des exports.
