"""Checks for the animated startup splash screen."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

from ui.splash import LOGO_SVG, SplashScreen


class SplashTest(unittest.TestCase):
    def test_logo_exists_and_animates(self) -> None:
        app = QApplication.instance() or QApplication([])
        self.assertTrue(LOGO_SVG.is_file())
        splash = SplashScreen()
        splash.start()
        QTest.qWait(120)
        self.assertTrue(splash.isVisible())
        splash.stop()
        splash.close()
        del app


if __name__ == "__main__":
    unittest.main()
