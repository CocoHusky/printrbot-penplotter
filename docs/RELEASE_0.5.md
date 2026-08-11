# Historical Release 0.5 Notes — Retired Raster Studio

> This is a historical implementation note, not current product documentation.
> Its `/raster` workflow and manual editor were retired in favor of Studio 2 at
> `/studio2`. Current behavior is documented in the root README.

Release 0.5 adds raster input and a browser correction workflow to the same geometry pipeline already used by text and SVG. A scanned note, photographed handwriting sample, sketch, logo, or simple image can be thresholded, cleaned, traced into polylines, manually corrected, previewed in exact machine coordinates, and converted to guarded Marlin G-code.

The release does **not** recognize or retype handwriting. It traces visible marks.

## Release pipeline

```text
PNG / JPEG / WebP / TIFF / BMP
                ↓
EXIF orientation + grayscale
                ↓
blur / threshold / inversion
                ↓
connected-component cleanup
                ↓
centerline OR contour tracing
                ↓
pixel-space simplification
                ↓
editable raw polylines
                ↓
manual correction
                ↓
page placement + machine validation
                ↓
exact preview + Marlin G-code
```

## Completed

### Raster preprocessing

- [x] Pillow and NumPy runtime dependencies.
- [x] EXIF orientation handling.
- [x] Transparent images composited onto white.
- [x] Missing, unreadable, empty, oversized, and blank raster rejection.
- [x] Downsampling before expensive tracing work.
- [x] Longest-side and total-pixel limits.
- [x] Deterministic global Otsu thresholding.
- [x] Manual 0–255 threshold override.
- [x] Light-on-dark inversion.
- [x] Optional Gaussian blur.
- [x] Connected-component noise removal.
- [x] Trace metadata for resize, threshold, cleanup, skeletonization, strokes, and points.

### Centerline and contour tracing

- [x] Zhang-Suen thinning for handwriting and stroke-like input.
- [x] Skeleton graph converted into drawable path segments.
- [x] Branches preserved rather than silently discarded.
- [x] Foreground contour tracing for logos, silhouettes, and filled regions.
- [x] Deterministic RDP simplification before machine placement.
- [x] Centerline and contour modes remain explicit rather than being conflated.

### CLI workflow

- [x] `printrbot-plotter image SOURCE`.
- [x] `printrbot-plotter handwriting SOURCE`.
- [x] `--trace-svg` raw trace export.
- [x] Corrected SVGs can be re-imported through the established SVG adapter.
- [x] Raster jobs use the existing page, machine, air-plot, USB, and ESP32 boundaries.

### Browser Image & Handwriting Studio

- [x] Add `printrbot-studio` unified local server.
- [x] Drag-and-drop image upload.
- [x] Image/contour and handwriting/centerline mode selection.
- [x] Live controls for threshold, inversion, blur, component cleanup, simplification, and air/pen output.
- [x] Four-stage view: original → cleaned mask → raw trace → final machine preview.
- [x] Click-to-select path editor.
- [x] Shift-click multi-selection.
- [x] Delete selected paths.
- [x] Reverse path direction.
- [x] Split a selected path at its midpoint.
- [x] Join two selected paths using the nearest compatible endpoint orientation.
- [x] Drag start/end points of a selected path.
- [x] Undo recent edits.
- [x] Rebuild final machine preview and G-code from the edited geometry.
- [x] Download edited SVG.
- [x] Download final G-code.
- [x] Download reproducible job JSON.

### Reproducibility

- [x] SHA-256 hash uploaded source bytes.
- [x] Record source filename and byte count.
- [x] Record effective threshold and trace configuration.
- [x] Preserve raw trace polylines in the job sidecar.
- [x] Preserve final machine-space polylines after browser finalization.
- [x] Mark handwriting recognition as false in metadata.

### Tests

- [x] Thick-stroke centerline reduction.
- [x] Closed contour output.
- [x] Connected-component cleanup.
- [x] Inverted input.
- [x] Deterministic downsampling metadata.
- [x] Blank-image rejection.
- [x] Raster jobs through the shared preview/G-code pipeline.
- [x] Handwriting centerline semantics.
- [x] Editable trace SVG generation.
- [x] CLI raster output.
- [x] Browser studio route.
- [x] Multipart raster upload and four-stage response.
- [x] Source SHA-256 sidecar generation.
- [x] Edited-geometry finalization.
- [x] Non-finite edited-geometry rejection.

## Deferred enhancements

These are useful improvements but are no longer blockers for the Release 0.5 core workflow:

- adaptive/local thresholding for strongly uneven lighting;
- automatic paper-background normalization;
- automatic perspective correction for angled phone photographs;
- branch-pruning controls for short skeleton spurs;
- more sophisticated contour hole/diagonal topology;
- gap closing for broken ink strokes;
- point-level arbitrary split selection rather than midpoint split;
- multi-point curve handles and advanced smoothing;
- large corpus performance benchmarking.

They can be incorporated into the later unified studio without creating another raster pipeline.

## Browser use

```bash
printrbot-studio
```

This historical prototype was retired during the Studio consolidation. Use the
current image workflow at `http://127.0.0.1:8000/studio2`; the root page at
`http://127.0.0.1:8000/` remains the writing interface.

## Safety behavior

Raster ingestion does not change hardware safety rules:

- tracing and editing work without hardware;
- uploads never enable homing;
- final edited geometry is revalidated before machine placement;
- machine and paper bounds still apply;
- air-plot mode cannot lower the pen;
- G-code generation remains centralized in `gcode.py`;
- USB and ESP32 transports keep their existing command filters;
- pen-down use remains gated by Release 0.2 physical validation;
- ESP32 UART use remains gated by Release 0.4 electrical validation.

## Release acceptance

Release 0.5 is accepted when CI passes and the browser workflow can take an uploaded raster image through original/mask/trace/final inspection, allow manual path correction, and regenerate preview/G-code from the exact edited geometry without introducing a second renderer.
