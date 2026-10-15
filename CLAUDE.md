# VoltForge — instructions de développement

## Architecture

- `core/components.py`, `circuit.py`, `solver.py`, `simulation.py`,
  `scenario.py` et `voltage_arrow.py` contiennent le modèle et la physique.
  Le cœur ne doit pas dépendre de Qt.
- `ui/canvas.py` dessine et manipule le circuit sur une grille magnétique.
  `ui/main_window.py` compose les outils, propriétés, projets et commandes.
- `assets/icons/` contient les icônes SVG des outils et des 16 composants ;
  la palette ne doit apparaître que dans la barre supérieure.
- `exporters/` réutilise le dessin du canevas pour les formats statiques et
  capture les états du moteur pour les GIF.
- `main.py` est le point d'entrée.

## Conventions

- Garder les composants indépendants de l'interface et représenter les
  propriétés à partir de `Component.PROPS`.
- La tension de branche suit `U = V(p) - V(n)` et le courant positif va de p
  vers n. La masse est déterminée par `Circuit.recompute_nodes()`.
- Les projets sont des documents JSON versionnés via `Circuit.to_dict()`.
- Utiliser les helpers existants `parse_value`, `parse_time` et
  `parse_scenario` plutôt que de créer d'autres syntaxes.

## Commandes

```bash
python -m pip install -r requirements.txt
./run.sh
python -m compileall -q core ui exporters
python -m unittest discover -s tests
./compil.sh
```

`run.bat` et `compil.bat` sont les équivalents Windows. Les dépendances
principales sont PyQt6, NumPy et Pillow ; PyInstaller est optionnel pour la
compilation.
