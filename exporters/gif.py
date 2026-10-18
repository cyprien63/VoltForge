"""Capture d'une session de lecture en GIF animé."""

from __future__ import annotations

from io import BytesIO
from math import ceil
from typing import Callable, List, Optional, Sequence

from PIL import Image
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice

from .static import render_image


def capture_frame(canvas) -> Image.Image:
    """Rendu PNG du canevas, converti en image RGB indépendante."""
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not render_image(canvas).save(buffer, "PNG"):
        raise OSError("Impossible de capturer une image du canevas.")
    buffer.close()
    with Image.open(BytesIO(bytes(encoded))) as image:
        return image.convert("RGB").copy()


def save_gif(frames: Sequence[Image.Image], durations_ms: Sequence[int],
             filename: str) -> None:
    """Écrit ``frames`` en GIF animé avec les durées d'image indiquées."""
    frames[0].save(
        filename,
        format="GIF",
        save_all=True,
        append_images=list(frames[1:]),
        duration=list(durations_ms),
        loop=0,
        optimize=False,
        disposal=2,
    )


def export_gif(engine, canvas, filename: str, duration: float = 3.0,
               fps: float = 15.0,
               progress: Optional[Callable[[int, int], None]] = None) -> int:
    """Enregistre ``duration`` secondes de session à ``fps`` images par seconde.

    L'export pilote le moteur lui-même : ``engine.start_play()`` démarre
    une session fraîche, chaque image est rendue à intervalle ``1/fps``
    d'horloge simulée, puis ``engine.stop_play()`` termine la session dans
    un bloc ``finally``. Le rappel ``progress`` est invoqué après chaque
    image ; s'il traite les événements Qt, l'utilisateur peut interagir
    avec le canevas pendant la capture et ses gestes sont enregistrés.
    """
    if duration <= 0.0:
        raise ValueError("La durée doit être positive.")
    if fps <= 0.0:
        raise ValueError("La cadence d'images doit être positive.")
    frame_step = 1.0 / fps
    frame_count = max(2, ceil(duration * fps - 1e-9))

    frames: List[Image.Image] = []
    engine.start_play(duration=0.0, loop=False)
    try:
        for index in range(frame_count):
            if index:
                engine.advance(frame_step)
            frames.append(capture_frame(canvas))
            if progress is not None:
                progress(index + 1, frame_count)
    finally:
        engine.stop_play()

    total_ms = round(duration * 1000)
    step_ms = max(10, round(frame_step * 1000))
    durations_ms = [step_ms] * (frame_count - 1)
    durations_ms.append(max(10, total_ms - step_ms * (frame_count - 1)))
    try:
        save_gif(frames, durations_ms, filename)
    finally:
        for frame in frames:
            frame.close()
    return frame_count
