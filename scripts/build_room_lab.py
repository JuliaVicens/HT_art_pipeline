#!/usr/bin/env python3
"""Build deterministic wall/floor layers and visual QA for the room lab."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


THEMES = {
    "pastel": {
        "wall_top": "#FFF8EF", "wall_left": "#F2B8B5", "wall_right": "#DFA2AD",
        "floor": "#DDA86F", "floor_alt": "#E7B77F", "floor_line": "#B87D4C", "outline": "#8B6758",
        "wall_detail": "#F7D7D2", "floor_pattern": "checker",
    },
    "modern": {
        "wall_top": "#F7F4EE", "wall_left": "#AABAC5", "wall_right": "#899BA8",
        "floor": "#C79762", "floor_alt": "#D1A371", "floor_line": "#9E7045", "outline": "#596872",
        "wall_detail": "#CFD8DD", "floor_pattern": "planks",
    },
    "gamer": {
        "wall_top": "#F7F2FC", "wall_left": "#BCA9DB", "wall_right": "#9B85C1",
        "floor": "#46424F", "floor_alt": "#514A5C", "floor_line": "#766A82", "outline": "#65567D",
        "wall_detail": "#D8C9EB", "floor_pattern": "grid",
    },
}


def rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4)) + (alpha,)


def polygon_mask(size: tuple[int, int], points: list[tuple[int, int]]) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def iso(layout: dict, x: float, y: float, z: float = 0) -> tuple[int, int]:
    grid = layout["grid"]
    tile_width, tile_height = grid["tile_size"]
    origin_x, origin_y = grid["origin"]
    return (round(origin_x + (x - y) * tile_width / 2),
            round(origin_y + (x + y) * tile_height / 2 - z * grid["elevation_step"]))


def draw_walls(size: tuple[int, int], palette: dict[str, str], layout: dict) -> Image.Image:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cells_x, cells_y = layout["grid"]["floor_cells"]
    height = layout["grid"]["wall_height_cells"]
    band = layout["grid"]["wall_color_band_cells"]
    back, left, right = iso(layout, 0, 0), iso(layout, 0, cells_y), iso(layout, cells_x, 0)
    top_back, top_left, top_right = iso(layout, 0, 0, height), iso(layout, 0, cells_y, height), iso(layout, cells_x, 0, height)
    left_div, back_div, right_div = iso(layout, 0, cells_y, band), iso(layout, 0, 0, band), iso(layout, cells_x, 0, band)

    draw.polygon([top_left, top_back, back, left], fill=rgba(palette["wall_top"]))
    draw.polygon([top_back, top_right, right, back], fill=rgba(palette["wall_top"]))
    draw.polygon([left_div, back_div, back, left], fill=rgba(palette["wall_left"]))
    draw.polygon([back_div, right_div, right, back], fill=rgba(palette["wall_right"]))

    # Sparse, clipped pixel-art accents distinguish themes without changing geometry.
    detail = rgba(palette["wall_detail"])
    for step in range(1, cells_y):
        start = iso(layout, 0, step, band + 0.18)
        end = iso(layout, 0, step + 0.55, band + 0.18)
        draw.line([start, end], fill=detail, width=2)
    for step in range(1, cells_x):
        start = iso(layout, step, 0, band + 0.18)
        end = iso(layout, step + 0.55, 0, band + 0.18)
        draw.line([start, end], fill=detail, width=2)

    outline = rgba(palette["outline"])
    for start, end in [(top_left, top_back), (top_back, top_right), (top_left, left),
                       (top_right, right), (top_back, back), (left, back), (back, right),
                       (left_div, back_div), (back_div, right_div)]:
        draw.line([start, end], fill=outline, width=2)
    return image


def draw_floor(size: tuple[int, int], palette: dict[str, str], layout: dict) -> Image.Image:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    cells_x, cells_y = layout["grid"]["floor_cells"]
    points = [iso(layout, 0, 0), iso(layout, 0, cells_y),
              iso(layout, cells_x, cells_y), iso(layout, cells_x, 0)]
    mask = polygon_mask(size, points)
    texture = Image.new("RGBA", size, rgba(palette["floor"]))
    lines = ImageDraw.Draw(texture)
    line_color = rgba(palette["floor_line"])

    if palette["floor_pattern"] == "checker":
        for x in range(cells_x):
            for y in range(cells_y):
                if (x + y) % 2:
                    lines.polygon([iso(layout, x, y), iso(layout, x + 1, y),
                                   iso(layout, x + 1, y + 1), iso(layout, x, y + 1)],
                                  fill=rgba(palette["floor_alt"]))
    elif palette["floor_pattern"] == "planks":
        for x in range(cells_x):
            for y in range(cells_y):
                if (x + 2 * y) % 3 == 0:
                    a = iso(layout, x + 0.12, y + 0.5)
                    b = iso(layout, x + 0.88, y + 0.5)
                    lines.line([a, b], fill=rgba(palette["floor_alt"]), width=2)
    else:
        for x in range(0, cells_x, 2):
            for y in range(0, cells_y, 2):
                points_cell = [iso(layout, x, y), iso(layout, x + 1, y),
                               iso(layout, x + 1, y + 1), iso(layout, x, y + 1)]
                lines.polygon(points_cell, fill=rgba(palette["floor_alt"]))

    for x in range(cells_x + 1):
        lines.line([iso(layout, x, 0), iso(layout, x, cells_y)], fill=line_color, width=1)
    for y in range(cells_y + 1):
        lines.line([iso(layout, 0, y), iso(layout, cells_x, y)], fill=line_color, width=1)

    image.paste(texture, (0, 0), mask)
    ImageDraw.Draw(image).line(points + [points[0]], fill=rgba(palette["outline"]), width=2)
    return image


def composite(wall: Image.Image, floor: Image.Image) -> Image.Image:
    result = Image.new("RGBA", wall.size, (238, 234, 228, 255))
    result.alpha_composite(wall)
    result.alpha_composite(floor)
    return result


def label_panel(image: Image.Image, label: str) -> Image.Image:
    panel = Image.new("RGBA", (image.width, image.height + 34), (31, 34, 40, 255))
    panel.alpha_composite(image, (0, 34))
    ImageDraw.Draw(panel).text((12, 10), label, fill=(245, 245, 245, 255), font=ImageFont.load_default())
    return panel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    root = args.root.resolve()
    room = root / "rooms" / "bedroom_01"
    layout = json.loads((room / "room_layout.json").read_text(encoding="utf-8"))
    size = tuple(layout["logical_size"])
    assets = room / "assets"
    previews = room / "previews"
    assets.mkdir(parents=True, exist_ok=True)
    previews.mkdir(parents=True, exist_ok=True)

    layers = {}
    panels = []
    room_manifest_path = room / "room_assets_manifest.json"
    room_manifest = (json.loads(room_manifest_path.read_text(encoding="utf-8"))
                     if room_manifest_path.is_file() else {"assets": []})
    room_assets = {entry["asset"]: entry for entry in room_manifest["assets"]}
    room_catalog_path = room / "room_assets.json"
    room_catalog = (json.loads(room_catalog_path.read_text(encoding="utf-8"))
                    if room_catalog_path.is_file() else {"assets": []})
    for theme, palette in THEMES.items():
        wall = draw_walls(size, palette, layout)
        floor = draw_floor(size, palette, layout)
        wall_path = assets / f"wall_{theme}.png"
        floor_path = assets / f"floor_{theme}.png"
        wall.save(wall_path, optimize=True)
        floor.save(floor_path, optimize=True)
        preview = composite(wall, floor)
        preview.save(previews / f"room_{theme}.png", optimize=True)
        layers[theme] = (wall, floor)
        panels.append(label_panel(preview, theme.upper()))

        furnished = preview.copy()
        themed_assets = [entry for entry in room_catalog["assets"] if entry["theme"] == theme]
        themed_assets.sort(key=lambda entry: layout["slots"][entry["slot"]]["z_index"])
        for declaration in themed_assets:
            furniture = room / "assets" / "furniture" / f"{declaration['name']}.png"
            if not furniture.is_file():
                continue
            sprite = Image.open(furniture).convert("RGBA")
            asset = room_assets.get(declaration["name"], {})
            offset = asset.get("placement_offset") or {"x": 0, "y": 0}
            slot = layout["slots"][declaration["slot"]]
            x, y, _ = slot["grid_position"]
            width, depth, _ = slot["slots"]
            anchor = iso(layout, x + width / 2, y + depth / 2)
            anchor = (anchor[0] + int(offset["x"]), anchor[1] + int(offset["y"]))
            furnished.alpha_composite(sprite, (anchor[0] - sprite.width // 2,
                                                anchor[1] - sprite.height))
        furnished.save(previews / f"room_{theme}_furnished.png", optimize=True)

    reference_wall_alpha = layers["pastel"][0].getchannel("A").tobytes()
    reference_floor_alpha = layers["pastel"][1].getchannel("A").tobytes()
    for theme, (wall, floor) in layers.items():
        if wall.getchannel("A").tobytes() != reference_wall_alpha:
            raise ValueError(f"{theme} wall geometry differs from pastel")
        if floor.getchannel("A").tobytes() != reference_floor_alpha:
            raise ValueError(f"{theme} floor geometry differs from pastel")
        for layer_name, layer in (("wall", wall), ("floor", floor)):
            if set(layer.getchannel("A").getdata()) - {0, 255}:
                raise ValueError(f"{theme} {layer_name} alpha is not binary")

    mixed = composite(layers["gamer"][0], layers["pastel"][1])
    mixed.save(previews / "room_mixed_gamer_wall_pastel_floor.png", optimize=True)
    panels.append(label_panel(mixed, "MIXED: GAMER WALL + PASTEL FLOOR"))

    scale = 2
    thumb_size = (size[0] // scale, size[1] // scale + 34)
    thumbs = [panel.resize(thumb_size, Image.Resampling.NEAREST) for panel in panels]
    sheet = Image.new("RGBA", (thumb_size[0] * 2, thumb_size[1] * 2), (22, 24, 29, 255))
    for index, panel in enumerate(thumbs):
        sheet.alpha_composite(panel, ((index % 2) * thumb_size[0], (index // 2) * thumb_size[1]))
    sheet.save(previews / "comparison_montage.png", optimize=True)

    technical = composite(layers["modern"][0], layers["modern"][1])
    draw = ImageDraw.Draw(technical)
    cells_x, cells_y = layout["grid"]["floor_cells"]
    for point, name in [(iso(layout, 0, 0), "grid origin"),
                        (iso(layout, 0, cells_y), "left"),
                        (iso(layout, cells_x, cells_y), "front"),
                        (iso(layout, cells_x, 0), "right")]:
        x, y = point
        draw.line([(x - 6, y), (x + 6, y)], fill=(255, 50, 80, 255), width=2)
        draw.line([(x, y - 6), (x, y + 6)], fill=(255, 50, 80, 255), width=2)
        draw.text((x + 8, y - 10), name, fill=(255, 50, 80, 255), font=ImageFont.load_default())
    technical.save(previews / "room_geometry_qa.png", optimize=True)

    slot_qa = composite(layers["modern"][0], layers["modern"][1])
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    slot_draw = ImageDraw.Draw(overlay)
    slot_colors = {
        "bed_slot": (239, 75, 98, 150),
        "desk_slot": (35, 145, 220, 150),
        "chair_slot": (71, 191, 118, 170),
        "lamp_slot": (245, 166, 35, 170),
        "window_slot": (36, 181, 165, 150),
        "corkboard_slot": (240, 105, 45, 150),
        "shelf_slot": (134, 91, 210, 150),
    }
    drawable_slots = [(name, slot) for name, slot in layout["slots"].items()
                      if name not in {"wall_slot", "floor_slot"}]
    for index, (slot_name, slot) in enumerate(drawable_slots):
        color = slot_colors.get(slot_name, (80 + index * 29 % 150,
                                            110 + index * 41 % 120,
                                            150 + index * 31 % 100, 150))
        if slot["surface"] == "floor":
            x, y, _ = slot["grid_position"]
            width, depth, _ = slot["slots"]
            points = [iso(layout, x, y), iso(layout, x + width, y),
                      iso(layout, x + width, y + depth), iso(layout, x, y + depth)]
            slot_draw.polygon(points, fill=color, outline=color[:3] + (255,), width=2)
            label_x = sum(point[0] for point in points) // len(points)
            label_y = sum(point[1] for point in points) // len(points)
            anchor_x, anchor_y = iso(layout, x + width / 2, y + depth / 2)
        else:
            along, elevation = slot["wall_position"]
            width, _, height = slot["slots"]
            if slot["surface"] == "left_wall":
                lower_a, lower_b = iso(layout, 0, along, elevation), iso(layout, 0, along + width, elevation)
                upper_b, upper_a = iso(layout, 0, along + width, elevation + height), iso(layout, 0, along, elevation + height)
            else:
                lower_a, lower_b = iso(layout, along, 0, elevation), iso(layout, along + width, 0, elevation)
                upper_b, upper_a = iso(layout, along + width, 0, elevation + height), iso(layout, along, 0, elevation + height)
            points = [lower_a, lower_b, upper_b, upper_a]
            slot_draw.polygon(points, fill=color, outline=color[:3] + (255,), width=2)
            label_x = sum(point[0] for point in points) // len(points)
            label_y = sum(point[1] for point in points) // len(points)
            anchor_x = (lower_a[0] + lower_b[0]) // 2
            anchor_y = (lower_a[1] + lower_b[1]) // 2
        slot_draw.line([(anchor_x - 5, anchor_y), (anchor_x + 5, anchor_y)],
                       fill=(255, 255, 255, 255), width=2)
        slot_draw.line([(anchor_x, anchor_y - 5), (anchor_x, anchor_y + 5)],
                       fill=(255, 255, 255, 255), width=2)
        slot_draw.text((label_x - 30, label_y - 6), slot_name,
                       fill=(20, 20, 24, 255), font=ImageFont.load_default())
    slot_qa.alpha_composite(overlay)
    slot_qa.save(previews / "room_slots_qa.png", optimize=True)
    print(f"OK: room lab built at {room}")


if __name__ == "__main__":
    main()
