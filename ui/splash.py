"""Animated startup splash screen built from the SVG logo."""

from __future__ import annotations

import math
import time
from pathlib import Path

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QSplashScreen, QWidget

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "icons"
LOGO_SVG = ASSETS / "voltforge.svg"

FRAME_MS = 33
MIN_VISIBLE_MS = 900


class SplashScreen(QSplashScreen):
    """Petite animation de chargement autour du logo VoltForge."""

    def __init__(self) -> None:
        pixmap = QPixmap(320, 320)
        pixmap.fill(QColor("#0b1220"))
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
        self._angle = (self._angle + 6.0) % 360.0
        self._pulse += 0.12
        self.repaint()

    def paintEvent(self, event) -> None:  # noqa: D102
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        width = float(self.width())
        height = float(self.height())
        painter.fillRect(self.rect(), QColor("#0b1220"))

        size = 180.0 + 8.0 * math.sin(self._pulse)
        origin = QPointF((width - size) / 2.0, (height - size) / 2.0 - 12.0)
        painter.save()
        painter.translate(origin.x() + size / 2.0, origin.y() + size / 2.0)
        painter.rotate(2.0 * math.sin(self._pulse / 2.0))
        painter.scale(size / 256.0, size / 256.0)
        painter.translate(-128.0, -128.0)
        self._renderer.render(painter)
        painter.restore()

        center = QPointF(width / 2.0, origin.y() + size + 28.0)
        radius = 18.0
        track = QPen(QColor("#24344d"), 5.0)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(
            int(center.x() - radius), int(center.y() - radius),
            int(radius * 2), int(radius * 2),
            0, 360 * 16,
        )

        pen = QPen(QColor("#44d7b6"), 5.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        span = int(120 * 16)
        painter.drawArc(
            int(center.x() - radius), int(center.y() - radius),
            int(radius * 2), int(radius * 2),
            int(-self._angle * 16), span,
        )

        painter.setPen(QColor("#8ea4b8"))
        font = QFont()
        font.setPixelSize(14)
        painter.setFont(font)
        painter.drawText(
            0, int(center.y() + radius + 24), self.width(),
            18, Qt.AlignmentFlag.AlignHCenter, "Chargement…",
        )
        painter.end()

    def finish(self, widget: QWidget) -> None:
        elapsed_ms = (time.monotonic() - self._started_at) * 1000.0
        remaining = MIN_VISIBLE_MS - elapsed_ms
        if remaining > 0:
            QTimer.singleShot(int(remaining), lambda: self._close(widget))
        else:
            self._close(widget)

    def _close(self, widget: QWidget) -> None:
        self.stop()
        super().finish(widget)
