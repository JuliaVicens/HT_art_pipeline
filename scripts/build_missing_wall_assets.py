#!/usr/bin/env python3
"""Create deterministic transparent source art for missing wall accessories."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (256, 192), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def build(root: Path) -> None:
    sources = root / "rooms" / "bedroom_01" / "sources"
    image, draw = canvas()
    draw.rectangle((42, 78, 214, 98), fill="#8e4f48")
    draw.rectangle((52, 66, 204, 82), fill="#d99278")
    draw.rectangle((62, 98, 194, 112), fill="#70403e")
    draw.rectangle((74, 112, 88, 154), fill="#8e4f48")
    draw.rectangle((168, 112, 182, 154), fill="#8e4f48")
    image.save(sources / "wall_shelf_pastel_01.source.png")

    image, draw = canvas()
    draw.rectangle((76, 30, 180, 160), fill="#b87883")
    draw.rectangle((88, 42, 168, 148), fill="#e7b5ae")
    for y in range(52, 144, 18):
        draw.line((96, y, 160, y + 10), fill="#f5d9c7", width=5)
    draw.rectangle((72, 28, 184, 36), fill="#8e4f48")
    image.save(sources / "wall_textile_pastel_01.source.png")

    image, draw = canvas()
    draw.ellipse((70, 38, 186, 154), fill="#8e4f48")
    draw.ellipse((80, 48, 176, 144), fill="#f3d6b5")
    draw.line((128, 96, 128, 64), fill="#70403e", width=6)
    draw.line((128, 96, 154, 110), fill="#70403e", width=6)
    for point in ((128, 54), (170, 96), (128, 138), (86, 96)):
        draw.rectangle((point[0] - 4, point[1] - 4, point[0] + 4, point[1] + 4), fill="#70403e")
    image.save(sources / "wall_clock_pastel_01.source.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    build(parser.parse_args().root.resolve())
    print("OK: missing wall source art generated")


if __name__ == "__main__":
    main()