# Step 5 — Deterministic Line-Art Styles

Step 5 adds the first artistic rendering layer for raster images. It consumes the deterministic grayscale/feature outputs from Steps 2 and 3, converts those features to shared polyline geometry, and applies the Step 4 vector-cleanup layer before machine placement.

The output remains ordinary `Polylines`. Preview and G-code therefore continue to consume the same final geometry.

## Styles

The initial style library contains:

- `minimal_outline` — silhouette plus only the strongest interior features.
- `clean_outline` — clean subject boundary with selected strong interior lines.
- `detailed_outline` — outline, selected edges, and tonal boundaries.
- `continuous_contour` — flowing cleanup and endpoint joining for fewer fragmented strokes.
- `one_line_art` — intentionally stylized nearest-chain connections between open strokes; inserted bridges are reported in metadata.
- `loose_sketch` — broader selected edges plus dark-region boundaries with flowing cleanup.
- `refined_pen_sketch` — balanced silhouette, interior edge, and tonal-boundary rendering.
- `pet_portrait` — a deterministic feature-emphasis preset tuned toward dark internal detail and outline retention. It does not detect pets.
- `portrait` — a deterministic feature-emphasis preset. It does not detect faces or people.
- `comic_ink` — stronger boundaries and dark-region separation.
- `architectural_pen` — longer, more geometric strong-edge and tone-boundary rendering.
- `technical_drawing` — strong structural edges with conservative smoothing and corner preservation.
- `silhouette` — foreground contour only.
- `topographic` — brightness-band boundaries plus the subject outline.

No Step 5 style performs semantic recognition, remote AI inference, hatching, crosshatching, stippling, or physical pen-width simulation. Those remain later roadmap items.

## API

```python
from printrbot_penplotter.line_art import LineArtConfig, render_line_art

result = render_line_art(
    "photo.jpg",
    LineArtConfig(style="refined_pen_sketch"),
)

polylines = result.polylines
metadata = result.metadata
```

For callers that already have a Step 3 analysis result:

```python
from printrbot_penplotter.line_art import render_line_art_from_analysis

result = render_line_art_from_analysis(analysis, LineArtConfig(style="clean_outline"))
```

## Determinism and metadata

Step 5 contains no randomness. Re-running the same input with the same Step 2, Step 3, Step 4, and Step 5 settings produces the same line geometry.

Metadata includes:

- `line_art_schema = printrbot-line-art/v1`
- selected style name
- source selected-edge and foreground pixel counts
- raw style stroke count
- final style stroke/point count
- complete Step 4 cleanup metadata
- explicit bridge counts/length for `one_line_art`
- `semantic_recognition = false` for pet/portrait presets

## Safety boundary

Step 5 does not create G-code and cannot move hardware. The result continues through page placement, motion optimization, exact preview, the host job validator, the ESP32 validator, and Marlin exactly like every other geometry source.

## CI

`.github/workflows/line-art-styles.yml` runs on pull requests and pushes to `main` using Python 3.11 and 3.13. It verifies:

1. all Step 5 style tests;
2. Step 4 vector-cleanup regressions;
3. Step 3 image-understanding regressions;
4. Step 2 preprocessing/raster/Studio regressions;
5. deterministic image → analysis → style → cleanup output.

The repository's existing Test, Safety Contract, Image Preprocessing, Image Understanding, and Vector Cleanup workflows remain independent regression gates.

## Deferred to Step 6+

Step 6 will add true tonal pen shading: parallel hatch, crosshatch, contour hatch, stipple, engraving, and related texture styles. Automatic style selection, pen-tip-aware detail filtering, and Studio 2.0 remain later milestones.
