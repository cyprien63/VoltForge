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
    rotate_offset,
    snap,
)
from core.simulation import SimulationEngine
from core.voltage_arrow import VoltageArrow


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
        self.selected_items: list[object] = []
        self._origin = QPointF(0, 0)
        self._view_touched = False
        self.zoom = 1.0
        self._panning = False
        self._space_down = False
        self._pan_start = QPointF()
        self._pan_origin_start = QPointF()
        self._drag_offset = QPointF(0, 0)
        self._dragging = False
        self._drag_moved = False
        self._drag_start = (0, 0)
        self._drag_component_origin: Optional[tuple[float, float]] = None
        self._drag_terminals: dict[str, tuple[int, int]] = {}
        self._drag_wires: list[tuple[Wire, list[tuple[int, int]]]] = []
        self._drag_wire_points: Optional[list[tuple[int, int]]] = None
        self._drag_wire_endpoint: Optional[int] = None
        self._drag_arrow_part: Optional[str] = None
        self._drag_arrow_start_scene = (0.0, 0.0)
        self._drag_arrow_start_offset = 0.0
        self._drag_arrow_start_label_offset = (0.0, 0.0)
        self._marquee_start: Optional[QPointF] = None
        self._marquee_end: Optional[QPointF] = None
        self._group_drag_start: Optional[tuple[float, float]] = None
        self._group_component_origins: dict[Component, tuple[float, float]] = {}
        self._group_wire_origins: dict[Wire, list[tuple[int, int]]] = {}
        self._group_arrow_origins: dict[
            VoltageArrow, tuple[tuple[int, int], tuple[int, int]]
        ] = {}
        self.theme = "dark"
        self._wire_start: Optional[tuple[int, int]] = None
        self._wire_preview_end: Optional[tuple[int, int]] = None
        self._wire_snap_target: Optional[tuple[int, int]] = None
        self._arrow_start: Optional[tuple[int, int]] = None
        self._arrow_preview_end: Optional[tuple[int, int]] = None
        self.show_node_labels = False
        self.show_meshes = False

    def set_mode(self, mode: str, kind: Optional[Kind] = None) -> None:
        self.mode = mode
        self.place_kind = kind
        self._preview_component = (
            create_component(kind, 0, 0, label="__preview__")
            if mode == "place" and kind is not None else None
        )
        self._preview_rotation = 0
        self._wire_start = None
        self._wire_preview_end = None
        self._wire_snap_target = None
        self._arrow_start = None
        self._arrow_preview_end = None
        self.setCursor(
            Qt.CursorShape.CrossCursor if mode in ("wire", "voltage", "place")
            else Qt.CursorShape.ArrowCursor
        )
        self.statusMessage.emit({
            "select": "Sélection : glissez sur le vide pour sélectionner plusieurs éléments "
                      "(Ctrl+A = tout) ; glissez la sélection pour la déplacer. "
                      "Espace + glisser ou bouton milieu = déplacer la vue.",
            "wire": "Fil continu : cliquez les points du trajet ; le cercle vert indique l'accrochage. Clic droit ou Échap termine.",
            "voltage": "Flèche U : cliquez deux bornes ou nœuds ; l'aperçu jaune montre le sens avant validation.",
            "place": "Aperçu avant pose — R tourne le composant, cliquez pour le placer.",
        }.get(mode, ""))
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def set_selection(self, item: Optional[object]) -> None:
        self.selected = item
        self.selected_items = [item] if item is not None else []
        self.selectionChanged.emit(item)
        self.update()

    def set_selections(self, items: list[object]) -> None:
        unique = list(dict.fromkeys(items))
        self.selected_items = unique
        self.selected = unique[-1] if unique else None
        self.selectionChanged.emit(
            unique if len(unique) > 1 else (unique[0] if unique else None)
        )
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        if theme == "light":
            self.BACKGROUND = QColor("#f7fafc")
            self.GRID_COLOR = QColor("#d7e0e8")
            self.WIRE_COLOR = QColor("#374957")
            self.COMPONENT_COLOR = QColor("#172b3a")
            self.ACCENT = QColor("#00836f")
        else:
            self.BACKGROUND = QColor("#101820")
            self.GRID_COLOR = QColor("#26343e")
            self.WIRE_COLOR = QColor("#c6d1d8")
            self.COMPONENT_COLOR = QColor("#f4f7f8")
            self.ACCENT = QColor("#44d7b6")
        self.update()

    def resizeEvent(self, event) -> None:
        if not self._view_touched:
            self._origin = QPointF(self.width() / 2, self.height() / 2)
        super().resizeEvent(event)

    def scene_pos(self, point: QPointF) -> tuple[int, int]:
        x, y = self.scene_float_pos(point)
        return snap(x), snap(y)

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
        if self.show_meshes:
            self._draw_topology(painter)
        for component in self.circuit.components:
            self._draw_component(painter, component)
        if self.show_meshes:
            self._draw_mesh_badges(painter)
        if self.show_node_labels:
            self._draw_node_labels(painter)
        self._draw_preview(painter)
        self._draw_arrows(painter)
        if self._wire_start is not None:
            painter.setPen(QPen(self.ACCENT, 2))
            painter.drawEllipse(QPointF(*self._wire_start), 5, 5)
            if self.mode == "wire" and self._wire_preview_end is not None:
                painter.setPen(QPen(self.ACCENT, 1.6, Qt.PenStyle.DashLine))
                preview = self._orthogonalize([
                    self._wire_start,
                    (self._wire_preview_end[0], self._wire_start[1]),
                    self._wire_preview_end,
                ])
                path = QPainterPath(QPointF(*preview[0]))
                for point in preview[1:]:
                    path.lineTo(QPointF(*point))
                painter.drawPath(path)
        if self.mode == "wire" and self._wire_snap_target is not None:
            painter.setPen(QPen(QColor("#7CFF6B"), 2.2))
            painter.setBrush(QColor(124, 255, 107, 70))
            painter.drawEllipse(QPointF(*self._wire_snap_target), 8, 8)
        if self._arrow_start is not None:
            painter.setPen(QPen(QColor("#ffc857"), 2))
            painter.drawEllipse(QPointF(*self._arrow_start), 5, 5)
            if self._arrow_preview_end is not None:
                self._draw_voltage_arrow(
                    painter, self._arrow_start, self._arrow_preview_end,
                    "Uab", QColor("#ffc857"), dashed=True,
                )
        if self._marquee_start is not None and self._marquee_end is not None:
            start = QPointF(
                self._origin.x() + self._marquee_start.x() * self.zoom,
                self._origin.y() + self._marquee_start.y() * self.zoom,
            )
            end = QPointF(
                self._origin.x() + self._marquee_end.x() * self.zoom,
                self._origin.y() + self._marquee_end.y() * self.zoom,
            )
            rect = QRectF(start, end).normalized()
            painter.resetTransform()
            painter.setPen(QPen(self.ACCENT, 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(self.ACCENT.red(), self.ACCENT.green(),
                                    self.ACCENT.blue(), 36))
            painter.drawRect(rect)
        self._draw_topology_counter(painter, width)
        painter.restore()

    def _draw_topology(self, painter: QPainter) -> None:
        painter.save()
        if self.show_meshes:
            colors = self._mesh_colors()
            meshes = self.circuit.meshes()
            for mesh_index, mesh in enumerate(meshes):
                color = colors[mesh_index % len(colors)]
                mesh_nodes = {
                    node_id
                    for component in mesh
                    for node_id in (component.node_p, component.node_n)
                    if node_id is not None
                }
                painter.setPen(QPen(color, 3.6, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap,
                                    Qt.PenJoinStyle.RoundJoin))
                for wire in self.circuit.wires:
                    endpoint_nodes = {
                        self.circuit.node_id_at(*point, radius=2)
                        for point in wire.endpoints()
                    }
                    if endpoint_nodes & mesh_nodes:
                        path = QPainterPath(QPointF(*wire.points[0]))
                        for point in wire.points[1:]:
                            path.lineTo(QPointF(*point))
                        painter.drawPath(path)
        painter.restore()

    def _draw_node_labels(self, painter: QPainter) -> None:
        painter.save()
        painter.setFont(self.font())
        for node in self.circuit.nodes.values():
            painter.setPen(QPen(self.BACKGROUND, 1))
            painter.setBrush(QColor("#63c9e8"))
            painter.drawEllipse(QPointF(node.x, node.y), 5.5, 5.5)
            label_rect = QRectF(node.x + 7, node.y - 18, 38, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.BACKGROUND)
            painter.drawRoundedRect(label_rect.adjusted(-2, -1, 2, 1), 3, 3)
            painter.setPen(QPen(self.COMPONENT_COLOR, 1))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft |
                             Qt.AlignmentFlag.AlignVCenter, node.name)
        painter.restore()

    def _draw_topology_counter(self, painter: QPainter, width: int) -> None:
        text = self._topology_counter_text()
        painter.save()
        painter.resetTransform()
        painter.setFont(self.font())
        rect = QRectF(12, 12, min(width - 24, 260), 30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.BACKGROUND.red(), self.BACKGROUND.green(),
                                self.BACKGROUND.blue(), 225))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(QPen(self.COMPONENT_COLOR, 1))
        painter.drawText(rect.adjusted(9, 0, -6, 0),
                         Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()

    def _topology_counter_text(self) -> str:
        return (
            f"Nœuds : {len(self.circuit.nodes)}   ·   "
            f"Mailles : {self.circuit.mesh_count()}"
        )

    @staticmethod
    def _mesh_colors() -> tuple[QColor, ...]:
        return (
            QColor("#ff6b6b"), QColor("#4dabf7"), QColor("#69db7c"),
            QColor("#ffd43b"), QColor("#da77f2"), QColor("#ffa94d"),
        )

    def _draw_mesh_badges(self, painter: QPainter) -> None:
        meshes = self.circuit.meshes()
        colors = self._mesh_colors()
        painter.save()
        for mesh_index, mesh in enumerate(meshes):
            color = colors[mesh_index % len(colors)]
            for component_index, component in enumerate(mesh):
                painter.setPen(QPen(color, 1.7, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(component.x, component.y), 25, 23)
                if component_index == 0:
                    painter.setPen(QPen(color, 1))
                    painter.drawText(QPointF(component.x + 22, component.y - 20),
                                     f"M{mesh_index + 1}")
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
            selected = wire in self.selected_items
            color = self.ACCENT if selected else self.WIRE_COLOR
            width = 3.2 if selected else 2.2
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
            if selected:
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
        elif comp.get_prop("blown"):
            color = QColor("#ff6978")
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
        if comp.get_prop("blown"):
            painter.setPen(QPen(QColor("#ff6978"), 2.5))
            painter.drawLine(-8, -8, 8, 8)
            painter.drawLine(-8, 8, 8, -8)
        painter.setFont(default_font)
        painter.setPen(QPen(color, 1.4))
        painter.drawText(QRectF(-52, 29, 104, 18), Qt.AlignmentFlag.AlignCenter,
                         comp.label)
        value = comp.display_value()
        if value:
            painter.setPen(QPen(QColor("#aabac4"), 1))
            painter.drawText(QRectF(-66, -43, 132, 16), Qt.AlignmentFlag.AlignCenter,
                             value)
        if comp in self.selected_items:
            painter.setPen(QPen(self.ACCENT, 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(-48, -31, 96, 68), 8, 8)
        if result and abs(result.i) > 1e-6:
            self._draw_current(painter, comp, result.i)
        painter.restore()

    @staticmethod
    def _draw_polarities(painter: QPainter, comp: Component,
                         color: QColor) -> None:
        if isinstance(comp, Battery):
            return
        terminals = comp.TERMINAL_OFFSETS
        if "p" not in terminals or "n" not in terminals:
            return
        painter.save()
        font = painter.font()
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(QPen(color, 1))
        for name, mark in (("p", "+"), ("n", "−")):
            x, y = terminals[name]
            painter.drawText(QRectF(x - 6, y + 3, 12, 13),
                             Qt.AlignmentFlag.AlignCenter, mark)
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
        self._draw_polarities(painter, comp, self.COMPONENT_COLOR)

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
        for arrow in self.circuit.arrows:
            color = self.ACCENT if arrow is self.selected else QColor("#ffc857")
            self._draw_voltage_arrow(
                painter, arrow.start, arrow.end,
                arrow.text(self.engine.solution), color,
                offset=arrow.offset, label_offset=arrow.label_offset,
            )
        painter.restore()

    @staticmethod
    def _arrow_line(start: tuple[float, float], end: tuple[float, float],
                    offset: float) -> tuple[tuple[float, float],
                                            tuple[float, float],
                                            tuple[float, float]]:
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 1:
            return start, end, (0.0, 0.0)
        normal = (-dy / length, dx / length)
        shift = (normal[0] * offset, normal[1] * offset)
        return (
            (start[0] + shift[0], start[1] + shift[1]),
            (end[0] + shift[0], end[1] + shift[1]),
            normal,
        )

    @staticmethod
    def _arrow_label_rect(arrow: VoltageArrow, label: str) -> QRectF:
        first, last, _ = CircuitCanvas._arrow_line(
            arrow.start, arrow.end, arrow.offset
        )
        text_width = max(58.0, min(190.0, len(label) * 8.5))
        center_x = (first[0] + last[0]) / 2 + arrow.label_offset[0]
        center_y = (first[1] + last[1]) / 2 + arrow.label_offset[1]
        return QRectF(center_x - text_width / 2, center_y - 9,
                      text_width, 18)

    @staticmethod
    def _draw_voltage_arrow(
        painter: QPainter,
        start: tuple[float, float],
        end: tuple[float, float],
        label: str,
        color: QColor,
        dashed: bool = False,
        offset: float = 24.0,
        label_offset: tuple[float, float] = (0.0, -20.0),
    ) -> None:
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 1:
            return
        ux, uy = dx / length, dy / length
        first, last, _ = CircuitCanvas._arrow_line(start, end, offset)
        style = Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine
        painter.save()
        painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 170),
                            1.4, Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(*start), QPointF(*first))
        painter.drawLine(QPointF(*end), QPointF(*last))
        painter.setPen(QPen(color, 2.5 if not dashed else 1.8, style,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPointF(*first), QPointF(*last))
        angle = math.atan2(uy, ux)
        for wing in (2.55, -2.55):
            painter.drawLine(
                QPointF(*last),
                QPointF(
                    last[0] - 10 * math.cos(angle + wing),
                    last[1] - 10 * math.sin(angle + wing),
                ),
            )
        text_width = max(58.0, min(190.0, len(label) * 8.5))
        text_center_x = (first[0] + last[0]) / 2 + label_offset[0]
        text_center_y = (first[1] + last[1]) / 2 + label_offset[1]
        text_rect = QRectF(
            text_center_x - text_width / 2,
            text_center_y - 9,
            text_width,
            18,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#101820"))
        painter.drawRoundedRect(text_rect.adjusted(-3, -2, 3, 2), 3, 3)
        painter.setPen(QPen(QColor("#fff2cc"), 1.2))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def _item_at(self, x: int, y: int):
        for arrow in reversed(self.circuit.arrows):
            label = arrow.text(self.engine.solution)
            if self._arrow_label_rect(arrow, label).contains(QPointF(x, y)):
                return arrow
            first, last, _ = self._arrow_line(
                arrow.start, arrow.end, arrow.offset
            )
            if self._distance_to_segment(x, y, first, last) <= 12 / self.zoom:
                return arrow
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
        if event.button() == Qt.MouseButton.LeftButton and self._space_down:
            self._panning = True
            self._view_touched = True
            self._pan_start = event.position()
            self._pan_origin_start = QPointF(self._origin)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._view_touched = True
            self._pan_start = event.position()
            self._pan_origin_start = QPointF(self._origin)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() == Qt.MouseButton.RightButton:
            if self.mode == "select":
                x, y = self.scene_float_pos(event.position())
                node_id = self.circuit.node_id_at(x, y, radius=12 / self.zoom)
                item = self._item_at(x, y)
                if item is not None or node_id is not None:
                    self.set_selection(item)
                    menu = QMenu(self)
                    rename_action = None
                    if node_id is not None:
                        rename_action = menu.addAction(
                            f"Renommer le nœud {self.circuit.nodes[node_id].name}…"
                        )
                        menu.addSeparator()
                    delete_action = (
                        menu.addAction("Supprimer") if item is not None else None
                    )
                    chosen = menu.exec(event.globalPosition().toPoint())
                    if delete_action is not None and chosen is delete_action:
                        self._delete_selected()
                    elif chosen is rename_action and node_id is not None:
                        node = self.circuit.nodes[node_id]
                        name, accepted = QInputDialog.getText(
                            self, "Renommer le nœud", "Nom du nœud :",
                            text=node.name,
                        )
                        if accepted and name.strip():
                            self.circuit.rename_node(node_id, name)
                            self.circuit.recompute_nodes()
                            self.circuitChanged.emit()
                            self.update()
            elif self.mode == "wire":
                self._wire_start = None
                self._wire_preview_end = None
                self._wire_snap_target = None
            elif self.mode == "voltage":
                self._arrow_start = None
                self._arrow_preview_end = None
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
            snap_target = self._snap_target(raw_x, raw_y)
            if self._wire_start is None:
                self._wire_start = snap_target or (x, y)
                self._wire_preview_end = self._wire_start
                self._wire_snap_target = snap_target
            else:
                end = snap_target or (x, y)
                start = self._wire_start
                if start != end:
                    self.circuit.add_wire(self._orthogonalize(
                        [start, (end[0], start[1]), end]
                    ))
                    self._wire_start = end
                    self._wire_preview_end = end
                    self._wire_snap_target = snap_target
                    self.engine.recompute()
                    self.circuitChanged.emit()
            self.update()
            return
        if self.mode == "voltage":
            if self._arrow_start is None:
                self._arrow_start = self._snap_target(raw_x, raw_y) or (x, y)
                self._arrow_preview_end = self._arrow_start
            else:
                start = self._arrow_start
                end = self._snap_target(raw_x, raw_y) or (x, y)
                self._arrow_start = None
                self._arrow_preview_end = None
                if start != end:
                    arrow = VoltageArrow(start, end, circuit=self.circuit)
                    label, accepted = QInputDialog.getText(
                        self, "Annotation de tension", "Nom de la tension :",
                        text=arrow.label,
                    )
                    if accepted and label.strip():
                        arrow.label = label.strip()
                        arrow._automatic_label = False
                    self.circuit.arrows.append(arrow)
                    self.circuit.recompute_nodes()
                    self.circuitChanged.emit()
            self.update()
            return
        item = self._item_at(raw_x, raw_y)
        additive = bool(event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ))
        if item is None:
            self._marquee_start = QPointF(raw_x, raw_y)
            self._marquee_end = QPointF(raw_x, raw_y)
            if not additive:
                self.set_selections([])
            return
        if additive:
            selected = list(self.selected_items)
            if item in selected:
                selected.remove(item)
            else:
                selected.append(item)
            self.set_selections(selected)
            if item not in self.selected_items:
                return
        elif item not in self.selected_items:
            self.set_selection(item)

        if len(self.selected_items) > 1:
            self._dragging = True
            self._group_drag_start = (raw_x, raw_y)
            self._group_component_origins = {
                selected: selected.position
                for selected in self.selected_items
                if isinstance(selected, Component)
            }
            self._group_arrow_origins = {
                selected: (selected.start, selected.end)
                for selected in self.selected_items
                if isinstance(selected, VoltageArrow)
            }
            self._group_wire_origins = {
                wire: list(wire.points)
                for wire in self.circuit.wires
                if wire in self.selected_items or any(
                    point in {
                        (snap(tx), snap(ty))
                        for component in self._group_component_origins
                        for tx, ty in component.terminal_positions().values()
                    }
                    for point in wire.points
                )
            }
            return
        if isinstance(item, Component):
            self._dragging = True
            self._drag_offset = QPointF(x - item.x, y - item.y)
            self._drag_start = (x, y)
            self._drag_component_origin = item.position
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
        elif isinstance(item, VoltageArrow):
            self._dragging = True
            raw_pos = (raw_x, raw_y)
            self._drag_arrow_start_scene = raw_pos
            label = item.text(self.engine.solution)
            if self._arrow_label_rect(item, label).contains(QPointF(raw_x, raw_y)):
                self._drag_arrow_part = "label"
                self._drag_arrow_start_label_offset = item.label_offset
            else:
                self._drag_arrow_part = "line"
                self._drag_arrow_start_offset = item.offset
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
            return min(
                node.points or [(node.x, node.y)],
                key=lambda point: (point[0] - x) ** 2 + (point[1] - y) ** 2,
            )
        return x, y

    def _snap_target(self, x: float, y: float) -> Optional[tuple[int, int]]:
        radius = 16 / self.zoom
        candidates = [
            (snap(tx), snap(ty))
            for component in self.circuit.components
            for tx, ty in component.terminal_positions().values()
        ]
        for wire in self.circuit.wires:
            candidates.extend(wire.points)
            for (ax, ay), (bx, by) in zip(wire.points, wire.points[1:]):
                if ay == by:
                    px = max(min(x, max(ax, bx)), min(ax, bx))
                    candidates.append((snap(px), ay))
                elif ax == bx:
                    py = max(min(y, max(ay, by)), min(ay, by))
                    candidates.append((ax, snap(py)))
        if not candidates:
            return None
        target = min(
            candidates,
            key=lambda point: (point[0] - x) ** 2 + (point[1] - y) ** 2,
        )
        return target if math.hypot(target[0] - x, target[1] - y) <= radius else None

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.position() - self._pan_start
            self._origin = self._pan_origin_start + delta
            self.update()
            return
        if self._dragging and self._group_drag_start is not None:
            raw_x, raw_y = self.scene_float_pos(event.position())
            dx = snap(raw_x - self._group_drag_start[0])
            dy = snap(raw_y - self._group_drag_start[1])
            self._drag_moved = self._drag_moved or bool(dx or dy)
            self._move_group(dx, dy)
            self.circuit.recompute_nodes()
            self.update()
        elif self._dragging and isinstance(self.selected, VoltageArrow):
            raw_x, raw_y = self.scene_float_pos(event.position())
            delta_x = raw_x - self._drag_arrow_start_scene[0]
            delta_y = raw_y - self._drag_arrow_start_scene[1]
            self._drag_moved = self._drag_moved or bool(delta_x or delta_y)
            if self._drag_arrow_part == "label":
                self.selected.label_offset = (
                    self._drag_arrow_start_label_offset[0] + delta_x,
                    self._drag_arrow_start_label_offset[1] + delta_y,
                )
            else:
                _, _, normal = self._arrow_line(
                    self.selected.start, self.selected.end, 0.0
                )
                self.selected.offset = max(
                    -300.0,
                    min(300.0, self._drag_arrow_start_offset +
                        delta_x * normal[0] + delta_y * normal[1]),
                )
            self.update()
        elif self._dragging and isinstance(self.selected, Component):
            x, y = self.scene_pos(event.position())
            self._drag_moved = self._drag_moved or (
                x - self._drag_offset.x() != self.selected.x
                or y - self._drag_offset.y() != self.selected.y
            )
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
            dx = self.selected.x - self._drag_component_origin[0]
            dy = self.selected.y - self._drag_component_origin[1]
            for wire, original_points in self._drag_wires:
                attached = {
                    point for point in self._drag_terminals.values()
                    if point in original_points
                }
                if len(attached) >= 2:
                    wire.points = [(px + dx, py + dy)
                                   for px, py in original_points]
                else:
                    wire.points = [
                        moved_by_terminal.get(point, point)
                        for point in original_points
                    ]
                wire.points = self._orthogonalize(wire.points)
            self.circuit.recompute_nodes()
            self.update()
        elif self._dragging and isinstance(self.selected, Wire) and \
                self._drag_wire_points is not None:
            raw_x, raw_y = self.scene_float_pos(event.position())
            self._drag_moved = self._drag_moved or (
                (snap(raw_x) != self._drag_start[0])
                or (snap(raw_y) != self._drag_start[1])
            )
            if self._drag_wire_endpoint is not None:
                self._wire_snap_target = self._snap_target(raw_x, raw_y)
                points = list(self._drag_wire_points)
                index = self._drag_wire_endpoint
                adjacent = points[1] if index == 0 else points[-2]
                original = points[index]
                if self._wire_snap_target is not None:
                    point = self._wire_snap_target
                elif adjacent[0] == original[0]:
                    point = (adjacent[0], snap(raw_y))
                else:
                    point = (snap(raw_x), adjacent[1])
                points[index] = point
                self.selected.points = self._orthogonalize(points)
            else:
                self._wire_snap_target = None
                x, y = snap(raw_x), snap(raw_y)
                dx, dy = x - self._drag_start[0], y - self._drag_start[1]
                self.selected.points = [
                    (px + dx, py + dy) for px, py in self._drag_wire_points
                ]
            self.circuit.recompute_nodes()
            self.update()
        elif self._marquee_start is not None:
            self._marquee_end = QPointF(*self.scene_float_pos(event.position()))
            self.update()
        elif self.mode == "place":
            self._preview_pos = self.scene_pos(event.position())
            self.update()
        elif self.mode == "wire":
            raw_x, raw_y = self.scene_float_pos(event.position())
            self._wire_snap_target = self._snap_target(raw_x, raw_y)
            if self._wire_start is not None:
                self._wire_preview_end = self._wire_snap_target or (
                    snap(raw_x), snap(raw_y)
                )
            self.update()
        elif self.mode == "voltage" and self._arrow_start is not None:
            raw_x, raw_y = self.scene_float_pos(event.position())
            self._arrow_preview_end = self._snap_target(raw_x, raw_y) or (
                snap(raw_x), snap(raw_y)
            )
            self.update()
        super().mouseMoveEvent(event)

    def _move_group(self, dx: int, dy: int) -> None:
        for component, (x, y) in self._group_component_origins.items():
            component.move_to(x + dx, y + dy)
        moved_terminals = {}
        for component, (x, y) in self._group_component_origins.items():
            original = component.TERMINAL_OFFSETS
            for name, (ox, oy) in original.items():
                rx, ry = rotate_offset(ox, oy, component.rotation)
                current = (snap(x + rx), snap(y + ry))
                moved_terminals[current] = (current[0] + dx, current[1] + dy)
        for wire, points in self._group_wire_origins.items():
            if wire in self.selected_items:
                wire.points = [(x + dx, y + dy) for x, y in points]
                continue
            attached = {point for point in points if point in moved_terminals}
            if len(attached) >= 2:
                wire.points = [(x + dx, y + dy) for x, y in points]
            elif attached:
                wire.points = [
                    moved_terminals.get(point, point) for point in points
                ]
        for arrow, (start, end) in self._group_arrow_origins.items():
            arrow.start = (start[0] + dx, start[1] + dy)
            arrow.end = (end[0] + dx, end[1] + dy)

    def _items_in_rect(self, rect: QRectF) -> list[object]:
        found: list[object] = []
        for component in self.circuit.components:
            bounds = QRectF(component.x - 30, component.y - 30, 60, 60)
            if rect.intersects(bounds):
                found.append(component)
        for wire in self.circuit.wires:
            if any(rect.contains(QPointF(*point)) for point in wire.points) or any(
                rect.intersects(QRectF(QPointF(*start), QPointF(*end))
                                .normalized().adjusted(-2, -2, 2, 2))
                for start, end in zip(wire.points, wire.points[1:])
            ):
                found.append(wire)
        for arrow in self.circuit.arrows:
            label = arrow.text(self.engine.solution)
            line_rect = QRectF(QPointF(*arrow.start),
                               QPointF(*arrow.end)).normalized()
            if rect.intersects(self._arrow_label_rect(arrow, label)) or \
                    rect.intersects(line_rect.adjusted(-2, -2, 2, 2)):
                found.append(arrow)
        return found

    def mouseReleaseEvent(self, event) -> None:
        if event.button() in (
            Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton
        ) and self._panning:
            self._panning = False
            self.setCursor(
                Qt.CursorShape.CrossCursor
                if self.mode in ("wire", "voltage", "place")
                else Qt.CursorShape.ArrowCursor
            )
            return
        if event.button() == Qt.MouseButton.LeftButton and \
                self._marquee_start is not None:
            raw_x, raw_y = self.scene_float_pos(event.position())
            rect = QRectF(self._marquee_start, QPointF(raw_x, raw_y)).normalized()
            items = self._items_in_rect(rect)
            if event.modifiers() & (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
            ):
                items = list(dict.fromkeys([*self.selected_items, *items]))
            self._marquee_start = None
            self._marquee_end = None
            self.set_selections(items)
            return
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            if self._drag_moved:
                self.engine.recompute()
                self.circuitChanged.emit()
            self._drag_moved = False
            self._drag_wires = []
            self._drag_terminals = {}
            self._drag_wire_points = None
            self._drag_wire_endpoint = None
            self._wire_snap_target = None
            self._drag_arrow_part = None
            self._drag_component_origin = None
            self._group_drag_start = None
            self._group_component_origins = {}
            self._group_wire_origins = {}
            self._group_arrow_origins = {}

    def wheelEvent(self, event) -> None:
        old_zoom = self.zoom
        new_zoom = max(0.35, min(3.5, old_zoom * 1.15 ** (event.angleDelta().y() / 120)))
        if new_zoom == old_zoom:
            return
        cursor = event.position()
        scene_x, scene_y = self.scene_float_pos(cursor)
        self.zoom = new_zoom
        self._view_touched = True
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
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            if not self._panning:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if event.key() == Qt.Key.Key_A and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_selections([
                *self.circuit.components,
                *self.circuit.wires,
                *self.circuit.arrows,
            ])
            return
        if event.key() == Qt.Key.Key_Escape and self.mode in ("wire", "voltage"):
            self._wire_start = None
            self._wire_preview_end = None
            self._wire_snap_target = None
            self._arrow_start = None
            self._arrow_preview_end = None
            self.update()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected:
            self._delete_selected()
        elif event.key() == Qt.Key.Key_R and self.mode == "place":
            self._preview_rotation = (self._preview_rotation + 90) % 360
            self.update()
        elif event.key() == Qt.Key.Key_R and isinstance(self.selected, Component):
            self.rotate_component(self.selected)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            if not self._panning:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        super().keyReleaseEvent(event)

    def rotate_preview(self) -> None:
        if self._preview_component is not None:
            self._preview_rotation = (self._preview_rotation + 90) % 360
            self.update()

    def _delete_selected(self) -> None:
        selected_items = list(self.selected_items)
        if not selected_items and self.selected is not None:
            selected_items = [self.selected]
        if not selected_items:
            return
        for item in selected_items:
            if isinstance(item, VoltageArrow):
                self.circuit.remove_arrow(item)
            else:
                self.circuit.remove(getattr(item, "label", ""))
        self.set_selections([])
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
            attached = {point for point in terminal_points if point in points}
            if len(attached) >= 2:
                wire.points = [
                    tuple(
                        snap(origin + rotated)
                        for origin, rotated in zip(
                            (component.x, component.y),
                            rotate_offset(px - component.x, py - component.y, delta),
                        )
                    )
                    for px, py in points
                ]
            else:
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
