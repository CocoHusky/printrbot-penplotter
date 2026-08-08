# Step 2 — Image preprocessing engine

Step 2 adds deterministic image normalization upstream of tracing. It does not add photo-sketch styles, edge understanding, hatching, or new machine motion; those remain later roadmap steps.

## Pipeline boundary

```text
source raster
  -> EXIF orientation
  -> crop / perspective / rotation / optional deskew
  -> bounded resize
  -> grayscale/channel conversion
  -> denoise
  -> background normalization/removal
  -> exposure / levels / contrast / gamma
  -> optional histogram equalization / CLAHE
  -> threshold selection
  -> binary foreground mask
  -> existing component cleanup
  -> existing centerline or contour trace
  -> shared polyline / preview / G-code pipeline
```

All image operations are local and deterministic. No cloud or remote AI image processing is used.

## Geometric normalization

`ImagePreprocessConfig` supports:

- normalized crop box;
- arbitrary rotation;
- optional deterministic deskew with a bounded correction angle;
- normalized four-corner perspective correction;
- EXIF orientation correction;
- bounded downsampling before expensive operations.

Crop and perspective coordinates are stored as normalized values so a saved configuration can be replayed against the same source without depending on an absolute working resolution.

## Grayscale and channel selection

Available grayscale modes:

- `auto` — chooses the highest robust-contrast candidate among luminance/red/green/blue;
- `luminance`;
- `average`;
- `desaturate`;
- `red`;
- `green`;
- `blue`;
- `max`;
- `min`;
- `custom` RGB weights.

The effective channel choice is written to metadata.

## Tonal normalization

Available deterministic controls:

- exposure in EV;
- additive brightness;
- contrast;
- gamma;
- manual black and white points;
- percentile auto-levels;
- global histogram equalization;
- contrast-limited adaptive histogram equalization (CLAHE).

The effective black/white points used after auto-level analysis are recorded.

## Denoising

Available controls:

- Gaussian blur;
- median filtering;
- bounded bilateral filtering;
- median despeckle pass.

Bilateral filtering is intentionally radius-bounded because raster files are untrusted input and processing cost must remain bounded.

## Background handling

Three local deterministic modes are available:

- `keep` — do not modify illumination/background;
- `suppress` — estimate low-frequency illumination and normalize it toward white;
- `remove` — suppress illumination and set locally weak foreground contrast to white.

This is traditional image processing, not semantic object/background segmentation. Semantic subject extraction remains a future feature.

## Threshold modes

`ThresholdConfig` supports:

- manual global threshold;
- Otsu;
- global mean;
- triangle threshold;
- adaptive local mean;
- adaptive Gaussian;
- Sauvola;
- Niblack.

Local methods record threshold minimum, maximum, mean/effective threshold, window size, offsets, and method-specific parameters. Inversion remains explicit.

## Raster integration

`RasterTraceConfig` keeps all Release 0.5 fields for compatibility and adds two optional nested records:

```python
RasterTraceConfig(
    mode="centerline",
    preprocess=ImagePreprocessConfig(...),
    thresholding=ThresholdConfig(...),
)
```

When the nested records are omitted, existing behavior remains compatible: luminance grayscale, optional legacy Gaussian blur, bounded resize, Otsu or manual threshold, inversion, component cleanup, and centerline/contour tracing.

Every traced result now records `preprocessing_schema = printrbot-image-preprocess/v2` plus the complete effective preprocessing and threshold metadata.

## CI and acceptance

Step 2 is guarded by `.github/workflows/image-preprocess.yml`, which runs on pull requests and pushes to `main` and includes:

- Python 3.11 and 3.13;
- compilation checks;
- Step 2 preprocessing tests;
- existing raster and Studio regression tests;
- deterministic adaptive-threshold smoke test.

The repository's existing `Test` and `Safety Contract` workflows also run on the Step 2 pull request, so image work cannot merge if the Step 1 hardware contract regresses.

## Explicitly not Step 2

The following remain later roadmap work:

- Canny/Sobel/Scharr/DoG edge understanding;
- semantic subject masks;
- region and tone interpretation for artwork;
- curve/vector quality improvements;
- clean-outline / sketch / portrait styles;
- hatching, crosshatching, stippling, engraving, fur strokes;
- automatic artistic style selection;
- Studio 2.0 UI for exposing the complete advanced filter stack.
