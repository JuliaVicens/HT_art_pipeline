# HabitTracker terrain source prompt contract

Use this block when generating any source that will pass through the terrain
normalizer. Replace the bracketed fields; keep the production constraints.

```text
Use case: stylized-concept
Asset type: HabitTracker Nature terrain source/reference
Primary request: one isolated isometric [SUBJECT] tile
Scene/backdrop: genuinely transparent background; isolated asset only
Subject: one centered exact 2:1 isometric diamond [SUBJECT]
Style/medium: cozy pastel pixel-art-inspired game asset; simple crisp clusters;
  designed for nearest-neighbor reduction to a 64x32 surface
Composition: exact geometric center; balanced detail around the center; the
  dominant pattern must not drift toward any corner or edge
Pattern scale: medium and large pixel clusters that survive reduction; typical
  feature width 10-25% of the surface width (about 6-16 pixels in the final
  64-pixel tile); no essential line, dot, blade, pebble or ripple thinner than
  6 source-to-output pixels; avoid microtexture, tiny speckles and dense noise
Pattern hierarchy: use a few readable repeated clusters rather than many tiny
  motifs; broad secondary color regions may reach 35% when softly distributed,
  but no single region may become a unique landmark or dominate the tile
Pattern distribution: statistically uniform across the complete top face;
  comparable density and average brightness in every quadrant
Edge behavior: keep the outer 10% of all four surface edges visually neutral;
  opposite edges must have similar average color, brightness and detail density
Lighting: uniform soft diffuse light; no directional gradient across the tile;
  no bright corner, dark corner, hotspot, vignette, rim glow or cast shadow
Perspective: exact symmetric 2:1 isometric surface; left and right vertices at
  equal height; top and bottom vertices on the vertical center axis
Color palette: [PALETTE NOTES]
Constraints: actual alpha transparency; no large-scale heterogeneity; no unique
  landmark; no composition-wide wave, stripe, blob or diagonal lighting band;
  no text, watermark, border or scenery outside the tile
```

## Water additions

Append:

```text
Water pattern: broad evenly distributed ripple clusters with no dominant wave
direction; each final highlight must be at least 6 pixels long and 2 pixels
thick; no hairline ripples, tiny sparkle noise, large reflection or central hotspot;
all four edges must have similar water tone and ripple density; surface only,
with no soil sides or shoreline.
```

## Connected path additions

Append:

```text
Connection rule: the path centerline passes through the exact tile center and
meets the requested edge centers precisely; endpoint widths are identical;
the path keeps a constant width of approximately 18% of the surface width;
no taper, meander, off-center endpoint or lighting change at either connection.
Connections: [NW-SE | NE-SW | TURN | T | CROSS | END]
```

## Why these constraints exist

The normalizer can fix dimensions, palette and one- or two-pixel border
differences. It should not be expected to recover patterns that collapse below
one pixel after reduction, or remove broad illumination gradients, large unique
patches or displaced motifs without visibly damaging the art. Judge every motif
at the final `64x32` size, not only in the large source image.
