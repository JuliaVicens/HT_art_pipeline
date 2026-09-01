#!/usr/bin/env python3
"""Build one terrain or object using the project's safe production defaults."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def asset_name(source: Path) -> str:
    name = source.stem
    if name.endswith(".source"):
        name = name[:-len(".source")]
    return name


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Input PNG; .source.png is optional")
    parser.add_argument("--slots", type=int, nargs=3, metavar=("X", "Y", "Z"),
                        help="Declares an object and its X Y Z slot dimensions")
    parser.add_argument("--height", type=int,
                        help="Terrain elevation; defaults to 0 for water names and 8 otherwise")
    parser.add_argument("--object-scale", type=float, default=0.8,
                        help="Uniform object fit within its slots (default: 0.8)")
    parser.add_argument("--ground-contact", type=float, nargs=2, metavar=("X", "Y"),
                        help="Normalized semantic contact override for an object")
    parser.add_argument("--skip-qa", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent,
                        help=argparse.SUPPRESS)
    args = parser.parse_args()

    root = args.root.resolve()
    source = args.source.resolve()
    if not source.is_file():
        parser.error(f"source not found: {source}")
    if source.suffix.lower() != ".png":
        parser.error("source must be a PNG")
    name = asset_name(source)
    output = root / "output" / f"{name}.png"
    manifest = root / "manifest.json"
    palette = root / "palettes" / "nature.json"
    normalizer = root / "scripts" / "normalize_asset.py"
    command = [
        sys.executable, str(normalizer), str(source),
        "--palette", str(palette), "--output", str(output),
        "--manifest", str(manifest), "--width", "64", "--depth", "32",
    ]

    if args.slots:
        if min(args.slots) < 1:
            parser.error("all slot dimensions must be at least 1")
        command += [
            "--height", "64", "--asset-type", "object",
            "--slots", *(str(value) for value in args.slots),
            "--object-scale", str(args.object_scale),
            "--auto-align-object", "--geometry-locked",
        ]
        if args.ground_contact:
            command += ["--ground-contact", *(str(value) for value in args.ground_contact)]
    else:
        height = args.height if args.height is not None else (0 if "water" in name else 8)
        command += [
            "--height", str(height), "--asset-type", "terrain",
            "--tiling", "none", "--projection", "legacy",
            "--side-mode", "palette", "--edge-blend", "2",
            "--qa-dir", str(root / "qa"),
        ]
    run(command)

    if args.skip_qa:
        pass
    elif args.slots:
        output_dir = root / "output"
        terrain_candidates = [output_dir / "nature_grass_01.png"]
        terrain_candidates += sorted(output_dir.glob("*grass*.png"))
        terrain_candidates += sorted(output_dir.glob("*.png"))
        terrain = next((path for path in terrain_candidates if path.is_file()), None)
        if terrain:
            run([
                sys.executable, str(root / "scripts" / "render_object_qa.py"),
                "--terrain", str(terrain), "--manifest", str(manifest),
                "--output", str(root / "qa" / "objects_current_montage.png"),
            ])
        else:
            print("REVIEW: object built; object sheet skipped because no terrain output exists")
    else:
        run([
            sys.executable, str(root / "scripts" / "validate_tileset.py"), str(output),
            "--output", str(root / "qa" / f"{name}_montage.png"),
        ])
    print(f"OK: automatic {'object' if args.slots else 'terrain'} build complete: {name}")


if __name__ == "__main__":
    main()
