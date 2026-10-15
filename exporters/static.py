"""Static diagram export using the canvas' native scene renderer."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QImage, QPageLayout, QPainter
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtSvg import QSvgGenerator


def render_image(canvas, scale: int = 1) -> QImage:
    width, height = max(1, canvas.width()), max(1, canvas.height())
    image = QImage(width * scale, height * scale, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    painter.scale(scale, scale)
    canvas.draw_scene(painter, width, height)
    painter.end()
    return image


def export_static(canvas, filename: str) -> None:
    """Write a PNG/JPEG, SVG, or PDF diagram; raise on unsupported output."""
    path = Path(filename)
    suffix = path.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg"):
        image = render_image(canvas, scale=2)
        image_format = "JPEG" if suffix in (".jpg", ".jpeg") else "PNG"
        if not image.save(str(path), image_format):
            raise OSError(f"Impossible d'écrire l'image : {path}")
        return

    width, height = max(1, canvas.width()), max(1, canvas.height())
    if suffix == ".svg":
        generator = QSvgGenerator()
        generator.setFileName(str(path))
        generator.setSize(QSize(width, height))
        generator.setViewBox(QRect(0, 0, width, height))
        generator.setTitle("VoltForge — Schéma électrique")
        painter = QPainter(generator)
        canvas.draw_scene(painter, width, height)
        painter.end()
        return

    if suffix == ".pdf":
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(path))
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        printer.setFullPage(True)
        painter = QPainter(printer)
        page = printer.pageRect(QPrinter.Unit.DevicePixel)
        scale = min(page.width() / width, page.height() / height)
        painter.translate((page.width() - width * scale) / 2,
                          (page.height() - height * scale) / 2)
        painter.scale(scale, scale)
        canvas.draw_scene(painter, width, height)
        painter.end()
        return

    raise ValueError("Format non pris en charge. Choisissez PNG, JPG, SVG ou PDF.")
