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
- Générateur, pile, résistance, thermistance NTC, photorésistance,
  potentiomètre, interrupteur, bouton-poussoir, condensateur, bobine, diode,
  LED, lampe, moteur, résistance chauffante, haut-parleur, buzzer, fusible,
  masse, instruments de mesure et composants personnalisés.
- Pack d'icônes SVG cohérent dans `assets/icons/`, utilisé par la barre
  d'outils unique.
- Logo VoltForge dédié pour l'icône de la fenêtre, les exécutables et
  l'installateur Windows, ainsi que les lanceurs Linux et leur recherche
  d'applications.
- Résolution DC et transitoire (Euler implicite pour C et L), mesures de
  tension/courant/puissance, limites de tension et de puissance, composants
  grillés en cas de surcharge et fusibles déclenchés.
- Sélection rectangulaire et déplacement/suppression groupés, déplacement du
  plan de travail, thèmes clair et sombre.
- Projets `.voltforge` réouvrables, export PNG/JPEG/SVG/PDF et GIF animé à
  partir d'une séquence de paramètres configurée dans l'interface.

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
de tour. En mode **Sélection**, glissez sur une zone vide pour sélectionner
plusieurs éléments, puis glissez l'un d'eux pour les déplacer ensemble.
`Ctrl+A` sélectionne tout et `Delete` supprime la sélection. Cliquez un seul
composant pour le déplacer ; utilisez `R` ou **Tourner**.
Quand un composant est sélectionné, le panneau **Réglage en direct** propose
des curseurs et des champs numériques pour ses paramètres principaux : les
tensions, courants et états se recalculent immédiatement sans ouvrir l'éditeur
de propriétés avancées.
La thermistance utilise un modèle bêta NTC à température réglable ; la
photorésistance suit l'éclairement saisi. Résistance chauffante, haut-parleur et
buzzer sont simulés en DC par leur résistance/impédance équivalente : la
simulation ne modélise pas leur acoustique, leur température ni leur réponse en
fréquence.
Sélectionnez un fil pour le déplacer, attrapez un de ses ronds d'extrémité
pour le rerouter, ou faites un clic droit pour le supprimer. Le bouton milieu
ou `Espace` + glisser déplace le plan de travail ; la molette règle le zoom.
Dans l'outil **Fil**, un repère vert apparaît à
proximité d'une borne ou d'un fil pour indiquer l'accrochage. Le double-clic
sur un interrupteur ou son bouton dans le panneau de propriétés le bascule.
Pour tracer plusieurs fils à la suite, gardez l'outil **Fil**
sélectionné et cliquez les points du trajet ; le clic droit ou `Échap` termine
le tracé courant. Dans **Affichage**, activez les lettres de nœuds ou les
indicateurs de mailles. Faites un clic droit près d'un nœud pour lui donner un
nom personnalisé. Les flèches de tension reçoivent automatiquement un nom
comme `Uab` ; l'aperçu indique leur orientation avant la pose, et leur trait
reste visible au-dessus du circuit sans point aux extrémités. Faites glisser
le trait pour le placer au-dessus ou au-dessous du circuit, et faites glisser
son texte indépendamment. Les bornes des composants indiquent `+` et `−`.
Les propriétés de chaque composant exposent sa tension maximale et son état
« grillé » ; les lampes utilisent aussi leur tension nominale. Une surcharge
grille le composant durablement : sélectionnez-le puis utilisez **Réparer le
composant** dans l'inspecteur. Un court-circuit de générateur ou de pile le
grille également. Un composant qui grille pendant une simulation reste grillé
après la restauration des paramètres du scénario. Le compteur de nœuds et de
mailles reste visible sur le canevas ; activez les repères de nœuds pour voir
leurs noms sur le circuit.
Le menu **Affichage > Thème** bascule entre les thèmes clair et sombre.

Le menu **Simulation > Configurer / lancer** permet de choisir une durée, la
cadence d'images et le pas de calcul, puis d'ajouter des changements de
paramètres horodatés avec des formulaires. Le même réglage sert à lancer la
simulation ou à exporter un GIF, sans écrire de scénario. Le **Calculateur loi
d'Ohm** déduit U, I, R et P à partir de deux valeurs saisies.
L'outil **Calculer une résistance de protection** estime une résistance série
normalisée et sa puissance minimale à partir des caractéristiques de la source
et du récepteur. Les deux calculateurs affichent les formules et les
substitutions numériques ; le panneau de résultats détaille aussi les équations
utilisées pour chaque branche du circuit.

Les projets se sauvegardent au format VoltForge `.voltforge` (archive de projet,
distincte d'un fichier JSON). Les anciens projets JSON restent importables. Si
le circuit comporte des modifications non enregistrées, VoltForge propose de
les enregistrer, de les abandonner ou d'annuler la fermeture.

## Compilation

`./compil.sh` (Windows : `compil.bat`) construit un exécutable avec PyInstaller.
Le logo de l'application est défini dans `assets/icons/voltforge.svg` et sa
version Windows multi-résolution dans `assets/icons/voltforge.ico`.
Les releases Windows proposent un installateur classique `.exe` et un `.exe`
portable autonome qui peut être lancé sans installation.

## Releases automatiques

Chaque push sur `main` déclenche une compilation Windows et Linux, puis publie
une release GitHub avec l'installateur Windows (`-setup.exe`), l'exécutable
Windows portable (`-portable.exe`), l'archive Linux portable (`.tar.gz`), le
paquet Debian (`.deb`) et un AppImage Linux autonome (`.AppImage`). La première
release est `v1.0.0` ;
chaque push suivant incrémente le numéro de correctif (`v1.0.1`, `v1.0.2`, etc.).
Les notes de version listent les commits, leurs auteurs et les fichiers modifiés.
Le workflow nécessite que les Actions aient le droit d'écrire dans les releases
du dépôt.

## Architecture

- `core/` : modèles électriques, topologie, parseur de scénario et solveur MNA,
  indépendants de Qt.
- `ui/` : fenêtre principale, canevas, édition et orchestration interactive.
- `exporters/` : export de canevas statique et génération GIF.
- `skills/` : notes de référence pour les extensions du solveur et des exports.
