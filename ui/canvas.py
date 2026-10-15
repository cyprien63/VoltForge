"""Interactive circuit canvas and shared Qt scene renderer."""

from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QInputDialog, QMenu, QWidget

from core.circuit import Circuit
from core.components import (
    Ammeter,
    Battery,
    Capacitor,
    Component,
    CustomComponent,
    Diode,
    Fuse,
    Generator,
    Ground,
    Inductor,
    Kind,
    Lamp,
    Led,
    Motor,
    Ohmmeter,
    Potentiometer,
    Resistor,
    Switch,
    Voltmeter,
    Wire,
    create_component,
    snap,
)
from core.simulation import SimulationEngine


class CircuitCanvas(QWidget):
    """Grille interactive pour éditer et afficher le circuit."""

    circuitChanged = pyqtSignal()
    selectionChanged = pyqtSignal(object)
    statusMessage = pyqtSignal(str)

    GRID = 20
    BACKGROUND = QColor("#101820")
    GRID_COLOR = QColor("#26343e")
    WIRE_COLOR = QColor("#c6d1d8")
    COMPONENT_COLOR = QColor("#f4f7f8")
    ACCENT = QColor("#44d7b6")

    def __init__(self, circuit: Circuit, engine: SimulationEngine, parent=None):
        super().__init__(parent)
        self.circuit = circuit
        self.engine = engine
        self.setMinimumSize(560, 420)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.mode = "select"
        self.place_kind: Optional[Kind] = None
        self._preview_component: Optional[Component] = None
        self._preview_pos = (0, 0)
        self._preview_rotation = 0
        self.selected: Optional[object] = None
        self._origin = QPointF(0, 0)
        self.zoom = 1.0
        self._panning = False
        self._pan_start = QPointF()
        self._pan_origin_start = QPointF()
        self._drag_offset = QPointF(0, 0)
        self._dragging = False
        self._drag_start = (0, 0)
        self._drag_terminals: dict[str, tuple[int, int]] = {}
        self._drag_wires: list[tuple[Wire, list[tuple[int, int]]]] = []
        self._drag_wire_points: Optional[list[tuple[int, int]]] = None
        self._drag_wire_endpoint: Optional[int] = None
        self._wire_start: Optional[tuple[int, int]] = None
        self._arrow_start: Optional[tuple[int, int]] = None

    def set_mode(self, mode: str, kind: Optional[Kind] = None) -> None:
        self.mode = mode
        self.place_kind = kind
        self._preview_component = (
            create_component(kind, 0, 0, label="__preview__")
            if mode == "place" and kind is not None else None
        )
        self._preview_rotation = 0
        self._wire_start = None
        self._arrow_start = None
        self.setCursor(
            Qt.CursorShape.CrossCursor if mode in ("wire", "voltage", "place")
            else Qt.CursorShape.ArrowCursor
        )
        self.statusMessage.emit({
            "select": "Sélection : glisser pour déplacer ; R tourne ; Delete supprime. "
                      "Molette = zoom, bouton milieu = déplacement de la vue.",
            "wire": "Fil : cliquez sur le début puis la fin de la connexion.",
            "voltage": "Flèche de tension : choisissez les deux nœuds orientés.",
            "place": "Aperçu avant pose — R tourne le composant, cliquez pour le placer.",
        }.get(mode, ""))
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def set_selection(self, item: Optional[object]) -> None:
        self.selected = item
        self.selectionChanged.emit(item)
        self.update()

    def resizeEvent(self, event) -> None:
        if self._origin == QPointF(0, 0):
            self._origin = QPointF(self.width() / 2, self.height() / 2)
        super().resizeEvent(event)

    def scene_pos(self, point: QPointF) -> tuple[int, int]:
        return snap(point.x() - self._origin.x()), snap(point.y() - self._origin.y())

    def scene_float_pos(self, point: QPointF) -> tuple[float, float]:
        return (
            (point.x() - self._origin.x()) / self.zoom,
            (point.y() - self._origin.y()) / self.zoom,
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        self.draw_scene(painter, self.width(), self.height())
        painter.end()

    def draw_scene(self, painter: QPainter, width: int, height: int,
                   draw_grid: bool = True) -> None:
        painter.save()
        painter.fillRect(QRectF(0, 0, width, height), self.BACKGROUND)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self._origin)
        painter.scale(self.zoom, self.zoom)
        if draw_grid:
            self._draw_grid(painter, width, height)
        self._draw_wires(painter)
        for component in self.circuit.components:
            self._draw_component(painter, component)
        self._draw_preview(painter)
        self._draw_arrows(painter)
        if self._wire_start is not None:
            painter.setPen(QPen(self.ACCENT, 2))
            painter.drawEllipse(QPointF(*self._wire_start), 5, 5)
        if self._arrow_start is not None:
            painter.setPen(QPen(QColor("#ffc857"), 2))
            painter.drawEllipse(QPointF(*self._arrow_start), 5, 5)
        painter.restore()

    def _draw_leads(self, painter: QPainter, comp: Component) -> None:
        if isinstance(comp, Ground):
            painter.drawLine(0, -20, 0, -12)
        elif isinstance(comp, Potentiometer):
            painter.drawLine(0, 20, 0, 12)
        elif isinstance(comp, Resistor):
            painter.drawLine(-20, 0, -14, 0)
            painter.drawLine(14, 0, 20, 0)
        else:
            lead_start = 20
            if isinstance(comp, Battery):
                lead_start = 5
            elif isinstance(comp, Generator):
                lead_start = 18
            elif isinstance(comp, Switch):
                lead_start = 16
            elif isinstance(comp, Capacitor):
                lead_start = 5
            elif isinstance(comp, Inductor):
                lead_start = 18
            elif isinstance(comp, (Voltmeter, Ammeter, Ohmmeter, Lamp, Motor)):
                lead_start = 17 if not isinstance(comp, (Lamp, Motor)) else 18
            elif isinstance(comp, (Diode, Led)):
                lead_start = 11
            elif isinstance(comp, Fuse):
                lead_start = 12
            painter.drawLine(-20, 0, -lead_start, 0)
            painter.drawLine(lead_start, 0, 20, 0)

    def _draw_preview(self, painter: QPainter) -> None:
        if self._preview_component is None:
            return
        painter.save()
        painter.setOpacity(0.52)
        painter.translate(*self._preview_pos)
        painter.rotate(self._preview_rotation)
        painter.setPen(QPen(self.ACCENT, 2, Qt.PenStyle.DashLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(self.BACKGROUND)
        self._draw_leads(painter, self._preview_component)
        self._draw_symbol(painter, self._preview_component)
        painter.restore()

    def _draw_grid(self, painter: QPainter, width: int, height: int) -> None:
        painter.save()
        painter.resetTransform()
        painter.setPen(QPen(self.GRID_COLOR, 1))
        step = self.GRID * self.zoom
        left = int((-self._origin.x()) // step) - 1
        right = int((width - self._origin.x()) // step) + 1
        top = int((-self._origin.y()) // step) - 1
        bottom = int((height - self._origin.y()) // step) + 1
        for x in range(left, right + 1):
            for y in range(top, bottom + 1):
                painter.drawPoint(QPointF(self._origin.x() + x * step,
                                          self._origin.y() + y * step))
        painter.restore()

    def _draw_wires(self, painter: QPainter) -> None:
        painter.save()
        for wire in self.circuit.wires:
            color = self.ACCENT if wire is self.selected else self.WIRE_COLOR
            width = 3.2 if wire is self.selected else 2.2
            painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            path = QPainterPath(QPointF(*wire.points[0]))
            for point in wire.points[1:]:
                path.lineTo(QPointF(*point))
            painter.drawPath(path)
            for x, y in wire.points:
                node_id = self.circuit.node_id_at(x, y, radius=2)
                if self.circuit.degree(node_id) >= 3:
                    painter.setBrush(self.WIRE_COLOR)
                    painter.drawEllipse(QPointF(x, y), 3.5, 3.5)
            if wire is self.selected:
                painter.setPen(QPen(self.ACCENT, 1.5))
                painter.setBrush(self.BACKGROUND)
                for point in (wire.points[0], wire.points[-1]):
                    painter.drawEllipse(QPointF(*point), 5, 5)
        painter.restore()

    def _draw_component(self, painter: QPainter, comp: Component) -> None:
        result = self.engine.solution.branches.get(comp.label)
        color = self.COMPONENT_COLOR
        if result and result.state in ("power", "fault", "error"):
            color = QColor("#ff6978" if result.state != "power" else "#ffc857")
        elif result and result.state == "disconnected":
            color = QColor("#9ba8b0")
        if isinstance(comp, Led) and comp.on:
            color = QColor(comp.color_hex)
        painter.save()
        default_font = painter.font()
        painter.translate(comp.x, comp.y)
        painter.rotate(comp.rotation)
        painter.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(self.BACKGROUND)
        self._draw_leads(painter, comp)
        self._draw_symbol(painter, comp)
        painter.setFont(default_font)
        painter.setPen(QPen(color, 1.4))
        painter.drawText(QRectF(-52, 29, 104, 18), Qt.AlignmentFlag.AlignCenter,
                         comp.label)
        value = comp.display_value()
        if value:
            painter.setPen(QPen(QColor("#aabac4"), 1))
            painter.drawText(QRectF(-66, -43, 132, 16), Qt.AlignmentFlag.AlignCenter,
                             value)
        if self.selected is comp:
            painter.setPen(QPen(self.ACCENT, 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(-48, -31, 96, 68), 8, 8)
        if result and abs(result.i) > 1e-6:
            self._draw_current(painter, comp, result.i)
        painter.restore()

    def _draw_symbol(self, painter: QPainter, comp: Component) -> None:
        if isinstance(comp, Battery):
            painter.drawLine(-5, -14, -5, 14)
            painter.drawLine(5, -9, 5, 9)
            painter.drawLine(-16, -14, -12, -14)
            painter.drawLine(-14, -16, -14, -12)
            painter.drawLine(12, 14, 16, 14)
        elif isinstance(comp, Generator):
            painter.drawEllipse(QRectF(-18, -18, 36, 36))
            font = painter.font()
            font.setBold(True)
            font.setPointSizeF(12)
            painter.setFont(font)
            painter.drawText(QRectF(-14, -13, 28, 26),
                             Qt.AlignmentFlag.AlignCenter, "G")
        elif isinstance(comp, Resistor):
            painter.drawRect(QRectF(-14, -8, 28, 16))
            if isinstance(comp, CustomComponent):
                font = painter.font()
                font.setBold(True)
                font.setPointSizeF(10)
                painter.setFont(font)
                painter.drawText(QRectF(-13, -7, 26, 14),
                                 Qt.AlignmentFlag.AlignCenter, comp.symbol[:4])
        elif isinstance(comp, Potentiometer):
            painter.drawRect(QRectF(-14, -8, 28, 16))
            level_x = round(-15 + 30 * comp.level)
            painter.drawLine(0, 12, level_x, -11)
            painter.drawLine(level_x, -11, level_x - 5, -5)
            painter.drawLine(level_x, -11, level_x + 2, -4)
        elif isinstance(comp, Switch):
            painter.drawEllipse(QPointF(-16, 0), 2.4, 2.4)
            painter.drawEllipse(QPointF(16, 0), 2.4, 2.4)
            painter.drawLine(-14, 0, 12 if comp.closed else 7, 0 if comp.closed else -11)
        elif isinstance(comp, Capacitor):
            painter.drawLine(-5, -15, -5, 15)
            painter.drawLine(5, -15, 5, 15)
        elif isinstance(comp, Inductor):
            for index in range(4):
                painter.drawArc(QRectF(-18 + index * 9, -8, 10, 16), 0, 180 * 16)
        elif isinstance(comp, (Diode, Led)):
            path = QPainterPath(QPointF(-10, -11))
            path.lineTo(6, 0)
            path.lineTo(-10, 11)
            path.closeSubpath()
            if isinstance(comp, Led) and comp.on:
                painter.setBrush(QColor(comp.color_hex))
                painter.setOpacity(0.35)
                painter.drawEllipse(QRectF(-15, -17, 34, 34))
                painter.setOpacity(1)
            painter.drawPath(path)
            painter.drawLine(8, -12, 8, 12)
            if isinstance(comp, Led):
                painter.drawLine(0, -14, 8, -22)
                painter.drawLine(5, -17, 8, -22)
                painter.drawLine(8, -22, 3, -21)
                painter.drawLine(5, -7, 13, -15)
                painter.drawLine(10, -10, 13, -15)
                painter.drawLine(13, -15, 8, -14)
        elif isinstance(comp, Lamp):
            painter.drawEllipse(QRectF(-18, -18, 36, 36))
            if self.engine.solution.branches.get(comp.label):
                branch = self.engine.solution.branches[comp.label]
                p_max = float(comp.get_prop("p_max") or 0.0)
                glow = min(0.8, abs(branch.p) / max(p_max, 1e-9))
                if glow > 0:
                    painter.setOpacity(glow)
                    painter.setBrush(QColor("#ffc857"))
                    painter.drawEllipse(QRectF(-14, -14, 28, 28))
                    painter.setOpacity(1)
            painter.drawLine(-7, -7, 7, 7)
            painter.drawLine(-7, 7, 7, -7)
        elif isinstance(comp, Motor):
            painter.drawEllipse(QRectF(-18, -18, 36, 36))
            font = painter.font()
            font.setBold(True)
            font.setPointSizeF(17)
            painter.setFont(font)
            painter.drawText(QRectF(-14, -12, 28, 24),
                             Qt.AlignmentFlag.AlignCenter, "M")
        elif isinstance(comp, Fuse):
            painter.drawRoundedRect(QRectF(-12, -10, 24, 20), 3, 3)
            if not comp.blown:
                painter.drawLine(-8, 0, -3, -5)
                painter.drawLine(-3, -5, 3, 5)
                painter.drawLine(3, 5, 8, 0)
        elif isinstance(comp, Ground):
            painter.drawLine(-12, -12, 12, -12)
            painter.drawLine(-8, -7, 8, -7)
            painter.drawLine(-4, -2, 4, -2)
        elif isinstance(comp, (Voltmeter, Ammeter, Ohmmeter)):
            painter.drawEllipse(QRectF(-17, -17, 34, 34))
            symbol = (
                "V" if isinstance(comp, Voltmeter) else
                "A" if isinstance(comp, Ammeter) else "Ω"
            )
            font = painter.font()
            font.setBold(True)
            font.setPointSizeF(19 if symbol != "Ω" else 15)
            painter.setFont(font)
            painter.drawText(QRectF(-13, -12, 26, 24),
                             Qt.AlignmentFlag.AlignCenter, symbol)

    def _draw_current(self, painter: QPainter, comp: Component, current: float) -> None:
        direction = 1 if current >= 0 else -1
        x1, x2 = (-13, 13) if direction > 0 else (13, -13)
        y = -25
        painter.setPen(QPen(QColor("#44d7b6"), 1.5))
        painter.drawLine(x1, y, x2, y)
        painter.drawLine(x2, y, x2 - 5 * direction, y - 4)
        painter.drawLine(x2, y, x2 - 5 * direction, y + 4)

    def _draw_arrows(self, painter: QPainter) -> None:
        painter.save()
        painter.setPen(QPen(QColor("#ffc857"), 1.8))
        for arrow in self.circuit.arrows:
            x1, y1 = arrow.start
            x2, y2 = arrow.end
            painter.drawLine(x1, y1, x2, y2)
            angle = math.atan2(y2 - y1, x2 - x1)
            for offset in (2.55, -2.55):
                painter.drawLine(
                    x2, y2,
                    x2 + 9 * math.cos(angle + offset),
                    y2 + 9 * math.sin(angle + offset),
                )
            painter.setPen(QPen(QColor("#ffe0a3"), 1))
            painter.drawText(QPointF((x1 + x2) / 2 + 6, (y1 + y2) / 2 - 7),
                             arrow.text(self.engine.solution))
            painter.setPen(QPen(QColor("#ffc857"), 1.8))
        painter.restore()

    def _item_at(self, x: int, y: int):
        for comp in reversed(self.circuit.components):
            dx, dy = x - comp.x, y - comp.y
            angle = math.radians(-comp.rotation)
            local_x = dx * math.cos(angle) - dy * math.sin(angle)
            local_y = dx * math.sin(angle) + dy * math.cos(angle)
            if abs(local_x) <= 27 and abs(local_y) <= 24:
                return comp
        for wire in reversed(self.circuit.wires):
            for a, b in zip(wire.points, wire.points[1:]):
                if self._distance_to_segment(x, y, a, b) <= 12 / self.zoom:
                    return wire
        return None

    @staticmethod
    def _distance_to_segment(x, y, a, b) -> float:
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if not length_sq:
            return math.hypot(x - ax, y - ay)
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length_sq))
        return math.hypot(x - ax - t * dx, y - ay - t * dy)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self._pan_origin_start = QPointF(self._origin)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._wire_start = None
            self._arrow_start = None
            if self.mode == "select":
                x, y = self.scene_float_pos(event.position())
                item = self._item_at(x, y)
                if item is not None:
                    self.set_selection(item)
                    menu = QMenu(self)
                    delete_action = menu.addAction("Supprimer")
                    if menu.exec(event.globalPosition().toPoint()) is delete_action:
                        self._delete_selected()
            self.update()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        raw_x, raw_y = self.scene_float_pos(event.position())
        x, y = snap(raw_x), snap(raw_y)
        if self.mode == "place" and self.place_kind is not None:
            component = create_component(
                self.place_kind, x, y, rotation=self._preview_rotation
            )
            self.circuit.add(component)
            self.engine.recompute()
            self.circuitChanged.emit()
            return
        if self.mode == "wire":
            if self._wire_start is None:
                self._wire_start = self._nearest_node(x, y)
            else:
                end = self._nearest_node(x, y)
                start = self._wire_start
                self._wire_start = None
                if start != end:
                    points = [start, (end[0], start[1]), end]
                    self.circuit.add_wire(points)
                    self.engine.recompute()
                    self.circuitChanged.emit()
            self.update()
            return
        if self.mode == "voltage":
            if self._arrow_start is None:
                self._arrow_start = self._nearest_node(x, y)
            else:
                start = self._arrow_start
                end = self._nearest_node(x, y)
                self._arrow_start = None
                if start != end:
                    from core.voltage_arrow import VoltageArrow
                    arrow = VoltageArrow(start, end, circuit=self.circuit)
                    label, accepted = QInputDialog.getText(
                        self, "Annotation de tension", "Nom de la tension :",
                        text=arrow.label,
                    )
                    if accepted and label.strip():
                        arrow.label = label.strip()
                    self.circuit.arrows.append(arrow)
                    self.circuit.recompute_nodes()
                    self.circuitChanged.emit()
            self.update()
            return
        item = self._item_at(raw_x, raw_y)
        self.set_selection(item)
        if isinstance(item, Component):
            self._dragging = True
            self._drag_offset = QPointF(x - item.x, y - item.y)
            self._drag_start = (x, y)
            self._drag_terminals = {
                name: (snap(tx), snap(ty))
                for name, (tx, ty) in item.terminal_positions().items()
            }
            terminal_points = set(self._drag_terminals.values())
            self._drag_wires = [
                (wire, list(wire.points))
                for wire in self.circuit.wires
                if any(point in terminal_points for point in wire.points)
            ]
        elif isinstance(item, Wire):
            self._dragging = True
            self._drag_start = (x, y)
            self._drag_wire_points = list(item.points)
            endpoint_radius = 16 / self.zoom
            if math.hypot(raw_x - item.points[0][0],
                          raw_y - item.points[0][1]) <= endpoint_radius:
                self._drag_wire_endpoint = 0
            elif math.hypot(raw_x - item.points[-1][0],
                            raw_y - item.points[-1][1]) <= endpoint_radius:
                self._drag_wire_endpoint = len(item.points) - 1

    def _nearest_node(self, x: int, y: int) -> tuple[int, int]:
        node_id = self.circuit.node_id_at(x, y, radius=18)
        if node_id is not None:
            node = self.circuit.nodes[node_id]
            return node.x, node.y
        return x, y

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.position() - self._pan_start
            self._origin = self._pan_origin_start + delta
            self.update()
            return
        if self._dragging and isinstance(self.selected, Component):
            x, y = self.scene_pos(event.position())
            self.selected.move_to(x - self._drag_offset.x(),
                                  y - self._drag_offset.y())
            moved_terminals = {
                name: (snap(tx), snap(ty))
                for name, (tx, ty) in self.selected.terminal_positions().items()
            }
            moved_by_terminal = {
                self._drag_terminals[name]: moved_terminals[name]
                for name in self._drag_terminals
            }
            for wire, original_points in self._drag_wires:
                wire.points = [
                    moved_by_terminal.get(point, point) for point in original_points
                ]
                wire.points = self._orthogonalize(wire.points)
            self.circuit.recompute_nodes()
            self.update()
        elif self._dragging and isinstance(self.selected, Wire) and \
                self._drag_wire_points is not None:
            raw_x, raw_y = self.scene_float_pos(event.position())
            if self._drag_wire_endpoint is not None:
                points = list(self._drag_wire_points)
                index = self._drag_wire_endpoint
                adjacent = points[1] if index == 0 else points[-2]
                original = points[index]
                if adjacent[0] == original[0]:
                    point = (adjacent[0], snap(raw_y))
                else:
                    point = (snap(raw_x), adjacent[1])
                points[index] = point
                self.selected.points = points
            else:
                x, y = snap(raw_x), snap(raw_y)
                dx, dy = x - self._drag_start[0], y - self._drag_start[1]
                self.selected.points = [
                    (px + dx, py + dy) for px, py in self._drag_wire_points
                ]
            self.circuit.recompute_nodes()
            self.update()
        elif self.mode == "place":
            self._preview_pos = self.scene_pos(event.position())
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(
                Qt.CursorShape.CrossCursor
                if self.mode in ("wire", "voltage", "place")
                else Qt.CursorShape.ArrowCursor
            )
            return
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.engine.recompute()
            self.circuitChanged.emit()
            self._drag_wires = []
            self._drag_terminals = {}
            self._drag_wire_points = None
            self._drag_wire_endpoint = None

    def wheelEvent(self, event) -> None:
        old_zoom = self.zoom
        new_zoom = max(0.35, min(3.5, old_zoom * 1.15 ** (event.angleDelta().y() / 120)))
        if new_zoom == old_zoom:
            return
        cursor = event.position()
        scene_x, scene_y = self.scene_float_pos(cursor)
        self.zoom = new_zoom
        self._origin = QPointF(
            cursor.x() - scene_x * new_zoom,
            cursor.y() - scene_y * new_zoom,
        )
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        x, y = self.scene_float_pos(event.position())
        item = self._item_at(x, y)
        if isinstance(item, Switch):
            item.closed = not item.closed
            self.engine.recompute()
            self.circuitChanged.emit()
        elif isinstance(item, Component):
            self.set_selection(item)
            self.statusMessage.emit(f"Composant sélectionné : {item.label}")

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected:
            self._delete_selected()
        elif event.key() == Qt.Key.Key_R and self.mode == "place":
            self._preview_rotation = (self._preview_rotation + 90) % 360
            self.update()
        elif event.key() == Qt.Key.Key_R and isinstance(self.selected, Component):
            self.rotate_component(self.selected)
        else:
            super().keyPressEvent(event)

    def rotate_preview(self) -> None:
        if self._preview_component is not None:
            self._preview_rotation = (self._preview_rotation + 90) % 360
            self.update()

    def _delete_selected(self) -> None:
        if self.selected is None:
            return
        self.circuit.remove(getattr(self.selected, "label", ""))
        self.set_selection(None)
        self.engine.recompute()
        self.circuitChanged.emit()

    def rotate_component(self, component: Component, delta: int = 90) -> None:
        old_terminals = {
            name: (snap(tx), snap(ty))
            for name, (tx, ty) in component.terminal_positions().items()
        }
        terminal_points = set(old_terminals.values())
        attached_wires = [
            (wire, list(wire.points))
            for wire in self.circuit.wires
            if any(point in terminal_points for point in wire.points)
        ]
        component.rotate(delta)
        new_terminals = {
            name: (snap(tx), snap(ty))
            for name, (tx, ty) in component.terminal_positions().items()
        }
        moved_by_terminal = {
            old_terminals[name]: new_terminals[name] for name in old_terminals
        }
        for wire, points in attached_wires:
            wire.points = self._orthogonalize(
                [moved_by_terminal.get(point, point) for point in points]
            )
        self.circuit.recompute_nodes()
        self.engine.recompute()
        self.circuitChanged.emit()
        self.update()

    @staticmethod
    def _orthogonalize(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if not points:
            return []
        result = [points[0]]
        for point in points[1:]:
            previous = result[-1]
            if previous[0] != point[0] and previous[1] != point[1]:
                result.append((point[0], previous[1]))
            if result[-1] != point:
                result.append(point)
        return result
