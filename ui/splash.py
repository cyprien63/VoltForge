"""Animated startup splash screen built from the SVG logo."""

from __future__ import annotations

import math
import time
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QSplashScreen, QWidget

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "icons"
LOGO_SVG = ASSETS / "voltforge.svg"

FRAME_MS = 16
MIN_VISIBLE_MS = 400
FADE_MS = 160

BG = QColor("#0b1220")
ACCENT = QColor("#44d7b6")
ACCENT_LIGHT = QColor("#b6fff0")
ORANGE = QColor("#ffb454")
TRACK = QColor("#24344d")
TEXT_DIM = QColor("#8ea4b8")
TEXT_BRIGHT = QColor("#e8f1f8")

WIDTH = 340
HEIGHT = 300
LOGO_SIZE = 132.0
ORBIT_RADIUS = 84.0
TRAIL_SEGMENTS = 14
TRAIL_STEP_DEG = 9.0


class SplashScreen(QSplashScreen):
    """Petite animation de chargement autour du logo VoltForge."""

    def __init__(self) -> None:
        pixmap = QPixmap(WIDTH, HEIGHT)
        pixmap.fill(BG)
        super().__init__(pixmap)
        self.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._renderer = QSvgRenderer(str(LOGO_SVG))
        self._angle = 0.0
        self._pulse = 0.0
        self._started_at = 0.0
        self._fade: QPropertyAnimation | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._advance)
        self.repaint()

    def start(self) -> None:
        self._started_at = time.monotonic()
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _advance(self) -> None:
        self._angle = (self._angle + 4.5) % 360.0
        self._pulse += 0.09
        self.repaint()

    def paintEvent(self, event) -> None:  # noqa: D102
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), BG)

        center = QPointF(WIDTH / 2.0, 128.0)
        self._draw_logo(painter, center)
        self._draw_orbit(painter, center)
        self._draw_texts(painter)
        painter.end()

    def _draw_logo(self, painter: QPainter, center: QPointF) -> None:
        breathe = 1.0 + 0.02 * math.sin(self._pulse)
        size = LOGO_SIZE * breathe
        painter.save()
        painter.translate(center)
        painter.rotate(1.5 * math.sin(self._pulse / 2.0))
        painter.scale(size / 256.0, size / 256.0)
        painter.translate(-128.0, -128.0)
        self._renderer.render(painter)
        painter.restore()

    def _draw_orbit(self, painter: QPainter, center: QPointF) -> None:
        rect_size = int(ORBIT_RADIUS * 2)
        x = int(center.x() - ORBIT_RADIUS)
        y = int(center.y() - ORBIT_RADIUS)
        span = int(TRAIL_STEP_DEG * 0.75 * 16)

        track = QPen(TRACK, 4.0)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(x, y, rect_size, rect_size, 0, 360 * 16)

        for i in range(TRAIL_SEGMENTS):
            fade = 1.0 - i / TRAIL_SEGMENTS
            if i == 0:
                color = ACCENT_LIGHT
            elif i < TRAIL_SEGMENTS // 2:
                color = QColor(ACCENT)
            else:
                color = QColor(ORANGE)
            color.setAlphaF(fade * fade)
            pen = QPen(color, 4.5 if i == 0 else 3.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            start = -(self._angle + i * TRAIL_STEP_DEG)
            painter.drawArc(x, y, rect_size, rect_size, int(start * 16), -span)

    def _draw_texts(self, painter: QPainter) -> None:
        title = QFont()
        title.setBold(True)
        title.setPixelSize(24)
        painter.setFont(title)
        painter.setPen(TEXT_BRIGHT)
        painter.drawText(
            0, 232, WIDTH, 28,
            Qt.AlignmentFlag.AlignHCenter, "VoltForge",
        )

        dots = "." * (1 + int(self._pulse / 1.2) % 3)
        body = QFont()
        body.setPixelSize(13)
        painter.setFont(body)
        painter.setPen(TEXT_DIM)
        painter.drawText(
            0, 260, WIDTH, 18,
            Qt.AlignmentFlag.AlignHCenter, f"Chargement{dots}",
        )

    def finish(self, widget: QWidget) -> None:
        elapsed_ms = (time.monotonic() - self._started_at) * 1000.0
        remaining = max(MIN_VISIBLE_MS - elapsed_ms, 0.0)
        QTimer.singleShot(int(remaining), lambda: self._fade_out(widget))

    def _fade_out(self, widget: QWidget) -> None:
        self._timer.stop()
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(1.0)
        self.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(FADE_MS)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.finished.connect(lambda: self._close(widget))
        self._fade = fade
        fade.start()

    def _close(self, widget: QWidget) -> None:
        self._timer.stop()
        self._fade = None
        super().finish(widget)
