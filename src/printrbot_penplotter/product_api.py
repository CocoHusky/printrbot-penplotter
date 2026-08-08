"""Local-only Step 10 product APIs for profiles, handwriting packs, history, and queue."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .handwriting_packs import HandwritingPackStore
from .product_store import ProductStore

router = APIRouter()

class ProfileRequest(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=80)
    values: dict[str, object]

class HandwritingPackRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    font: dict[str, object]

class JobRecordRequest(BaseModel):
    metadata: dict[str, object]
    gcode: str
    preview_svg: str

class QueueRequest(BaseModel):
    job_id: str

def _store() -> ProductStore:
    return ProductStore.default()

def _pack_store() -> HandwritingPackStore:
    return HandwritingPackStore(_store().root)

@router.get("/api/product/profiles")
def list_profiles(kind: str | None = None) -> dict[str, object]:
    try:
        return _store().list_profiles(kind)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.post("/api/product/profiles")
def save_profile(request: ProfileRequest) -> dict[str, object]:
    try:
        return _store().save_profile(request.kind, request.name, request.values)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.get("/api/product/handwriting-packs")
def list_handwriting_packs() -> dict[str, object]:
    return {"packs": _pack_store().list()}

@router.post("/api/product/handwriting-packs")
def install_handwriting_pack(request: HandwritingPackRequest) -> dict[str, object]:
    try:
        return _pack_store().install(request.name, request.font)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc

@router.get("/api/product/jobs")
def list_jobs(limit: int = 20) -> dict[str, object]:
    try:
        return {"jobs": _store().list_jobs(limit), "queue": _store().queue()}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.post("/api/product/jobs")
def record_job(request: JobRecordRequest) -> dict[str, object]:
    return _store().record_job(metadata=request.metadata, gcode=request.gcode, preview_svg=request.preview_svg)

@router.post("/api/product/queue")
def queue_job(request: QueueRequest) -> dict[str, object]:
    try:
        return {"queue": _store().queue_job(request.job_id)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

@router.delete("/api/product/queue/{job_id}")
def dequeue_job(job_id: str) -> dict[str, object]:
    return {"queue": _store().dequeue_job(job_id)}
