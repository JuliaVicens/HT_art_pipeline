#!/usr/bin/env python3
"""Render one continuous isometric path surrounded by grass."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def surface_only(tile: Image.Image) -> Image.Image:
    width = tile.width
    depth = width // 2
    result = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    src, dst = tile.load(), result.load()
    cx, cy = (width - 1) / 2, (depth - 1) / 2
    for y in range(depth):
        for x in range(width):
            if abs(x - cx) / (width / 2) + abs(y - cy) / (depth / 2) <= 1:
                dst[x, y] = src[x, y]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grass", required=True, type=Path)
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--grid", type=int, default=5)
    args = parser.parse_args()
    grass = surface_only(Image.open(args.grass).convert("RGBA"))
    path = surface_only(Image.open(args.path).convert("RGBA"))
    width, depth = grass.width, grass.width // 2
    grid = args.grid
    canvas = Image.new("RGBA", (width * (grid + 2), depth * (grid + 3)), (0, 0, 0, 0))
    origin_x = width * (grid // 2 + 1)
    path_row = grid // 2
    placements = []
    for row in range(grid):
        for column in range(grid):
            x = origin_x + (column - row) * (width // 2)
            y = (row + column) * (depth // 2)
            placements.append((row + column, row, column, x, y))
    for _, row, column, x, y in sorted(placements):
        # NW-SE connects along increasing columns; only one grid row is path.
        tile = path if row == path_row else grass
        canvas.alpha_composite(tile, (x, y))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, optimize=True)
    print(f"OK: straight path across {grid} connected tiles; preview: {args.output}")


if __name__ == "__main__":
    main()
