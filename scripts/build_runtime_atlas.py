#!/usr/bin/env python3
"""Build and validate deterministic runtime atlases from the asset manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


CATALOG_VERSION = 1
PADDING = 2
MAX_WIDTH = 512


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review_reasons(entry: dict) -> list[str]:
    reasons = []
    if entry.get("segmentation") == "estimated":
        reasons.append("estimated segmentation")
    for field in ("geometry_qa", "containment_qa"):
        if (entry.get(field) or {}).get("status") == "review":
            reasons.append(field)
    return reasons


def output_path(root: Path, entry: dict) -> Path:
    path = Path(entry["output"])
    candidates = (path, root / path, root / "output" / f"{entry['asset']}.png")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"Missing output for {entry['asset']}")


def pack(entries: list[dict], root: Path) -> tuple[list[dict], tuple[int, int]]:
    packed = []
    x = y = PADDING
    row_height = 0
    used_right = PADDING
    for entry in entries:
        path = output_path(root, entry)
        with Image.open(path) as source:
            width, height = source.size
        if width + PADDING * 2 > MAX_WIDTH:
            raise ValueError(f"{entry['asset']} is wider than the atlas packing width")
        if x > PADDING and x + width + PADDING > MAX_WIDTH:
            x = PADDING
            y += row_height + PADDING
            row_height = 0
        packed.append({"manifest": entry, "path": path, "x": x, "y": y,
                       "width": width, "height": height})
        x += width + PADDING
        row_height = max(row_height, height)
        used_right = max(used_right, x)
    return packed, (max(1, used_right), max(1, y + row_height + PADDING))


def validate(atlas: Image.Image, packed: list[dict], catalog: dict) -> None:
    if atlas.mode != "RGBA":
        raise ValueError("Atlas must be RGBA")
    alpha = atlas.getchannel("A")
    if set(alpha.getdata()) - {0, 255}:
        raise ValueError("Atlas transparency is not binary")

    occupied: list[tuple[int, int, int, int]] = []
    for item, record in zip(packed, catalog["assets"], strict=True):
        rect = (item["x"], item["y"], item["x"] + item["width"], item["y"] + item["height"])
        if any(rect[0] < other[2] and rect[2] > other[0] and
               rect[1] < other[3] and rect[3] > other[1] for other in occupied):
            raise ValueError(f"Overlapping atlas rectangle: {item['manifest']['asset']}")
        occupied.append(rect)
        with Image.open(item["path"]) as source:
            expected = source.convert("RGBA")
        if atlas.crop(rect).tobytes() != expected.tobytes():
            raise ValueError(f"Atlas pixels differ from {item['manifest']['asset']}")
        expected_record = (item["x"], item["y"], item["width"], item["height"])
        actual_record = (record["x"], record["y"], record["width"], record["height"])
        if expected_record != actual_record:
            raise ValueError(f"Catalog rectangle mismatch: {record['name']}")

    for py in range(atlas.height):
        for px in range(atlas.width):
            if not any(left <= px < right and top <= py < bottom
                       for left, top, right, bottom in occupied) and alpha.getpixel((px, py)) != 0:
                raise ValueError(f"Non-transparent padding pixel at {px},{py}")


def build_catalog(root: Path, manifest_entries: list[dict], include_review: bool,
                  png_path: Path, json_path: Path) -> tuple[list[dict], dict]:
    selected = []
    for entry in sorted(manifest_entries, key=lambda item: item["asset"]):
        reasons = review_reasons(entry)
        if include_review or not reasons:
            selected.append(entry)
    packed, size = pack(selected, root)
    atlas = Image.new("RGBA", size, (0, 0, 0, 0))
    records = []
    for item in packed:
        entry = item["manifest"]
        reasons = review_reasons(entry)
        with Image.open(item["path"]) as source:
            sprite = source.convert("RGBA")
        if set(sprite.getchannel("A").getdata()) - {0, 255}:
            raise ValueError(f"{entry['asset']} does not have binary transparency")
        # No mask: preserve even RGB values hidden beneath fully transparent pixels.
        atlas.paste(sprite, (item["x"], item["y"]))
        sprite_checksum = sha256(item["path"])
        if entry.get("sha256") and entry["sha256"] != sprite_checksum:
            raise ValueError(f"Manifest checksum mismatch: {entry['asset']}")
        records.append({
            "name": entry["asset"], "type": entry["asset_type"],
            "x": item["x"], "y": item["y"], "width": item["width"], "height": item["height"],
            "slots": entry.get("slots"), "anchor": entry.get("anchor"),
            "placement_offset": entry.get("placement_offset"),
            "ground_contact": entry.get("ground_contact"),
            "status": "REVIEW" if reasons else "PASS", "review_reasons": reasons,
            "sprite_sha256": sprite_checksum, "catalog_version": CATALOG_VERSION,
        })
    catalog = {
        "catalog_version": CATALOG_VERSION, "atlas": png_path.name,
        "atlas_width": atlas.width, "atlas_height": atlas.height,
        "padding": PADDING, "packing": "name_sorted_shelf_v1",
        "includes_review": include_review, "assets": records,
    }
    validate(atlas, packed, catalog)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(png_path, format="PNG", optimize=True)
    catalog["atlas_sha256"] = sha256(png_path)
    json_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    # Re-open serialized artifacts so validation covers the actual runtime files.
    saved_catalog = json.loads(json_path.read_text(encoding="utf-8"))
    with Image.open(png_path) as saved:
        validate(saved.convert("RGBA"), packed, saved_catalog)
    if saved_catalog["atlas_sha256"] != sha256(png_path):
        raise ValueError("Saved atlas checksum mismatch")
    return packed, catalog


def render_qa(review_png: Path, packed: list[dict], output: Path) -> None:
    with Image.open(review_png) as source:
        atlas = source.convert("RGBA")
    scale = 3
    atlas = atlas.resize((atlas.width * scale, atlas.height * scale), Image.Resampling.NEAREST)
    header = 28
    sheet = Image.new("RGBA", (atlas.width, atlas.height + header), (28, 31, 38, 255))
    sheet.alpha_composite(atlas, (0, header))
    draw = ImageDraw.Draw(sheet)
    draw.text((6, 7), "Nature runtime atlas QA - PASS / REVIEW", fill=(240, 240, 240, 255))
    for item in packed:
        reasons = review_reasons(item["manifest"])
        color = (239, 91, 91, 255) if reasons else (83, 210, 124, 255)
        x, y = item["x"] * scale, item["y"] * scale + header
        width, height = item["width"] * scale, item["height"] * scale
        draw.rectangle((x - 1, y - 1, x + width, y + height), outline=color, width=2)
        label = f"{item['manifest']['asset']} {'REVIEW' if reasons else 'PASS'}"
        draw.text((x + 2, y + 2), label, fill=color, stroke_width=2, stroke_fill=(20, 20, 20, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    runtime = root / "runtime"
    _, production = build_catalog(root, manifest["assets"], False,
                                  runtime / "nature_atlas.png", runtime / "nature_atlas.json")
    review_packed, review = build_catalog(root, manifest["assets"], True,
                                         runtime / "nature_atlas_review.png",
                                         runtime / "nature_atlas_review.json")
    render_qa(runtime / "nature_atlas_review.png", review_packed,
              root / "qa" / "nature_atlas_montage.png")
    print(f"OK: runtime atlases: {len(production['assets'])} production, "
          f"{len(review['assets'])} review-inclusive")


if __name__ == "__main__":
    main()
