"""Tests cœur du moteur de simulation (sessions de lecture, transitoire).

Sans interface graphique : uniquement ``core``.
"""

from __future__ import annotations

import math
import unittest

from core.circuit import Circuit
from core.components import Kind, create_component
from core.simulation import SimulationEngine


def route(circuit: Circuit, a, b, y_mid: float = 140.0) -> None:
    """Relie ``a`` à ``b`` via une ligne horizontale (évite les croisements)."""
    (ax, ay), (bx, by) = a, b
    points = [(ax, ay)]
    if ay != y_mid:
        points.append((ax, y_mid))
    if bx != ax:
        points.append((bx, y_mid))
    if by != y_mid:
        points.append((bx, by))
    circuit.add_wire(points)


def series_circuit(stages):
    """Chaîne source -- composants en série -- masse ; le 1er stage est la source."""
    circuit = Circuit()
    placed = []
    x = 140.0
    for index, (kind, props) in enumerate(stages):
        rotation = 180 if index == 0 else 0
        comp = create_component(kind, x, 100.0, rotation=rotation, **props)
        circuit.add(comp)
        placed.append(comp)
        x += 80.0
    ground = create_component(Kind.GROUND, 240, 180)
    circuit.add(ground)
    ground_p = ground.terminal_positions()["p"]
    for index, (a, b) in enumerate(zip(placed, placed[1:])):
        outgoing = "p" if index == 0 else "n"
        route(circuit, a.terminal_positions()[outgoing],
              b.terminal_positions()["p"], y_mid=120.0)
    route(circuit, placed[0].terminal_positions()["n"], ground_p, y_mid=160.0)
    route(circuit, placed[-1].terminal_positions()["n"], ground_p, y_mid=160.0)
    return circuit, placed


def rc_stages(voltage: float = 12.0, capacitance: float = 1e-3,
              v0: float = 0.0):
    return [
        (Kind.GENERATOR, dict(label="G1", voltage=voltage, ri=0.01, p_max=100.0)),
        (Kind.RESISTOR, dict(label="R1", resistance=100.0, p_max=50.0)),
        (Kind.CAPACITOR, dict(label="C1", capacitance=capacitance, v0=v0)),
    ]


class ComponentPropCoercionTests(unittest.TestCase):
    def test_boolean_prop_accepts_numeric_one_and_zero(self) -> None:
        switch = create_component(Kind.SWITCH, 0, 0, label="K1", closed=False)
        switch.set_prop("closed", 1)
        self.assertTrue(switch.closed)
        switch.set_prop("closed", 0.0)
        self.assertFalse(switch.closed)
        switch.set_prop("closed", "1.0")
        self.assertTrue(switch.closed)


class SessionEngineTests(unittest.TestCase):
    def test_rc_charges_monotonically_during_session(self) -> None:
        circuit, _stages = series_circuit(rc_stages())
        engine = SimulationEngine(circuit)

        engine.start_play(duration=0.2, loop=False)
        samples = [engine.solution.branch("C1").u]
        while engine.playing:
            engine.advance(0.01)
            samples.append(engine.solution.branch("C1").u)

        self.assertFalse(engine.playing)
        self.assertAlmostEqual(engine.t, 0.2, places=6)
        # premier pas d'Euler : U·dt/(R·C+dt) ≈ 0,57 V (et non 0 V)
        self.assertLess(samples[0], 0.7)
        analytic = 12.0 * (1.0 - math.exp(-0.2 / 0.1))
        self.assertAlmostEqual(samples[-1], analytic, delta=0.25)
        self.assertTrue(
            all(b >= a - 1e-9 for a, b in zip(samples, samples[1:])),
            "la charge du condensateur doit être monotone",
        )

    def test_session_without_duration_runs_until_stopped(self) -> None:
        circuit, _stages = series_circuit(rc_stages())
        engine = SimulationEngine(circuit)

        engine.start_play()
        engine.advance(1.0)
        self.assertTrue(engine.playing)
        self.assertAlmostEqual(engine.t, 1.0, places=6)

        solution = engine.stop_play()
        self.assertFalse(engine.playing)
        self.assertEqual(engine.t, 0.0)
        # Retour en DC : le condensateur redevient un circuit ouvert.
        self.assertAlmostEqual(solution.branch("C1").u, 12.0, delta=1e-3)

    def test_loop_restarts_the_session_without_stopping(self) -> None:
        circuit, _stages = series_circuit(rc_stages())
        engine = SimulationEngine(circuit)

        engine.start_play(duration=0.1, loop=True)
        engine.advance(0.25)
        self.assertTrue(engine.playing)
        self.assertAlmostEqual(engine.t, 0.05, places=6)

    def test_pause_freezes_the_clock(self) -> None:
        circuit, _stages = series_circuit(rc_stages())
        engine = SimulationEngine(circuit)

        engine.start_play(duration=1.0, loop=False)
        engine.pause_play()
        engine.advance(0.5)
        self.assertEqual(engine.t, 0.0)
        self.assertTrue(engine.playing)
        engine.resume_play()
        engine.advance(0.1)
        self.assertAlmostEqual(engine.t, 0.1, places=6)

    def test_live_switch_toggle_applies_immediately(self) -> None:
        circuit, (_gen, switch, resistor) = series_circuit([
            (Kind.GENERATOR, dict(label="G1", voltage=12.0, ri=0.01, p_max=100.0)),
            (Kind.SWITCH, dict(label="K1", closed=False, p_max=50.0)),
            (Kind.RESISTOR, dict(label="R1", resistance=100.0, p_max=50.0)),
        ])
        engine = SimulationEngine(circuit)
        engine.start_play(duration=5.0)
        engine.advance(0.3)
        self.assertLess(abs(engine.solution.branch("R1").i), 1e-3)

        switch.set_prop("closed", True)
        engine.recompute()
        self.assertAlmostEqual(engine.solution.branch("R1").i, 0.12, delta=0.01)
        self.assertTrue(engine.playing)
        self.assertAlmostEqual(engine.t, 0.3, places=12)

    def test_live_voltage_edit_persists_after_stop(self) -> None:
        circuit, (gen, _switch, resistor) = series_circuit([
            (Kind.GENERATOR, dict(label="G1", voltage=12.0, ri=0.01, p_max=100.0)),
            (Kind.SWITCH, dict(label="K1", closed=True, p_max=50.0)),
            (Kind.RESISTOR, dict(label="R1", resistance=100.0, p_max=50.0)),
        ])
        engine = SimulationEngine(circuit)
        engine.start_play(duration=5.0)
        engine.advance(0.2)

        gen.set_prop("voltage", 24.0)
        engine.recompute()
        self.assertAlmostEqual(engine.solution.branch("R1").i, 0.24, delta=0.01)

        engine.stop_play()
        # Aucune restauration cachée : le réglage fait en lecture reste.
        self.assertEqual(gen.get_prop("voltage"), 24.0)
        self.assertAlmostEqual(engine.solution.branch("R1").i, 0.24, delta=1e-3)

    def test_recompute_during_session_preserves_dynamic_state(self) -> None:
        circuit, _stages = series_circuit(rc_stages())
        engine = SimulationEngine(circuit)
        capacitor = circuit.get("C1")

        engine.start_play(duration=1.0, loop=False)
        engine.advance(0.05)
        saved = capacitor.tstate["v"]

        for _ in range(5):
            engine.recompute()
        self.assertEqual(capacitor.tstate["v"], saved)
        self.assertTrue(engine.playing)
        self.assertAlmostEqual(engine.t, 0.05, places=12)

    def test_start_play_seeds_capacitor_from_v0(self) -> None:
        circuit, _stages = series_circuit(rc_stages(v0=5.0))
        engine = SimulationEngine(circuit)

        engine.start_play(duration=0.2, loop=False)
        u0 = engine.solution.branch("C1").u
        self.assertGreater(u0, 5.0)
        self.assertLess(u0, 5.6)

    def test_component_burned_during_session_stays_burned(self) -> None:
        circuit, (gen, resistor) = series_circuit([
            (Kind.GENERATOR, dict(label="G1", voltage=9.0, ri=0.1, p_max=100.0)),
            (Kind.RESISTOR, dict(label="R1", resistance=10.0, p_max=1.0)),
        ])
        engine = SimulationEngine(circuit)
        engine.start_play(duration=0.1, loop=False)

        gen.set_prop("voltage", 220.0)
        engine.recompute()
        self.assertTrue(resistor.get_prop("blown"))
        engine.advance(0.1)
        engine.stop_play()

        self.assertEqual(gen.get_prop("voltage"), 220.0)
        self.assertTrue(resistor.get_prop("blown"))

    def test_zero_u_max_disables_voltage_limit(self) -> None:
        circuit, (_gen, resistor) = series_circuit([
            (Kind.GENERATOR, dict(label="G1", voltage=220.0, ri=0.1, p_max=1000.0)),
            (Kind.RESISTOR, dict(label="R1", resistance=1000.0, p_max=1000.0)),
        ])
        resistor.set_prop("u_max", 0.0)
        engine = SimulationEngine(circuit)
        solution = engine.recompute()
        self.assertFalse(resistor.get_prop("blown"))
        self.assertAlmostEqual(solution.branch("R1").u, 220.0 * 1000.0 / 1000.1,
                               delta=1.0)


if __name__ == "__main__":
    unittest.main()
