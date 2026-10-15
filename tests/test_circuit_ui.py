"""Regression checks for circuit catalog, battery polarity, and editor tools."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from PIL import Image, ImageChops

from core.circuit import Circuit
from core.components import Battery, Kind, Lamp, Led, Resistor
from core.simulation import SimulationEngine
from exporters.gif import export_gif
from ui.main_window import MainWindow


class CircuitEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_component_catalog_has_one_palette_and_valid_icons(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        self.assertEqual(window.splitter.count(), 2)
        self.assertEqual(len(window.tool_group.actions()), 3)
        self.assertEqual(len(window.component_categories), 6)
        category_actions = [
            action
            for _, menu in window.component_categories.values()
            for action in menu.actions()
            if not action.isSeparator()
        ]
        self.assertEqual(len(category_actions), len(window.TOOL_COMPONENTS) + 1)
        self.assertIn((Kind.LED, "LED"), window.TOOL_COMPONENTS)
        self.assertIn((Kind.MOTOR, "Moteur"), window.TOOL_COMPONENTS)
        for icon_name in window.ICONS.values():
            icon = QIcon(str(window._icon_path(icon_name)))
            self.assertFalse(icon.isNull(), icon_name)

    def test_battery_negative_terminal_is_grounded_and_simulated(self) -> None:
        circuit = Circuit()
        battery = circuit.add(Battery(-80, 0, rotation=90, label="BAT_TEST"))
        resistor = circuit.add(Resistor(0, 0, resistance=100))
        circuit.add_wire([(-80, -20), (-20, -20), (-20, 0)])
        circuit.add_wire([(-80, 20), (20, 20), (20, 0)])

        solution = SimulationEngine(circuit).recompute()

        self.assertTrue(solution.solved, solution.errors)
        self.assertEqual(circuit.ground_id, battery.node_n)
        self.assertAlmostEqual(solution.branches[resistor.label].u, 8.991, places=2)

    def test_preview_rotation_and_post_placement_delete(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas
        center = QPoint(canvas.width() // 2, canvas.height() // 2)

        canvas.set_mode("place", Kind.RESISTOR)
        QTest.mouseMove(canvas, center)
        QTest.keyClick(canvas, Qt.Key.Key_R)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center)
        self.app.processEvents()
        self.assertEqual(len(window.circuit.components), 1)
        self.assertEqual(window.circuit.components[0].rotation, 90)

        canvas.set_mode("select")
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center)
        QTest.keyClick(canvas, Qt.Key.Key_R)
        self.assertEqual(window.circuit.components[0].rotation, 180)
        QTest.keyClick(canvas, Qt.Key.Key_Delete)
        self.assertEqual(window.circuit.components, [])

    def test_component_drag_keeps_attached_wire_connected(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        resistor = window.circuit.add(Resistor(0, 0))
        wire = window.circuit.add_wire([(20, 0), (80, 0)])
        window.engine.recompute()
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas
        center = QPoint(canvas.width() // 2, canvas.height() // 2)

        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(canvas, center + QPoint(40, 0))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=center + QPoint(40, 0))
        self.assertEqual(resistor.position, (40.0, 0.0))
        self.assertEqual(wire.points[0], (60, 0))

        canvas.rotate_component(resistor)
        self.assertEqual(resistor.rotation, 90)
        self.assertEqual(wire.points[0], (40, 20))
        self.assertTrue(all(
            x1 == x2 or y1 == y2
            for (x1, y1), (x2, y2) in zip(wire.points, wire.points[1:])
        ))
        QTest.keyClick(canvas, Qt.Key.Key_Delete)
        self.assertNotIn(wire, window.circuit.wires)

        loose_wire = window.circuit.add_wire([(-80, 80), (80, 80)])
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton,
                         pos=center + QPoint(-80, 80))
        QTest.mouseMove(canvas, center + QPoint(-100, 80))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=center + QPoint(-100, 80))
        self.assertEqual(loose_wire.points[0], (-100, 80))

        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         pos=center + QPoint(0, 80))
        self.assertIs(canvas.selected, loose_wire)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton,
                         pos=center + QPoint(0, 80))
        QTest.mouseMove(canvas, center + QPoint(20, 80))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=center + QPoint(20, 80))
        self.assertEqual(loose_wire.points[0], (-80, 80))
        QTest.keyClick(canvas, Qt.Key.Key_Delete)
        self.assertNotIn(loose_wire, window.circuit.wires)

    def test_crossing_wires_form_a_junction(self) -> None:
        circuit = Circuit()
        horizontal = circuit.add_wire([(-40, 0), (40, 0)])
        vertical = circuit.add_wire([(0, -40), (0, 40)])

        circuit.recompute_nodes()

        self.assertIn((0, 0), horizontal.points)
        self.assertIn((0, 0), vertical.points)
        self.assertTrue(any(
            node.degree == 4 and (0, 0) in node.junction_coords
            for node in circuit.nodes.values()
        ))

    def test_gif_captures_final_event_and_preserves_duration(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        battery = window.circuit.add(Battery(-80, 0, rotation=90, label="BAT_GIF"))
        window.circuit.add(Resistor(0, 0))
        window.circuit.add_wire([(-80, -20), (-20, -20), (-20, 0)])
        window.circuit.add_wire([(-80, 20), (20, 20), (20, 0)])
        window.engine.recompute()
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        scenario = (
            "loop 0s 0.25s\nfps 5\ndt 1ms\n"
            "t=0.2s: BAT_GIF.voltage=5V"
        )
        with TemporaryDirectory() as temp:
            path = Path(temp) / "scenario.gif"
            count = export_gif(window.engine, window.canvas, scenario, str(path))
            self.assertEqual(count, 2)
            self.assertEqual(battery.voltage, 9.0)
            with Image.open(path) as image:
                self.assertEqual(image.n_frames, 2)
                image.seek(0)
                durations = [image.info["duration"]]
                first = image.convert("RGB").copy()
                image.seek(1)
                durations.append(image.info["duration"])
                last = image.convert("RGB").copy()
            self.assertEqual(sum(durations), 250)
            self.assertIsNotNone(ImageChops.difference(first, last).getbbox())

    def test_led_and_lamp_calculate_illuminated_states(self) -> None:
        circuit = Circuit()
        circuit.add(Battery(-100, 0, rotation=90, label="BAT_LIGHT"))
        resistor = circuit.add(Resistor(-40, 0, resistance=330))
        led = circuit.add(Led(40, 0))
        circuit.add_wire([(-100, -20), (-60, -20), (-60, 0)])
        circuit.add_wire([(-20, 0), (20, 0)])
        circuit.add_wire([(60, 0), (60, 40), (-100, 40), (-100, 20)])
        solution = SimulationEngine(circuit).recompute()
        self.assertTrue(solution.solved, solution.errors)
        self.assertTrue(led.on)
        self.assertGreater(solution.branches[resistor.label].i, 0.01)

        lamp_circuit = Circuit()
        lamp_circuit.add(Battery(-80, 0, rotation=90, label="BAT_LAMP"))
        lamp = lamp_circuit.add(Lamp(0, 0))
        lamp_circuit.add_wire([(-80, -20), (-20, -20), (-20, 0)])
        lamp_circuit.add_wire([(-80, 20), (20, 20), (20, 0)])
        lamp_solution = SimulationEngine(lamp_circuit).recompute()
        self.assertGreater(abs(lamp_solution.branches[lamp.label].p), 1.0)


if __name__ == "__main__":
    unittest.main()
