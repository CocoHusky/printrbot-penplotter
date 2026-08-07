# Custom Stroke-Font Format

Release 0.3 introduces a native centerline font format for pen plotting. Unlike a normal TTF/OTF outline, each glyph is stored as one or more paths that the pen draws directly.

The format is JSON so glyphs can be authored, generated, versioned, and exchanged without changing Python code.

## Minimal structure

```json
{
  "name": "my-font",
  "description": "A personal monoline alphabet.",
  "cap_height": 1.0,
  "line_height": 1.4,
  "fallback": "?",
  "glyphs": {
    "?": [
      {
        "advance": 0.8,
        "strokes": [
          [[0.0, 0.8], [0.3, 1.0], [0.6, 0.8], [0.3, 0.4]],
          [[0.3, 0.02], [0.31, 0.02]]
        ]
      }
    ]
  }
}
```

Coordinates use normalized font units. With the default `cap_height` of `1.0`, `y=0` is the baseline and `y=1` is the nominal capital-letter height. Descenders can use negative Y coordinates.

## Font fields

| Field | Required | Meaning |
|---|---:|---|
| `name` | recommended | Font identifier shown by the CLI and metadata |
| `description` | no | Human-readable purpose or style |
| `cap_height` | no | Normalized height corresponding to `--font-size`; default `1.0` |
| `line_height` | no | Baseline-to-baseline distance in normalized units; default `1.35` |
| `fallback` | no | Glyph used for unsupported characters; default `?` |
| `glyphs` | yes | Object mapping one Unicode character to one or more variants |

The fallback character must exist in `glyphs`.

## Glyph variants

Every glyph value is a non-empty array. Each item is a distinct way to draw the character:

```json
"a": [
  {
    "label": "round-a",
    "advance": 0.68,
    "entry": [0.02, 0.0],
    "exit": [0.62, 0.0],
    "strokes": [
      [[0.02, 0.0], [0.12, 0.34], [0.38, 0.42], [0.58, 0.0]]
    ]
  },
  {
    "label": "narrow-a",
    "advance": 0.64,
    "entry": [0.02, 0.0],
    "exit": [0.58, 0.0],
    "strokes": [
      [[0.02, 0.0], [0.1, 0.32], [0.34, 0.42], [0.54, 0.0]]
    ]
  }
]
```

| Field | Required | Meaning |
|---|---:|---|
| `strokes` | yes | Array of paths; each path requires at least two `[x,y]` points |
| `advance` | no | Horizontal cursor movement after the glyph; default `1.0` |
| `entry` | no | Anchor where a connector may enter the glyph |
| `exit` | no | Anchor where a connector may leave the glyph |
| `label` | no | Variant name written into job metadata |

All coordinates and numeric values must be finite. The loader rejects malformed paths, missing fallbacks, empty variants, and invalid advances.

## Variant selection

```bash
--variant-mode first
--variant-mode seeded
--variant-mode cycle
```

- `first` always uses the first authored form.
- `seeded` selects a deterministic variant from the text position, character, and `--seed`.
- `cycle` rotates through variants in order and is useful for inspecting a font pack.

The same text, font pack, settings, and seed produce the same output.

## Cursive connection anchors

When `--connect-letters` is enabled, the engine can add a short connector between the previous glyph's `exit` and the next glyph's `entry`.

```bash
printrbot-plotter text "minimum" \
  --engine stroke \
  --stroke-font hand \
  --connect-letters
```

Connection anchors do not force a glyph's first or last stroke to begin at those exact points. They define the intended joining location. Fonts without anchors remain unconnected.

Release 0.3 uses simple baseline connectors. Contextual letter substitution, ligatures, collision avoidance, and calligraphic entry/exit shaping remain later writing-engine work.

## Inspect a font

List built-ins:

```bash
printrbot-plotter fonts
```

Inspect a built-in:

```bash
printrbot-plotter fonts --font hand
```

Validate and inspect a custom pack:

```bash
printrbot-plotter fonts --file fonts/example-stroke-font.json
```

## Render with a custom pack

```bash
printrbot-plotter text "Aaa" \
  --engine stroke \
  --stroke-font-path fonts/example-stroke-font.json \
  --variant-mode cycle \
  --connect-letters \
  --font-size 18
```

Unsupported characters use the configured fallback and are listed in the generated job metadata.

## Included example

[`fonts/example-stroke-font.json`](../fonts/example-stroke-font.json) contains a fallback glyph, an uppercase `A`, and two lowercase `a` variants. It is intentionally small and should be copied before editing.
