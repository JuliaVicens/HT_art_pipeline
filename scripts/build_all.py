#!/usr/bin/env python3
"""Discover every declared source and rebuild the complete local asset collection."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


OBJECT_KEYS = {"schema_version", "slots", "object_scale", "ground_contact", "enabled"}
TERRAIN_KEYS = {"schema_version", "height", "enabled"}


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def load_config(path: Path, allowed: set[str]) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"Unknown fields in {path.name}: {', '.join(sorted(unknown))}")
    return data


def source_for_config(config: Path, suffix: str) -> Path:
    return config.with_name(config.name.removesuffix(suffix) + ".source.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    root = args.root.resolve()
    sources = root / "sources"
    output = root / "output"
    qa = root / "qa"
    manifest_path = root / "manifest.json"
    output.mkdir(parents=True, exist_ok=True)
    qa.mkdir(parents=True, exist_ok=True)

    # Only derived PNGs are disposable. Sources and JSON declarations are never removed.
    for directory in (output, qa):
        for path in directory.glob("*.png"):
            path.unlink()
    manifest_path.write_text('{\n  "schema_version": 1,\n  "assets": []\n}\n', encoding="utf-8")

    object_configs = {}
    for config_path in sorted(sources.glob("*.object.json")):
        source = source_for_config(config_path, ".object.json")
        if not source.is_file():
            raise ValueError(f"Object declaration has no source PNG: {config_path.name}")
        config = load_config(config_path, OBJECT_KEYS)
        slots = config.get("slots")
        if not isinstance(slots, list) or len(slots) != 3 or any(not isinstance(v, int) or v < 1 for v in slots):
            raise ValueError(f"{config_path.name}: slots must contain three positive integers")
        scale = config.get("object_scale", 0.8)
        if not isinstance(scale, (int, float)) or not 0.1 <= scale <= 1.0:
            raise ValueError(f"{config_path.name}: object_scale must be between 0.1 and 1.0")
        contact = config.get("ground_contact")
        if contact is not None and (not isinstance(contact, dict)
                                    or set(contact) != {"x", "y"}
                                    or any(not isinstance(contact[key], (int, float))
                                           or not 0 <= contact[key] <= 1 for key in ("x", "y"))):
            raise ValueError(f"{config_path.name}: ground_contact needs x/y values between 0 and 1")
        object_configs[source.resolve()] = (config_path, config)

    terrain_configs = {}
    for config_path in sorted(sources.glob("*.terrain.json")):
        source = source_for_config(config_path, ".terrain.json")
        if not source.is_file():
            raise ValueError(f"Terrain declaration has no source PNG: {config_path.name}")
        config = load_config(config_path, TERRAIN_KEYS)
        height = config.get("height")
        if height is not None and (not isinstance(height, int) or height < 0):
            raise ValueError(f"{config_path.name}: height must be a non-negative integer")
        terrain_configs[source.resolve()] = (config_path, config)

    all_sources = sorted(path.resolve() for path in sources.glob("*.source.png"))
    terrain_sources = [path for path in all_sources if path not in object_configs]
    object_sources = [path for path in all_sources if path in object_configs]
    builder = root / "scripts" / "build_asset.py"

    built_terrains = []
    for source in terrain_sources:
        config = terrain_configs.get(source, (None, {}))[1]
        if config.get("enabled", True) is False:
            continue
        command = [sys.executable, str(builder), str(source), "--root", str(root), "--skip-qa"]
        if "height" in config:
            command += ["--height", str(config["height"])]
        run(command)
        built_terrains.append(output / f"{source.name.removesuffix('.source.png')}.png")

    built_objects = []
    for source in object_sources:
        config = object_configs[source][1]
        if config.get("enabled", True) is False:
            continue
        command = [
            sys.executable, str(builder), str(source), "--root", str(root), "--skip-qa",
            "--slots", *(str(value) for value in config["slots"]),
            "--object-scale", str(config.get("object_scale", 0.8)),
        ]
        if "ground_contact" in config:
            contact = config["ground_contact"]
            command += ["--ground-contact", str(contact["x"]), str(contact["y"])]
        run(command)
        built_objects.append(output / f"{source.name.removesuffix('.source.png')}.png")

    validator = root / "scripts" / "validate_tileset.py"
    for terrain in built_terrains:
        run([sys.executable, str(validator), str(terrain),
             "--output", str(qa / f"{terrain.stem}_montage.png")])

    if built_objects:
        grass = next((path for path in built_terrains if "grass" in path.stem), None)
        terrain = grass or (built_terrains[0] if built_terrains else None)
        if terrain is None:
            raise ValueError("Object QA requires at least one enabled terrain source")
        run([sys.executable, str(root / "scripts" / "render_object_qa.py"),
             "--terrain", str(terrain), "--manifest", str(manifest_path),
             "--output", str(qa / "objects_current_montage.png")])

    run([sys.executable, str(root / "scripts" / "build_runtime_atlas.py"),
         "--root", str(root)])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reviews = []
    for entry in manifest["assets"]:
        reasons = []
        if entry.get("segmentation") == "estimated":
            reasons.append("estimated segmentation")
        for field in ("geometry_qa", "containment_qa"):
            if (entry.get(field) or {}).get("status") == "review":
                reasons.append(field)
        status = "REVIEW" if reasons else "PASS"
        print(f"{status}: {entry['asset']}" + (f" ({', '.join(reasons)})" if reasons else ""))
        if reasons:
            reviews.append(entry["asset"])
    print(f"OK: discovered build complete: {len(built_terrains)} terrain, "
          f"{len(built_objects)} objects, {len(reviews)} review")


if __name__ == "__main__":
    main()
