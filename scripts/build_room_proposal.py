#!/usr/bin/env python3
"""Validate and render an AI-authored modular room proposal without promoting it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from build_room_lab import iso, slot_anchor, wall_slot_points


COLORS = {
    "planned": (255, 166, 54, 130),
    "suggested": (40, 205, 205, 130),
    "outline": (255, 255, 255, 255),
}
OBJECT_COLORS = [
    (35, 196, 220, 120), (255, 153, 51, 120), (234, 76, 137, 120),
    (105, 205, 120, 120), (146, 100, 220, 120), (250, 205, 70, 120),
    (65, 135, 235, 120), (230, 95, 70, 120), (85, 200, 175, 120),
]


def overlaps(a: dict, b: dict) -> bool:
    if a["surface"] != b["surface"]:
        return False
    nonblocking = {"floor_covering", "wall_accessory"}
    if a.get("collision_group", "solid") in nonblocking or b.get("collision_group", "solid") in nonblocking:
        return False
    if a["surface"] == "floor":
        ax, ay, _ = a["grid_position"]
        bx, by, _ = b["grid_position"]
        aw, ad, _ = a["slots"]
        bw, bd, _ = b["slots"]
        return ax < bx + bw and bx < ax + aw and ay < by + bd and by < ay + ad
    aa, az = a["wall_position"]
    ba, bz = b["wall_position"]
    aw, _, ah = a["slots"]
    bw, _, bh = b["slots"]
    return aa < ba + bw and ba < aa + aw and az < bz + bh and bz < az + ah


def validate(proposal: dict, layout: dict) -> list[str]:
    errors: list[str] = []
    room_contract = proposal.get("room_contract", {})
    expected_room = {
        "projection": layout["grid"]["projection"],
        "tile_size": layout["grid"]["tile_size"],
        "floor_cells": layout["grid"]["floor_cells"],
        "wall_height_cells": layout["grid"]["wall_height_cells"],
        "containment": "strict_slot",
        "concept_image_is_authoritative": False,
        "room_layout_is_authoritative": True,
    }
    for key, expected in expected_room.items():
        if room_contract.get(key) != expected:
            errors.append(f"room_contract.{key} must match {expected!r}")
    contract = proposal.get("asset_contract", {})
    required_contract = {
        "kind": "modular_object",
        "generation_unit": "individual",
        "transparent_background": True,
        "position_owned_by_layout": True,
        "allow_baked_room_position": False,
        "allow_surrounding_wall_or_floor": False,
        "allow_unlisted_companion_objects": False,
        "objects_array_contains_only_individual_objects": True,
    }
    for key, expected in required_contract.items():
        if contract.get(key) != expected:
            errors.append(f"asset_contract.{key} must be {expected!r}")
    floor_x, floor_y = layout["grid"]["floor_cells"]
    wall_height = layout["grid"]["wall_height_cells"]
    objects = proposal["objects"]
    ids = [item["id"] for item in objects]
    if len(ids) != len(set(ids)):
        errors.append("Object ids must be unique")
    for item in objects:
        width, depth, height = item["slots"]
        if item["surface"] == "floor":
            x, y, z = item["grid_position"]
            if min(x, y, z, width, depth, height) < 0 or x + width > floor_x or y + depth > floor_y:
                errors.append(f"{item['id']}: floor bounds exceeded")
        elif item["surface"] in {"left_wall", "right_wall"}:
            along, elevation = item["wall_position"]
            wall_length = floor_y if item["surface"] == "left_wall" else floor_x
            expected = "wall_left" if item["surface"] == "left_wall" else "wall_right"
            if item.get("orientation") != expected:
                errors.append(f"{item['id']}: orientation must be {expected}")
            if min(along, elevation, width, height) < 0 or along + width > wall_length or elevation + height > wall_height:
                errors.append(f"{item['id']}: wall bounds exceeded")
        else:
            errors.append(f"{item['id']}: unsupported surface")
    for index, left in enumerate(objects):
        for right in objects[index + 1:]:
            if overlaps(left, right):
                errors.append(f"collision: {left['id']} / {right['id']}")
    return errors


def density_metrics(proposal: dict, layout: dict) -> dict:
    floor_x, floor_y = layout["grid"]["floor_cells"]
    policy = proposal.get("density_policy", {})
    wall_min, wall_max = policy.get("wall_elevation_range", [1, layout["grid"]["wall_height_cells"]])
    floor_occupied: set[tuple[int, int]] = set()
    blocked: set[tuple[int, int]] = set()
    wall_occupied: set[tuple[str, int, int]] = set()
    for item in proposal["objects"]:
        width, depth, height = item["slots"]
        if item["surface"] == "floor":
            x, y, _ = item["grid_position"]
            cells = {(cx, cy) for cx in range(x, x + width) for cy in range(y, y + depth)}
            floor_occupied.update(cells)
            if item.get("collision_group", "solid") != "floor_covering":
                blocked.update(cells)
        else:
            along, elevation = item["wall_position"]
            for column in range(along, along + width):
                for row in range(max(elevation, wall_min), min(elevation + height, wall_max)):
                    wall_occupied.add((item["surface"], column, row))

    perimeter = {(x, 0) for x in range(floor_x)} | {(0, y) for y in range(floor_y)}
    free = {(x, y) for x in range(floor_x) for y in range(floor_y)} - blocked
    connected: set[tuple[int, int]] = set()
    if free:
        pending = [max(free, key=lambda cell: cell[0] + cell[1])]
        while pending:
            cell = pending.pop()
            if cell in connected:
                continue
            connected.add(cell)
            x, y = cell
            pending.extend(candidate for candidate in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                           if candidate in free and candidate not in connected)
    wall_capacity = (floor_x + floor_y) * max(0, wall_max - wall_min)
    return {
        "near_wall_floor_coverage": round(len(floor_occupied & perimeter) / len(perimeter), 4),
        "floor_coverage": round(len(floor_occupied) / (floor_x * floor_y), 4),
        "wall_coverage": round(len(wall_occupied) / wall_capacity, 4) if wall_capacity else 0.0,
        "walkway_connected": connected == free,
        "walkable_cells": len(free),
    }


def density_errors(proposal: dict, metrics: dict) -> list[str]:
    policy = proposal.get("density_policy", {})
    checks = (
        ("near_wall_floor_coverage", "near_wall_floor_target"),
        ("floor_coverage", "minimum_floor_coverage"),
        ("wall_coverage", "minimum_wall_coverage"),
    )
    errors = [f"density: {metric} {metrics[metric]:.2%} < {policy[target]:.2%}"
              for metric, target in checks if target in policy and metrics[metric] < policy[target]]
    if policy.get("require_continuous_walkway") and not metrics["walkway_connected"]:
        errors.append("density: walkway is not continuous")
    return errors


def polygon(layout: dict, item: dict) -> list[tuple[int, int]]:
    if item["surface"] == "floor":
        x, y, _ = item["grid_position"]
        width, depth, _ = item["slots"]
        return [iso(layout, x, y), iso(layout, x + width, y),
                iso(layout, x + width, y + depth), iso(layout, x, y + depth)]
    return wall_slot_points(layout, item)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--room", required=True)
    parser.add_argument("--proposal", default="room_plan.proposal.json")
    parser.add_argument("--output-stem", default="room_proposal")
    args = parser.parse_args()
    room = args.root.resolve() / "rooms" / args.room
    proposal_path = room / args.proposal
    layout = json.loads((room / "room_layout.json").read_text(encoding="utf-8"))
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    if proposal.get("status") != "proposal":
        raise ValueError("Design input must remain an unapproved proposal")
    metrics = density_metrics(proposal, layout)
    errors = validate(proposal, layout) + density_errors(proposal, metrics)
    report = {
        "schema_version": 1,
        "proposal": proposal_path.name,
        "objects": len(proposal["objects"]),
        "individual_modular_objects": len(proposal["objects"]),
        "room_bounds": proposal["room_contract"],
        "existing": sum(item["asset_status"] == "existing" for item in proposal["objects"]),
        "planned": sum(item["asset_status"] == "planned" for item in proposal["objects"]),
        "suggested": sum(item["asset_status"] == "suggested" for item in proposal["objects"]),
        "density": metrics,
        "errors": errors,
        "status": "pass" if not errors else "fail",
    }
    previews = room / "previews"
    previews.mkdir(parents=True, exist_ok=True)
    (previews / f"{args.output_stem}_qa.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise ValueError("Invalid room proposal: " + "; ".join(errors))

    panels = []
    size = tuple(layout["logical_size"])
    catalog = json.loads((room / "room_assets.json").read_text(encoding="utf-8"))
    manifest = json.loads((room / "room_assets_manifest.json").read_text(encoding="utf-8"))
    manifest_by_name = {entry["asset"]: entry for entry in manifest["assets"]}
    for theme in proposal["themes"]:
        base_path = previews / f"room_{theme}.png"
        image = Image.open(base_path).convert("RGBA")
        declarations = {(entry["slot"], entry["theme"]): entry for entry in catalog["assets"]}
        for item in sorted(proposal["objects"], key=lambda value: value["z_index"]):
            if item["asset_status"] != "existing":
                continue
            declaration = declarations.get((item["slot"], theme))
            if not declaration:
                continue
            sprite_path = room / "assets" / "furniture" / f"{declaration['name']}.png"
            asset = manifest_by_name.get(declaration["name"], {})
            if not sprite_path.is_file():
                continue
            sprite = Image.open(sprite_path).convert("RGBA")
            anchor = slot_anchor(layout, item)
            offset = asset.get("placement_offset") or {"x": 0, "y": 0}
            local_anchor = asset.get("anchor") or [sprite.width // 2, sprite.height]
            image.alpha_composite(
                sprite,
                (anchor[0] + int(offset["x"]) - int(local_anchor[0]),
                 anchor[1] + int(offset["y"]) - int(local_anchor[1])),
            )
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        proposal_objects = sorted(proposal["objects"], key=lambda value: value["z_index"])
        for object_index, item in enumerate(proposal_objects):
            if item["asset_status"] == "existing":
                continue
            points = polygon(layout, item)
            color = (OBJECT_COLORS[object_index % len(OBJECT_COLORS)]
                     if proposal.get("visualization") == "object_colors"
                     else COLORS[item["asset_status"]])
            draw.polygon(points, fill=color, outline=COLORS["outline"], width=2)
            cx = sum(x for x, _ in points) // len(points)
            cy = sum(y for _, y in points) // len(points)
            draw.text((cx - 24, cy - 5), f"OBJ:{item['id']}",
                      fill=(20, 20, 24, 255), font=ImageFont.load_default())
        image.alpha_composite(overlay)
        theme_output = (f"room_{theme}_proposal.png" if args.output_stem == "room_proposal"
                        else f"{args.output_stem}_{theme}_slots.png")
        image.save(previews / theme_output, optimize=True)
        panels.append(image.resize((size[0] // 2, size[1] // 2), Image.Resampling.NEAREST))

    sheet = Image.new("RGBA", (len(panels) * size[0] // 2, size[1] // 2 + 28), (22, 24, 29, 255))
    sheet_draw = ImageDraw.Draw(sheet)
    sheet_draw.text((10, 8), "AI ROOM PROPOSAL  OBJ=individual modular asset  orange=planned  cyan=suggested",
                    fill=(245, 245, 245, 255), font=ImageFont.load_default())
    for index, panel in enumerate(panels):
        sheet.alpha_composite(panel, (index * size[0] // 2, 28))
    sheet_output = ("room_proposal_montage.png" if args.output_stem == "room_proposal"
                    else f"{args.output_stem}_slots.png")
    sheet.save(previews / sheet_output, optimize=True)
    print(f"OK: {args.room} proposal ({report['objects']} objects, QA PASS)")


if __name__ == "__main__":
    main()
