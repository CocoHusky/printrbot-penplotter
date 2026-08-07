# Release 0.3 — Native Writing Engine

Release 0.3 replaces outline-only text plotting with a centerline writing system designed for real pens. The release focuses on single-line glyphs, deterministic alternates, basic cursive joining, wrapping, and travel-aware stroke ordering.

## Release goal

A user can type text, choose a single-line handwriting or robot style, preview exactly one physical pen path per authored stroke, vary repeated letters reproducibly, wrap text to a physical width, and optionally connect compatible lowercase letters.

## Implemented in the first Release 0.3 increment

- [x] Add a native centerline `StrokeFont` and `GlyphVariant` model.
- [x] Add built-in `hand` and `robot` stroke fonts.
- [x] Cover uppercase A–Z, lowercase a–z, digits, and common punctuation.
- [x] Add three deterministic variants for built-in hand glyphs.
- [x] Add `first`, `seeded`, and `cycle` variant-selection modes.
- [x] Add entry and exit anchors for lowercase handwriting glyphs.
- [x] Add simple baseline connectors between compatible neighboring letters.
- [x] Add real millimeter cap height and word-wrap width.
- [x] Add configurable word spacing, tracking, and writing slant.
- [x] Preserve authored stroke order by default.
- [x] Add optional nearest-endpoint ordering for independent multi-stroke glyphs.
- [x] Add a validated JSON format for custom stroke-font packs.
- [x] Add a user-editable example font pack.
- [x] Preserve the conventional TTF/OTF outline engine as an explicit compatibility option.
- [x] Add CLI and browser controls for writing engine, font, variants, joins, wrapping, slant, and spacing.
- [x] Report font, variant labels, connector count, line count, and fallback characters in job metadata.
- [x] Add automated tests for built-ins, single-line behavior, deterministic variants, wrapping, joining, custom font loading, fallbacks, and stroke ordering.

## Important current limitations

- The built-in hand font is an initial engineering alphabet, not a polished calligraphy family.
- Cursive joining uses baseline connector curves; it does not yet perform contextual letter substitution or ligatures.
- Uppercase and punctuation glyphs generally do not expose cursive connection anchors.
- Glyph collision detection and word-level flourish planning are not implemented.
- Global reordering of handwriting strokes is intentionally avoided because it can scramble letter order.
- The outline engine still creates double-line letter edges by design and should not be described as single-line handwriting.

## Remaining before Release 0.3 is complete

### Glyph quality and coverage

- [ ] Review every built-in glyph in physical pen tests.
- [ ] Add alternate lowercase forms based on measured drawing quality.
- [ ] Add contextual beginning, middle, ending, and isolated variants.
- [ ] Add common ligatures such as `th`, `ll`, `tt`, `ing`, and `oo`.
- [ ] Add accented Latin characters and configurable fallback policy.
- [ ] Add punctuation entry/exit behavior where visually appropriate.
- [ ] Add a font-pack provenance and license field.

### Cursive and handwriting intelligence

- [ ] Replace generic connectors with glyph-specific exit/entry curves.
- [ ] Detect connector collisions with neighboring glyph strokes.
- [ ] Add optional continuous word strokes where the font defines them.
- [ ] Add word-level baseline drift and controlled slant variation.
- [ ] Add alternate capital-letter entry and terminal flourishes.
- [ ] Add a preview mode that highlights connectors separately from authored glyph strokes.

### Layout and editing

- [ ] Add paragraph alignment before final page placement.
- [ ] Add explicit line breaks and wrapping diagnostics in the browser.
- [ ] Add per-line width and baseline metadata.
- [ ] Add interactive glyph-variant replacement in the preview.
- [ ] Add drag handles for position, scale, and text box width.
- [ ] Add save/load of reproducible writing job settings.

### Motion quality

- [ ] Measure pen-up distance, ink distance, and estimated duration in every job.
- [ ] Optimize disconnected strokes without changing word order.
- [ ] Add near-endpoint stroke joining with a configurable tolerance.
- [ ] Add corner-aware feed-rate planning.
- [ ] Add optional smoothing that preserves authored endpoints and anchors.

### Tests and validation

- [ ] Add golden previews for every built-in glyph.
- [ ] Add physical sample sheets and measurement records.
- [ ] Test custom font packs containing malformed Unicode and extreme values.
- [ ] Add browser API tests for all writing controls.
- [ ] Add property tests for deterministic seeded selection.
- [ ] Add regression tests proving the stroke engine never silently switches to outlines.

## Release acceptance criteria

Release 0.3 is complete only when:

- every supported built-in glyph has been visually reviewed in preview and on paper;
- repeated characters can use reproducible, visibly distinct variants;
- a lowercase word can be joined without unintended pen lifts where anchors exist;
- physical wrapping respects the configured width within tolerance;
- unsupported characters are never silently dropped;
- custom font packs are validated before geometry generation;
- the selected text engine is explicit in metadata;
- a stroke-font `L` is drawn as one centerline stroke rather than a closed outline;
- Release 0.2 safety and machine-space validation remain intact.
