"""Validated local storage for personal/user-authored stroke-font packs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re

from .stroke_fonts import load_stroke_font

@dataclass(frozen=True)
class HandwritingPackStore:
    root: Path

    def _directory(self) -> Path:
        return self.root / "handwriting-packs"

    @staticmethod
    def _slug(name: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-._")
        if not slug or len(slug) > 80:
            raise ValueError("Handwriting pack name must produce a 1-80 character filename.")
        return slug

    def install(self, name: str, font_json: dict[str, object]) -> dict[str, object]:
        slug = self._slug(name)
        directory = self._directory(); directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{slug}.json"
        tmp = directory / f".{slug}.tmp.json"
        tmp.write_text(json.dumps(font_json, indent=2, sort_keys=True), encoding="utf-8")
        try:
            font = load_stroke_font(tmp)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(path)
        return {
            "name": name,
            "slug": slug,
            "path": str(path),
            "font_name": font.name,
            "glyphs": len(font.glyphs),
            "description": font.description,
        }

    def list(self) -> list[dict[str, object]]:
        directory = self._directory()
        if not directory.exists():
            return []
        result: list[dict[str, object]] = []
        for path in sorted(directory.glob("*.json")):
            try:
                font = load_stroke_font(path)
            except (ValueError, FileNotFoundError):
                continue
            result.append({
                "slug": path.stem,
                "path": str(path),
                "font_name": font.name,
                "glyphs": len(font.glyphs),
                "description": font.description,
            })
        return result
