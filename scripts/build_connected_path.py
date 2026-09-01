#!/usr/bin/env python3
"""Build a connection-safe straight path over an approved grass tile."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


def rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--palette", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", type=Path,
                        help="Update the asset catalog with the generated path")
    parser.add_argument("--half-width", type=int, default=4)
    args = parser.parse_args()
    tile = Image.open(args.base).convert("RGBA")
    spec = json.loads(args.palette.read_text(encoding="utf-8"))
    colors = {item["name"]: rgb(item["hex"]) for item in spec["colors"]}
    peach, clay, cream = colors["peach"], colors["clay"], colors["cream"]
    width, depth = tile.width, tile.width // 2
    pixels = tile.load()
    cx, cy = (width - 1) / 2, (depth - 1) / 2
    for y in range(depth):
        for x in range(width):
            inside = abs(x - cx) / (width / 2) + abs(y - cy) / (depth / 2) <= 1
            # NW->SE world-axis line: x - 2y = 0. Adjacent tiles shifted
            # by (32,16) preserve the same equation exactly.
            if inside and abs(x - 2 * y) <= args.half_width:
                color = peach
                if (x * 7 + y * 11) % 23 == 0:
                    color = cream
                elif (x * 5 + y * 3) % 17 == 0:
                    color = clay
                pixels[x, y] = (*color, 255)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tile.save(args.output, optimize=True)
    if args.manifest:
        height = tile.height - depth
        entry = {
            "asset": args.output.stem,
            "asset_type": "terrain",
            "segmentation": "generated_exact_path",
            "top_inset": None,
            "tiling": "exact_connected",
            "projection": "canonical_2_to_1",
            "side_mode": "inherited",
            "edge_blend": 0,
            "seam_score": 0,
            "source": args.base.resolve().as_posix(),
            "output": args.output.resolve().as_posix(),
            "palette": spec["id"],
            "palette_version": spec["version"],
            "dimensions": {"width": width, "depth": depth, "height": height},
            "slots": None,
            "canvas_size": list(tile.size),
            "generation_method": "exact_connected_path",
            "path_equation": "x-2y=0",
            "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest = {"schema_version": 1, "assets": []}
        if args.manifest.is_file():
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        manifest["assets"] = [item for item in manifest.get("assets", [])
                              if item.get("asset") != entry["asset"]]
        manifest["assets"].append(entry)
        manifest["assets"].sort(key=lambda item: item["asset"])
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"OK: exact NW-SE path, equation x-2y=0, output: {args.output}")


if __name__ == "__main__":
    main()
