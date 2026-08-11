# Historical Step 3 — Image understanding

> Historical design note. The supported image workflow is Studio 2; this file
> records the original analysis design and is not a separate user flow.

Step 3 adds deterministic feature analysis between Step 2 normalization and later vector/style generation. It does **not** change machine motion, G-code, the Step 1 safety contract, or the existing Release 0.5 centerline/contour tracer.

## Pipeline boundary

```text
source image
  -> Step 2 deterministic preprocessing
  -> bounded grayscale image
  -> Step 3 feature analysis
       -> edge strength
       -> detector edge mask
       -> detail-selected edge mask
       -> foreground mask
       -> tonal bands
       -> connected foreground regions
  -> later Step 4 vectorization / cleanup
  -> later Step 5+ drawing styles
```

All Step 3 outputs are analysis products. They are not sent to hardware directly.

## Edge detectors

`ImageUnderstandingConfig.edge_method` supports:

- `canny` — Gaussian smoothing, Sobel gradient, non-maximum suppression, deterministic hysteresis;
- `multiscale_canny` — combines Canny responses at three bounded blur scales;
- `sobel` — gradient magnitude;
- `scharr` — higher-weight 3x3 gradient magnitude;
- `laplacian` — second-derivative structure;
- `dog` — difference-of-Gaussians feature response;
- `morphological` — local max/min morphological gradient.

Each detector returns a normalized `edge_strength` array in 0..1 and a Boolean `edge_mask`.

## Detail selection

Four deterministic detail levels are available:

- `low`
- `medium`
- `high`
- `extreme`

The detail selector scores detector strength plus local edge continuity. Lower detail levels retain only stronger, better-connected features. Higher levels retain progressively more detector edges. The selected edge mask is always a subset of the detector edge mask.

This is feature selection, not semantic recognition. Step 3 does not claim that an edge is an eye, nose, fur, face, dog, person, or object.

## Foreground mask

Step 3 creates a traditional foreground mask using either:

- an explicit grayscale threshold; or
- deterministic Otsu thresholding when no foreground threshold is supplied.

Inversion is explicit. This foreground mask is used for region statistics only. It is not semantic background removal.

## Tonal bands

The normalized grayscale image is partitioned into configurable tonal bands. The default boundaries are:

```text
0..41
42..83
84..125
126..167
168..209
210..255
```

The result includes a per-pixel tone label and a tone histogram. Later hatching/shading work can consume this tonal representation without repeating image analysis.

## Region analysis

Four-connected foreground components are measured after a configurable minimum region size. Each retained `RegionRecord` stores:

- area in pixels;
- bounding box;
- centroid;
- mean grayscale;
- mean edge strength;
- whether the region touches the image border.

Regions are deterministically sorted by descending area and bounded by `max_regions` to keep untrusted images from generating unbounded analysis state.

## API

Analyze an already-normalized grayscale array:

```python
from printrbot_penplotter.image_understanding import (
    ImageUnderstandingConfig,
    analyze_gray,
)

result = analyze_gray(
    gray,
    ImageUnderstandingConfig(
        edge_method="multiscale_canny",
        detail_level="medium",
    ),
)
```

Or run Step 2 and Step 3 together:

```python
from printrbot_penplotter.image_preprocess import ImagePreprocessConfig
from printrbot_penplotter.image_understanding import ImageUnderstandingConfig, analyze_image

result = analyze_image(
    "photo.jpg",
    preprocess=ImagePreprocessConfig(background_mode="suppress", auto_levels=True),
    understanding=ImageUnderstandingConfig(detail_level="high"),
)
```

`analyze_image` merges the Step 2 reproducibility metadata with Step 3 metadata under `understanding_schema = printrbot-image-understanding/v1`.

## Determinism and limits

- No remote services or AI models are used.
- Detector results are deterministic for identical input arrays and configuration.
- Input size remains bounded by Step 2 preprocessing limits.
- Region count is explicitly bounded.
- Edge strength is normalized deterministically.
- Step 3 produces no polylines and no G-code.

## CI and acceptance

`.github/workflows/image-understanding.yml` runs:

- Python 3.11 and 3.13;
- compilation checks;
- all Step 3 tests;
- Step 2 preprocessing tests;
- raster/Studio regression tests;
- an end-to-end Step 2 -> Step 3 deterministic smoke test.

The existing `Test`, `Safety Contract`, and `Image Preprocessing` workflows also run on Step 3 pull requests. Step 3 must therefore preserve both the machine safety contract and all Step 2 behavior before merge.

## Explicitly not Step 3

Deferred to later roadmap steps:

- semantic subject/object/person/animal segmentation;
- face, eye, nose, fur, or object recognition;
- converting selected edges into improved smooth vector paths;
- spline/Bezier fitting and continuous-stroke reconstruction;
- clean-outline, pet portrait, sketch, comic, technical, or topographic styles;
- hatching, crosshatching, stippling, engraving, fur strokes, or other shading;
- automatic artistic style selection;
- Studio 2.0 controls and stage previews.
