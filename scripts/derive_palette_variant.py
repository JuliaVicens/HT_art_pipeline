#!/usr/bin/env python3
"""Derive a material-color variant while preserving source alpha and silhouette."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def colors(path: Path) -> list[tuple[int, int, int]]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    return [tuple(bytes.fromhex(item["hex"].lstrip("#"))) for item in spec["colors"]]


def distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return sum((left - right) ** 2 for left, right in zip(a, b))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-palette", type=Path, required=True)
    parser.add_argument("--target-palette", type=Path, required=True)
    args = parser.parse_args()

    source_palette = colors(args.source_palette)
    target_palette = colors(args.target_palette)
    source_order = sorted(range(len(source_palette)), key=lambda i: sum(source_palette[i]))
    target_order = sorted(range(len(target_palette)), key=lambda i: sum(target_palette[i]))
    rank = {palette_index: position for position, palette_index in enumerate(source_order)}

    image = Image.open(args.source).convert("RGBA")
    output = image.copy()
    pixels = output.load()
    for y in range(output.height):
        for x in range(output.width):
            r, g, b, a = pixels[x, y]
            # Preserve generated white/checker transparency candidates and the
            # luminous neutral glass. The normalizer removes only border-connected
            # neutral pixels, so holes and exterior light remain deterministic.
            if not a or (min(r, g, b) >= 225 and max(r, g, b) - min(r, g, b) <= 18):
                continue
            nearest_index = min(range(len(source_palette)), key=lambda i: distance((r, g, b), source_palette[i]))
            source_rank = rank[nearest_index]
            target_rank = round(source_rank * (len(target_order) - 1) / max(1, len(source_order) - 1))
            tr, tg, tb = target_palette[target_order[target_rank]]
            pixels[x, y] = (tr, tg, tb, a)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.save(args.output, optimize=True)


if __name__ == "__main__":
    main()
