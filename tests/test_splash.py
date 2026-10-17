"""Checks for the animated startup splash screen."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

from ui.splash import LOGO_SVG, SplashScreen


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


if __name__ == "__main__":
    unittest.main()
