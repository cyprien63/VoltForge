"""VoltForge — Moteur de simulation électrique (MNA).

Implémente l'**Analyse Nodale Modifiée** (*Modified Nodal Analysis*) :

* Régime permanent (DC) : condensateurs en circuit ouvert, bobines en
  court-circuit, résolution du système linéaire ``A·x = b`` (NumPy).
* Régime transitoire : modèles compagnons implicites (Euler implicite)
  pour C et L -> simulation dynamique (charge RC, LR…) et exécution des
  scénarios séquentiels / export GIF.
* Composants non linéaires (diode, LED) : modèle linéaire par morceaux
  (seuil ``vf`` + ``r_on``/``r_off``) convergé par itérations.
* Protections : fusibles et composants dépassant leurs limites de tension ou
  de puissance deviennent grillés (circuit ouvert) puis le réseau est résolu
  à nouveau ; un générateur court-circuité est également détruit.
* Instruments : Voltmètre (résistance ∞), Ampèremètre (shunt ≈ 0),
  Ohmmètre (injection d'un courant de test, lecture ``U/|I|``).
* Moteur CC : modèle ``U = r_m·I + ke·ω`` / ``kt·I = tc + b·ω`` ramené à
  une conductance et un courant équivalents (linéaire, rapide).

Conventions
-----------
* ``U = V(p) − V(n)`` : tension aux bornes du composant.
* ``I`` : courant circulant **de la borne p vers la borne n** à travers
  le corps du composant (négatif = le générateur délivre du courant).
* ``P = U·I`` : négatif = composant qui **délivre** de la puissance,
  positif = composant qui **dissipe**.

Indépendant de Qt (testable via ``python -m core``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .circuit import Circuit
from .components import (
    Ammeter,
    Capacitor,
    Component,
    Diode,
    Fuse,
    Generator,
    Ground,
    Inductor,
    Lamp,
    Kind,
    Led,
    Motor,
    Ohmmeter,
    Potentiometer,
    Resistor,
    SourceType,
    Switch,
    Voltmeter,
)

# --- constantes du solveur -------------------------------------------------
I_FAULT = 10.0        # A  : seuil « court-circuit »
G_LEAK = 1e-9         # S  : conductance de fuite vers masse (anti-singularité)
R_OPEN = 1e9          # Ω  : « circuit ouvert » en régime permanent
R_MIN = 1e-6          # Ω  : plancher numérique des conductances
MAX_ITER = 12         # itérations des modèles non linéaires


# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------

@dataclass
class BranchResult:
    """Résultat de calcul pour un composant branché."""
    u: float = 0.0            # tension U = V(p) − V(n)   [V]
    i: float = 0.0            # courant p → n             [A]
    p: float = 0.0            # puissance P = U·I         [W]
    state: str = "ok"         # ok | power | fault | disconnected | shorted | blown | error
    message: str = ""
    sourcing: bool = False                        # délivre de la puissance
    reading: Optional[float] = None               # valeur affichée dans l'instrument
    reading_unit: str = ""                        # unité de la lecture

    @property
    def is_warning(self) -> bool:
        return self.state in ("power", "disconnected")

    @property
    def is_fault(self) -> bool:
        return self.state in ("fault", "error", "blown")

    @property
    def ok(self) -> bool:
        return self.state == "ok"


@dataclass
class Solution:
    """Sortie complète d'une résolution du circuit."""
    node_voltages: Dict[int, float] = field(default_factory=dict)
    branches: Dict[str, BranchResult] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    ground_id: Optional[int] = None
    t: float = 0.0
    mode: str = "dc"          # "dc" | "transient"
    solved: bool = False
    iterations: int = 0

    def branch(self, label: str) -> BranchResult:
        return self.branches.get(label, BranchResult())

    def node_voltage(self, node_id: Optional[int]) -> float:
        if node_id is None:
            return float("nan")
        return self.node_voltages.get(node_id, float("nan"))


# ---------------------------------------------------------------------------
# Solveur
# ---------------------------------------------------------------------------

class Solver:
    """Résout un ``Circuit`` par analyse nodale modifiée."""

    def __init__(self, circuit: Circuit):
        self.circuit = circuit
        self._stamp_info: Dict[str, Dict[str, Any]] = {}

    # -- état transitoire --------------------------------------------------
    def reset_transient(self) -> None:
        """Réinitialise les grandeurs d'état (C, L, diodes)."""
        for comp in self.circuit.components:
            comp.tstate = {}
            if isinstance(comp, Capacitor):
                comp.tstate["v"] = float(comp.v0)
            elif isinstance(comp, Inductor):
                comp.tstate["i"] = 0.0
            elif isinstance(comp, (Diode, Led)):
                comp.tstate["on"] = 0

    # -- API publique ------------------------------------------------------
    def solve(self, dt: Optional[float] = None, t: float = 0.0) -> Solution:
        """Résout le circuit, en itérant les modèles non linéaires.

        ``dt=None`` -> régime permanent (DC).
        ``dt>0``    -> un pas de régime transitoire (modèles compagnons).
        """
        sol = self._solve_once(dt, t)
        nonlinear = [c for c in self.circuit.components if c.is_branch]
        iterations = 0
        converged = False
        for iterations in range(1, MAX_ITER + 1):
            changed = False
            for comp in nonlinear:
                res = sol.branches.get(comp.label)
                if res is None:
                    continue
                if isinstance(comp, Fuse):
                    if not comp.blown and abs(res.i) > comp.i_rated + 1e-12:
                        comp.blown = True
                        changed = True
                    continue
                if comp.get_prop("blown"):
                    continue
                if self._should_blow(comp, res):
                    comp.set_prop("blown", True)
                    if isinstance(comp, (Diode, Led)):
                        comp.tstate["on"] = 0
                    changed = True
                    continue
                if not isinstance(comp, (Diode, Led)):
                    continue
                # Diode / LED : hystérésis autour du seuil (anti-oscillation)
                state_on = bool(comp.tstate.get("on", 0))
                tol = 1e-6
                if state_on and res.u < comp.vf - tol:
                    comp.tstate["on"] = 0
                    changed = True
                elif (not state_on) and res.u > comp.vf + tol:
                    comp.tstate["on"] = 1
                    changed = True
            if not changed:
                converged = True
                break
            sol = self._solve_once(dt, t)
        if not converged:
            sol.warnings.append(
                "Modèles non linéaires non convergés : résultats approximatifs "
                "(vérifiez les seuils des diodes/LED)."
            )
        sol.iterations = iterations
        if dt is not None:
            self._commit_transient_state(sol)
        return sol

    def _commit_transient_state(self, sol: Solution) -> None:
        """Valide l'état des modèles compagnons, une seule fois par pas.

        Les ré-itérations des modèles non linéaires ne doivent pas faire
        avancer plusieurs fois la charge du condensateur ou le courant de
        la bobine au sein d'un même pas de temps.
        """
        for comp in self.circuit.components:
            res = sol.branches.get(comp.label)
            if res is None:
                continue
            if isinstance(comp, Capacitor):
                comp.tstate["v"] = res.u
            elif isinstance(comp, Inductor):
                comp.tstate["i"] = res.i

    # -- résolution linéaire ----------------------------------------------
    def _solve_once(self, dt: Optional[float], t: float) -> Solution:
        sol = Solution(t=t, mode="dc" if dt is None else "transient",
                       ground_id=self.circuit.ground_id)
        comps = [c for c in self.circuit.components if c.is_branch]

        if not comps:
            sol.warnings.append("Circuit vide : placez des composants.")
            return sol
        if self.circuit.ground_id is None:
            sol.errors.append("Aucun nœud détecté.")
            return sol
        if not any(isinstance(c, Generator) for c in comps):
            sol.warnings.append("Aucun générateur : le circuit ne sera pas alimenté.")

        ground = self.circuit.ground_id
        nodes = [n for n in self.circuit.nodes.values() if n.id != ground]
        node_index = {n.id: i for i, n in enumerate(nodes)}
        n_v = len(nodes)

        vsrcs: List[Generator] = [
            c for c in comps
            if isinstance(c, Generator) and
            c.source_type is SourceType.VOLTAGE and
            not c.get_prop("blown")
        ]
        m = n_v + len(vsrcs)
        A = np.zeros((m, m), dtype=float)
        b = np.zeros(m, dtype=float)

        def row(node_id: Optional[int]) -> Optional[int]:
            if node_id is None or node_id == ground:
                return None
            return node_index.get(node_id)

        def stamp_g(i: Optional[int], j: Optional[int], g: float) -> None:
            if i is not None:
                A[i, i] += g
            if j is not None:
                A[j, j] += g
            if i is not None and j is not None:
                A[i, j] -= g
                A[j, i] -= g

        def stamp_rhs(i: Optional[int], value: float) -> None:
            if i is not None:
                b[i] += value

        self._stamp_info = {}

        # --- tamponnage de chaque composant --------------------------------
        for comp in comps:
            rp = row(comp.node_p)
            rn = row(comp.node_n)
            info: Dict[str, Any] = {"mode": "passive", "g": 0.0, "ih": 0.0}

            if comp.get_prop("blown"):
                info.update(mode="blown")
            elif isinstance(comp, Generator) and comp.source_type is SourceType.CURRENT:
                # Source de courant réelle : I_s en parallèle avec r_i
                ri = max(comp.ri, 0.0)
                g = (1.0 / ri) if ri > R_MIN else 0.0
                i_s = float(comp.current)
                stamp_g(rp, rn, g)
                stamp_rhs(rp, i_s)
                stamp_rhs(rn, -i_s)
                info.update(mode="gen_i", g=g, isrc=i_s)

            elif isinstance(comp, Ohmmeter):
                # Ohmmètre : injecte i_test, résistance interne en parallèle
                g = 1.0 / max(comp.r_int, 1e3)
                i_s = comp.i_test
                stamp_g(rp, rn, g)
                stamp_rhs(rp, i_s)
                stamp_rhs(rn, -i_s)
                info.update(mode="gen_i", g=g, isrc=i_s)

            elif isinstance(comp, (Diode, Led)):
                if bool(comp.tstate.get("on", 0)):
                    g = 1.0 / max(comp.r_on, R_MIN)
                    i_s = comp.vf * g
                else:
                    g = 1.0 / R_OPEN
                    i_s = 0.0
                stamp_g(rp, rn, g)
                stamp_rhs(rp, i_s)
                stamp_rhs(rn, -i_s)
                info.update(mode="gen_i", g=g, isrc=i_s)

            elif isinstance(comp, Motor):
                g = comp.g_eq
                ih = comp.i_offset
                stamp_g(rp, rn, g)
                stamp_rhs(rp, -ih)
                stamp_rhs(rn, ih)
                info.update(g=g, ih=ih)

            elif isinstance(comp, Potentiometer):
                r_pw, r_wn = comp.sections
                rw = row(comp.node_of.get("w"))
                if rw is None and comp.node_of.get("w") is None:
                    # curseur non résolu : rhéostat série p-n
                    g = 1.0 / max(r_pw + r_wn, R_MIN)
                    stamp_g(rp, rn, g)
                    info.update(mode="pot", g1=g, g2=0.0)
                else:
                    g1 = 1.0 / max(r_pw, R_MIN)
                    g2 = 1.0 / max(r_wn, R_MIN)
                    stamp_g(rp, rw, g1)
                    stamp_g(rw, rn, g2)
                    info.update(mode="pot", g1=g1, g2=g2)

            elif isinstance(comp, Fuse):
                g = 1.0 / max(comp.resistance, R_MIN)
                stamp_g(rp, rn, g)
                info.update(g=g)

            elif isinstance(comp, (Resistor, Switch, Lamp)):
                r = max(float(comp.resistance), R_MIN)
                g = 1.0 / r
                stamp_g(rp, rn, g)
                info.update(g=g)

            elif isinstance(comp, Voltmeter):
                g = 1.0 / max(comp.r_int, 1e3)
                stamp_g(rp, rn, g)
                info.update(g=g)

            elif isinstance(comp, Ammeter):
                g = 1.0 / max(comp.r_sh, R_MIN)
                stamp_g(rp, rn, g)
                info.update(g=g)

            elif isinstance(comp, Capacitor):
                if dt is None:
                    g, ih = 1.0 / R_OPEN, 0.0
                else:
                    c = max(comp.capacitance, 1e-15)
                    g = c / dt
                    ih = -g * float(comp.tstate.get("v", comp.v0))
                stamp_g(rp, rn, g)
                stamp_rhs(rp, -ih)
                stamp_rhs(rn, ih)
                info.update(g=g, ih=ih, dynamic="c")

            elif isinstance(comp, Inductor):
                if dt is None:
                    g, ih = 1.0 / max(comp.r_w, R_MIN), 0.0
                else:
                    l = max(comp.inductance, 1e-12)
                    g = dt / l
                    ih = float(comp.tstate.get("i", 0.0))
                stamp_g(rp, rn, g)
                stamp_rhs(rp, -ih)
                stamp_rhs(rn, ih)
                info.update(g=g, ih=ih, dynamic="l")

            elif isinstance(comp, Generator):
                continue   # sources de tension -> tampon MNA dédié

            self._stamp_info[comp.label] = info

        # --- sources de tension (MNA) --------------------------------------
        for k, gen in enumerate(vsrcs):
            kv = n_v + k
            rp, rn = row(gen.node_p), row(gen.node_n)
            if rp is not None:
                A[rp, kv] += 1.0
                A[kv, rp] += 1.0
            if rn is not None:
                A[rn, kv] -= 1.0
                A[kv, rn] -= 1.0
            ri = max(gen.ri, 0.0)
            # V(p) − V(n) − r_i·i_k = U_s   (i_k : courant entrant en p)
            A[kv, kv] -= ri
            b[kv] = float(gen.voltage)
            self._stamp_info[gen.label] = {"mode": "gen_v", "k": kv}

        # --- fuite vers masse : garantit la régularité du système ---------
        for i in range(n_v):
            A[i, i] += G_LEAK

        # --- résolution ----------------------------------------------------
        x = np.zeros(m, dtype=float)
        if m > 0:
            try:
                x = np.linalg.solve(A, b)
            except np.linalg.LinAlgError:
                x, *_ = np.linalg.lstsq(A, b, rcond=None)
                sol.errors.append(
                    "Système nodal singulier : nœuds flottants ou sources "
                    "incompatibles."
                )
            if not np.all(np.isfinite(x)):
                sol.errors.append("Solution non finie (vérifiez les valeurs).")
                x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

        # --- tensions de nœuds ---------------------------------------------
        sol.node_voltages = {ground: 0.0}
        for nid, idx in node_index.items():
            sol.node_voltages[nid] = float(x[idx])

        # --- résultats par composant ---------------------------------------
        for comp in comps:
            vp = sol.node_voltages.get(comp.node_p) if comp.node_p is not None else None
            vn = sol.node_voltages.get(comp.node_n) if comp.node_n is not None else None
            if vp is None or vn is None:
                sol.branches[comp.label] = BranchResult(
                    state="error", message="Bornes non résolues")
                continue
            u = vp - vn
            info = self._stamp_info.get(comp.label, {"mode": "passive", "g": 0.0})
            mode = info["mode"]

            if mode == "gen_v":
                i = float(x[info["k"]])
                p = u * i
            elif mode == "gen_i":
                i = info["g"] * u - info["isrc"]
                p = u * i
            elif mode == "blown":
                i = p = 0.0
            elif mode == "pot":
                vw = sol.node_voltages.get(comp.node_of.get("w"), 0.0)
                u_pw, u_wn = vp - vw, vw - vn
                g1, g2 = info["g1"], info.get("g2", 0.0)
                i = g1 * u_pw
                p = g1 * u_pw * u_pw + g2 * u_wn * u_wn
            else:
                i = info["g"] * u + info.get("ih", 0.0)
                p = u * i

            res = BranchResult(
                u=u, i=i, p=p,
                sourcing=(p < -1e-6) if isinstance(comp, Generator) else False,
            )
            res.state, res.message = self._classify(comp, res)
            self._fill_reading(comp, res)
            sol.branches[comp.label] = res

        # --- masse (pas de branche) ----------------------------------------
        for g in self.circuit.ground_components():
            sol.branches[g.label] = BranchResult(state="ok", message="Masse (0 V)")

        # --- avertissements globaux ---------------------------------------
        deg = self.circuit.degree
        disconnected = [c.label for c in comps
                        if deg(c.node_p) <= 1 or deg(c.node_n) <= 1]
        if disconnected:
            sol.warnings.append("Bornes non connectées : " +
                                ", ".join(sorted(disconnected)[:6]))
            for c in comps:
                res = sol.branches.get(c.label)
                if res is not None and res.ok and \
                        (deg(c.node_p) <= 1 or deg(c.node_n) <= 1):
                    res.state = "disconnected"
                    res.message = "Terminal non connecté"
        over = [lbl for lbl, r in sol.branches.items() if r.state == "power"]
        if over:
            sol.warnings.append("Dépassement de puissance : " + ", ".join(sorted(over)))
        faults = [lbl for lbl, r in sol.branches.items() if r.state == "fault"]
        if faults:
            sol.warnings.append("Court-circuit détecté : " + ", ".join(sorted(faults)))
        blown = [lbl for lbl, r in sol.branches.items() if r.state == "blown"]
        if blown:
            sol.warnings.append("Composant(s) grillé(s) : " + ", ".join(sorted(blown)))

        sol.solved = True
        return sol

    # -- classification d'état --------------------------------------------
    @staticmethod
    def _classify(comp: Component, res: BranchResult) -> Tuple[str, str]:
        from .formatting import si_format
        if comp.get_prop("blown"):
            if isinstance(comp, Fuse):
                return "blown", f"Fusible grillé (Iᵣ = {si_format(comp.i_rated, 'A')})"
            return "blown", "Composant grillé — réarmez-le dans ses propriétés"
        if comp.node_p is not None and comp.node_p == comp.node_n and \
                not isinstance(comp, Ground):
            return "shorted", "Bornes court-circuitées (même nœud)"
        if abs(res.i) >= I_FAULT:
            return "fault", (f"Courant excessif {si_format(abs(res.i), 'A')} "
                             f"(court-circuit probable)")
        p_max = comp.get_prop("p_max")
        if p_max is not None and float(p_max) > 0 and abs(res.p) > float(p_max):
            return "power", (f"Puissance {si_format(abs(res.p), 'W')} > "
                             f"max {si_format(float(p_max), 'W')}")
        return "ok", ""

    @staticmethod
    def _should_blow(comp: Component, res: BranchResult) -> bool:
        if isinstance(comp, Generator):
            if comp.node_p is not None and comp.node_p == comp.node_n:
                return True
            p_max = comp.get_prop("p_max")
            if p_max is not None and float(p_max) > 0 and abs(res.p) > float(p_max):
                return True
            if p_max is not None and float(p_max) > 0 and res.sourcing:
                rated_current = float(p_max) / max(abs(comp.voltage), 1.0)
                return abs(res.i) > rated_current
            return False

        u_max = float(comp.get_prop("u_max") or 0.0)
        if isinstance(comp, Lamp):
            u_max = min(u_max, comp.u_rated)
        if abs(res.u) > u_max:
            return True
        p_max = comp.get_prop("p_max")
        return (
            p_max is not None and float(p_max) > 0
            and abs(res.p) > float(p_max)
        )

    # -- lectures d'instruments -------------------------------------------
    @staticmethod
    def _fill_reading(comp: Component, res: BranchResult) -> None:
        if isinstance(comp, Voltmeter):
            res.reading, res.reading_unit = res.u, "V"
        elif isinstance(comp, Ammeter):
            res.reading, res.reading_unit = res.i, "A"
        elif isinstance(comp, Ohmmeter):
            res.reading, res.reading_unit = comp.measured_r(res.u, res.i), "Ω"
        elif isinstance(comp, Motor):
            res.reading, res.reading_unit = comp.rpm(res.i), "tr/min"
        elif isinstance(comp, Lamp):
            res.reading, res.reading_unit = res.p, "W"
