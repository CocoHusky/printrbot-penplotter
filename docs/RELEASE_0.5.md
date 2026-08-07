# Release 0.5 — Image and Handwriting Ingestion

Release 0.5 adds raster input to the same geometry pipeline already used by text and SVG. A scanned note, photographed handwriting sample, sketch, logo, or simple image can be thresholded, cleaned, traced into polylines, previewed in exact machine coordinates, and converted to the same guarded Marlin G-code as every other input type.

The release does **not** add a second renderer and does **not** recognize or retype handwriting. It traces visible marks.

## Release goal

```text
PNG / JPEG / WebP / TIFF / BMP
                ↓
EXIF orientation + grayscale
                ↓
optional blur + threshold + inversion
                ↓
connected-component cleanup
                ↓
centerline OR contour tracing
                ↓
pixel-space simplification
                ↓
shared polyline model
                ↓
page placement + machine validation
                ↓
exact preview + Marlin G-code
```

A handwriting-specific command uses centerline tracing so a thick pen stroke can become one drawable path rather than two outline paths.

## Implemented in the first Release 0.5 increment

### Raster preprocessing

- [x] Add Pillow and NumPy as explicit runtime dependencies.
- [x] Respect image EXIF orientation before tracing.
- [x] Composite transparent images onto white before grayscale conversion.
- [x] Reject missing, unreadable, empty, and excessively large raster sources.
- [x] Downsample large images before expensive tracing work.
- [x] Bound processed images to both a longest-side limit and total-pixel limit.
- [x] Add deterministic global Otsu thresholding.
- [x] Allow an explicit 0–255 threshold override.
- [x] Support light marks on dark backgrounds with `--invert`.
- [x] Add optional Gaussian blur before thresholding.
- [x] Remove connected foreground components smaller than a configured pixel count.
- [x] Record preprocessing choices and cleanup counts in job metadata.

### Centerline tracing

- [x] Add deterministic Zhang-Suen thinning for binary foreground masks.
- [x] Convert the skeleton pixel graph into independent polylines.
- [x] Preserve branches as separate drawable stroke segments rather than hiding topology.
- [x] Track skeleton iteration count, convergence, and final pixel count in metadata.
- [x] Use centerline tracing as the default for the `handwriting` command.

### Contour tracing

- [x] Trace foreground pixel boundaries into ordered contour paths.
- [x] Close ordinary component outlines explicitly.
- [x] Use contour tracing as the default for the general `image` command.
- [x] Keep contour and centerline behavior explicit instead of pretending they are equivalent.

### Cleanup and manual correction path

- [x] Add deterministic pixel-space polyline simplification before page placement.
- [x] Add `--trace-svg` to export the raw traced paths before machine placement.
- [x] Keep the exported trace as plain SVG paths so it can be corrected in a normal vector editor.
- [x] Reuse the existing `svg` command to import a corrected trace back into the shared plotter pipeline.

### Pipeline and CLI

- [x] Add `render_image_job()`.
- [x] Add `render_handwriting_job()`.
- [x] Add `raster_to_polylines_with_metadata()` to the input-adapter boundary.
- [x] Add `printrbot-plotter image SOURCE`.
- [x] Add `printrbot-plotter handwriting SOURCE`.
- [x] Keep raster tracing upstream of physical layout and G-code generation.
- [x] Keep image and handwriting jobs compatible with `--air-plot`, page placement, machine bounds, and the existing USB/ESP32 transports.
- [x] Bump the Python package to 0.5.0.

### Tests

- [x] Test thick-stroke centerline reduction.
- [x] Test closed contour output.
- [x] Test connected-component noise removal.
- [x] Test inverted light-on-dark input.
- [x] Test deterministic image downsampling metadata.
- [x] Test blank-image failure.
- [x] Test image jobs through the shared preview/G-code pipeline.
- [x] Test handwriting jobs as centerline traces with recognition explicitly disabled.
- [x] Test editable trace SVG generation.
- [x] Test CLI image rendering with G-code, machine-space preview, and raw trace SVG outputs.

## Remaining before Release 0.5 is complete

### Browser workflow

- [ ] Add drag-and-drop raster upload to the local Python browser application.
- [ ] Add image/handwriting mode selection in the browser.
- [ ] Show the original image, cleaned binary mask, raw trace, and machine-space preview side by side.
- [ ] Add threshold, inversion, blur, component-size, and simplification controls with immediate preview.
- [ ] Add browser download for the editable raw trace SVG.
- [ ] Add an explicit image-to-ESP32 workflow that uploads only the reviewed final G-code.

### Manual correction

- [ ] Add an in-browser polyline editor for deleting noise strokes.
- [ ] Add point and segment deletion.
- [ ] Add stroke splitting and joining.
- [ ] Add endpoint dragging and simple smoothing.
- [ ] Add crop, rotate, and flip before tracing.
- [ ] Preserve all manual edits in a reproducible sidecar/job file.
- [ ] Ensure edited geometry remains the single source for both preview and G-code.

### Image cleanup quality

- [ ] Add adaptive/local thresholding for uneven lighting.
- [ ] Add background normalization for photographed paper.
- [ ] Add optional contrast normalization.
- [ ] Add perspective correction for angled phone photos.
- [ ] Add configurable branch pruning for short skeleton spurs.
- [ ] Improve diagonal-touch contour topology and hole handling.
- [ ] Add optional gap closing for broken handwriting strokes.
- [ ] Add optional stroke-width diagnostics before skeletonization.

### Reproducibility and job records

- [ ] Hash the source image and record the hash in job metadata.
- [ ] Record the complete raster configuration in a serializable job sidecar.
- [ ] Save raw trace geometry beside final machine-space geometry.
- [ ] Add a round-trip command that reloads a saved raster job without retracing the source image.
- [ ] Record software version and tracing algorithm version in every raster job.

### Performance and robustness

- [ ] Add performance tests on large but permitted images.
- [ ] Add pathological branch-density tests for centerline tracing.
- [ ] Add diagonal-contact and nested-hole contour fixtures.
- [ ] Add malformed-image corpus tests.
- [ ] Add memory-use reporting for the configured maximum raster size.
- [ ] Add static typing/formatting checks for the raster module.

## Current CLI examples

Trace a simple image as outlines:

```bash
printrbot-plotter image sketch.png \
  --trace-mode contour \
  --air-plot \
  --output out/sketch.gcode \
  --preview out/sketch.svg
```

Trace handwriting as stroke centerlines:

```bash
printrbot-plotter handwriting note.jpg \
  --air-plot \
  --output out/note.gcode \
  --preview out/note.svg
```

Export an editable pre-placement trace:

```bash
printrbot-plotter handwriting note.jpg \
  --trace-svg out/note-trace.svg \
  --air-plot
```

After editing `out/note-trace.svg` in a vector editor, bring the corrected geometry back through the established SVG adapter:

```bash
printrbot-plotter svg out/note-trace.svg \
  --air-plot \
  --output out/note-corrected.gcode \
  --preview out/note-corrected.svg
```

## Trace-mode semantics

### `centerline`

Best for pen handwriting, marker sketches, and other stroke-like input. The foreground mask is thinned to a one-pixel skeleton and then converted into graph paths. Junctions can produce several path segments because a branch is not physically one unambiguous pen stroke.

### `contour`

Best for filled shapes, logos, silhouettes, and artwork where the visible boundary is the intended drawing. The result follows the outside edges of foreground pixels. A thick handwritten line therefore becomes two sides of an outline, which is usually not the desired handwriting behavior.

## Safety behavior

Raster ingestion does not change hardware safety rules:

- tracing and previewing work without connected hardware;
- raster input never enables homing automatically;
- output still passes machine and paper bounds validation;
- `--air-plot` never lowers the pen;
- G-code generation remains centralized in `gcode.py`;
- USB sending and ESP32 upload keep their existing command safety filters;
- real plotting remains gated by Release 0.2 physical machine validation;
- ESP32 UART use remains gated by the Release 0.4 electrical and end-to-end checklist.

## Release acceptance criteria

Release 0.5 is complete only when:

- common raster formats can be loaded deterministically and safely;
- centerline and contour modes are both tested and remain explicit;
- preprocessing limits prevent unbounded image memory/geometry growth;
- a photographed/scanned handwriting sample can be converted into a useful centerline preview;
- a simple filled image can be converted into a useful contour preview;
- the exact final polylines still drive both preview and G-code;
- a user can inspect and manually correct trace geometry before hardware sending;
- browser raster upload and preview are available;
- raster source/configuration metadata is sufficient to reproduce a trace;
- Release 0.2 and Release 0.4 physical safety gates remain intact.
