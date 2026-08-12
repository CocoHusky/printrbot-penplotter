# Release 1.0.9 — Graves Text Cleanup

The Graves adapter now handles text compatibility explicitly:

- Common smart punctuation is normalized to ASCII.
- Unsupported punctuation and symbols are removed with a visible render
  warning instead of causing an opaque model failure.
- Unsupported letters and writing systems still produce a clear error because
  removing them could silently change the note's meaning.
- Extra whitespace created by cleanup is collapsed.
