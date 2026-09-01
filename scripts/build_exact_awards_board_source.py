#!/usr/bin/env python3
"""Build a decorative awards board on exact 2:1 isometric axes."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--art-source", type=Path,
                        help="Optional rich awards-board reference mapped into the exact frame")
    args = parser.parse_args()
    s = args.scale
    image = Image.new("RGBA", (192 * s, 160 * s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cream, sunlight = "#FFF3D6", "#E6E89A"
    sage, moss, deep = "#739E78", "#527665", "#3D5B52"
    peach, clay, earth = "#E7A27F", "#C77C68", "#955F59"
    blossom, sky = "#E8B4B8", "#A8CED0"

    def p(u: float, v: float) -> tuple[int, int]:
        # u follows the ground long axis exactly: (96,-48), slope -1/2.
        # v is screen-vertical, preserving upright posts.
        return (round((48 + 96 * u) * s), round((132 - 48 * u - 58 * v) * s))

    def poly(points, fill, outline=None, width=1):
        pts = [p(u, v) for u, v in points]
        draw.polygon(pts, fill=fill)
        if outline:
            draw.line(pts + [pts[0]], fill=outline, width=width * s)

    # Feet use exact +/- 1/2 ground axes.
    for u in (0.0, 1.0):
        x, y = p(u, 0)
        foot = [(x - 16*s, y), (x, y - 8*s), (x + 16*s, y), (x, y + 8*s)]
        draw.polygon(foot, fill=moss)
        draw.line(foot + [foot[0]], fill=deep, width=2*s)

    # Main face and layered frame share the exact long axis.
    poly([(0, .08), (1, .08), (1, .92), (0, .92)], earth, deep, 2)
    poly([(.035, .13), (.965, .13), (.965, .86), (.035, .86)], cream)
    poly([(.07, .18), (.93, .18), (.93, .81), (.07, .81)], sage, moss, 2)

    if args.art_source:
        art = Image.open(args.art_source).convert("RGBA")
        # Approved inner-board corners in the original rich reference.
        quad = [(334, 247), (1194, 404), (1188, 741), (333, 530)]
        dst = image.load()
        src = art.load()
        for py in range(image.height):
            world_y = py / s
            for px in range(image.width):
                world_x = px / s
                u = (world_x - 48) / 96
                v = (132 - 48*u - world_y) / 58
                if .07 <= u <= .93 and .18 <= v <= .81:
                    tu = (u - .07) / .86
                    tv = (.81 - v) / .63
                    p00, p10, p11, p01 = quad
                    sx = (1-tu)*(1-tv)*p00[0] + tu*(1-tv)*p10[0] + tu*tv*p11[0] + (1-tu)*tv*p01[0]
                    sy = (1-tu)*(1-tv)*p00[1] + tu*(1-tv)*p10[1] + tu*tv*p11[1] + (1-tu)*tv*p01[1]
                    dst[px, py] = src[min(max(round(sx), 0), art.width-1),
                                      min(max(round(sy), 0), art.height-1)]

    # Sturdy vertical posts.
    for u in (0.0, 1.0):
        x0, y0 = p(u, 0)
        x1, y1 = p(u, 1)
        draw.rounded_rectangle((x0-4*s, y1-3*s, x0+4*s, y0+3*s),
                               radius=2*s, fill=peach, outline=earth, width=2*s)
        draw.ellipse((x1-5*s, y1-6*s, x1+5*s, y1+4*s), fill=sunlight, outline=clay, width=s)

    if not args.art_source:
        # Lightweight fallback decorations when no art reference is supplied.
        medal_colors = (sunlight, sky, blossom)
        for index, u in enumerate((.25, .5, .75)):
            x, y = p(u, .60)
            draw.polygon([(x-4*s, y-10*s), (x, y-4*s), (x+4*s, y-10*s)], fill=cream)
            draw.ellipse((x-6*s, y-6*s, x+6*s, y+6*s), fill=medal_colors[index], outline=earth, width=s)
            draw.ellipse((x-2*s, y-2*s, x+2*s, y+2*s), fill=sunlight)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output, optimize=True)
    print(f"OK: exact awards board source: {args.output}")


if __name__ == "__main__":
    main()
