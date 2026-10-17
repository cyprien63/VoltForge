"""Animated startup splash screen built from the SVG logo."""

from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPointF,
    QPropertyAnimation,
    QRectF,
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
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QSplashScreen, QWidget

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
ORBIT_PEN = 4.5
TRAIL_SEGMENTS = 14
TRAIL_STEP_DEG = 9.0

SPEED_DEG_PER_S = 95.0
PULSE_SPEED = 1.6

TITLE_H = 30
SUBTITLE_H = 16
GAP_ORBIT_TITLE = 14.0
GAP_TITLE_SUBTITLE = 6.0


def content_layout() -> tuple[float, float, float]:
    """Retourne (centre vertical de l'orbite, y du titre, y du sous-titre).

    Le bloc complet (orbite + textes) est centré verticalement dans la fenêtre.
    """
    orbit_span = ORBIT_RADIUS * 2.0 + ORBIT_PEN
    content_h = (
        orbit_span
        + GAP_ORBIT_TITLE
        + TITLE_H
        + GAP_TITLE_SUBTITLE
        + SUBTITLE_H
    )
    top = (HEIGHT - content_h) / 2.0
    orbit_cy = top + orbit_span / 2.0
    title_y = top + orbit_span + GAP_ORBIT_TITLE
    subtitle_y = title_y + TITLE_H + GAP_TITLE_SUBTITLE
    return orbit_cy, title_y, subtitle_y


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
        self._clock = QElapsedTimer()
        self._angle = 0.0
        self._pulse = 0.0
        self._fade: QPropertyAnimation | None = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._advance)
        self.update()

    def start(self) -> None:
        self._clock.start()
        self._center_on_screen()
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.center() - self.rect().center())

    def _advance(self) -> None:
        seconds = self._clock.elapsed() / 1000.0
        self._angle = (seconds * SPEED_DEG_PER_S) % 360.0
        self._pulse = seconds * PULSE_SPEED
        self.update()

    def paintEvent(self, event) -> None:  # noqa: D102
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), BG)

        orbit_cy, title_y, subtitle_y = content_layout()
        center = QPointF(WIDTH / 2.0, orbit_cy)
        self._draw_logo(painter, center)
        self._draw_orbit(painter, center)
        self._draw_texts(painter, title_y, subtitle_y)
        painter.end()

    def _draw_logo(self, painter: QPainter, center: QPointF) -> None:
        breathe = 1.0 + 0.02 * math.sin(self._pulse)
        size = LOGO_SIZE * breathe
        painter.save()
        painter.translate(center)
        painter.rotate(1.5 * math.sin(self._pulse / 2.0))
        self._renderer.render(painter, QRectF(-size / 2.0, -size / 2.0, size, size))
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
            pen = QPen(color, ORBIT_PEN if i == 0 else 3.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            start = -(self._angle + i * TRAIL_STEP_DEG)
            painter.drawArc(x, y, rect_size, rect_size, int(start * 16), -span)

    def _draw_texts(self, painter: QPainter, title_y: float, subtitle_y: float) -> None:
        title = QFont()
        title.setBold(True)
        title.setPixelSize(24)
        painter.setFont(title)
        painter.setPen(TEXT_BRIGHT)
        painter.drawText(
            0, int(title_y), WIDTH, TITLE_H,
            Qt.AlignmentFlag.AlignHCenter, "VoltForge",
        )

        seconds = self._pulse / PULSE_SPEED
        dots = "." * (1 + int(seconds * 2.5) % 3)
        body = QFont()
        body.setPixelSize(13)
        painter.setFont(body)
        painter.setPen(TEXT_DIM)
        painter.drawText(
            0, int(subtitle_y), WIDTH, SUBTITLE_H,
            Qt.AlignmentFlag.AlignHCenter, f"Chargement{dots}",
        )

    def finish(self, widget: QWidget) -> None:
        elapsed_ms = float(self._clock.elapsed())
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
