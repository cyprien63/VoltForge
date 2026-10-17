"""Regression checks for circuit catalog, battery polarity, and editor tools."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer
from PyQt6.QtGui import QIcon, QImage, QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication, QPlainTextEdit, QPushButton, QMessageBox, QScrollArea,
    QTableWidget, QToolBar,
)
from PIL import Image, ImageChops

from core.circuit import Circuit
from core.components import (
    Battery,
    Buzzer,
    Heater,
    Kind,
    Lamp,
    Led,
    Photoresistor,
    PushButton,
    Resistor,
    Speaker,
    Switch,
    Thermistor,
    Wire,
    create_component,
)
from core.simulation import SimulationEngine
from core.voltage_arrow import VoltageArrow
from exporters.gif import export_gif
from ui.main_window import MainWindow, OhmCalculatorDialog, ResistorSizerDialog


class CircuitEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, MainWindow):
                widget.is_dirty = False

    def test_component_catalog_has_one_palette_and_valid_icons(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        self.assertFalse(window.windowIcon().isNull())
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
        self.assertIn((Kind.THERMISTOR, "Thermistance NTC"), window.TOOL_COMPONENTS)
        self.assertIn((Kind.PHOTORESISTOR, "Photorésistance"), window.TOOL_COMPONENTS)
        self.assertIn((Kind.PUSH_BUTTON, "Bouton-poussoir"), window.TOOL_COMPONENTS)
        for icon_name in window.ICONS.values():
            icon = QIcon(str(window._icon_path(icon_name)))
            self.assertFalse(icon.isNull(), icon_name)
        inspector_scroll = window.findChild(QScrollArea, "inspectorScroll")
        self.assertIsNotNone(inspector_scroll)
        self.assertEqual(
            inspector_scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )

        window.set_theme("light")
        light_pixel = window._icon("resistor.svg").pixmap(
            QSize(48, 48)
        ).toImage().pixelColor(13, 24)
        window.set_theme("dark")
        dark_pixel = window._icon("resistor.svg").pixmap(
            QSize(48, 48)
        ).toImage().pixelColor(13, 24)
        self.assertLess(light_pixel.red(), 100)
        self.assertGreater(dark_pixel.red(), 150)

    def test_added_passive_and_output_components_are_constructible_and_simulated(self) -> None:
        thermistor = create_component(Kind.THERMISTOR, 0, 0)
        photoresistor = create_component(Kind.PHOTORESISTOR, 0, 0)
        heater = create_component(Kind.HEATER, 0, 0)
        speaker = create_component(Kind.SPEAKER, 0, 0)
        buzzer = create_component(Kind.BUZZER, 0, 0)
        push_button = create_component(Kind.PUSH_BUTTON, 0, 0)

        self.assertIsInstance(thermistor, Thermistor)
        self.assertIsInstance(photoresistor, Photoresistor)
        self.assertIsInstance(heater, Heater)
        self.assertIsInstance(speaker, Speaker)
        self.assertIsInstance(buzzer, Buzzer)
        self.assertIsInstance(push_button, PushButton)
        self.assertGreater(thermistor.resistance, 0)
        self.assertGreater(photoresistor.resistance, 0)
        cold_resistance = thermistor.resistance
        thermistor.set_prop("temperature", 80)
        self.assertLess(thermistor.resistance, cold_resistance)
        dark_resistance = photoresistor.resistance
        photoresistor.set_prop("illumination", 1000)
        self.assertLess(photoresistor.resistance, dark_resistance)
        self.assertFalse(push_button.closed)
        self.assertAlmostEqual(speaker.resistance, 8.0)

        circuit = Circuit()
        circuit.add(Battery(-80, 0, rotation=90, voltage=9, p_max=100))
        circuit.add(heater)
        circuit.add_wire([(-80, -20), (-20, -20), (-20, 0)])
        circuit.add_wire([(-80, 20), (20, 20), (20, 0)])
        solution = SimulationEngine(circuit).recompute()

        self.assertTrue(solution.solved, solution.errors)
        self.assertIn(heater.label, solution.branches)
        restored = Circuit.from_dict(circuit.to_dict())
        self.assertIsInstance(restored.get(heater.label), Heater)

    def test_all_component_kinds_expose_a_display_value(self) -> None:
        for kind in Kind:
            component = create_component(kind, 0, 0)
            with self.subTest(kind=kind.value):
                self.assertIsInstance(component.display_value(), str)
                component.set_prop("blown", True)
                self.assertIsInstance(component.display_value(), str)
        self.assertIn("V max", create_component(Kind.BUZZER, 0, 0).display_value())

    def test_all_component_kinds_can_be_selected_and_drawn(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        components = [
            window.circuit.add(create_component(kind, 80 * index - 800, 0))
            for index, kind in enumerate(Kind)
        ]
        for component in components:
            self.assertIsInstance(component.display_value(), str, component.kind)
        window.engine.recompute()
        window.refresh_results()
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        image = QImage(window.canvas.size(), QImage.Format.Format_ARGB32)
        window.canvas.render(image)
        for component in components:
            window.canvas.set_selection(component)
            window.refresh_inspector()
            self.assertEqual(window.selection_title.text(),
                             component.short_description())

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

        moved_path = canvas._move_wire_endpoint(
            [(60, 0), (80, 0)], 0, (60, 40)
        )
        self.assertEqual(moved_path, [(60, 40), (80, 40), (80, 0)])
        self.assertTrue(all(
            x1 == x2 or y1 == y2
            for (x1, y1), (x2, y2) in zip(moved_path, moved_path[1:])
        ))

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

    def test_diagonal_component_drag_keeps_attached_wire_orthogonal(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        resistor = window.circuit.add(Resistor(0, 0))
        wire = window.circuit.add_wire([(20, 0), (80, 0)])
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas
        center = QPoint(canvas.width() // 2, canvas.height() // 2)

        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(canvas, center + QPoint(40, 40))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=center + QPoint(40, 40))

        self.assertEqual(resistor.position, (40.0, 40.0))
        self.assertEqual(wire.points, [(60, 40), (80, 40), (80, 0)])
        self.assertTrue(all(
            x1 == x2 or y1 == y2
            for (x1, y1), (x2, y2) in zip(wire.points, wire.points[1:])
        ))

    def test_marquee_select_moves_and_deletes_multiple_elements(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        first = window.circuit.add(Resistor(0, 0, label="R_MULTI1"))
        second = window.circuit.add(Resistor(80, 0, label="R_MULTI2"))
        bridge = window.circuit.add_wire([(20, 0), (60, 0)])
        window.engine.recompute()
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas
        center = QPoint(canvas.width() // 2, canvas.height() // 2)

        QTest.mousePress(canvas, Qt.MouseButton.LeftButton,
                         pos=center + QPoint(-40, -40))
        QTest.mouseMove(canvas, center + QPoint(120, 40))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=center + QPoint(120, 40))
        self.assertEqual(set(canvas.selected_items), {first, second, bridge})

        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(canvas, center + QPoint(40, 0))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=center + QPoint(40, 0))
        self.assertEqual(first.position, (40.0, 0.0))
        self.assertEqual(second.position, (120.0, 0.0))
        self.assertEqual(bridge.points, [(60, 0), (100, 0)])
        self.assertEqual(window.selection_label.text().splitlines()[0],
                         "3 éléments sélectionnés")
        QTest.keyClick(canvas, Qt.Key.Key_Delete)
        self.assertEqual(window.circuit.components, [])

    def test_space_drag_pans_workplane_and_theme_toggle_changes_canvas(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas
        origin = QPoint(round(canvas._origin.x()), round(canvas._origin.y()))
        QTest.keyPress(canvas, Qt.Key.Key_Space)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=origin)
        QTest.mouseMove(canvas, origin + QPoint(60, 30))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=origin + QPoint(60, 30))
        QTest.keyRelease(canvas, Qt.Key.Key_Space)
        self.assertEqual(
            (canvas._origin.x(), canvas._origin.y()),
            (canvas._pan_origin_start.x() + 60,
             canvas._pan_origin_start.y() + 30),
        )

        window.set_theme("light")
        self.assertEqual(canvas.BACKGROUND.name(), "#f7fafc")
        window.set_theme("dark")
        self.assertEqual(canvas.BACKGROUND.name(), "#101820")

    def test_wire_bridging_component_terminals_moves_and_rotates_as_one_route(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        resistor = window.circuit.add(Resistor(0, 0))
        bridge = window.circuit.add_wire([(-20, 0), (20, 0)])
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
        self.assertEqual(bridge.points, [(20, 0), (60, 0)])

        canvas.rotate_component(resistor)
        self.assertEqual(bridge.points, [(40, -20), (40, 20)])
        self.assertTrue(all(
            x1 == x2 or y1 == y2
            for (x1, y1), (x2, y2) in zip(bridge.points, bridge.points[1:])
        ))

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

    def test_node_markers_are_visible_over_components_when_enabled(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.circuit.add(Resistor(0, 0))
        window.circuit.recompute_nodes()
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        window.node_labels_action.setChecked(True)
        canvas = window.canvas
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
        canvas.render(image)
        center_x = round(canvas._origin.x() - 20 * canvas.zoom)
        center_y = round(canvas._origin.y())
        visible_marker = any(
            image.pixelColor(x, y).name() == "#63c9e8"
            for x in range(center_x - 7, center_x + 8)
            for y in range(center_y - 7, center_y + 8)
        )
        self.assertTrue(visible_marker)
        self.assertIn("Nœuds : 2", canvas._topology_counter_text())

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

    def test_voltage_arrow_label_and_side_can_be_dragged_separately(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        arrow = VoltageArrow((-100, 0), (100, 0), label="Uab")
        window.circuit.arrows.append(arrow)
        window.circuit.recompute_nodes()
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas

        def screen_pos(x: float, y: float) -> QPoint:
            return QPoint(round(canvas._origin.x() + x * canvas.zoom),
                          round(canvas._origin.y() + y * canvas.zoom))

        label_rect = canvas._arrow_label_rect(arrow, "Uab")
        label_center = screen_pos(label_rect.center().x(),
                                  label_rect.center().y())
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=label_center)
        QTest.mouseMove(canvas, label_center + QPoint(30, 40))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=label_center + QPoint(30, 40))
        self.assertEqual(arrow.label_offset, (30.0, 20.0))
        self.assertEqual(arrow.offset, 24.0)

        line_pos = screen_pos(0, arrow.offset)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=line_pos)
        QTest.mouseMove(canvas, line_pos + QPoint(0, 20))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=line_pos + QPoint(0, 20))
        self.assertEqual(arrow.offset, 44.0)
        restored = Circuit.from_dict(window.circuit.to_dict()).arrows[0]
        self.assertEqual(restored.offset, 44.0)
        self.assertEqual(restored.label_offset, (30.0, 20.0))

    def test_component_polarity_marks_are_rendered_at_both_terminals(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.circuit.add(Resistor(0, 0))
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32)
        canvas.render(image)

        def count_ink(scene_x: int) -> int:
            left = round(canvas._origin.x() + (scene_x - 7) * canvas.zoom)
            top = round(canvas._origin.y() + 2 * canvas.zoom)
            width = round(14 * canvas.zoom)
            height = round(17 * canvas.zoom)
            background = canvas.BACKGROUND
            return sum(
                image.pixelColor(x, y) != background
                for x in range(left, left + width)
                for y in range(top, top + height)
            )

        self.assertGreater(count_ink(-20), 0)
        self.assertGreater(count_ink(20), 0)

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
        circuit.add(Battery(-80, 0, rotation=90, ri=1.0, p_max=500.0,
                            label="BAT_SWITCH"))
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
        self.assertIn("R = U/I", dialog.result.text())

    def test_simulation_results_show_the_equation_used_for_each_component(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        resistor = window.circuit.add(Resistor(0, 0, resistance=100))
        window.engine.recompute()
        window.refresh_results()

        self.assertIn(
            f"I = U/R = 0/100 A", window.results_text.text()
        )
        self.assertIn("P = U×I", window.results_text.text())

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

    def test_overvoltage_burns_lamp_and_short_circuited_battery(self) -> None:
        circuit = Circuit()
        battery = circuit.add(Battery(-40, 0, voltage=220, ri=0.1))
        lamp = circuit.add(Lamp(40, 0, resistance=50, u_rated=5, p_max=10))
        circuit.add_wire([(-60, 0), (-60, -40), (20, -40), (20, 0)])
        circuit.add_wire([(-20, 0), (-20, 40), (60, 40), (60, 0)])

        solution = SimulationEngine(circuit).recompute()

        self.assertTrue(solution.solved, solution.errors)
        self.assertTrue(lamp.get_prop("blown"))
        self.assertTrue(battery.get_prop("blown"))
        self.assertEqual(solution.branches[lamp.label].state, "blown")
        self.assertEqual(solution.branches[battery.label].state, "blown")
        restored = Circuit.from_dict(circuit.to_dict())
        self.assertTrue(restored.get(lamp.label).get_prop("blown"))

        short_circuit = Circuit()
        battery = short_circuit.add(Battery(0, 0, ri=0.1))
        short_circuit.add_wire([(-20, 0), (20, 0)])
        short_solution = SimulationEngine(short_circuit).recompute()
        self.assertTrue(battery.get_prop("blown"))
        self.assertEqual(short_solution.branches[battery.label].state, "blown")

    def test_overloaded_resistor_burns_from_dissipated_power(self) -> None:
        circuit = Circuit()
        battery = circuit.add(Battery(-40, 0, voltage=12, ri=0.1, p_max=100))
        resistor = circuit.add(Resistor(40, 0, resistance=10, p_max=1))
        circuit.add_wire([(-60, 0), (-60, -40), (20, -40), (20, 0)])
        circuit.add_wire([(-20, 0), (-20, 40), (60, 40), (60, 0)])

        solution = SimulationEngine(circuit).recompute()

        self.assertTrue(solution.solved, solution.errors)
        self.assertTrue(resistor.get_prop("blown"))
        self.assertEqual(solution.branches[resistor.label].state, "blown")

    def test_components_burned_during_transient_remain_burned(self) -> None:
        circuit = Circuit()
        battery = circuit.add(Battery(-40, 0, voltage=9, ri=0.1,
                                     label="BAT_TRANSIENT"))
        lamp = circuit.add(Lamp(40, 0, resistance=50, u_rated=5, p_max=10))
        circuit.add_wire([(-60, 0), (-60, -40), (20, -40), (20, 0)])
        circuit.add_wire([(-20, 0), (-20, 40), (60, 40), (60, 0)])
        engine = SimulationEngine(circuit)
        program = engine.load_program(
            "loop 0s 0.1s\nfps 10\ndt 10ms\n"
            "t=0s: BAT_TRANSIENT.voltage=220V"
        )

        engine.begin_transient(program)
        self.assertTrue(lamp.get_prop("blown"))
        engine.advance(0.1)
        engine.end_transient()

        self.assertEqual(battery.voltage, 9)
        self.assertTrue(lamp.get_prop("blown"))
        self.assertTrue(battery.get_prop("blown"))

    def test_project_is_saved_as_styled_voltforge_archive(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.circuit.add(Resistor(0, 0, label="R_ARCHIVE"))
        window._circuit_changed()
        with TemporaryDirectory() as temp:
            path = Path(temp) / "mon-circuit.voltforge"
            self.assertTrue(window._write_project(path))
            self.assertFalse(window.is_dirty)
            self.assertTrue(zipfile.is_zipfile(path))
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(
                    set(archive.namelist()), {"manifest.txt", "circuit.vfdata"}
                )
                self.assertIn(
                    "VoltForge project",
                    archive.read("manifest.txt").decode("utf-8"),
                )
            with patch(
                "ui.main_window.QFileDialog.getOpenFileName",
                return_value=(str(path), ""),
            ):
                window.open_project()
            self.assertEqual([c.label for c in window.circuit.components],
                             ["R_ARCHIVE"])
            self.assertFalse(window.is_dirty)

    def test_resistor_sizer_recommends_safe_series_resistance(self) -> None:
        dialog = ResistorSizerDialog()
        dialog.source_voltage.setText("12 V")
        dialog.load_voltage.setText("5 V")
        dialog.load_current.setText("300 mA")
        dialog.calculate()
        self.assertIn("23.33 Ω", dialog.result.text())
        self.assertIn("27 Ω", dialog.result.text())
        self.assertIn("5 W", dialog.result.text())
        self.assertIn("R = (12 − 5)/0.3", dialog.result.text())
        self.assertIn("PR =", dialog.result.text())
        dialog.close()

    def test_dirty_close_offers_save_discard_or_cancel(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.is_dirty = True
        with patch(
            "ui.main_window.QMessageBox.exec",
            return_value=QMessageBox.StandardButton.Cancel,
        ):
            self.assertFalse(window.close())
        self.assertTrue(window.is_dirty)
        with patch(
            "ui.main_window.QMessageBox.exec",
            return_value=QMessageBox.StandardButton.Discard,
        ):
            self.assertTrue(window.close())

    def test_repair_button_resets_blown_component(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        lamp = window.circuit.add(Lamp(0, 0, blown=True))
        window.engine.recompute()
        window.canvas.set_selection(lamp)
        window.refresh_inspector()
        self.assertFalse(window.repair_button.isHidden())
        window.repair_button.click()
        self.assertFalse(lamp.get_prop("blown"))
        self.assertTrue(window.repair_button.isHidden())

    def test_selected_lamp_has_live_slider_parameter_controls(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        battery = window.circuit.add(
            Battery(-80, 0, rotation=90, voltage=9, p_max=100)
        )
        lamp = window.circuit.add(Lamp(0, 0))
        window.circuit.add_wire([(-80, -20), (-20, -20), (-20, 0)])
        window.circuit.add_wire([(-80, 20), (20, 20), (20, 0)])
        window.engine.recompute()
        initial_current = window.engine.solution.branches[lamp.label].i

        window.canvas.set_selection(lamp)
        window.refresh_inspector()

        self.assertFalse(window.quick_controls_group.isHidden())
        self.assertEqual(
            set(window._quick_parameter_controls),
            {"resistance", "u_rated", "p_max"},
        )
        resistance_slider, resistance_editor, _, _, _, _ = (
            window._quick_parameter_controls["resistance"]
        )
        resistance_editor.setValue(25)

        self.assertEqual(lamp.resistance, 25)
        self.assertNotEqual(
            window.engine.solution.branches[lamp.label].i, initial_current
        )
        self.assertAlmostEqual(
            window.engine.solution.branches[lamp.label].i,
            abs(window.engine.solution.branches[battery.label].i),
            places=5,
        )
        self.assertTrue(window.is_dirty)
        self.assertIn("I = U/R", window.selection_label.text())
        current_after_numeric_entry = window.engine.solution.branches[lamp.label].i

        resistance_slider.setValue(400)

        self.assertGreater(lamp.resistance, 3)
        self.assertLess(lamp.resistance, 5)
        self.assertNotEqual(
            window.engine.solution.branches[lamp.label].i,
            current_after_numeric_entry,
        )

        window.set_theme("light")
        self.assertIn("#f3f6fb", window.styleSheet())
        window.set_theme("dark")
        self.assertIn("#111a24", window.styleSheet())


class UndoRedoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, MainWindow):
                widget.is_dirty = False

    def test_menu_exposes_annuler_and_retablir_shortcuts(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        self.assertFalse(window.undo_action.isEnabled())
        self.assertFalse(window.redo_action.isEnabled())
        self.assertEqual(window.undo_action.shortcut(),
                         QKeySequence.StandardKey.Undo)
        self.assertEqual(
            [seq.toString() for seq in window.redo_action.shortcuts()],
            ["Ctrl+Y", "Ctrl+Shift+Z"],
        )

    def test_undo_redo_restores_added_component(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.circuit.add(Resistor(0, 0, label="R_UNDO"))
        window._circuit_changed()

        self.assertTrue(window.undo_action.isEnabled())
        self.assertEqual([c.label for c in window.circuit.components], ["R_UNDO"])
        window.undo()
        self.assertEqual(window.circuit.components, [])
        self.assertTrue(window.redo_action.isEnabled())

        window.redo()
        self.assertEqual([c.label for c in window.circuit.components], ["R_UNDO"])

    def test_undo_restores_rotation_and_property_edit(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        resistor = window.circuit.add(
            Resistor(0, 0, resistance=100, label="R_HIST")
        )
        window._circuit_changed()

        window.canvas.rotate_component(resistor)
        self.assertEqual(window.circuit.get("R_HIST").rotation, 90)
        window.undo()
        self.assertEqual(window.circuit.get("R_HIST").rotation, 0)

        component = window.circuit.get("R_HIST")
        component.set_prop("resistance", 220)
        window._circuit_changed()
        window.undo()
        self.assertEqual(window.circuit.get("R_HIST").resistance, 100)

    def test_move_drag_is_recorded_as_a_single_step(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.circuit.add(Resistor(0, 0, label="R_DRAG_HIST"))
        window._circuit_changed()
        window.resize(900, 650)
        window.show()
        self.app.processEvents()
        canvas = window.canvas
        center = QPoint(canvas.width() // 2, canvas.height() // 2)

        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(canvas, center + QPoint(40, 0))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton,
                           pos=center + QPoint(40, 0))
        self.assertEqual(window.circuit.get("R_DRAG_HIST").position, (40.0, 0.0))

        window.undo()
        self.assertEqual(window.circuit.get("R_DRAG_HIST").position, (0.0, 0.0))

    def test_wire_and_deletion_can_be_undone(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.circuit.add(Resistor(0, 0, label="R_WIRE_HIST"))
        window._circuit_changed()
        window.canvas.set_selection(window.circuit.get("R_WIRE_HIST"))
        window.circuit.add_wire([(20, 0), (80, 0)])
        window._circuit_changed()
        self.assertEqual(len(window.circuit.wires), 1)

        window.delete_selected()
        self.assertEqual(window.circuit.components, [])
        self.assertEqual(window.circuit.wires, [])

        window.undo()
        self.assertEqual(
            [c.label for c in window.circuit.components], ["R_WIRE_HIST"]
        )
        self.assertEqual(len(window.circuit.wires), 1)
        window.redo()
        self.assertEqual(window.circuit.components, [])
        self.assertEqual(window.circuit.wires, [])

    def test_undo_redo_is_cleared_on_new_project(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.circuit.add(Resistor(0, 0, label="R_CLEAR"))
        window._circuit_changed()
        self.assertTrue(window.undo_action.isEnabled())

        window.is_dirty = False
        window.new_project()
        self.assertFalse(window.undo_action.isEnabled())
        self.assertFalse(window.redo_action.isEnabled())
        self.assertEqual(window.circuit.components, [])

    def test_toolbar_exposes_undo_redo_buttons(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        toolbar = window.findChild(QToolBar, "mainToolbar")
        actions = {action.text(): action for action in toolbar.actions()}
        self.assertIs(actions["Annuler"], window.undo_action)
        self.assertIs(actions["Rétablir"], window.redo_action)
        self.assertTrue(actions["Annuler"].icon().isNull() is False)

        window.circuit.add(Resistor(0, 0, label="R_BTN"))
        window._circuit_changed()
        self.assertTrue(actions["Annuler"].isEnabled())
        actions["Annuler"].trigger()
        self.assertEqual(window.circuit.components, [])
        self.assertTrue(actions["Rétablir"].isEnabled())
        actions["Rétablir"].trigger()
        self.assertEqual([c.label for c in window.circuit.components], ["R_BTN"])

    def test_voltage_arrow_creation_and_deletion_are_undoable(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        arrow = VoltageArrow((0, 0), (80, 40), circuit=window.circuit)
        window.circuit.arrows.append(arrow)
        window.circuit.recompute_nodes()
        window.canvas.set_selection(arrow)
        window._circuit_changed()
        self.assertEqual(len(window.circuit.arrows), 1)

        window.delete_selected()
        self.assertEqual(window.circuit.arrows, [])
        window.undo()
        self.assertEqual(len(window.circuit.arrows), 1)
        window.redo()
        self.assertEqual(window.circuit.arrows, [])

    def test_quick_parameter_edit_is_undoable(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        lamp = window.circuit.add(Lamp(0, 0, resistance=100, label="L_QUICK"))
        window._circuit_changed()
        window.canvas.set_selection(lamp)
        window.refresh_inspector()
        resistance_editor = window._quick_parameter_controls["resistance"][1]
        resistance_editor.setValue(25)
        window._commit_quick_parameters()

        self.assertEqual(window.circuit.get("L_QUICK").resistance, 25)
        window.undo()
        self.assertEqual(window.circuit.get("L_QUICK").resistance, 100)


if __name__ == "__main__":
    unittest.main()
