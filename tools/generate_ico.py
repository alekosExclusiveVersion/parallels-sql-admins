"""
tools/generate_ico.py

Генерация многоразмерного assets/ParallelsSQLAdmin.ico из app_icon.png
(актуальный дизайн иконки — из него же собран assets/ParallelsSQLAdmin.icns).
Запускать из корня репозитория:

    .venv/bin/python tools/generate_ico.py
"""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PNG = ROOT / "assets" / "app_icon.png"
OUT = ROOT / "assets" / "ParallelsSQLAdmin.ico"

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    try:
        source = Image.open(PNG).convert("RGBA")
    except OSError:
        print(f"ERROR: не удалось загрузить PNG: {PNG}")
        return 1

    if source.size[0] < 256 or source.size[1] < 256:
        print(f"ERROR: PNG слишком маленький ({source.size}) — нужен >= 256x256")
        return 1

    frames = [source.resize((size, size), Image.LANCZOS) for size in SIZES]

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