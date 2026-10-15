"""VoltForge — Topologie du circuit : nœuds, jonctions et mailles.

Détecte automatiquement les nœuds électriques par **coïncidence
de coordinates** (bornes de composants + sommets des fils) via un
algorithme Union-Find.

Règles particulières :

* Toutes les **masses** (composant « ground ») sont fusionnées
  électriquement et la première (tri par label) devient la référence
  0 V ; à défaut, la borne n du premier générateur à tension sert de
  masse.
* Les points de jonction (3 connexions ou plus) sont détectés pour
  l'affichage des pastilles de soudure.

Indépendant de Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .components import (
    Component,
    Generator,
    Kind,
    SourceType,
    Terminal,
    Wire,
    component_from_dict,
    component_to_dict,
    snap,
)

Point = Tuple[int, int]


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------

class UnionFind:
    """Ensemble-union sur des points de grille (chemin par compression)."""

    def __init__(self) -> None:
        self._parent: Dict[Point, Point] = {}

    def add(self, p: Point) -> None:
        self._parent.setdefault(p, p)

    def find(self, p: Point) -> Point:
        root = self._parent.setdefault(p, p)
        while root != self._parent[root]:
            self._parent[root] = self._parent[self._parent[root]]
            root = self._parent[root]
        self._parent[p] = root
        return root

    def union(self, a: Point, b: Point) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def groups(self) -> Dict[Point, List[Point]]:
        out: Dict[Point, List[Point]] = {}
        for p in list(self._parent):
            out.setdefault(self.find(p), []).append(p)
        return out


# ---------------------------------------------------------------------------
# Nœud électrique
# ---------------------------------------------------------------------------

@dataclass
class CircuitNode:
    id: int
    x: int
    y: int
    name: str = ""
    is_ground: bool = False
    voltage: float = 0.0
    degree: int = 0          # nombre de segments/connexions incidents au nœud
    points: List[Point] = field(default_factory=list)      # coords fusionnées
    junction_coords: List[Point] = field(default_factory=list)

    @property
    def junction(self) -> bool:
        """Un point de jonction (3 connexions ou plus) doit être soudé."""
        return bool(self.junction_coords)


# ---------------------------------------------------------------------------
# Circuit
# ---------------------------------------------------------------------------

class Circuit:
    """Composants, fils, annotations + réseau nodal résolu."""

    def __init__(self) -> None:
        self.components: List[Component] = []
        self.wires: List[Wire] = []
        self.arrows: List[Any] = []          # core.voltage_arrow.VoltageArrow
        self.nodes: Dict[int, CircuitNode] = {}
        self.node_name_overrides: Dict[Point, str] = {}
        self.ground_id: Optional[int] = None
        self._next_uid = 1

    # -- identifiants ------------------------------------------------------
    def uid(self, prefix: str = "E") -> str:
        while True:
            name = f"{prefix}{self._next_uid}"
            self._next_uid += 1
            if not any(c.label == name for c in self.components) and \
               not any(w.label == name for w in self.wires):
                return name

    # -- ajout / suppression ----------------------------------------------
    def add(self, comp: Component) -> Component:
        self.components.append(comp)
        self.recompute_nodes()
        return comp

    def add_wire(self, points: List[Tuple[float, float]],
                 label: Optional[str] = None) -> Wire:
        w = Wire(points, label=label)
        self.wires.append(w)
        self.recompute_nodes()
        return w

    def get(self, label: str) -> Optional[Any]:
        for c in self.components:
            if c.label.lower() == label.lower():
                return c
        for w in self.wires:
            if w.label.lower() == label.lower():
                return w
        return None

    def remove(self, label: str) -> None:
        """Supprime un composant/fil, les fils orphelins et les flèches."""
        target = self.get(label)
        if target is None:
            arrow = next((item for item in self.arrows if item.label == label), None)
            if arrow is not None:
                self.arrows.remove(arrow)
                self.recompute_nodes()
            return
        if isinstance(target, Wire):
            self.wires.remove(target)
        else:
            self.components.remove(target)
            # Supprime les fils dont une extrémité touchait une borne du composant
            gone = {t.key for t in target.terminals()}
            self.wires = [
                w for w in self.wires
                if w.endpoints()[0] not in gone and w.endpoints()[1] not in gone
            ]
        for a in list(self.arrows):
            if getattr(a, "owner", None) == label:
                self.arrows.remove(a)
        self.recompute_nodes()

    def clear(self) -> None:
        self.components.clear()
        self.wires.clear()
        self.arrows.clear()
        self.node_name_overrides.clear()
        self.recompute_nodes()

    def _split_wires_at_junctions(self) -> None:
        """Insert vertices where orthogonal wires or component terminals meet."""
        segments = []
        for wire_index, wire in enumerate(self.wires):
            points = [(snap(x), snap(y)) for x, y in wire.points]
            for segment_index, (start, end) in enumerate(zip(points, points[1:])):
                segments.append((wire_index, segment_index, start, end))
        if not segments:
            return

        split_points = {
            (wire_index, segment_index): set()
            for wire_index, segment_index, _, _ in segments
        }

        def on_segment(point, start, end):
            x, y = point
            ax, ay = start
            bx, by = end
            if ay == by == y:
                return min(ax, bx) <= x <= max(ax, bx)
            if ax == bx == x:
                return min(ay, by) <= y <= max(ay, by)
            return False

        terminals = {
            terminal.key
            for component in self.components
            for terminal in component.terminals()
        }
        for wire_index, segment_index, start, end in segments:
            key = (wire_index, segment_index)
            split_points[key].update(
                point for point in terminals if on_segment(point, start, end)
            )

        for index, first in enumerate(segments):
            wi_a, si_a, a, b = first
            for wi_b, si_b, c, d in segments[index + 1:]:
                point = None
                if a[1] == b[1] and c[0] == d[0]:
                    if min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and \
                            min(c[1], d[1]) <= a[1] <= max(c[1], d[1]):
                        point = (c[0], a[1])
                elif a[0] == b[0] and c[1] == d[1]:
                    if min(c[0], d[0]) <= a[0] <= max(c[0], d[0]) and \
                            min(a[1], b[1]) <= c[1] <= max(a[1], b[1]):
                        point = (a[0], c[1])
                elif a[1] == b[1] == c[1] == d[1]:
                    overlap = {
                        candidate for candidate in (a, b, c, d)
                        if on_segment(candidate, a, b)
                        and on_segment(candidate, c, d)
                    }
                    split_points[(wi_a, si_a)].update(overlap)
                    split_points[(wi_b, si_b)].update(overlap)
                elif a[0] == b[0] == c[0] == d[0]:
                    overlap = {
                        candidate for candidate in (a, b, c, d)
                        if on_segment(candidate, a, b)
                        and on_segment(candidate, c, d)
                    }
                    split_points[(wi_a, si_a)].update(overlap)
                    split_points[(wi_b, si_b)].update(overlap)
                if point is not None:
                    split_points[(wi_a, si_a)].add(point)
                    split_points[(wi_b, si_b)].add(point)

        for wire_index, wire in enumerate(self.wires):
            points = [(snap(x), snap(y)) for x, y in wire.points]
            expanded = [points[0]]
            for segment_index, (start, end) in enumerate(zip(points, points[1:])):
                dx, dy = end[0] - start[0], end[1] - start[1]
                interior = split_points.get((wire_index, segment_index), set())
                ordered = sorted(
                    interior,
                    key=lambda p: (p[0] - start[0]) * dx + (p[1] - start[1]) * dy,
                )
                for point in (*ordered, end):
                    if point != expanded[-1]:
                        expanded.append(point)
            wire.points = expanded

    # -- résolution nodale -------------------------------------------------
    def recompute_nodes(self) -> None:
        """Reconstruit les nœuds électriques (Union-Find sur les coords).

        Le « degré » d'une coordonnée compte les bornes de composants et
        les **extrémités de segments** de fils (une extrémité = 1, un
        sommet intermédiaire d'une polyligne = 2). Une pastille de
        jonction est dessinée dès que 3 segments/connexions se
        rencontrent en un même point (un simple coude de fil n'en
        produit donc jamais).
        """
        self._split_wires_at_junctions()
        uf = UnionFind()
        local_degree: Dict[Point, int] = {}
        ground_keys: List[Point] = []

        def attach(p: Point, count: int) -> None:
            uf.add(p)
            local_degree[p] = local_degree.get(p, 0) + count

        for comp in self.components:
            for t in comp.terminals():
                attach(t.key, 1)
            if comp.kind is Kind.GROUND:
                gp = comp.terminal_positions()["p"]
                ground_keys.append((snap(gp[0]), snap(gp[1])))

        for wire in self.wires:
            pts = [(snap(px), snap(py)) for px, py in wire.points]
            last = len(pts) - 1
            for i, k in enumerate(pts):
                attach(k, 1 if (i == 0 or i == last) else 2)
            for a, b in zip(pts, pts[1:]):
                uf.union(a, b)

        # Toutes les masses sont solidaires (terre = conducteur commun)
        if ground_keys:
            first = ground_keys[0]
            uf.add(first)
            for k in ground_keys[1:]:
                uf.union(first, k)

        # Regroupement -> identifiants de nœuds (triés pour stabilité)
        groups = uf.groups()
        ordered = sorted(groups.keys(), key=lambda r: (r[1], r[0]))
        root_to_id = {root: i + 1 for i, root in enumerate(ordered)}

        self.nodes = {}
        for root, nid in root_to_id.items():
            members = groups[root]
            junctions = [p for p in members if local_degree.get(p, 0) >= 3]
            name = next(
                (self.node_name_overrides[p] for p in members
                 if p in self.node_name_overrides),
                self._node_name(nid - 1),
            )
            self.nodes[nid] = CircuitNode(
                id=nid, x=root[0], y=root[1], name=name,
                degree=max((local_degree.get(p, 0) for p in members), default=0),
                points=sorted(members, key=lambda p: (p[1], p[0])),
                junction_coords=sorted(junctions, key=lambda p: (p[1], p[0])),
            )

        # Bornes de chaque composant
        for comp in self.components:
            comp.resolve_nodes(root_to_id, uf)

        # Masse de référence
        self.ground_id = None
        grounds = sorted((c for c in self.components
                          if c.kind is Kind.GROUND), key=lambda c: c.label)
        for g in grounds:
            if g.node_p is not None and g.node_p in self.nodes:
                self.ground_id = g.node_p
                break
        if self.ground_id is None:
            # Sinon : borne n du premier générateur à tension imposée
            gens = sorted(self.components, key=lambda c: c.label)
            for g in gens:
                if isinstance(g, Generator) and \
                        g.get_prop("source_type") == SourceType.VOLTAGE.value and \
                        g.node_n is not None and g.node_n in self.nodes:
                    self.ground_id = g.node_n
                    break
        if self.ground_id is None and self.nodes:
            self.ground_id = min(self.nodes)
        if self.ground_id in self.nodes:
            self.nodes[self.ground_id].is_ground = True

        # Flèches de tension : résolution des extrémités en nœuds
        for arrow in self.arrows:
            arrow.resolve_nodes(self)

    @staticmethod
    def _node_name(index: int) -> str:
        """Return spreadsheet-like node names: A..Z, AA..AZ, and so on."""
        name = ""
        while index >= 0:
            index, remainder = divmod(index, 26)
            name = chr(ord("A") + remainder) + name
            index -= 1
        return name

    def rename_node(self, node_id: int, name: str) -> None:
        node = self.nodes.get(node_id)
        normalized = name.strip()
        if node is None or not normalized:
            raise ValueError("Le nom du nœud ne peut pas être vide.")
        if any(
            other.id != node_id and other.name.casefold() == normalized.casefold()
            for other in self.nodes.values()
        ):
            raise ValueError(f"Le nom de nœud {normalized!r} est déjà utilisé.")
        for point in node.points:
            self.node_name_overrides[point] = normalized
        node.name = normalized

    def remove_arrow(self, arrow: Any) -> None:
        if arrow in self.arrows:
            self.arrows.remove(arrow)
            self.recompute_nodes()

    # -- requêtes ----------------------------------------------------------
    def degree(self, node_id: Optional[int]) -> int:
        node = self.nodes.get(node_id) if node_id is not None else None
        return node.degree if node else 0

    def node_id_at(self, x: float, y: float, radius: float = 10.0) -> Optional[int]:
        """Nœud le plus proche de (x, y) dans un rayon donné (sinon None)."""
        best, best_d = None, radius * radius
        for nid, node in self.nodes.items():
            for px, py in node.points or [(node.x, node.y)]:
                d = (px - x) ** 2 + (py - y) ** 2
                if d <= best_d:
                    best, best_d = nid, d
        return best

    def junction_points(self) -> List[Tuple[int, int]]:
        """Points devant être soudés (pastille de jonction, 3+ connexions)."""
        return [p for n in self.nodes.values() for p in n.junction_coords]

    def branches(self) -> List[Component]:
        """Composants réellement branchés dans le solveur (hors masse/fils)."""
        return [c for c in self.components if c.is_branch]

    def ground_components(self) -> List[Component]:
        return [c for c in self.components if c.kind is Kind.GROUND]

    def is_complete(self) -> bool:
        return any(isinstance(c, Generator) for c in self.components)

    # -- mailles (base des cycles indépendants du graphe des branches) -------
    def mesh_count(self) -> int:
        return len(self.meshes())

    def meshes(self) -> List[List[Component]]:
        """Return a fundamental cycle basis for the circuit's branch graph."""
        branches = [
            component for component in self.branches()
            if component.node_p is not None and component.node_n is not None
        ]
        adjacency: Dict[int, List[Tuple[int, int]]] = {}
        for edge_index, component in enumerate(branches):
            a, b = component.node_p, component.node_n
            adjacency.setdefault(a, []).append((b, edge_index))
            adjacency.setdefault(b, []).append((a, edge_index))

        tree_edges: set[int] = set()
        visited: set[int] = set()
        parent: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
        for start in adjacency:
            if start in visited:
                continue
            visited.add(start)
            parent[start] = (None, None)
            stack = [start]
            while stack:
                node = stack.pop()
                for neighbor, edge_index in adjacency[node]:
                    if edge_index in tree_edges:
                        continue
                    if neighbor not in visited:
                        visited.add(neighbor)
                        parent[neighbor] = (node, edge_index)
                        tree_edges.add(edge_index)
                        stack.append(neighbor)

        meshes: List[List[Component]] = []
        for edge_index, component in enumerate(branches):
            if edge_index in tree_edges:
                continue
            start, end = component.node_p, component.node_n
            ancestors: Dict[int, List[int]] = {}
            node, path = start, []
            while node is not None:
                ancestors[node] = list(path)
                parent_node, parent_edge = parent[node]
                if parent_edge is not None:
                    path.append(parent_edge)
                node = parent_node
            node, end_path = end, []
            while node not in ancestors:
                parent_node, parent_edge = parent[node]
                if parent_edge is not None:
                    end_path.append(parent_edge)
                node = parent_node
            cycle_edges = ancestors[node] + end_path + [edge_index]
            meshes.append([branches[index] for index in cycle_edges])
        return meshes

    # -- sérialisation -----------------------------------------------------
    def to_dict(self, scenario_text: str = "") -> Dict[str, Any]:
        return {
            "version": 1,
            "components": [component_to_dict(c) for c in self.components],
            "wires": [Wire.to_dict(w) for w in self.wires],
            "arrows": [a.to_dict() for a in self.arrows],
            "node_labels": [
                {"point": list(point), "name": name}
                for point, name in self.node_name_overrides.items()
            ],
            "scenario": scenario_text,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Circuit":
        circuit = cls()
        for cd in data.get("components", []):
            circuit.components.append(component_from_dict(cd))
        for wd in data.get("wires", []):
            circuit.wires.append(Wire.from_dict(wd))
        from .voltage_arrow import VoltageArrow
        for ad in data.get("arrows", []):
            circuit.arrows.append(VoltageArrow.from_dict(ad))
        circuit.node_name_overrides = {
            tuple(item["point"]): item["name"]
            for item in data.get("node_labels", [])
        }
        circuit.recompute_nodes()
        return circuit
