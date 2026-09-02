# HabitTracker art-pipeline prototype

A small, local-only prototype that turns a loose source/reference image into a
runtime-ready isometric block. It enforces the first **Nature** palette, an
explicit `width x depth x height`, hard-edged transparency, nearest-neighbour reduction, palette
quantization, snake-case naming and a checksum manifest.

## Room Lab

Room composition is validated in `rooms/bedroom_01` before it is integrated in
Flutter. Build the current empty-room experiment with:

```powershell
.\run.ps1 -RoomLab
```

The wall and floor are exported as independent full-canvas transparent layers
for every visual variant. Open
`rooms/bedroom_01/previews/comparison_montage.png` for the fastest review, or
`room_geometry_qa.png` to inspect the shared anchor and floor corners. Geometry
lives only in `room_layout.json`; variant images never own placement data.
`room_slots_qa.png` overlays every fixed object footprint, wall bound and anchor
without requiring any object art to exist yet.

New generated inputs should follow `prompts/terrain_source_prompt.md`. Its
composition contract keeps patterns centered, limits low-frequency variation,
reserves neutral edges and standardizes connected-path endpoints before the
normalizer touches the image. The matching JSON records its measurable defaults.

## Run on Windows

Requirements: Windows, Python 3.10+ and the Python Launcher (`py`). From
PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\art_pipeline\run.ps1
```

The first run creates a local `.venv` and installs Pillow. It discovers the
current declarations in `sources/`, rebuilds their PNGs in `output/`, writes
`manifest.json`, creates visual checks in `qa/`, and rebuilds the runtime atlases.

## Runtime atlas

A complete build writes two deterministic, nearest-neighbor-free packages (the
finished sprites are copied pixel-for-pixel and are never resized):

- `runtime/nature_atlas.png` and `.json`: production, containing only `PASS` assets
- `runtime/nature_atlas_review.png` and `.json`: every current asset, including `REVIEW`
- `qa/nature_atlas_montage.png`: annotated QA only; it is not a runtime file

Sprites are packed by ascending asset name with the versioned
`name_sorted_shelf_v1` algorithm. Every sprite has two transparent padding
pixels on every side. `REVIEW` is recorded but is not a build error.

The JSON has top-level `catalog_version`, atlas filename and dimensions,
`padding`, packing algorithm, `includes_review`, `atlas_sha256`, and `assets`.
Each asset record contains `name`, `type`, atlas `x`/`y`, `width`/`height`,
`slots`, `anchor`, `placement_offset`, `ground_contact`, `status`,
`review_reasons`, `sprite_sha256`, and `catalog_version`. Coordinates address
the sprite rectangle itself; padding is outside that rectangle.

Example consumption (Python/Pillow):

```python
import json
from pathlib import Path
from PIL import Image

runtime = Path("runtime")
catalog = json.loads((runtime / "nature_atlas.json").read_text())
atlas = Image.open(runtime / catalog["atlas"])
treadmill = next(asset for asset in catalog["assets"] if asset["name"] == "nature_treadmill_02")
sprite = atlas.crop((treadmill["x"], treadmill["y"],
                     treadmill["x"] + treadmill["width"],
                     treadmill["y"] + treadmill["height"]))
```

`scripts/build_runtime_atlas.py --root .` can rebuild and validate both packages
from existing outputs without normalizing the source art again. Validation
rejects overlaps, altered sprite pixels, non-binary alpha, non-transparent
padding, catalog rectangle mismatches, or checksum mismatches.

Run the same command again whenever the source or palette changes. No backend,
API key or external service is used by the normalizer.

### Build one new asset

The same entry point automatically distinguishes terrain from objects. For a
standard `64x32x8` terrain, pass only its PNG:

```powershell
.\art_pipeline\run.ps1 .\my_sources\nature_stone_01.png
```

For an object, add only its gameplay slots (`X,Y,Z`):

```powershell
.\art_pipeline\run.ps1 .\my_sources\nature_bench_01.png -Slots 1,2,1
```

The filename becomes the asset ID; both `nature_stone_01.png` and
`nature_stone_01.source.png` produce `output/nature_stone_01.png`. Terrain uses
the sibling `*.views.json` automatically when present and otherwise records an
estimated segmentation for review. Names containing `water` default to a flat
height of zero. For another flat or unusually elevated terrain, use `-Height`,
for example `-Height 0`. Objects default to uniform scale `0.8`, automatic
anchoring and `geometry-locked`; `-ObjectScale` may change only that uniform fit.

Every one-asset invocation updates `manifest.json` and its relevant QA montage.
Running `run.ps1` without arguments discovers and rebuilds the complete current
collection automatically.

A complete build starts by removing derived PNGs from `output/` and `qa/` and
recreates `manifest.json` from the declarations in `sources/`. It never removes the
artistic files in `sources/`. This prevents deleted experiments and stale
montages from silently returning to the current collection.

## Add another asset

For terrain, add only a snake-case source PNG:

```text
sources/nature_stone_01.source.png
```

It defaults to height `8`; names containing `water` default to height `0`. An
optional `nature_stone_01.terrain.json` can declare `{"height": 0}` or
`{"enabled": false}`. A sibling `nature_stone_01.source.views.json` supplies
precise segmentation; without it the pipeline uses an inspectable estimate and
marks the asset `REVIEW`.

For an object, add its image and declaration:

```text
sources/nature_bike_01.source.png
sources/nature_bike_01.object.json
```

```json
{
  "schema_version": 1,
  "slots": [2, 1, 1],
  "object_scale": 0.8,
  "ground_contact": {"x": 0.5, "y": 0.85}
}
```

`slots` is required and `object_scale` defaults to `0.8`. Set `"enabled": false`
to keep a source without building it. Unknown fields, invalid slots and orphaned
declarations fail immediately. `scripts/build_all.py` processes terrains first,
then objects, renders QA once, and prints one `PASS` or `REVIEW` line per asset.
`ground_contact` is optional and uses normalized coordinates inside the cropped
visible silhouette (`0..1`). It identifies semantic contacts such as a sole or
pot base when alpha-only inference is ambiguous. Declared contact locks vertical
placement; containment may still correct X or uniformly reduce the sprite.

### Chroma-key object inputs

True-alpha object sources remain preferred. When an input must use an opaque
background, choose a flat color that does not occur in the Nature palette and
declare it explicitly:

```json
{
  "schema_version": 1,
  "slots": [1, 1, 1],
  "background": {
    "mode": "chroma_key",
    "color": "#FF00FF",
    "tolerance": 0
  }
}
```

The chroma color is removed globally before alpha crop, including where it is
visible through enclosed handles, frames or object openings. Intentional white
and cream pixels are preserved. The declared key is rejected if it belongs to
the active palette, a key matching no pixels fails the build, and tolerance is
limited to `0..64`. The manifest records the mode, color, tolerance and number
of removed pixels. Do not use a textured background, lighting spill or a chroma
color present in the object itself.

## Asset contract

- Dimensions: `width` is horizontal surface size, `depth` is surface depth and
  `height` is vertical elevation
- Example: `64x32x8` produces a `64x40` transparent PNG canvas
- Alpha: only fully transparent or fully opaque pixels
- Footprint: centered isometric diamond plus two visible elevated side faces
- Resampling: nearest-neighbour only
- Color: every visible pixel belongs to the selected theme palette
- Name: lowercase snake case such as `nature_grass_01.png`

## Asset types

- `--asset-type terrain`: enforces a diamond surface and generates elevated soil faces.
- `--asset-type object`: preserves the transparent source silhouette and never adds soil.

The manifest is updated by asset name, so running several assets keeps all their
entries instead of overwriting the previous one.

## Corner and seam QA

Terrain uses fixed grid steps of 32 pixels horizontally and 16 vertically for a
64x32 surface. Every build compares the full alpha silhouette of all terrain
tiles, checks the canonical top/left/right/bottom anchors and creates a 3x3
alternating surface montage. Interior side faces are deliberately culled: the
game compositor must show them only on exposed boundaries or height changes. A
mismatched edge makes `run.ps1` fail.

The build writes three montage previews: mixed terrain, grass-only and dirt-only.
It also builds a flat water test (`64x32x0`) and a straight dirt-path connection
test (`64x32x8`), each with its own repeated montage.

Straight paths are generated over the approved grass tile by
`scripts/build_connected_path.py`. Their center line follows the exact isometric
grid equation `x - 2y = 0`; translating a neighboring cell by `(32,16)` leaves
that equation unchanged. This guarantees that the path is one continuous line
through the cells instead of inheriting a slightly diagonal or curved route from
the source illustration. `qa/path_connection_montage.png` is the dedicated
connection check produced by `run.ps1`.

## View segmentation and seamless terrain

Each terrain source can have a sibling `*.views.json` defining the `top`, `left`,
`right`, `bottom` and lower-face anchors. The normalizer rectifies those three
views independently, so side pixels cannot leak onto the top surface. Without a
sidecar it uses a centered estimate and exposes the result in QA.
Grass blocks with an overhanging green rim can set `"top_inset": 0.12` in the
views sidecar. The rim remains outside the repeatable top plane instead of being
mistaken for surface texture; ordinary terrain defaults to `0.04`.

The production build currently uses `--tiling none` to preserve the source art.
`run.ps1` uses `--projection legacy`: it crops the segmented top bounds and
reduces them directly into the final diamond, preserving the visual behavior of
the original prototype while excluding the side faces. `--projection direct`
remains available for later experiments with geometric rectification.

The official build also uses `--side-mode palette`. At an elevation of only
8 pixels, this produces clean deterministic earth faces instead of compressing
high-detail source sides into visual noise. `--side-mode source` remains
available for larger or carefully authored side textures.

`run.ps1` uses `--edge-blend 2`: it harmonizes the opposite diamond borders and
softens two inward pixels. It reduces repeated-tile seams without modifying the
center texture or applying full periodic synthesis. Set it to `0` for raw source
edges or `1` for a lighter correction.
`--tiling seamless` remains an optional experiment, but is not used by
`run.ps1` until it can pass visual QA without degrading the texture.
`--qa-dir qa` writes a colored segmentation preview and the flat rectified
texture. The manifest records the chosen tiling mode and its seam score.

## Object sprites

Objects use a transparent source with one isolated subject. The normalizer keeps
the silhouette, applies a hard alpha threshold to remove generated halos,
quantizes it to the theme palette and defines the bottom-center pixel as its
ground anchor. Unlike terrain, objects are not segmented into top and side views
and are never made periodic.

Every object declares `--slots X Y Z`. X and Y describe its ground footprint;
Z describes its vertical allowance. `--object-scale` controls how much of that
space the visible sprite occupies without changing gameplay dimensions. Sources
are cropped to their real alpha bounds before scaling, so unequal source margins
cannot move an object away from its footprint center.
The exported object canvas includes transparent safety padding around the
declared footprint, preventing handles, branches or wide feet from being clipped.
`--anchor-offset X Y` applies a small placement correction when an asymmetric
object's lowest visible pixel is not the geometric center of its feet. This is
stored in the manifest and used by the compositor; it never adds terrain to the
transparent object PNG.
`--object-mirror-x` moves an authored object onto the opposite isometric axis
without swapping its declared X/Y slot dimensions. This is useful when a source
was drawn as `2x1` but the gameplay asset must remain `1x2`.
`--object-shear-y` rectifies an approximate source perspective to the exact
isometric ground slope using nearest-neighbor sampling. For example, `-0.25`
adds the missing quarter-pixel vertical change per horizontal pixel to a panel
whose authored baseline is shallower than the grid.

The current discovered object collection is defined exclusively by
`*.object.json` files. `qa/objects_current_montage.png` is the single current
object-QA sheet. It is generated automatically from the object entries in
`manifest.json` whose output PNGs exist, so removed experiments are not brought
back into the official collection. Each panel shows the sprite over its complete
footprint, every slot outline, the footprint center, placement anchor, both
isometric axes, `X x Y x Z`, alignment method, `geometry_qa`,
`exact_axis_scores`, and the resulting `PASS` or `REVIEW` state. Compact
silhouettes for which `geometry_qa` is not applicable pass that check; their
exact-axis scores remain visible for inspection. The corresponding files in
`output/` remain isolated transparent sprites.

Slot count cannot be inferred reliably from an isolated image because it has no
physical scale. The production contract therefore keeps slot count explicit.
Automated QA may recommend a larger footprint from contact points, orientation
and safe margins, but must not silently change gameplay dimensions.

`--auto-align-object` automatically fits the lower alpha envelope, selects the
matching isometric axis, rectifies its slope to `+0.5` or `-0.5`, and derives the
bottom-center placement offset. The measured mirror, shear and pivot are stored
in the manifest. Manual orientation and anchor flags remain available only as a
fallback for silhouettes without readable ground contacts.

The automatic selector uses `contact_line` for wide, shallow objects such as
boards and fences. For deep machines or furniture it uses `lower_structure`,
measuring the principal axis of the lower 55% instead of mistaking unrelated
feet and rollers for a single baseline. The selected method is recorded per
asset in the manifest.

Compact `1x1` objects use `base_contact` for placement. It finds the center of
only the lowest opaque support band and anchors the center of that band to the
tile center. Wide leaves, handles or other asymmetric upper details therefore
cannot pull a pot, trophy or similarly compact object away from the center of
its base, while a single lowest pixel cannot pull it too far down.
The band is adaptive: upright/square silhouettes use the bottom 12%, while low,
wide silhouettes use 28% so footwear is aligned by the visible sole rather than
by its single lowest pixel.
Tall elongated objects use `support_plane`: the horizontal pivot comes from the
lower contact line, while a robust upper-quartile support depth ignores one
protruding roller or foot. Short elongated objects keep the original contact-line
placement.

After choosing that pivot, `support_containment` checks the lower support against
the union of its declared isometric slot diamonds: the actual bottom 12% for
compact `1x1` bases, and the lower 35% for machines and furniture.
It first searches for the smallest translation that contains the support. If the
base is physically too large, it reduces the sprite uniformly in 4% nearest-
neighbor steps; it never stretches or shears it. `containment_qa` records support
pixels outside before/after, the applied uniform scale and `pass`/`review`.
For `1x1` objects the vertical coordinate from `base_contact` is locked during
this step: containment may move the sprite horizontally or reduce it, but cannot
push it downward and mistake the upper pot or shoe body for the ground base.

Use `--geometry-locked` to preserve pixel-art shape. The pipeline still crops,
scales uniformly, quantizes and centers contact points, but it is forbidden from
shearing or stretching the sprite. Auto-alignment mirrors the sprite when its
long axis points opposite to the declared X/Y footprint; mirroring does not alter
proportions. Remaining angle mismatches must be reported in QA and fixed in
the source rather than hidden through deformation.
For elongated objects, `geometry_qa` in the manifest records the expected and
measured axis slopes, absolute error, and `pass`/`review` status. The current
tolerance is `0.08`; review never triggers an automatic shear.
The lightweight `exact_axis_scores` check scans only the final alpha boundary
and reports support for `+1/2`, `-1/2` and screen-vertical directions. It uses no
network, AI call or heavy computer-vision dependency, so it can run for every
object on every build.

White or checkerboard backgrounds are removed automatically from the image
border before alpha crop. The flood fill uses eight-direction connectivity so
diagonally open gaps in handles, frames and chair backs are cleaned as background,
while genuinely enclosed cream details remain intact. Specialized
local source builders may still be run explicitly, but only a resulting source
with the appropriate declaration participates in the discovered collection.
