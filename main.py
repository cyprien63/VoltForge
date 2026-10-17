"""Point d'entrée de l'application VoltForge."""

from __future__ import annotations

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.splash import LOGO_SVG, SplashScreen


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("VoltForge")
    app.setOrganizationName("VoltForge")
    app.setWindowIcon(QIcon(str(LOGO_SVG)))
    splash = SplashScreen()
    splash.start()
    QTimer.singleShot(0, lambda: _open_window(app, splash))
    return app.exec()


def _open_window(app: QApplication, splash: SplashScreen) -> None:
    window = MainWindow()
    app.setWindowIcon(window.windowIcon())
    window.show()
    splash.finish(window)


if __name__ == "__main__":
    raise SystemExit(main())
