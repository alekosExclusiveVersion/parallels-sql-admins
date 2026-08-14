"""
tools/generate_ico.py

Генерация многоразмерного assets/ParallelsSQLAdmin.ico из app_icon.svg
(QSvgRenderer → PNG-кадры → Pillow ICO). Запускать из корня репозитория:

    PYTHONPATH=. QT_QPA_PLATFORM=offscreen \
    .venv/bin/python tools/generate_ico.py
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "assets" / "app_icon.svg"
OUT = ROOT / "assets" / "ParallelsSQLAdmin.ico"

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    app = QGuiApplication(sys.argv)

    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        print(f"ERROR: не удалось загрузить SVG: {SVG}")
        return 1

    frames = []
    for size in SIZES:
        image = QImage(size, size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        renderer.render(painter, image.rect())
        painter.end()

        buffer = image.constBits().tobytes()
        frame = Image.frombuffer(
            "RGBA", (size, size), buffer, "raw", "RGBA", 0, 1
        )
        frames.append(frame)

    frames[-1].save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[:-1],
    )
    print(f"OK: {OUT} ({len(frames)} sizes: {', '.join(map(str, SIZES))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
