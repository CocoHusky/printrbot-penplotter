# Release 1.0.6 — Native Graves Scale

The Graves worker now preserves the reference model's native trajectory scale.
Printrbot applies physical sizing later during page layout, avoiding an extra
adapter-level scale that could distort proportions before fitting.
