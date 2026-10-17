"""Checks for the animated startup splash screen."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

from ui.splash import BG, HEIGHT, LOGO_SVG, WIDTH, SplashScreen


class SplashTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_logo_exists_and_animates(self) -> None:
        self.assertTrue(LOGO_SVG.is_file())
        splash = SplashScreen()
        splash.start()
        QTest.qWait(120)
        self.assertTrue(splash.isVisible())
        self.assertTrue(splash._timer.isActive())
        splash.stop()
        splash.close()
        self.assertFalse(splash.isVisible())

    def test_finish_fades_out_without_long_wait(self) -> None:
        splash = SplashScreen()
        splash.start()
        QTest.qWait(50)
        splash.finish(splash)
        QTest.qWait(700)
        self.assertFalse(splash.isVisible())
        self.assertFalse(splash._timer.isActive())

    def test_angle_progression_is_time_based(self) -> None:
        splash = SplashScreen()
        splash.start()
        QTest.qWait(300)
        first = splash._angle
        QTest.qWait(300)
        second = splash._angle
        self.assertGreater(second, first)
        self.assertLess(second, first + 95.0)
        splash.stop()
        splash.close()

    def test_splash_window_is_centered_on_screen(self) -> None:
        splash = SplashScreen()
        splash.start()
        screen = splash.screen()
        self.assertIsNotNone(screen)
        area = screen.availableGeometry()
        self.assertEqual(splash.pos(), area.center() - splash.rect().center())
        splash.stop()
        splash.close()

    def test_rendered_content_is_centered(self) -> None:
        splash = SplashScreen()
        ink = self._ink_bounds(splash)
        left, right, top, bottom = ink
        self.assertLessEqual(abs((left + right) / 2.0 - WIDTH / 2.0), 2.0)
        self.assertLessEqual(abs((top + bottom) / 2.0 - HEIGHT / 2.0), 2.0)
        self.assertLessEqual(abs((WIDTH - 1 - right) - left), 2)

    @staticmethod
    def _ink_bounds(splash: SplashScreen) -> tuple[int, int, int, int]:
        image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
        image.fill(BG)
        painter = QPainter(image)
        splash.render(painter, QPoint(0, 0))
        painter.end()
        background = BG.rgb()
        xs: list[int] = []
        ys: list[int] = []
        for y in range(HEIGHT):
            for x in range(WIDTH):
                if image.pixel(x, y) != background:
                    xs.append(x)
                    ys.append(y)
        return min(xs), max(xs), min(ys), max(ys)


if __name__ == "__main__":
    unittest.main()
