"""VoltForge — Annotation « flèche de tension » (ex. U_ab).

Une flèche relie deux points du schéma et affiche la différence de
potentiel U_ab = V(a) − V(b) calculée par le solveur. Les extrémités se
résolvent automatiquement en nœuds électriques lors de la reconstruction
du réseau.

Indépendant de Qt.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from .components import snap


class VoltageArrow:
    """Flèche de tension orientée de ``start`` vers ``end``."""

    def __init__(self, start: Tuple[float, float], end: Tuple[float, float],
                 label: Optional[str] = None, circuit: Any = None):
        self.start: Tuple[int, int] = (snap(start[0]), snap(start[1]))
        self.end: Tuple[int, int] = (snap(end[0]), snap(end[1]))
        self.label = label or ""
        self.node_a: Optional[int] = None
        self.node_b: Optional[int] = None
        self.node_a_name = "A"
        self.node_b_name = "B"
        self._automatic_label = not bool(label)
        if circuit is not None:
            self.resolve_nodes(circuit)
        if self._automatic_label:
            self.label = self._auto_label()

    # -- identité ----------------------------------------------------------
    @property
    def id(self) -> str:
        return self.label

    def _auto_label(self) -> str:
        return f"U{self.node_a_name.lower()}{self.node_b_name.lower()}"

    def auto_rename(self) -> None:
        """Renomme selon les nœuds résolus (U_1_2 si connu)."""
        self.label = self._auto_label()

    # -- résolution nodale -------------------------------------------------
    def resolve_nodes(self, circuit: Any) -> None:
        """Appelé par ``Circuit.recompute_nodes`` à chaque changement."""
        self.node_a = circuit.node_id_at(self.start[0], self.start[1], radius=12.0)
        self.node_b = circuit.node_id_at(self.end[0], self.end[1], radius=12.0)
        if self.node_a in circuit.nodes:
            self.node_a_name = circuit.nodes[self.node_a].name.lower()
        if self.node_b in circuit.nodes:
            self.node_b_name = circuit.nodes[self.node_b].name.lower()
        if self._automatic_label:
            self.label = self._auto_label()

    # -- déplacement -------------------------------------------------------
    def move_by(self, dx: float, dy: float) -> None:
        from .components import snap as s
        self.start = (self.start[0] + s(dx), self.start[1] + s(dy))
        self.end = (self.end[0] + s(dx), self.end[1] + s(dy))

    def set_endpoint(self, which: str, x: float, y: float) -> None:
        pt = (snap(x), snap(y))
        if which == "start":
            self.start = pt
        else:
            self.end = pt

    # -- valeur mesurée ----------------------------------------------------
    def voltage(self, solution: Any) -> Optional[float]:
        """U_ab = V(a) − V(b) si les deux nœuds sont connus."""
        if solution is None or self.node_a is None or self.node_b is None:
            return None
        va = solution.node_voltages.get(self.node_a)
        vb = solution.node_voltages.get(self.node_b)
        if va is None or vb is None:
            return None
        return va - vb

    def text(self, solution: Any) -> str:
        u = self.voltage(solution)
        name = self.label.replace("U_", "U").replace("u_", "U")
        if u is None:
            return name
        from .formatting import si_format
        return f"{name} = {si_format(u, 'V')}"

    # -- sérialisation -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "automatic_label": self._automatic_label,
            "start": list(self.start),
            "end": list(self.end),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VoltageArrow":
        label = data.get("label")
        automatic = data.get("automatic_label")
        if automatic is None:
            automatic = not label or bool(re.fullmatch(r"U_[0-9]+_[0-9]+", label))
        a = cls(
            tuple(data["start"]), tuple(data["end"]),
            label=None if automatic else label,
        )
        return a
