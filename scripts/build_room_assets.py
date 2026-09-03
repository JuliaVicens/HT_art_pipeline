#!/usr/bin/env python3
"""Normalize declared room furniture variants into deterministic slot sprites."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    root = args.root.resolve()
    room = root / "rooms" / "bedroom_01"
    catalog = json.loads((room / "room_assets.json").read_text(encoding="utf-8"))
    layout = json.loads((room / "room_layout.json").read_text(encoding="utf-8"))
    manifest = room / "room_assets_manifest.json"
    if manifest.exists():
        manifest.unlink()
    output = room / "assets" / "furniture"
    output.mkdir(parents=True, exist_ok=True)
    for entry in catalog["assets"]:
        source = room / "sources" / f"{entry['name']}.source.png"
        if not source.is_file():
            raise ValueError(f"Missing room source: {source.name}")
        slot = layout["slots"][entry["slot"]]
        is_wall = slot["surface"] in {"left_wall", "right_wall"}
        command = [
            sys.executable, str(root / "scripts" / "normalize_asset.py"), str(source),
            "--palette", str(root / "palettes" / f"bedroom_{entry['theme']}.json"),
            "--output", str(output / f"{entry['name']}.png"),
            "--manifest", str(manifest), "--asset-type", "wall_object" if is_wall else "object",
            "--slots", *(str(value) for value in entry["slots"]),
            "--object-scale", str(entry.get("object_scale", 0.8)),
        ]
        if is_wall:
            command.extend(["--wall-orientation", slot["orientation"]])
        else:
            command.extend(["--auto-align-object", "--geometry-locked"])
        subprocess.run(command, check=True)
    terrain = next(iter(sorted((root / "output").glob("*grass*.png"))), None)
    if terrain:
        subprocess.run([
            sys.executable, str(root / "scripts" / "render_object_qa.py"),
            "--terrain", str(terrain), "--manifest", str(manifest),
            "--output", str(room / "previews" / "furniture_qa.png")], check=True)
    print(f"OK: room furniture built ({len(catalog['assets'])} variants)")


if __name__ == "__main__":
    main()
