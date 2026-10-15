"""Sequential scenario capture to animated GIF."""

from __future__ import annotations

from io import BytesIO

from PIL import Image
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice

from .static import render_image


def export_gif(engine, canvas, scenario_text: str, filename: str,
               progress=None) -> int:
    """Simulate and capture every frame through the complete scenario."""
    program = engine.load_program(scenario_text)
    if engine.program_errors:
        raise ValueError("\n".join(engine.program_errors))
    if program.duration <= 0 or program.frame_count <= 0:
        raise ValueError("Le scénario doit définir une durée positive.")

    frames = []
    engine.begin_transient(program, restore_after=True)
    try:
        frame_count = program.frame_count
        frame_step = 1.0 / program.fps
        if program.duration <= frame_step:
            frame_times = [program.start, program.end]
            frame_durations = [program.duration / 2] * 2
        else:
            frame_times = [
                program.start + index * frame_step
                for index in range(frame_count - 1)
            ] + [program.end]
            frame_durations = (
                [frame_step] * (frame_count - 1)
                + [program.duration - (frame_count - 1) * frame_step]
            )

        for index, frame_time in enumerate(frame_times):
            if index:
                engine.advance(max(0.0, frame_time - engine.t))
            encoded = QByteArray()
            buffer = QBuffer(encoded)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            if not render_image(canvas).save(buffer, "PNG"):
                raise OSError("Impossible de capturer une image du canevas.")
            buffer.close()
            with Image.open(BytesIO(bytes(encoded))) as image:
                frames.append(image.convert("RGB").copy())
            if progress is not None:
                progress(index + 1, len(frame_times))
        if engine.missing_targets:
            raise ValueError(
                "Composants absents du circuit : " + ", ".join(engine.missing_targets)
            )
        durations_ms = [
            max(10, round(duration * 100) * 10)
            for duration in frame_durations
        ]
        frames[0].save(
            filename,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations_ms,
            loop=0,
            optimize=False,
            disposal=2,
        )
        return len(frames)
    finally:
        engine.end_transient(restore=True)
        for frame in frames:
            frame.close()
