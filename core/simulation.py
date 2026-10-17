"""VoltForge — Orchestration de la simulation.

``SimulationEngine`` fait le lien entre le circuit, le solveur MNA et un
programme séquentiel :

* **Mode DC** (par défaut) : ``recompute()`` résout le circuit à chaque
  modification de valeur -> mise à jour *instantanée* des tensions et
  courants dans l'interface.
* **Mode transitoire** : ``begin_transient()`` / ``advance(dt)`` rejouent
  un scénario pas à pas (modèles compagnons), pour la lecture en temps
  réel **et** l'enregistrement GIF. Les propriétés d'origine sont
  mémorisées à l'identité (labels compris) : relancer une lecture
  repart toujours des mêmes valeurs de départ, éventuellement renommées
  en cours de route, sans jamais écraser une valeur grillée.

Indépendant de Qt.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .circuit import Circuit
from .scenario import ScenarioProgram, parse_scenario
from .solver import Solution, Solver


class SimulationEngine:
    """Moteur de simulation du circuit courant."""

    def __init__(self, circuit: Circuit):
        self.circuit = circuit
        self.solver = Solver(circuit)
        self.solution: Solution = Solution()
        # --- mode transitoire ---
        self.program: Optional[ScenarioProgram] = None
        self.program_errors: List[str] = []
        self.playing: bool = False
        self.t: float = 0.0
        self._cursor: int = 0
        self._snapshot: List[Tuple[Any, Dict[str, Any]]] = []
        self._missing: List[str] = []

    # ------------------------------------------------------------------
    # Mode permanent (DC) — utilisé à chaque édition dans l'interface
    # ------------------------------------------------------------------
    def recompute(self) -> Solution:
        """Résout le circuit en régime permanent et stocke la solution."""
        if self.playing:
            # Pendant la lecture d'un scénario, le résultat transitoire prime.
            return self.solution
        self.solution = self.solver.solve(dt=None, t=self.t)
        return self.solution

    # ------------------------------------------------------------------
    # Mode transitoire (lecture de scénario / export GIF)
    # ------------------------------------------------------------------
    @property
    def is_transient(self) -> bool:
        return self.playing

    def load_program(self, text: str) -> ScenarioProgram:
        """Analyse un scénario textuel et mémorise les erreurs éventuelles."""
        program, errors = parse_scenario(text)
        self.program = program
        seen, uniq = set(), []
        for e in errors:
            msg = f"Ligne {e.line} : {e.message}"
            if msg not in seen:
                seen.add(msg)
                uniq.append(msg)
        self.program_errors = uniq
        return program

    @property
    def snapshot_pending(self) -> bool:
        """Vrai si un snapshot de restauration attend la prochaine lecture."""
        return bool(self._snapshot)

    def begin_transient(self, program: Optional[ScenarioProgram] = None,
                        restore_after: bool = True) -> Solution:
        """Démarre une simulation transitoire (snapshot des propriétés).

        Si un snapshot est resté en attente (lecture précédente non
        explicitement restaurée), il est réappliqué d'abord : chaque
        exécution repart donc des mêmes valeurs de départ. Le snapshot
        est ensuite reconstruit à l'identité, label compris.
        """
        prog = program or self.program
        if prog is None:
            raise RuntimeError("Aucun programme de simulation chargé.")
        if self._snapshot:
            self.restore_snapshot()
        if restore_after:
            self._snapshot = [
                (c, {k: v for k, v in c.props().items()})
                for c in self.circuit.components
            ]
        else:
            self._snapshot = []
        self._missing = []
        self.program = prog
        self.playing = True
        self.t = prog.start
        self._cursor = 0
        self.solver.reset_transient()
        # Applique les événements déjà dus à l'instant initial (t0)
        self._cursor = prog.apply_upto(self.circuit, self.t, self._cursor,
                                       self._missing)
        # Résolution du circuit à l'instant initial (t0)
        self.solution = self.solver.solve(dt=prog.dt, t=self.t)
        return self.solution

    def advance(self, dt: float) -> Solution:
        """Avance la simulation de ``dt`` secondes (pas à pas internes)."""
        if not self.playing or self.program is None:
            return self.solution
        prog = self.program
        target = min(self.t + dt, prog.end)
        while self.t < target - 1e-9:
            next_event_t = self._next_event_time()
            step = min(prog.dt, target - self.t)
            if next_event_t is not None:
                step = min(step, max(0.0, next_event_t - self.t))
            if step <= 1e-12:
                # événements dus : application puis reprise
                self._cursor = prog.apply_upto(self.circuit, self.t,
                                               self._cursor, self._missing)
                continue
            self.t += step
            self._cursor = prog.apply_upto(self.circuit, self.t, self._cursor,
                                           self._missing)
            self.solution = self.solver.solve(dt=step, t=self.t)
        if self.t >= prog.end - 1e-9:
            self.playing = False    # programme terminé
        return self.solution

    def _next_event_time(self) -> Optional[float]:
        assert self.program is not None
        if self._cursor < len(self.program.events):
            return self.program.events[self._cursor].time
        return None

    @property
    def finished(self) -> bool:
        return self.program is not None and not self.playing

    def end_transient(self, restore: bool = True) -> Solution:
        """Termine la lecture ; restaure les propriétés d'origine si demandé.

        Avec ``restore=False``, le snapshot est conservé : l'état final
        de la simulation reste le nouveau point de départ et pourra être
        réappliqué à la lecture suivante (rejeu reproductible).
        """
        self.playing = False
        if restore:
            if self._snapshot:
                self.restore_snapshot()
            self._snapshot = []
        self.t = 0.0
        self._cursor = 0
        self.solution = self.solver.solve(dt=None, t=0.0)
        return self.solution

    def restore_snapshot(self) -> None:
        """Remet les valeurs d'origine (annule les mutations du scénario).

        Les composants sont retrouvés par identité, pas par label : un
        renommage pendant la simulation ne casse pas la restauration.
        Un composant grillé pendant la lecture reste grillé.
        """
        for comp, saved in self._snapshot:
            burned_during_simulation = bool(comp.get_prop("blown"))
            for k, v in saved.items():
                if k == "blown":
                    continue
                try:
                    comp.set_prop(k, v)
                except (ValueError, KeyError):
                    pass
            comp.set_prop(
                "blown",
                burned_during_simulation or bool(saved.get("blown", False)),
            )

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------
    @property
    def missing_targets(self) -> List[str]:
        """Composants référencés par le scénario mais absents du circuit."""
        return list(dict.fromkeys(self._missing))

    def measure(self, label: str) -> Optional[Dict[str, float]]:
        r = self.solution.branches.get(label)
        if r is None:
            return None
        return {"u": r.u, "i": r.i, "p": r.p}
