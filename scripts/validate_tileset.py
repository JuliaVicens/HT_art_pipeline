#!/usr/bin/env python3
"""Validate terrain geometry and render an isometric seam-check montage."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def alpha_signature(image: Image.Image) -> bytes:
    return image.convert("RGBA").getchannel("A").tobytes()


def validate_geometry(images: list[Image.Image], paths: list[Path]) -> None:
    expected_size = images[0].size
    expected_alpha = alpha_signature(images[0])
    for image, path in zip(images, paths):
        if image.size != expected_size:
            raise ValueError(f"Geometry mismatch: {path} is {image.size}, expected {expected_size}")
        if alpha_signature(image) != expected_alpha:
            raise ValueError(f"Corner/edge mismatch: {path} has a different alpha silhouette")

    width, canvas_height = expected_size
    depth = width // 2
    elevation = canvas_height - depth
    alpha = images[0].getchannel("A")
    anchors = {
        "top-left pixel": (width // 2 - 1, 0),
        "top-right pixel": (width // 2, 0),
        "left corner": (0 if elevation else 1, depth // 2),
        "right corner": (width - 1 if elevation else width - 2, depth // 2),
        "bottom corner": (width // 2, depth + elevation - 1),
    }
    for label, point in anchors.items():
        if alpha.getpixel(point) != 255:
            raise ValueError(f"Missing canonical {label} at {point}")


def render_montage(images: list[Image.Image], output: Path, grid: int = 3) -> None:
    tile_width, tile_height = images[0].size
    depth = tile_width // 2
    step_x, step_y = tile_width // 2, depth // 2
    margin = tile_width
    canvas = Image.new(
        "RGBA",
        (margin * 2 + tile_width + (grid - 1) * tile_width, margin + tile_height + (grid - 1) * depth),
        (0, 0, 0, 0),
    )
    placements = []
    for row in range(grid):
        for column in range(grid):
            x = margin + (column - row) * step_x
            y = (row + column) * step_y
            placements.append((row + column, row, column, x, y))
    for _, row, column, x, y in sorted(placements):
        tile = images[(row + column) % len(images)]
        # A continuous floor draws only top faces internally. Side faces belong
        # exclusively to exposed map boundaries or height differences.
        surface = Image.new("RGBA", tile.size, (0, 0, 0, 0))
        src, dst = tile.load(), surface.load()
        cx, cy = (tile_width - 1) / 2, (depth - 1) / 2
        for sy in range(depth):
            for sx in range(tile_width):
                if abs(sx - cx) / (tile_width / 2) + abs(sy - cy) / (depth / 2) <= 1:
                    dst[sx, sy] = src[sx, sy]
        canvas.alpha_composite(surface, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tiles", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    images = [Image.open(path).convert("RGBA") for path in args.tiles]
    validate_geometry(images, args.tiles)
    render_montage(images, args.output)
    print(f"OK: {len(images)} terrain tiles share canonical corners; preview: {args.output}")


if __name__ == "__main__":
    main()
