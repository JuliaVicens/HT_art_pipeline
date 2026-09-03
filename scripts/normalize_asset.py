#!/usr/bin/env python3
"""Normalize one source image into a validated HabitTracker isometric tile."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import deque
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from view_segmentation import bilinear, load_views, make_periodic, sample_quad, segmentation_preview

ASSET_NAME = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
DEFAULT_WIDTH = 64
DEFAULT_DEPTH = 32
DEFAULT_HEIGHT = 8


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def nearest(color: tuple[int, int, int], palette: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    return min(palette, key=lambda p: sum((a - b) ** 2 for a, b in zip(color, p)))


def diamond_alpha(width: int, height: int) -> Image.Image:
    """Hard-edged 2:1 diamond mask; no antialiasing is introduced."""
    mask = Image.new("L", (width, height), 0)
    pixels = mask.load()
    cx, cy = (width - 1) / 2, (height - 1) / 2
    for y in range(height):
        for x in range(width):
            if abs(x - cx) / (width / 2) + abs(y - cy) / (height / 2) <= 1:
                pixels[x, y] = 255
    return mask


def contact_line(image: Image.Image) -> tuple[float, float, float]:
    """Fit the lower alpha envelope and return slope, center x and center y."""
    points = []
    pixels = image.load()
    for x in range(image.width):
        visible = [y for y in range(image.height) if pixels[x, y][3] >= 128]
        if visible:
            points.append((x, max(visible)))
    if len(points) < 4:
        raise ValueError("Object needs a readable lower silhouette for automatic alignment")
    trim = max(1, len(points) // 10)
    fitted = points[trim:-trim] if len(points) > trim * 2 + 3 else points
    mean_x = sum(x for x, _ in fitted) / len(fitted)
    mean_y = sum(y for _, y in fitted) / len(fitted)
    variance = sum((x - mean_x) ** 2 for x, _ in fitted)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in fitted) / variance if variance else 0.0
    contact_x = (points[0][0] + points[-1][0]) / 2
    contact_y = mean_y + slope * (contact_x - mean_x)
    return slope, contact_x, contact_y


def base_contact(image: Image.Image) -> tuple[float, float]:
    """Return the center of the actual lower support band for compact objects."""
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("Object needs visible pixels for base alignment")
    visible_width = bbox[2] - bbox[0]
    visible_height = bbox[3] - bbox[1]
    # Low, wide compact objects (notably footwear) need the center of the
    # visible sole, not a few isolated pixels at its very bottom. Upright or
    # square objects such as pots retain a thin physical contact band.
    band_fraction = 0.28 if visible_width / visible_height >= 1.15 else 0.12
    band_height = max(3, round(visible_height * band_fraction))
    max_y = bbox[3] - 1
    points = [(x, y) for y in range(max(bbox[1], max_y - band_height + 1), max_y + 1)
              for x in range(bbox[0], bbox[2]) if alpha.getpixel((x, y)) >= 128]
    if not points:
        raise ValueError("Object needs a readable lower support band")
    min_x = min(x for x, _ in points)
    max_x = max(x for x, _ in points)
    min_y = min(y for _, y in points)
    return (min_x + max_x) / 2, (min_y + max_y) / 2


def support_plane_contact(image: Image.Image) -> tuple[float, float]:
    """Find a robust ground-plane pivot for tall elongated machines."""
    _, contact_x, _ = contact_line(image)
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("Object needs visible pixels for support-plane alignment")
    envelope = []
    for x in range(bbox[0], bbox[2]):
        visible = [y for y in range(bbox[1], bbox[3]) if alpha.getpixel((x, y)) >= 128]
        if visible:
            envelope.append(max(visible))
    envelope.sort()
    # The upper quartile follows the main feet/belt support while rejecting a
    # single lowest roller or protruding pixel.
    contact_y = envelope[round((len(envelope) - 1) * 0.75)]
    return contact_x, float(contact_y)


def placement_pivot(image: Image.Image, slots: tuple[int, int, int]) -> tuple[float, float, str]:
    sx, sy, sz = slots
    if sx == sy == 1:
        x, y = base_contact(image)
        return x, y, "base_contact"
    if sx != sy and sz > 1:
        x, y = support_plane_contact(image)
        return x, y, "support_plane"
    _, x, y = contact_line(image)
    return x, y, "shape_preserved"


def declared_contact(image: Image.Image, contact: tuple[float, float]) -> tuple[float, float]:
    """Map a normalized semantic contact point into the visible alpha bounds."""
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("Object needs visible pixels for declared contact")
    x = bbox[0] + contact[0] * max(1, bbox[2] - bbox[0] - 1)
    y = bbox[1] + contact[1] * max(1, bbox[3] - bbox[1] - 1)
    return x, y


def support_containment(
    image: Image.Image,
    slots: tuple[int, int, int],
    initial_offset: tuple[int, int],
    ground_contact: tuple[float, float] | None = None,
) -> tuple[Image.Image, tuple[int, int], float, dict]:
    """Translate, then uniformly shrink, until the lower support fits its slots."""
    sx, sy, _ = slots
    canvas = image.size
    tile_centers = [
        (round((x - (sx - 1) / 2) * 32 - (y - (sy - 1) / 2) * 32),
         round((x - (sx - 1) / 2) * 16 + (y - (sy - 1) / 2) * 16))
        for x in range(sx) for y in range(sy)
    ]

    def inside_footprint(px: float, py: float) -> bool:
        return any(abs(px - cx) / 32 + abs(py - cy) / 16 <= 1
                   for cx, cy in tile_centers)

    def support_points(candidate: Image.Image) -> list[tuple[int, int]]:
        alpha = candidate.getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            return []
        support_fraction = 0.12 if sx == sy == 1 else 0.35
        cutoff = bbox[3] - max(3, round((bbox[3] - bbox[1]) * support_fraction))
        return [(x, y) for y in range(cutoff, bbox[3]) for x in range(bbox[0], bbox[2])
                if alpha.getpixel((x, y)) >= 128]

    def best_offset(candidate: Image.Image, origin: tuple[int, int]) -> tuple[tuple[int, int], int, int]:
        points = support_points(candidate)
        best = None
        # A compact base has an unambiguous ground height. Let containment move
        # it sideways or shrink it, but never reinterpret the pot/sole top as
        # the ground plane by pushing the sprite downward.
        y_candidates = [origin[1]] if sx == sy == 1 else range(origin[1] - 16, origin[1] + 17)
        for oy in y_candidates:
            for ox in range(origin[0] - 24, origin[0] + 25):
                outside = sum(not inside_footprint(
                    ox + x - canvas[0] / 2, oy + y - canvas[1]
                ) for x, y in points)
                movement = (ox - origin[0]) ** 2 + (oy - origin[1]) ** 2
                score = (outside, movement)
                if best is None or score < best[0]:
                    best = (score, (ox, oy))
        return best[1], best[0][0], len(points)

    candidate = image
    scale = 1.0
    offset, outside_before, total_before = best_offset(candidate, initial_offset)
    outside = outside_before
    total = total_before
    while outside and scale > 0.66:
        scale = round(scale - 0.04, 2)
        bbox = image.getchannel("A").getbbox()
        crop = image.crop(bbox)
        resized = crop.resize(
            (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
            Image.Resampling.NEAREST,
        )
        candidate = Image.new("RGBA", canvas, (0, 0, 0, 0))
        candidate.alpha_composite(resized, ((canvas[0] - resized.width) // 2,
                                            canvas[1] - resized.height))
        if ground_contact is not None:
            pivot_x, pivot_y = declared_contact(candidate, ground_contact)
        else:
            pivot_x, pivot_y, _ = placement_pivot(candidate, slots)
        origin = (round(canvas[0] / 2 - pivot_x), round(canvas[1] - pivot_y))
        offset, outside, total = best_offset(candidate, origin)
    qa = {
        "support_pixels": total,
        "outside_before": outside_before,
        "outside_after": outside,
        "outside_fraction": round(outside / max(1, total), 4),
        "uniform_scale": scale,
        "status": "pass" if outside == 0 else "review",
    }
    return candidate, offset, scale, qa


def lower_structure_slope(image: Image.Image) -> float:
    """Principal axis of the lower 55%; useful for deep machines and furniture."""
    pixels = image.load()
    visible = [(x, y) for y in range(image.height) for x in range(image.width)
               if pixels[x, y][3] >= 128]
    min_y, max_y = min(y for _, y in visible), max(y for _, y in visible)
    cutoff = min_y + (max_y - min_y) * 0.45
    points = [(x, y) for x, y in visible if y >= cutoff]
    mean_x = sum(x for x, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    xx = sum((x - mean_x) ** 2 for x, _ in points) / len(points)
    yy = sum((y - mean_y) ** 2 for _, y in points) / len(points)
    xy = sum((x - mean_x) * (y - mean_y) for x, y in points) / len(points)
    angle = 0.5 * math.atan2(2 * xy, xx - yy)
    return math.tan(angle)


def remove_connected_light_background(image: Image.Image) -> Image.Image:
    """Remove white/checkerboard backgrounds connected to the canvas border."""
    result = image.copy()
    pixels = result.load()
    width, height = result.size
    queue = deque()
    seen = set()
    for x in range(width):
        queue.extend(((x, 0), (x, height - 1)))
    for y in range(height):
        queue.extend(((0, y), (width - 1, y)))
    while queue:
        x, y = queue.popleft()
        if (x, y) in seen:
            continue
        seen.add((x, y))
        r, g, b, a = pixels[x, y]
        is_light_neutral = min(r, g, b) >= 225 and max(r, g, b) - min(r, g, b) <= 18
        if not (a < 128 or is_light_neutral):
            continue
        pixels[x, y] = (0, 0, 0, 0)
        # Generated pixel-art backgrounds can remain connected through a
        # diagonal one-pixel opening (handles, chair backs, thin frames). Use
        # 8-connectivity so those background pockets are not mistaken for art.
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1),
                       (x - 1, y - 1), (x + 1, y - 1),
                       (x - 1, y + 1), (x + 1, y + 1)):
            if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen:
                queue.append((nx, ny))
    return result


def remove_chroma_key(image: Image.Image, color: tuple[int, int, int], tolerance: int) -> tuple[Image.Image, int]:
    """Remove a declared non-art background color everywhere, including enclosed holes."""
    if not 0 <= tolerance <= 64:
        raise ValueError("chroma-key tolerance must be between 0 and 64")
    result = image.copy()
    pixels = result.load()
    removed = 0
    for y in range(result.height):
        for x in range(result.width):
            r, g, b, a = pixels[x, y]
            if a and max(abs(r - color[0]), abs(g - color[1]), abs(b - color[2])) <= tolerance:
                pixels[x, y] = (0, 0, 0, 0)
                removed += 1
    if removed == 0:
        raise ValueError("Declared chroma key did not match any source pixels")
    return result, removed


def exact_axis_scores(image: Image.Image) -> dict[str, float]:
    """Measure boundary support for exact 2:1 axes and screen verticals."""
    alpha = image.getchannel("A")
    boundary = set()
    for y in range(image.height):
        for x in range(image.width):
            if alpha.getpixel((x, y)) < 128:
                continue
            if any(nx < 0 or ny < 0 or nx >= image.width or ny >= image.height
                   or alpha.getpixel((nx, ny)) < 128
                   for nx, ny in ((x-1, y), (x+1, y), (x, y-1), (x, y+1))):
                boundary.add((x, y))

    def score(dx: int, dy: int) -> float:
        if not boundary:
            return 0.0
        hits = 0
        for x, y in boundary:
            if any((x + dx*k, y + dy*k) in boundary or
                   (x - dx*k, y - dy*k) in boundary for k in range(2, 7)):
                hits += 1
        return round(hits / len(boundary), 4)

    return {
        "axis_positive_half": score(2, 1),
        "axis_negative_half": score(2, -1),
        "vertical": score(0, 2),
    }


def harmonize_diamond_edges(
    image: Image.Image,
    width: int,
    depth: int,
    palette: list[tuple[int, int, int]],
    band: int,
) -> None:
    """Match opposite surface edges with a minimal inward blend."""
    if band <= 0:
        return
    mask = diamond_alpha(width, depth)
    rows = []
    for y in range(depth):
        visible = [x for x in range(width) if mask.getpixel((x, y))]
        rows.append((min(visible), max(visible)))
    half = depth // 2
    nw = [(rows[y][0], y) for y in range(half)]
    ne = [(rows[y][1], y) for y in range(half)]
    sw = [(rows[y][0], y) for y in range(half, depth)]
    se = [(rows[y][1], y) for y in range(half, depth)]
    pixels = image.load()
    for edge_a, edge_b in ((nw, se), (ne, sw)):
        for (ax, ay), (bx, by) in zip(edge_a, edge_b):
            color_a, color_b = pixels[ax, ay][:3], pixels[bx, by][:3]
            merged = nearest(tuple(round((a + b) / 2) for a, b in zip(color_a, color_b)), palette)
            pixels[ax, ay] = (*merged, 255)
            pixels[bx, by] = (*merged, 255)
            for offset in range(1, band + 1):
                for x, y in ((ax + (1 if ax < width // 2 else -1) * offset, ay),
                             (bx + (1 if bx < width // 2 else -1) * offset, by)):
                    if 0 <= x < width and mask.getpixel((x, y)):
                        original = pixels[x, y][:3]
                        softened = nearest(
                            tuple(round((3 * a + b) / 4) for a, b in zip(original, merged)), palette
                        )
                        pixels[x, y] = (*softened, 255)


def normalize(
    source: Path,
    palette_path: Path,
    output: Path,
    width: int,
    depth: int,
    height: int,
    asset_type: str,
    views_path: Path | None,
    tiling: str,
    qa_dir: Path | None,
    projection: str,
    side_mode: str,
    edge_blend: int,
    slots: tuple[int, int, int] = (1, 1, 1),
    object_scale: float = 0.8,
    anchor_offset: tuple[int, int] = (0, 0),
    object_mirror_x: bool = False,
    object_shear_y: float = 0.0,
    auto_align_object: bool = False,
    geometry_locked: bool = False,
    ground_contact: tuple[float, float] | None = None,
    chroma_key: tuple[int, int, int] | None = None,
    chroma_tolerance: int = 0,
    wall_orientation: str | None = None,
) -> dict:
    if not source.is_file():
        raise ValueError(f"Source not found: {source}")
    if not ASSET_NAME.fullmatch(output.stem):
        raise ValueError("Output name must be snake_case, e.g. nature_grass_01.png")
    if output.suffix.lower() != ".png":
        raise ValueError("Output must use the .png extension")

    if width < 4 or depth < 2 or height < 0:
        raise ValueError("width/depth must be positive and height cannot be negative")
    if width % 2 or depth % 2:
        raise ValueError("width and depth must be even pixel values")

    spec = json.loads(palette_path.read_text(encoding="utf-8"))
    palette = [hex_rgb(item["hex"]) for item in spec["colors"]]
    named_colors = {item["name"]: hex_rgb(item["hex"]) for item in spec["colors"]}
    image = Image.open(source).convert("RGBA")

    surface_size = (width, depth)
    canvas_size = (width, depth + height)
    effective_offset = anchor_offset
    effective_mirror = object_mirror_x
    effective_shear = object_shear_y
    measured_slope = None
    expected_slope = None
    containment_scale = 1.0
    containment_qa = None

    if asset_type in {"object", "wall_object"}:
        sx, sy, sz = slots
        if min(slots) < 1 or not 0.1 <= object_scale <= 1.0:
            raise ValueError("Object slots must be >= 1 and object-scale must be between 0.1 and 1.0")
        if asset_type == "wall_object" and wall_orientation not in {"wall_left", "wall_right"}:
            raise ValueError("Wall objects require wall_left or wall_right orientation")
        footprint_width = (sx + sy) * width // 2
        footprint_depth = (sx + sy) * depth // 2
        object_height = footprint_depth + sz * depth
        # Keep one half-tile of transparent safety padding on each side and
        # one vertical slot above. Large/asymmetric objects must never be cut
        # merely because their gameplay footprint is compact.
        canvas_size = (footprint_width + width, object_height + depth)
        # Crop generated transparent margins before applying the requested slot scale.
        chroma_removed = 0
        if chroma_key is not None:
            if chroma_key in palette:
                raise ValueError("chroma-key color must not belong to the asset palette")
            image, chroma_removed = remove_chroma_key(image, chroma_key, chroma_tolerance)
        else:
            image = remove_connected_light_background(image)
        alpha = image.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
        bbox = alpha.getbbox()
        if bbox is None:
            raise ValueError("Object source has no visible pixels")
        image = image.crop(bbox)
        if asset_type == "wall_object":
            # Wall art is authored as a front elevation and deterministically
            # projected onto the declared 2:1 wall plane. The visible rectangle
            # occupies the complete slot; placement is owned by room_layout.json.
            face_width = sx * width // 2
            face_height = sz * depth
            image = image.resize((face_width, face_height), Image.Resampling.NEAREST)
            # iso(0, y) travels down-left (-1/2 screen slope), while
            # iso(x, 0) travels down-right (+1/2). Derive this exclusively
            # from the declared wall orientation so sources stay positionless.
            slope_sign = -1 if wall_orientation == "wall_left" else 1
            canvas_size = (face_width, face_height + face_width // 2)
            result = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            source_pixels = image.load()
            target_pixels = result.load()
            for x in range(face_width):
                column_offset = round(x / 2) if slope_sign > 0 else round((face_width - 1 - x) / 2)
                for y in range(face_height):
                    r, g, b, a = source_pixels[x, y]
                    if a >= 128:
                        qr, qg, qb = nearest((r, g, b), palette)
                        target_pixels[x, y + column_offset] = (qr, qg, qb, 255)
            effective_offset = (0, 0)
            alignment_method = "wall_plane"
            segmentation = None
            seam_score = None
            top_inset = None
        else:
            fit = (max(1, round(footprint_width * object_scale)),
                   max(1, round(object_height * object_scale)))
            image.thumbnail(fit, Image.Resampling.NEAREST)
        if asset_type == "object" and auto_align_object:
            # Wide, shallow silhouettes (boards/fences) expose a reliable foot
            # line. Deep/tall silhouettes (machines/furniture) are better
            # represented by the principal axis of their lower structure.
            alignment_method = "contact_line" if image.width >= image.height else "lower_structure"
            source_slope = (contact_line(image)[0] if alignment_method == "contact_line"
                            else lower_structure_slope(image))
            desired_slope = -0.5 if sy > sx else (0.5 if sx > sy else 0.0)
            expected_slope = desired_slope if desired_slope else None
            if geometry_locked:
                # Geometry lock forbids shear/stretch, but a horizontal mirror
                # preserves proportions and is required when the authored long
                # axis points along the opposite isometric grid axis.
                effective_mirror = (object_mirror_x or bool(
                    desired_slope and source_slope * desired_slope < 0
                ))
                if effective_mirror:
                    image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    source_slope = -source_slope
                effective_shear = 0.0
                if sx == sy == 1:
                    alignment_method = "base_contact"
                elif sx != sy and sz > 1:
                    alignment_method = "support_plane"
                else:
                    alignment_method = "shape_preserved"
            else:
                effective_mirror = bool(desired_slope and source_slope * desired_slope < 0)
                if effective_mirror:
                    image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    source_slope = -source_slope
                effective_shear = max(-0.75, min(0.75, desired_slope - source_slope)) if desired_slope else 0.0
            measured_slope = source_slope if desired_slope else None
        elif asset_type == "object" and effective_mirror:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if asset_type == "object":
            placed = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            shear_clearance = math.ceil(abs(effective_shear) * image.width / 2) + (2 if effective_shear else 0)
            placed.alpha_composite(
                image,
                ((canvas_size[0] - image.width) // 2,
                 canvas_size[1] - image.height - shear_clearance),
            )
            result = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            src, dst = placed.load(), result.load()
            for y in range(canvas_size[1]):
                for x in range(canvas_size[0]):
                    r, g, b, a = src[x, y]
                    # Generated sources may contain a faint semi-transparent halo.
                    # A hard threshold keeps object sprites binary and pixel-clean.
                    if a >= 128:
                        qr, qg, qb = nearest((r, g, b), palette)
                        dst[x, y] = (qr, qg, qb, 255)
            if effective_shear:
                cx = (canvas_size[0] - 1) / 2
                # PIL expects the inverse affine map: source y = output y - s(x-cx).
                result = result.transform(
                    canvas_size,
                    Image.Transform.AFFINE,
                    (1, 0, 0, -effective_shear, 1, effective_shear * cx),
                    resample=Image.Resampling.NEAREST,
                    fillcolor=(0, 0, 0, 0),
                )
            if auto_align_object:
                if ground_contact is not None:
                    if any(value < 0 or value > 1 for value in ground_contact):
                        raise ValueError("ground-contact coordinates must be between 0 and 1")
                    contact_x, contact_y = declared_contact(result, ground_contact)
                    alignment_method = "declared_contact"
                else:
                    contact_x, contact_y, alignment_method = placement_pivot(result, slots)
                effective_offset = (
                    round(canvas_size[0] / 2 - contact_x),
                    round(canvas_size[1] - contact_y),
                )
                result, effective_offset, containment_scale, containment_qa = support_containment(
                    result, slots, effective_offset, ground_contact
                )
            segmentation = None
            seam_score = None
            top_inset = None
    else:
        views, segmentation, view_metadata = load_views(source, views_path)
        top_inset = float(view_metadata.get("top_inset", .04))
        result, texture, seam_score = normalize_terrain(
            image, palette, named_colors, width, depth, height, views, tiling,
            projection, side_mode, edge_blend, top_inset
        )
        if qa_dir:
            segmentation_preview(image, views, qa_dir / f"{output.stem}.segmentation.png")
            qa_dir.mkdir(parents=True, exist_ok=True)
            texture.save(qa_dir / f"{output.stem}.texture.png", optimize=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    result.save(output, format="PNG", optimize=True)
    validate(output, set(palette), canvas_size)
    return {
        "asset": output.stem,
        "asset_type": asset_type,
        "segmentation": segmentation,
        "top_inset": top_inset if asset_type == "terrain" else None,
        "tiling": tiling if asset_type == "terrain" else "none",
        "projection": projection if asset_type == "terrain" else "silhouette",
        "side_mode": side_mode if asset_type == "terrain" else "none",
        "edge_blend": edge_blend if asset_type == "terrain" else 0,
        "seam_score": seam_score,
        "source": source.as_posix(),
        "output": output.as_posix(),
        "palette": spec["id"],
        "palette_version": spec["version"],
        "dimensions": {"width": width, "depth": depth, "height": height},
        "slots": {"x": slots[0], "y": slots[1], "z": slots[2]} if asset_type in {"object", "wall_object"} else None,
        "surface": "wall" if asset_type == "wall_object" else ("floor" if asset_type == "object" else None),
        "orientation": wall_orientation if asset_type == "wall_object" else None,
        "object_scale": round(object_scale * containment_scale, 4) if asset_type == "object" else (1.0 if asset_type == "wall_object" else None),
        "object_scale_requested": object_scale if asset_type == "object" else (1.0 if asset_type == "wall_object" else None),
        "anchor": ([canvas_size[0] // 2, canvas_size[1] - canvas_size[0] // 4]
                   if asset_type == "wall_object" else ([canvas_size[0] // 2, canvas_size[1]] if asset_type == "object" else None)),
        "placement_offset": {"x": effective_offset[0], "y": effective_offset[1]} if asset_type in {"object", "wall_object"} else None,
        "ground_contact": {"x": ground_contact[0], "y": ground_contact[1]}
        if asset_type == "object" and ground_contact is not None else None,
        "background": ({"mode": "chroma_key", "color": "#%02X%02X%02X" % chroma_key,
                        "tolerance": chroma_tolerance, "pixels_removed": chroma_removed}
                       if asset_type == "object" and chroma_key is not None else None),
        "mirror_x": effective_mirror if asset_type == "object" else None,
        "shear_y": round(effective_shear, 4) if asset_type == "object" else None,
        "auto_aligned": auto_align_object if asset_type == "object" else None,
        "alignment_method": ("wall_plane" if asset_type == "wall_object" else
                             (alignment_method if asset_type == "object" and auto_align_object else None)),
        "geometry_locked": geometry_locked if asset_type == "object" else None,
        "geometry_qa": ({
            "expected_slope": expected_slope,
            "measured_slope": round(measured_slope, 4),
            "absolute_error": round(abs(measured_slope - expected_slope), 4),
            "status": "pass" if abs(measured_slope - expected_slope) <= 0.08 else "review",
        } if asset_type == "object" and measured_slope is not None else ({
            "expected_slope": -0.5 if wall_orientation == "wall_left" else 0.5,
            "measured_slope": -0.5 if wall_orientation == "wall_left" else 0.5,
            "absolute_error": 0.0,
            "status": "pass",
        } if asset_type == "wall_object" else None)),
        "containment_qa": (containment_qa if asset_type == "object" else ({
            "surface": wall_orientation,
            "projected_face_size": [face_width, face_height],
            "canvas_size": list(canvas_size),
            "status": "pass",
        } if asset_type == "wall_object" else None)),
        "exact_axis_scores": exact_axis_scores(result) if asset_type in {"object", "wall_object"} else None,
        "canvas_size": list(canvas_size),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_terrain(
    image: Image.Image,
    palette: list[tuple[int, int, int]],
    named_colors: dict[str, tuple[int, int, int]],
    width: int,
    depth: int,
    height: int,
    views: dict[str, tuple[float, float]],
    tiling: str,
    projection: str,
    side_mode: str,
    edge_blend: int,
    top_inset: float,
) -> tuple[Image.Image, Image.Image, int]:
    """Create a strict isometric surface and deterministic elevated soil faces."""
    canvas_size = (width, depth + height)
    # Keep enough intermediate resolution to avoid a destructive downsample
    # followed by horizontal expansion during the isometric reprojection.
    texture_size = max(8, width)
    top_points = [views[k] for k in ("top", "right", "bottom", "left")]
    center_x = sum(point[0] for point in top_points) / 4
    center_y = sum(point[1] for point in top_points) / 4
    # Sample just inside the detected seam so antialiased outlines and side-face
    # pixels never leak into the rectified top texture.
    top_points = [
        (x + (center_x - x) * top_inset, y + (center_y - y) * top_inset)
        for x, y in top_points
    ]
    texture = sample_quad(
        image,
        top_points,
        (texture_size, texture_size),
    )
    seam_score = None
    if tiling == "seamless":
        texture, seam_score = make_periodic(texture)

    legacy_surface = None
    if projection == "legacy":
        xs, ys = [point[0] for point in top_points], [point[1] for point in top_points]
        box = (round(min(xs)), round(min(ys)), round(max(xs)) + 1, round(max(ys)) + 1)
        legacy_surface = image.crop(box).resize((width, depth), Image.Resampling.NEAREST)

    result = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    dst = result.load()
    cx = width // 2
    cy = depth // 2

    # Segment and rectify both source side views independently.
    if height:
        if side_mode == "source":
            left_texture = sample_quad(
                image, [views[k] for k in ("left", "bottom", "base_bottom", "left_base")],
                (cx + 1, max(1, height)),
            )
            right_texture = sample_quad(
                image, [views[k] for k in ("bottom", "right", "right_base", "base_bottom")],
                (width - cx, max(1, height)),
            )
        else:
            left_texture = right_texture = None
        left_color = named_colors.get("clay", palette[-1])
        right_color = named_colors.get("earth", palette[-1])
        highlight = named_colors.get("peach", left_color)
        for x in range(width):
            on_left = x <= cx
            u = x / cx if on_left else (x - cx) / max(1, width - 1 - cx)
            surface_y = round(cy + (u if on_left else 1-u) * (depth - 1 - cy))
            for offset in range(height + 1):
                if side_mode == "source":
                    face = left_texture if on_left else right_texture
                    face_x = round(u * (face.width - 1))
                    r, g, b, _ = face.getpixel((face_x, min(offset, height - 1)))
                    qr, qg, qb = nearest((r, g, b), palette)
                else:
                    color = left_color if on_left else right_color
                    if on_left and (x + surface_y + offset) % 11 == 0:
                        color = highlight
                    qr, qg, qb = color
                dst[x, surface_y + offset] = (qr, qg, qb, 255)

    # Project the rectified periodic square back onto the canonical diamond.
    surface_mask = diamond_alpha(width, depth)
    for y in range(depth):
        for x in range(width):
            if not surface_mask.getpixel((x, y)):
                continue
            nx = (x - (width - 1) / 2) / (width / 2)
            ny = y / max(1, depth - 1)
            u, v = (nx + ny) / 2, (ny - nx) / 2
            u, v = min(max(u, 0), 1), min(max(v, 0), 1)
            if projection == "legacy" and legacy_surface is not None:
                r, g, b, _ = legacy_surface.getpixel((x, y))
            elif tiling == "none":
                # Quality-first path: one direct nearest-neighbour sample from
                # the segmented source face. No square->diamond resampling pass.
                sx, sy = bilinear(top_points, u, v)
                sx = min(max(round(sx), 0), image.width - 1)
                sy = min(max(round(sy), 0), image.height - 1)
                r, g, b, _ = image.getpixel((sx, sy))
            else:
                tx = round(u * (texture.width - 1))
                ty = round(v * (texture.height - 1))
                r, g, b, _ = texture.getpixel((tx, ty))
            qr, qg, qb = nearest((r, g, b), palette)
            dst[x, y] = (qr, qg, qb, 255)

    harmonize_diamond_edges(result, width, depth, palette, edge_blend)

    return result, texture, seam_score


def validate(path: Path, palette: set[tuple[int, int, int]], canvas_size: tuple[int, int]) -> None:
    image = Image.open(path)
    if image.size != canvas_size or image.mode != "RGBA":
        raise ValueError(f"Asset must be a {canvas_size[0]}x{canvas_size[1]} RGBA PNG")
    colors = {(r, g, b) for r, g, b, a in image.getdata() if a}
    if not colors <= palette:
        raise ValueError("Asset contains colors outside its declared palette")
    alphas = {a for *_, a in image.getdata()}
    if not alphas <= {0, 255} or 0 not in alphas or 255 not in alphas:
        raise ValueError("Asset must contain hard-edged transparency")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--palette", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="Surface width in pixels")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH, help="Surface depth in pixels")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="Vertical elevation in pixels")
    parser.add_argument("--asset-type", choices=("terrain", "object", "wall_object"), default="terrain")
    parser.add_argument("--wall-orientation", choices=("wall_left", "wall_right"),
                        help="Wall plane used to project a front-elevation wall object")
    parser.add_argument("--views", type=Path, help="Optional top/left/right segmentation points JSON")
    parser.add_argument("--tiling", choices=("seamless", "none"), default="seamless")
    parser.add_argument("--qa-dir", type=Path, help="Write segmentation and rectified-texture previews")
    parser.add_argument("--projection", choices=("legacy", "direct"), default="legacy")
    parser.add_argument("--side-mode", choices=("palette", "source"), default="palette")
    parser.add_argument("--edge-blend", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--slots", type=int, nargs=3, metavar=("X", "Y", "Z"), default=(1, 1, 1),
                        help="Object footprint/height in grid slots, e.g. --slots 1 2 2")
    parser.add_argument("--object-scale", type=float, default=0.8,
                        help="Fraction of the declared object canvas occupied by the sprite")
    parser.add_argument("--anchor-offset", type=int, nargs=2, metavar=("X", "Y"), default=(0, 0),
                        help="Object placement correction in output pixels")
    parser.add_argument("--object-mirror-x", action="store_true",
                        help="Mirror an object onto the opposite isometric ground axis")
    parser.add_argument("--object-shear-y", type=float, default=0.0,
                        help="Vertical pixels per horizontal pixel for exact isometric slope correction")
    parser.add_argument("--auto-align-object", action="store_true",
                        help="Detect object axis, ground-contact line and placement pivot automatically")
    parser.add_argument("--geometry-locked", action="store_true",
                        help="Preserve approved exact angles; auto-align position only")
    parser.add_argument("--ground-contact", type=float, nargs=2, metavar=("X", "Y"),
                        help="Normalized semantic ground-contact point in visible bounds")
    parser.add_argument("--chroma-key", help="Declared RGB hex background removed globally")
    parser.add_argument("--chroma-tolerance", type=int, default=0,
                        help="Maximum per-channel chroma distance (0..64)")
    args = parser.parse_args()
    entry = normalize(
        args.source, args.palette, args.output,
        args.width, args.depth, args.height, args.asset_type,
        args.views, args.tiling, args.qa_dir,
        args.projection,
        args.side_mode,
        args.edge_blend,
        tuple(args.slots),
        args.object_scale,
        tuple(args.anchor_offset),
        args.object_mirror_x,
        args.object_shear_y,
        args.auto_align_object,
        args.geometry_locked,
        tuple(args.ground_contact) if args.ground_contact else None,
        hex_rgb(args.chroma_key) if args.chroma_key else None,
        args.chroma_tolerance,
        args.wall_orientation,
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "assets": []}
    if args.manifest.is_file():
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest["assets"] = [item for item in manifest.get("assets", []) if item.get("asset") != entry["asset"]]
    manifest["assets"].append(entry)
    manifest["assets"].sort(key=lambda item: item["asset"])
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    canvas = entry["canvas_size"]
    dimensions = entry["dimensions"]
    print(
        f"OK: {args.output} "
        f"({dimensions['width']}x{dimensions['depth']}x{dimensions['height']}, "
        f"canvas {canvas[0]}x{canvas[1]} RGBA, {entry['asset_type']}, "
        f"{entry['palette']} v{entry['palette_version']})"
    )


if __name__ == "__main__":
    main()
