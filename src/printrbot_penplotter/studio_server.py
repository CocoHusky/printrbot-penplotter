"""Unified local application for writing and the Studio art workflow."""

from __future__ import annotations

from pathlib import Path

from starlette.datastructures import UploadFile as StarletteUploadFile

from . import image_engine
from .geometry import MAX_POINTS, MAX_STROKES
from . import image_workspace, image_workspace_fixes
from .web import app

# Preserve the image-workspace large-job cleanup propagation. The current
# workspace owns the final orientation transform and persistent action bar.
image_workspace_fixes._patch_large_job_limits()
image_workspace_fixes._patch_image_orientation(image_engine)
# request.form() returns Starlette's UploadFile instance; the workspace accepts
# it directly while still passing it to the shared engine render function.
image_workspace.UploadFile = StarletteUploadFile

# Interactive Auto maps balanced to the quick engine render path. Keep that
# browser-preview raster genuinely small so normal photographs do not spend
# minutes in tracing/cleanup. Manual balanced/best remain 720/960 px.
image_workspace.engine._WORKING_DIMENSION["quick"] = 320

studio2_router = image_workspace.router

app.include_router(studio2_router)


def _configure_local_neural_worker() -> None:
    """Use the optional repo-local Graves install when it has been prepared."""
    repo_root = Path(__file__).resolve().parents[2]
    worker = repo_root / "scripts" / "graves_worker.py"
    python = repo_root / ".venv-neural" / "bin" / "python"
    model = repo_root / ".external" / "handwriting-synthesis"
    if worker.is_file() and python.is_file() and model.is_dir():
        import os

        os.environ.setdefault("PRINTRBOT_HANDWRITING_WORKER", str(worker))
        os.environ.setdefault("PRINTRBOT_HANDWRITING_PYTHON", str(python))
        os.environ.setdefault("PRINTRBOT_GRAVES_SOURCE", str(model))


# Configure the optional backend during module import as well as in ``main``.
# This keeps the notes page consistent when the app is launched by uvicorn
# (``uvicorn printrbot_penplotter.studio_server:app``) instead of the module
# launcher.
_configure_local_neural_worker()


def _validate_studio_runtime() -> None:
    """Refuse to start with the obsolete 20k shared geometry guard."""
    if MAX_STROKES < 200_000 or MAX_POINTS < 20_000_000:
        raise RuntimeError(
            "Image workspace is using obsolete geometry limits "
            f"({MAX_STROKES:,} strokes / {MAX_POINTS:,} points). "
            "Reinstall the current repo with: python -m pip install -e '.[dev]'"
        )


def main() -> None:
    import uvicorn

    _validate_studio_runtime()
    _configure_local_neural_worker()
    package_root = Path(__file__).resolve().parent
    print(
        "Studio 2 geometry guard: "
        f"{MAX_STROKES:,} strokes / {MAX_POINTS:,} points | source: {package_root}"
    )
    print("Studio 2 interactive quick raster cap: 320 px")
    uvicorn.run("printrbot_penplotter.studio_server:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
