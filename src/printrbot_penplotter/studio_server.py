"""Unified local web application with writing, raster, Studio 2, and product routes."""

from __future__ import annotations

from pathlib import Path

from starlette.datastructures import UploadFile as StarletteUploadFile

from .geometry import MAX_POINTS, MAX_STROKES
from .product_api import router as product_router
from .raster_studio import router as raster_router
from . import studio2_fixes, studio2_v3
from .web import app

# Preserve the Studio-only large-job cleanup propagation. Studio 2.1 owns the
# final orientation transform and persistent action bar itself, so do not apply
# the older HTML/orientation monkey patches here.
studio2_fixes._patch_large_job_limits()
# request.form() returns Starlette's UploadFile instance; Studio 2.1 accepts it
# directly while still passing it to the established FastAPI render function.
studio2_v3.UploadFile = StarletteUploadFile
studio2_router = studio2_v3.router

app.include_router(raster_router)
app.include_router(studio2_router)
app.include_router(product_router)


def _validate_studio_runtime() -> None:
    """Refuse to start Studio with the legacy 20k shared geometry guard."""
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
