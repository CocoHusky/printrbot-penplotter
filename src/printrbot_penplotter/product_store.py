"""Step 10 local product state: profiles, reproducible jobs, and queue.

The store is intentionally local-only and never starts hardware motion. Queued
jobs still require the existing validated bridge/upload/start path.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import hashlib
import json
import os
import time

ProfileKind = Literal["machine", "pen", "style"]

@dataclass(frozen=True)
class ProductStore:
    root: Path

    @classmethod
    def default(cls) -> "ProductStore":
        override = os.environ.get("PRINTRBOT_HOME")
        return cls(Path(override).expanduser() if override else Path.home() / ".printrbot-penplotter")

    def _load(self, name: str, default: object) -> object:
        path = self.root / name
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, name: str, value: object) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def save_profile(self, kind: ProfileKind, name: str, values: dict[str, object]) -> dict[str, object]:
        clean = name.strip()
        if not clean or len(clean) > 80:
            raise ValueError("Profile name must contain 1-80 characters.")
        if kind not in ("machine", "pen", "style"):
            raise ValueError("Invalid profile kind.")
        payload = self._load("profiles.json", {"schema": "printrbot-profiles/v1", "profiles": {}})
        assert isinstance(payload, dict)
        profiles = payload.setdefault("profiles", {})
        assert isinstance(profiles, dict)
        bucket = profiles.setdefault(kind, {})
        assert isinstance(bucket, dict)
        record = {"name": clean, "values": values, "updated_unix": int(time.time())}
        bucket[clean] = record
        self._save("profiles.json", payload)
        return record

    def list_profiles(self, kind: ProfileKind | None = None) -> dict[str, object]:
        payload = self._load("profiles.json", {"schema": "printrbot-profiles/v1", "profiles": {}})
        assert isinstance(payload, dict)
        if kind is None:
            return payload
        profiles = payload.get("profiles", {})
        assert isinstance(profiles, dict)
        return {"schema": payload.get("schema"), "profiles": {kind: profiles.get(kind, {})}}

    def record_job(self, *, metadata: dict[str, object], gcode: str, preview_svg: str) -> dict[str, object]:
        digest = hashlib.sha256((json.dumps(metadata, sort_keys=True) + "\n" + gcode).encode("utf-8")).hexdigest()
        job_id = digest[:16]
        payload = self._load("jobs.json", {"schema": "printrbot-job-history/v1", "jobs": [], "queue": []})
        assert isinstance(payload, dict)
        jobs = payload.setdefault("jobs", [])
        assert isinstance(jobs, list)
        existing = next((job for job in jobs if isinstance(job, dict) and job.get("id") == job_id), None)
        if existing is None:
            record = {
                "id": job_id,
                "sha256": digest,
                "created_unix": int(time.time()),
                "metadata": metadata,
                "gcode": gcode,
                "preview_svg": preview_svg,
            }
            jobs.insert(0, record)
            del jobs[100:]
        else:
            record = existing
        self._save("jobs.json", payload)
        return record

    def list_jobs(self, limit: int = 20) -> list[dict[str, object]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        payload = self._load("jobs.json", {"jobs": []})
        assert isinstance(payload, dict)
        jobs = payload.get("jobs", [])
        assert isinstance(jobs, list)
        return [job for job in jobs[:limit] if isinstance(job, dict)]

    def queue_job(self, job_id: str) -> list[str]:
        payload = self._load("jobs.json", {"schema": "printrbot-job-history/v1", "jobs": [], "queue": []})
        assert isinstance(payload, dict)
        jobs = payload.setdefault("jobs", [])
        queue = payload.setdefault("queue", [])
        assert isinstance(jobs, list) and isinstance(queue, list)
        if not any(isinstance(job, dict) and job.get("id") == job_id for job in jobs):
            raise ValueError("Unknown job id.")
        if job_id not in queue:
            queue.append(job_id)
        self._save("jobs.json", payload)
        return [str(item) for item in queue]

    def dequeue_job(self, job_id: str) -> list[str]:
        payload = self._load("jobs.json", {"schema": "printrbot-job-history/v1", "jobs": [], "queue": []})
        assert isinstance(payload, dict)
        queue = payload.setdefault("queue", [])
        assert isinstance(queue, list)
        payload["queue"] = [item for item in queue if item != job_id]
        self._save("jobs.json", payload)
        return [str(item) for item in payload["queue"]]

    def queue(self) -> list[str]:
        payload = self._load("jobs.json", {"queue": []})
        assert isinstance(payload, dict)
        queue = payload.get("queue", [])
        assert isinstance(queue, list)
        return [str(item) for item in queue]
