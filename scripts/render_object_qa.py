#!/usr/bin/env python3
"""Render a manifest-driven object QA sheet with isometric geometry overlays."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TILE_W, TILE_H = 64, 32
PANEL_W, PANEL_H = 420, 330
COLORS = {
    "background": (22, 28, 25, 255), "panel": (34, 43, 38, 255),
    "text": (235, 239, 226, 255), "muted": (174, 186, 174, 255),
    "outline": (244, 205, 94, 255), "positive": (91, 192, 222, 255),
    "negative": (224, 116, 159, 255), "center": (255, 255, 255, 255),
    "anchor": (255, 126, 67, 255), "pass": (101, 205, 132, 255),
    "review": (247, 174, 66, 255),
}


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def manifest_output(manifest_path: Path, entry: dict) -> Path:
    """Resolve output locally; old manifest paths may include the project directory."""
    direct = Path(entry.get("output", ""))
    candidates = [direct, manifest_path.parent / direct,
                  manifest_path.parent / "output" / f"{entry['asset']}.png"]
    return next((path for path in candidates if path.is_file()), candidates[-1])


def diamond(cx: int, cy: int) -> list[tuple[int, int]]:
    return [(cx, cy - TILE_H // 2), (cx + TILE_W // 2, cy),
            (cx, cy + TILE_H // 2), (cx - TILE_W // 2, cy)]


def cross(draw: ImageDraw.ImageDraw, point: tuple[int, int], color: tuple[int, ...], radius: int) -> None:
    x, y = point
    draw.line((x - radius, y, x + radius, y), fill=color, width=2)
    draw.line((x, y - radius, x, y + radius), fill=color, width=2)


def render_panel(terrain: Image.Image, sprite: Image.Image, entry: dict) -> Image.Image:
    panel = Image.new("RGBA", (PANEL_W, PANEL_H), COLORS["panel"])
    draw = ImageDraw.Draw(panel)
    slots = entry["slots"]
    sx, sy, sz = slots["x"], slots["y"], slots["z"]
    center = (PANEL_W // 2, 194)

    reach = max(sx, sy) * 34 + 18
    draw.line((center[0] - reach, center[1] - reach // 2,
               center[0] + reach, center[1] + reach // 2), fill=COLORS["positive"], width=2)
    draw.line((center[0] - reach, center[1] + reach // 2,
               center[0] + reach, center[1] - reach // 2), fill=COLORS["negative"], width=2)

    tiles = []
    for x in range(sx):
        for y in range(sy):
            dx = round((x - (sx - 1) / 2) * 32 - (y - (sy - 1) / 2) * 32)
            dy = round((x - (sx - 1) / 2) * 16 + (y - (sy - 1) / 2) * 16)
            tiles.append((dy, center[0] + dx, center[1] + dy))
    for _, cx, cy in sorted(tiles):
        panel.alpha_composite(terrain, (cx - terrain.width // 2, cy - terrain.width // 4))
    draw = ImageDraw.Draw(panel)
    for _, cx, cy in tiles:
        points = diamond(cx, cy)
        draw.line(points + [points[0]], fill=COLORS["outline"], width=2)

    offset = entry.get("placement_offset") or {"x": 0, "y": 0}
    anchor = (center[0] + int(offset["x"]), center[1] + int(offset["y"]))
    panel.alpha_composite(sprite, (anchor[0] - sprite.width // 2, anchor[1] - sprite.height))
    draw = ImageDraw.Draw(panel)
    cross(draw, center, COLORS["center"], 6)
    draw.ellipse((anchor[0] - 5, anchor[1] - 5, anchor[0] + 5, anchor[1] + 5),
                 outline=COLORS["anchor"], width=2)
    draw.line((center[0], center[1], anchor[0], anchor[1]), fill=COLORS["anchor"], width=1)

    geometry = entry.get("geometry_qa")
    status = (geometry or {}).get("status", "pass").upper()
    status_color = COLORS["review"] if status == "REVIEW" else COLORS["pass"]
    draw.text((18, 14), entry["asset"], font=font(18, True), fill=COLORS["text"])
    badge_box = (PANEL_W - 105, 12, PANEL_W - 18, 39)
    draw.rounded_rectangle(badge_box, radius=5, fill=status_color)
    status_font = font(13, True)
    label_width = draw.textbbox((0, 0), status, font=status_font)[2]
    draw.text((badge_box[0] + (87 - label_width) // 2, 18), status,
              font=status_font, fill=(20, 28, 23, 255))
    method = entry.get("alignment_method") or ("manual" if not entry.get("auto_aligned") else "auto")
    draw.text((18, 45), f"Slots  {sx} x {sy} x {sz}    Align  {method}",
              font=font(13), fill=COLORS["text"])
    if geometry:
        geometry_text = (f"Geometry  expected {geometry['expected_slope']:+.4f}   "
                         f"measured {geometry['measured_slope']:+.4f}   error {geometry['absolute_error']:.4f}")
    else:
        geometry_text = "Geometry  axis not applicable to compact silhouette"
    draw.text((18, 278), geometry_text, font=font(12), fill=COLORS["text"])
    scores = entry.get("exact_axis_scores") or {}
    score_text = (f"Exact axes  +1/2 {scores.get('axis_positive_half', 0):.4f}   "
                  f"-1/2 {scores.get('axis_negative_half', 0):.4f}   "
                  f"vertical {scores.get('vertical', 0):.4f}")
    draw.text((18, 300), score_text, font=font(12), fill=COLORS["muted"])
    draw.text((18, 72), "+1/2", font=font(11, True), fill=COLORS["positive"])
    draw.text((65, 72), "-1/2", font=font(11, True), fill=COLORS["negative"])
    draw.text((116, 72), "+ center", font=font(11), fill=COLORS["center"])
    draw.text((190, 72), "o anchor", font=font(11), fill=COLORS["anchor"])
    return panel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terrain", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    terrain = Image.open(args.terrain).convert("RGBA")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    entries = []
    for entry in manifest["assets"]:
        output = manifest_output(args.manifest, entry)
        if entry.get("asset_type") == "object" and output.is_file():
            entries.append((entry, output))
    entries.sort(key=lambda item: item[0]["asset"])
    if not entries:
        raise ValueError("Manifest has no object entries with an existing output PNG")

    columns = 2
    rows = (len(entries) + columns - 1) // columns
    gap, margin, header = 12, 18, 52
    size = (margin * 2 + columns * PANEL_W + gap,
            margin * 2 + header + rows * PANEL_H + gap * (rows - 1))
    sheet = Image.new("RGBA", size, COLORS["background"])
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 14), "OBJECT GEOMETRY QA", font=font(22, True), fill=COLORS["text"])
    draw.text((margin + 264, 20), "manifest-driven / 64 x 32 isometric grid",
              font=font(12), fill=COLORS["muted"])
    for index, (entry, output) in enumerate(entries):
        panel = render_panel(terrain, Image.open(output).convert("RGBA"), entry)
        x = margin + (index % columns) * (PANEL_W + gap)
        y = margin + header + (index // columns) * (PANEL_H + gap)
        sheet.alpha_composite(panel, (x, y))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, optimize=True)
    print(f"OK: object QA sheet ({len(entries)} objects): {args.output}")


if __name__ == "__main__":
    main()
