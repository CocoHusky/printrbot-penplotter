"""Unified local web application with writing, raster, Studio 2, and product routes."""

from __future__ import annotations

from pathlib import Path

from . import studio2 as studio2_module
from .geometry import MAX_POINTS, MAX_STROKES
from .product_api import router as product_router
from .raster_studio import router as raster_router
from .studio2_fixes import apply_studio2_fixes
from .web import app

# Apply Studio-only integration fixes before the router serves HTML or renders jobs.
apply_studio2_fixes(studio2_module)
studio2_router = studio2_module.router

app.include_router(raster_router)
app.include_router(studio2_router)
app.include_router(product_router)


def _validate_studio_runtime() -> None:
    """Refuse to start Studio with the legacy 20k shared geometry guard.

    Studio 2 owns the normal adjustable artistic soft limit. The shared geometry
    layer must retain the higher bounded hard guard so the explicit expert bypass
    can reach placement, preview, physical planning, and G-code generation.
    This catches stale/mixed editable installs that otherwise make the UI claim a
    bypass is active while an older geometry.py still rejects at 20,000 strokes.
    """
    if MAX_STROKES < 200_000 or MAX_POINTS < 20_000_000:
        raise RuntimeError(
            "Studio 2 runtime is using legacy geometry limits "
            f"({MAX_STROKES:,} strokes / {MAX_POINTS:,} points). "
            "Reinstall the current repo with: python -m pip install -e '.[dev]'"
        )


def main() -> None:
    import uvicorn

    _validate_studio_runtime()
    package_root = Path(__file__).resolve().parent
    print(
        "Studio 2 geometry guard: "
        f"{MAX_STROKES:,} strokes / {MAX_POINTS:,} points | source: {package_root}"
    )
    uvicorn.run("printrbot_penplotter.studio_server:app", host="127.0.0.1", port=8000)
