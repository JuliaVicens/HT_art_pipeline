#!/usr/bin/env python3
"""Compose an approved room from layout slots and independent asset sprites."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from build_room_lab import slot_anchor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--room", default="bedroom_01")
    parser.add_argument("--proposal", default="room_reference_layout.proposal.json")
    parser.add_argument("--theme", default="pastel")
    parser.add_argument("--output", default="room_approved_pastel.png")
    args = parser.parse_args()

    root = args.root.resolve()
    room = root / "rooms" / args.room
    proposal = json.loads((room / args.proposal).read_text(encoding="utf-8"))
    layout = json.loads((room / "room_layout.json").read_text(encoding="utf-8"))
    catalog = json.loads((room / "room_assets.json").read_text(encoding="utf-8"))
    manifest = json.loads((room / "room_assets_manifest.json").read_text(encoding="utf-8"))
    if args.theme not in proposal["themes"]:
        raise ValueError(f"Theme is not declared by proposal: {args.theme}")

    base = room / "previews" / f"room_{args.theme}.png"
    if not base.is_file():
        raise ValueError(f"Missing room base layer: {base}")
    image = Image.open(base).convert("RGBA")
    declarations = {(item["object_id"], item["theme"]): item for item in catalog["assets"]}
    manifest_by_name = {item["asset"]: item for item in manifest["assets"]}
    missing = []
    for item in sorted(proposal["objects"], key=lambda value: value["z_index"]):
        declaration = declarations.get((item["id"], args.theme))
        if declaration is None:
            missing.append(f"{item['id']}: catalog declaration")
            continue
        asset = manifest_by_name.get(declaration["name"])
        sprite_path = room / "assets" / "furniture" / f"{declaration['name']}.png"
        if asset is None or not sprite_path.is_file():
            missing.append(f"{item['id']}: normalized asset")
            continue
        for qa_key in ("geometry_qa", "containment_qa"):
            if (asset.get(qa_key) or {}).get("status") == "review":
                raise ValueError(f"Asset QA is REVIEW: {declaration['name']} ({qa_key})")
        sprite = Image.open(sprite_path).convert("RGBA")
        anchor = slot_anchor(layout, item)
        offset = asset.get("placement_offset") or {"x": 0, "y": 0}
        local_anchor = asset.get("anchor") or [sprite.width // 2, sprite.height]
        image.alpha_composite(sprite, (anchor[0] + int(offset["x"]) - int(local_anchor[0]),
                                        anchor[1] + int(offset["y"]) - int(local_anchor[1])))
    if missing:
        raise ValueError("Approved room has incomplete assets: " + ", ".join(missing))

    output = room / "previews" / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, optimize=True)
    print(f"OK: approved room composed ({len(proposal['objects'])} objects): {output}")


if __name__ == "__main__":
    main()