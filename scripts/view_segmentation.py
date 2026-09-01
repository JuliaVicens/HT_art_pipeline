"""Lightweight view segmentation and seamless-texture helpers."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

Point = tuple[float, float]


def load_views(source: Path, views_path: Path | None) -> tuple[dict[str, Point], str, dict]:
    candidate = views_path or source.with_suffix(".views.json")
    if candidate.is_file():
        raw = json.loads(candidate.read_text(encoding="utf-8"))
        metadata = {key: value for key, value in raw.items() if key != "points"}
        return {name: tuple(value) for name, value in raw["points"].items()}, candidate.as_posix(), metadata

    # Conservative fallback for centered isometric references. A generated QA
    # preview makes this estimate inspectable; production assets can override it.
    with Image.open(source) as image:
        width, height = image.size
    ratios = {
        "top": (.50, .08), "left": (.04, .47), "right": (.96, .47),
        "bottom": (.50, .82), "left_base": (.04, .56),
        "right_base": (.96, .56), "base_bottom": (.50, .91),
    }
    return {name: (x * width, y * height) for name, (x, y) in ratios.items()}, "estimated", {}


def bilinear(points: list[Point], u: float, v: float) -> Point:
    p00, p10, p11, p01 = points
    x = (1-u)*(1-v)*p00[0] + u*(1-v)*p10[0] + u*v*p11[0] + (1-u)*v*p01[0]
    y = (1-u)*(1-v)*p00[1] + u*(1-v)*p10[1] + u*v*p11[1] + (1-u)*v*p01[1]
    return x, y


def sample_quad(source: Image.Image, points: list[Point], size: tuple[int, int]) -> Image.Image:
    result = Image.new("RGBA", size, (0, 0, 0, 0))
    src, dst = source.load(), result.load()
    max_x, max_y = source.width - 1, source.height - 1
    for y in range(size[1]):
        v = y / max(1, size[1] - 1)
        for x in range(size[0]):
            u = x / max(1, size[0] - 1)
            sx, sy = bilinear(points, u, v)
            dst[x, y] = src[min(max(round(sx), 0), max_x), min(max(round(sy), 0), max_y)]
    return result


def make_periodic(texture: Image.Image, band: int = 2) -> tuple[Image.Image, int]:
    """Blend opposite strips symmetrically, guaranteeing identical outer edges."""
    result = texture.copy().convert("RGBA")
    pixels = result.load()
    width, height = result.size
    band = min(band, width // 2, height // 2)
    for offset in range(band):
        weight = (band - offset) / band
        for y in range(height):
            left, right = pixels[offset, y], pixels[width - 1 - offset, y]
            merged = tuple(round((a + b) / 2) for a, b in zip(left, right))
            pixels[offset, y] = tuple(round(a*(1-weight) + b*weight) for a, b in zip(left, merged))
            pixels[width - 1 - offset, y] = tuple(round(a*(1-weight) + b*weight) for a, b in zip(right, merged))
    for offset in range(band):
        weight = (band - offset) / band
        for x in range(width):
            top, bottom = pixels[x, offset], pixels[x, height - 1 - offset]
            merged = tuple(round((a + b) / 2) for a, b in zip(top, bottom))
            pixels[x, offset] = tuple(round(a*(1-weight) + b*weight) for a, b in zip(top, merged))
            pixels[x, height - 1 - offset] = tuple(round(a*(1-weight) + b*weight) for a, b in zip(bottom, merged))
    score = sum(
        sum(abs(a-b) for a, b in zip(pixels[0, y], pixels[width-1, y])) for y in range(height)
    ) + sum(
        sum(abs(a-b) for a, b in zip(pixels[x, 0], pixels[x, height-1])) for x in range(width)
    )
    return result, score


def segmentation_preview(source: Image.Image, points: dict[str, Point], output: Path) -> None:
    preview = source.copy().convert("RGBA")
    overlay = Image.new("RGBA", preview.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    top = [points[k] for k in ("top", "right", "bottom", "left")]
    left = [points[k] for k in ("left", "bottom", "base_bottom", "left_base")]
    right = [points[k] for k in ("bottom", "right", "right_base", "base_bottom")]
    draw.polygon(top, fill=(100, 210, 140, 96), outline=(100, 255, 160, 255), width=4)
    draw.polygon(left, fill=(245, 180, 90, 96), outline=(255, 200, 100, 255), width=4)
    draw.polygon(right, fill=(180, 130, 245, 96), outline=(205, 160, 255, 255), width=4)
    preview = Image.alpha_composite(preview, overlay)
    output.parent.mkdir(parents=True, exist_ok=True)
    preview.thumbnail((768, 768), Image.Resampling.NEAREST)
    preview.save(output, optimize=True)
