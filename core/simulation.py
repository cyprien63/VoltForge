"""VoltForge — Session de simulation interactive.

``SimulationEngine`` fait le lien entre le circuit et le solveur MNA :

* **Mode DC** (par défaut) : ``recompute()`` résout le circuit à chaque
  modification de valeur -> mise à jour *instantanée* des tensions et
  courants dans l'interface.
* **Session de lecture** : ``start_play()`` démarre une passe transitoire
  en temps réel, ``advance(dt)`` avance l'horloge, ``pause_play()`` la
  fige et ``stop_play()`` la termine. Pendant la lecture, l'utilisateur
  reste libre d'interagir : basculer un interrupteur ou régler un curseur
  puis ``recompute()`` applique le changement immédiatement, sans perdre
  la session et sans qu'aucune valeur ne soit restaurée en secret — les
  réglages faits en cours de route restent en place après l'arrêt.
  Une durée finie avec ``loop=True`` reboucle sans jamais s'arrêter
  (boucle à la Scratch) ; ``duration=0`` signifie « jusqu'à l'arrêt ».

Indépendant de Qt.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .circuit import Circuit
from .solver import Solution, Solver


class SimulationEngine:
    """Moteur de simulation du circuit courant."""

    def __init__(self, circuit: Circuit):
        self.circuit = circuit
        self.solver = Solver(circuit)
        self.solution: Solution = Solution()
        self.playing: bool = False
        self.paused: bool = False
        self.t: float = 0.0
        self.duration: float = 0.0    # 0 s = session illimitée
        self.loop: bool = True
        self.step: float = 0.005      # pas de calcul interne (s)

    # ------------------------------------------------------------------
    # Résolution — édition en DC et rafraîchissement pendant la lecture
    # ------------------------------------------------------------------
    def recompute(self) -> Solution:
        """Résout le circuit sans jamais perdre l'état de la session.

        En DC, la résolution est permanente. Pendant la lecture, elle
        utilise les modèles compagnons de l'instant courant mais n'avance
        pas l'horloge : l'édition de l'utilisateur s'applique tout de
        suite et l'état dynamique (charge du condensateur, courant de la
        bobine) est conservé à l'identique. Un composant qui grille reste
        grillé, y compris pendant puis après la session.
        """
        if not self.playing:
            self.solution = self.solver.solve(dt=None, t=self.t)
            return self.solution
        states = self._dynamic_states()
        self.solution = self.solver.solve(dt=self.step, t=self.t)
        self._restore_dynamic_states(states)
        return self.solution

    # ------------------------------------------------------------------
    # Session de lecture
    # ------------------------------------------------------------------
    def start_play(self, duration: float = 0.0, loop: bool = True) -> Solution:
        """Démarre une session transitoire depuis les valeurs actuelles.

        Les grandeurs d'état repartent de leurs conditions initiales
        (``v0`` du condensateur, bobine à vide) ; les propriétés du
        circuit telles que l'utilisateur les a réglées sont conservées.
        """
        self.duration = max(0.0, float(duration))
        self.loop = bool(loop)
        self.solver.reset_transient()
        self.t = 0.0
        self.playing = True
        self.paused = False
        self.solution = self.solver.solve(dt=self.step, t=0.0)
        return self.solution

    def pause_play(self) -> None:
        """Figge l'horloge de la session (la reprise reprend au même point)."""
        self.paused = True

    def resume_play(self) -> None:
        self.paused = False

    def stop_play(self) -> Solution:
        """Termine la session et repasse en régime permanent.

        Les valeurs réglées pendant la lecture sont conservées : il n'y
        a pas de restauration cachée, la session modifie le circuit.
        """
        self.playing = False
        self.paused = False
        self.t = 0.0
        self.solution = self.solver.solve(dt=None, t=0.0)
        return self.solution

    def advance(self, dt: float) -> Solution:
        """Avance la session de ``dt`` secondes (pas à pas internes).

        Si une durée finie est atteinte : reboucle à t = 0 quand
        ``loop=True``, sinon termine la session en conservant l'horloge.
        """
        if not self.playing or self.paused or dt <= 0.0:
            return self.solution
        remaining = float(dt)
        while remaining > 1e-12 and self.playing:
            step = min(self.step, remaining)
            if self.duration > 0.0:
                until_end = self.duration - self.t
                if until_end <= 1e-12:
                    self._cycle_or_finish()
                    continue
                step = min(step, until_end)
            self.t += step
            remaining -= step
            self.solution = self.solver.solve(dt=step, t=self.t)
            if self.duration > 0.0 and self.t >= self.duration - 1e-9:
                self._cycle_or_finish()
        return self.solution

    def _cycle_or_finish(self) -> None:
        """Reboucle la session à t = 0, ou l'arrête à durée épuisée."""
        if self.loop:
            self.solver.reset_transient()
            self.t = 0.0
            self.solution = self.solver.solve(dt=self.step, t=0.0)
        else:
            # Fin naturelle : la solution transitoire du dernier instant
            # reste affichée (frame finale de la session) jusqu'à la
            # prochaine édition, à un nouveau lancement ou à l'arrêt
            # explicite, qui repassent en régime permanent.
            self.playing = False
            self.paused = False

    # ------------------------------------------------------------------
    # État dynamique (conservé par recompute pendant la lecture)
    # ------------------------------------------------------------------
    def _dynamic_states(self) -> List[Tuple[Any, Dict[str, Any]]]:
        return [(comp, dict(comp.tstate)) for comp in self.circuit.components]

    @staticmethod
    def _restore_dynamic_states(
        states: List[Tuple[Any, Dict[str, Any]]]
    ) -> None:
        # Seules les grandeurs d'état sont rétablies : l'hystérésis des
        # diodes/LED (« on ») et les composants grillés restent ceux que
        # la résolution vient de déterminer avec les nouvelles valeurs.
        for comp, saved in states:
            for key in ("v", "i"):
                if key in saved:
                    comp.tstate[key] = saved[key]
