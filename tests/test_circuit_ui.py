"""Regression checks for circuit catalog, battery polarity, and editor tools."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QIcon, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPlainTextEdit, QPushButton, QTableWidget
from PIL import Image, ImageChops

from core.circuit import Circuit
from core.components import Battery, Kind, Lamp, Led, Resistor, Switch, Wire
from core.simulation import SimulationEngine
from core.voltage_arrow import VoltageArrow
from exporters.gif import export_gif
from ui.main_window import MainWindow, OhmCalculatorDialog


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

    def test_diagonal_wire_is_routed_as_orthogonal_segments(self) -> None:
        wire = Wire([(0, 0), (80, 60)])
        self.assertEqual(wire.points, [(0, 0), (80, 0), (80, 60)])
        self.assertTrue(all(
            x1 == x2 or y1 == y2
            for (x1, y1), (x2, y2) in zip(wire.points, wire.points[1:])
        ))

    def test_wire_remains_orthogonal_when_points_are_reassigned(self) -> None:
        wire = Wire([(0, 0), (80, 0)])
        wire.points = [(0, 0), (40, 40), (80, 40)]
        self.assertEqual(wire.points, [(0, 0), (40, 0), (40, 40), (80, 40)])
        circuit = Circuit()
        circuit.wires.append(wire)
        circuit.recompute_nodes()
        self.assertTrue(all(
            x1 == x2 or y1 == y2
            for (x1, y1), (x2, y2) in zip(wire.points, wire.points[1:])
        ))

    def test_wire_tool_keeps_drawing_from_the_last_endpoint(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas
        center = QPoint(canvas.width() // 2, canvas.height() // 2)
        canvas.set_mode("wire")
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         pos=center + QPoint(-80, 0))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         pos=center + QPoint(0, 0))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         pos=center + QPoint(0, 80))
        self.assertEqual(len(window.circuit.wires), 2)
        self.assertEqual(window.circuit.wires[0].points[-1], (0, 0))
        self.assertEqual(window.circuit.wires[1].points[0], (0, 0))
        QTest.mouseClick(canvas, Qt.MouseButton.RightButton,
                         pos=center + QPoint(0, 80))
        self.assertIsNone(canvas._wire_start)

    def test_nodes_are_named_and_voltage_arrow_uses_node_names(self) -> None:
        circuit = Circuit()
        resistor = circuit.add(Resistor(0, 0))
        start, end = resistor.terminals()
        arrow = VoltageArrow(start.pos, end.pos, circuit=circuit)
        circuit.arrows.append(arrow)
        circuit.recompute_nodes()

        self.assertEqual(arrow.label, "Uab")
        self.assertEqual(sorted(node.name for node in circuit.nodes.values()), ["A", "B"])
        first_node = resistor.node_of["p"]
        circuit.rename_node(first_node, "IN")
        circuit.recompute_nodes()
        self.assertEqual(arrow.label, "Uinb")
        restored = Circuit.from_dict(circuit.to_dict())
        self.assertEqual(restored.arrows[0].label, "Uinb")
        restored.remove_arrow(restored.arrows[0])
        self.assertEqual(restored.arrows, [])

    def test_selected_voltage_arrow_can_be_removed_from_inspector(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        arrow = VoltageArrow((0, 0), (80, 40), circuit=window.circuit)
        window.circuit.arrows.append(arrow)
        window.circuit.recompute_nodes()
        window.canvas.set_selection(arrow)
        window.delete_selected()
        self.assertEqual(window.circuit.arrows, [])

    def test_voltage_arrow_is_visible_above_wire_and_component_layer(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        arrow = VoltageArrow((-100, 0), (100, 0), label="Uab")
        window.circuit.arrows.append(arrow)
        window.circuit.recompute_nodes()
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
        canvas.render(image)
        sample = image.pixelColor(
            canvas.width() // 2 + 65, canvas.height() // 2 + 24
        )
        self.assertGreater(sample.red(), 220)
        self.assertGreater(sample.green(), 140)

    def test_voltage_tool_places_and_selects_a_visible_arrow(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.circuit.add(Resistor(0, 0))
        window.circuit.recompute_nodes()
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas
        center = QPoint(canvas.width() // 2, canvas.height() // 2)
        canvas.set_mode("voltage")
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         pos=center + QPoint(-20, 0))
        QTest.mouseMove(canvas, center + QPoint(20, 0))
        self.assertEqual(canvas._arrow_preview_end, (20, 0))
        with patch("ui.canvas.QInputDialog.getText", return_value=("Uab", True)):
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                             pos=center + QPoint(20, 0))
        self.assertEqual(len(window.circuit.arrows), 1)
        arrow = window.circuit.arrows[0]
        self.assertEqual((arrow.start, arrow.end), ((-20, 0), (20, 0)))
        self.assertIs(canvas._item_at(0, 10), arrow)

    def test_wire_snap_target_and_drag_coordinates_respect_zoom(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        resistor = window.circuit.add(Resistor(0, 0))
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas
        center = QPoint(canvas.width() // 2, canvas.height() // 2)
        canvas.zoom = 2.0
        self.assertEqual(canvas.scene_pos(center + QPoint(40, 0)), (20, 0))
        self.assertEqual(canvas._snap_target(-20 + 3, 1), (-20, 0))
        canvas.set_mode("wire")
        QTest.mouseMove(canvas, center + QPoint(-36, 2))
        self.assertEqual(canvas._wire_snap_target, (-20, 0))
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
        canvas.render(image)
        snap_pixel = image.pixelColor(
            canvas.width() // 2 - 40, canvas.height() // 2
        )
        self.assertGreater(snap_pixel.green(), snap_pixel.red())
        canvas.set_mode("select")
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(canvas, center + QPoint(40, 0))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=center + QPoint(40, 0))
        self.assertEqual(resistor.position, (20.0, 0.0))
        wire = window.circuit.add_wire([(-60, -40), (60, -40)])
        window.circuit.recompute_nodes()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton,
                         pos=center + QPoint(0, -80))
        QTest.mouseMove(canvas, center + QPoint(40, -40))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=center + QPoint(40, -40))
        self.assertEqual(wire.points, [(-40, -20), (80, -20)])

    def test_open_switch_reduces_current_and_has_an_explicit_toggle(self) -> None:
        circuit = Circuit()
        circuit.add(Battery(-80, 0, rotation=90, ri=1.0, label="BAT_SWITCH"))
        switch = circuit.add(Switch(0, 0, label="K_TEST"))
        circuit.add_wire([(-80, -20), (-20, -20), (-20, 0)])
        circuit.add_wire([(-80, 20), (20, 20), (20, 0)])
        engine = SimulationEngine(circuit)
        closed_current = abs(engine.recompute().branches[switch.label].i)
        switch.closed = False
        open_current = abs(engine.recompute().branches[switch.label].i)
        self.assertGreater(closed_current, open_current * 100_000)

        window = MainWindow()
        self.addCleanup(window.close)
        window.circuit = circuit
        window.engine = engine
        window.canvas.circuit = circuit
        window.canvas.engine = engine
        window.canvas.set_selection(switch)
        window.refresh_inspector()
        self.assertFalse(window.switch_button.isHidden())
        self.assertIn("Fermer", window.switch_button.text())
        window.toggle_selected_switch()
        self.assertTrue(switch.closed)

        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        center = QPoint(window.canvas.width() // 2, window.canvas.height() // 2)
        QTest.mouseDClick(window.canvas, Qt.MouseButton.LeftButton, pos=center)
        self.assertFalse(switch.closed)

    def test_mesh_basis_and_topology_display_toggles(self) -> None:
        circuit = Circuit()
        circuit.add(Battery(-80, 0, rotation=90, label="BAT_MESH"))
        circuit.add(Resistor(0, 0))
        circuit.add_wire([(-80, -20), (-20, -20), (-20, 0)])
        circuit.add_wire([(-80, 20), (20, 20), (20, 0)])
        self.assertEqual(circuit.mesh_count(), 1)
        window = MainWindow()
        self.addCleanup(window.close)
        window.circuit = circuit
        window.engine = SimulationEngine(circuit)
        window.canvas.circuit = circuit
        window.canvas.engine = window.engine
        window.node_labels_action.setChecked(True)
        window.meshes_action.setChecked(True)
        image = QImage(
            window.canvas.size(), QImage.Format.Format_ARGB32
        )
        window.canvas.render(image)
        self.assertTrue(window.canvas.show_node_labels)
        self.assertTrue(window.canvas.show_meshes)
        window.meshes_action.setChecked(False)
        self.assertFalse(window.canvas.show_meshes)

    def test_ohms_law_calculator_derives_remaining_values(self) -> None:
        dialog = OhmCalculatorDialog()
        dialog.fields["u"].setText("12 V")
        dialog.fields["i"].setText("500 mA")
        dialog.calculate()
        self.assertAlmostEqual(float(dialog.fields["r"].text()), 24)
        self.assertAlmostEqual(float(dialog.fields["p"].text()), 6)

    def test_simulation_dialog_uses_parameter_form_not_script_editor(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.circuit.add(Battery(0, 0, label="BAT_FORM"))
        window.engine.recompute()
        observed = {}

        def inspect_dialog() -> None:
            dialog = next(
                widget for widget in self.app.topLevelWidgets()
                if widget.windowTitle() == "Simulation pas à pas"
            )
            observed["has_script_editor"] = bool(
                dialog.findChildren(QPlainTextEdit)
            )
            table = dialog.findChild(QTableWidget)
            observed["initial_rows"] = table.rowCount()
            add_button = next(
                button for button in dialog.findChildren(QPushButton)
                if button.text() == "Ajouter un changement"
            )
            add_button.click()
            observed["rows_after_add"] = table.rowCount()
            dialog.accept()

        QTimer.singleShot(20, inspect_dialog)
        window.open_scenario_dialog()
        self.assertFalse(observed["has_script_editor"])
        self.assertEqual(observed["initial_rows"], 1)
        self.assertEqual(observed["rows_after_add"], 2)

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
