"""Unified local web application with writing, raster, and Studio 2 routes."""

from __future__ import annotations

from .raster_studio import router as raster_router
from .studio2 import router as studio2_router
from .web import app

app.include_router(raster_router)
app.include_router(studio2_router)


def main() -> None:
    import uvicorn

    uvicorn.run("printrbot_penplotter.studio_server:app", host="127.0.0.1", port=8000)
