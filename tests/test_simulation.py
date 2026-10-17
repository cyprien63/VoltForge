"""Tests cœur du moteur de simulation (scénarios, transitoire, rejeu).

Sans interface graphique : uniquement ``core``.
"""

from __future__ import annotations

import math
import unittest

from core.circuit import Circuit
from core.components import Kind, create_component
from core.scenario import parse_scenario
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


class ScenarioParserTests(unittest.TestCase):
    def test_duration_ends_at_last_event_plus_tail(self) -> None:
        program, errors = parse_scenario("t=2: C1.v0=3\nt=5: C1.v0=6")
        self.assertFalse(errors)
        self.assertEqual(program.start, 2.0)
        self.assertAlmostEqual(program.end, 5.5)
        self.assertAlmostEqual(program.duration, 3.5)

    def test_directive_names_require_a_following_space(self) -> None:
        program, errors = parse_scenario(
            "loop 0s 2s\n"
            "dt1.resistance=50\n"
            "fps_gen.voltage=3V\n"
            "fps 20\ndt 5ms\ntail 200ms"
        )
        self.assertFalse(errors)
        self.assertEqual([ev.target for ev in program.events],
                         ["dt1", "fps_gen"])
        self.assertEqual(program.fps, 20.0)
        self.assertAlmostEqual(program.dt, 0.005)
        self.assertAlmostEqual(program.tail, 0.2)

    def test_label_accepts_text_and_state_aliases(self) -> None:
        program, errors = parse_scenario(
            "t=0: R1.label=RX\n"
            "t=1: RX.resistance=200\n"
            "t=2: K1.state=false\n"
            "t=3: F1.blown=grillé"
        )
        self.assertFalse(errors)
        self.assertEqual(program.events[0].value, "RX")
        self.assertEqual(program.events[1].target, "RX")
        self.assertEqual(program.events[2].prop, "closed")
        self.assertIs(program.events[2].value, False)
        self.assertEqual(program.events[3].prop, "blown")
        self.assertIs(program.events[3].value, True)

    def test_syntax_errors_are_reported_with_line_numbers(self) -> None:
        _program, errors = parse_scenario("fps abc\nR1.truc = 3\nt=x: R1.resistance=1")
        messages = " ".join(e.message for e in errors)
        self.assertIn("fps invalide", messages)
        self.assertIn("propriété inconnue", messages)
        self.assertIn("temps invalide", messages)
        self.assertTrue(all(e.line > 0 for e in errors))


class TransientEngineTests(unittest.TestCase):
    def test_rc_charges_monotonically_toward_source(self) -> None:
        circuit, _stages = series_circuit(rc_stages())
        engine = SimulationEngine(circuit)
        program = engine.load_program("loop 0s 0.2s\ndt 5ms")
        self.assertFalse(engine.program_errors)

        engine.begin_transient(program)
        samples = [engine.solution.branch("C1").u]
        while not engine.finished:
            engine.advance(0.01)
            samples.append(engine.solution.branch("C1").u)

        # premier pas d'Euler : U·dt/(R·C+dt) ≈ 0,57 V (et non 0 V)
        self.assertLess(samples[0], 0.7)
        analytic = 12.0 * (1.0 - math.exp(-0.2 / 0.1))
        self.assertAlmostEqual(samples[-1], analytic, delta=0.25)
        self.assertTrue(
            all(b >= a - 1e-9 for a, b in zip(samples, samples[1:])),
            "la charge du condensateur doit être monotone",
        )

    def test_switch_event_reroutes_current(self) -> None:
        circuit, (_gen, switch, resistor) = series_circuit([
            (Kind.GENERATOR, dict(label="G1", voltage=12.0, ri=0.01, p_max=100.0)),
            (Kind.SWITCH, dict(label="K1", closed=False, p_max=50.0)),
            (Kind.RESISTOR, dict(label="R1", resistance=100.0, p_max=50.0)),
        ])
        engine = SimulationEngine(circuit)
        engine.load_program("loop 0s 0.6s\ndt 5ms\nt=0.3: K1.closed=true")

        engine.begin_transient()
        self.assertLess(abs(engine.solution.branch("R1").i), 1e-3)

        engine.advance(0.35)
        self.assertTrue(switch.closed)
        self.assertAlmostEqual(engine.solution.branch("R1").i, 0.12, delta=0.01)

    def test_v0_event_at_start_reseeds_capacitor_state(self) -> None:
        circuit, _stages = series_circuit(rc_stages())
        engine = SimulationEngine(circuit)
        engine.load_program("loop 0s 0.2s\ndt 5ms\nt=0: C1.v0=5V")

        engine.begin_transient()
        u0 = engine.solution.branch("C1").u
        # sans réinjection, la résistance pilote U·R/(R+R) ≈ 0,57 V
        self.assertGreater(u0, 5.0)
        self.assertLess(u0, 5.6)

    def test_rename_mid_scenario_keeps_targets_resolvable(self) -> None:
        circuit, (_gen, resistor) = series_circuit([
            (Kind.GENERATOR, dict(label="G1", voltage=12.0, ri=0.01, p_max=100.0)),
            (Kind.RESISTOR, dict(label="R1", resistance=100.0, p_max=50.0)),
        ])
        engine = SimulationEngine(circuit)
        engine.load_program(
            "loop 0s 0.6s\ndt 5ms\nt=0.2: R1.label=RX\nt=0.4: RX.resistance=200")
        self.assertFalse(engine.program_errors)

        engine.begin_transient()
        while not engine.finished:
            engine.advance(0.05)

        self.assertEqual(engine.missing_targets, [])
        renamed = circuit.get("RX")
        self.assertIsNotNone(renamed)
        self.assertEqual(renamed.resistance, 200.0)
        self.assertIsNone(circuit.get("R1"))

        engine.end_transient(restore=True)
        self.assertEqual(resistor.label, "R1")
        self.assertEqual(resistor.resistance, 100.0)

    def test_missing_and_non_simulable_targets_are_reported(self) -> None:
        circuit, _stages = series_circuit(rc_stages()[:2])
        engine = SimulationEngine(circuit)
        engine.load_program(
            "loop 0s 1s\nt=0: ZZZ.voltage=3V\n"
            f"t=0.5: {circuit.wires[0].label}.voltage=3V")

        engine.begin_transient()
        engine.advance(1.0)
        missing = engine.missing_targets
        self.assertTrue(any("ZZZ" in message for message in missing), missing)
        self.assertTrue(any("non simulable" in message for message in missing),
                        missing)

    def test_load_program_reports_errors_once_per_line(self) -> None:
        circuit, _stages = series_circuit(rc_stages()[:2])
        engine = SimulationEngine(circuit)
        engine.load_program("fps abc\nR1.truc = 3")
        self.assertEqual(len(engine.program_errors), 2)
        self.assertTrue(
            all(msg.startswith("Ligne ") for msg in engine.program_errors),
            engine.program_errors,
        )

    def test_component_burned_during_transient_stays_burned(self) -> None:
        circuit, (gen, resistor) = series_circuit([
            (Kind.GENERATOR, dict(label="G1", voltage=9.0, ri=0.1, p_max=100.0)),
            (Kind.RESISTOR, dict(label="R1", resistance=10.0, p_max=1.0)),
        ])
        engine = SimulationEngine(circuit)
        engine.load_program("loop 0s 0.1s\ndt 10ms\nt=0: G1.voltage=220V")

        engine.begin_transient()
        self.assertTrue(resistor.get_prop("blown"))
        engine.advance(0.1)
        engine.end_transient(restore=True)

        self.assertEqual(gen.voltage, 9.0)
        self.assertTrue(resistor.get_prop("blown"))

    def test_replay_restarts_from_original_properties(self) -> None:
        circuit, (gen, _resistor) = series_circuit(rc_stages()[:2])
        engine = SimulationEngine(circuit)
        engine.load_program("loop 0s 0.5s\ndt 20ms\nt=0.2: G1.voltage=3V")

        engine.begin_transient()
        while not engine.finished:
            engine.advance(0.05)
        self.assertEqual(gen.voltage, 3.0)
        self.assertTrue(engine.snapshot_pending)

        engine.begin_transient()
        self.assertEqual(gen.voltage, 12.0)
        self.assertTrue(engine.is_transient)
        engine.advance(0.1)
        self.assertEqual(gen.get_prop("voltage"), 12.0)
        while not engine.finished:
            engine.advance(0.05)
        self.assertEqual(gen.voltage, 3.0)

        engine.end_transient(restore=True)
        self.assertEqual(gen.voltage, 12.0)
        self.assertFalse(engine.snapshot_pending)


if __name__ == "__main__":
    unittest.main()
