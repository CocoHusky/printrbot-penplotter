# Studio 2 geometry limits

Studio 2 owns the normal adjustable artistic soft limits. Shared geometry and physical planning use bounded hard memory guards so an explicit Studio expert bypass can pass through placement, preview, routing, and G-code generation.

- Default Studio soft limit: 20,000 artistic strokes / 2,000,000 artistic points.
- Expert bypass hard guard: 200,000 strokes / 20,000,000 points.
- The expert bypass must never be converted back to the soft values by the browser before submitting the render request.
- Machine bounds, safe homing/pen-up sequencing, and the G-code command guard remain independent safety checks.
