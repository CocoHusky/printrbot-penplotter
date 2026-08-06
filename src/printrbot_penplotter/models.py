"""Core data models for rendering and plotting jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

Point: TypeAlias = tuple[float, float]
Polyline: TypeAlias = list[Point]
Polylines: TypeAlias = list[Polyline]


@dataclass(frozen=True)
class PageConfig:
    """Physical plotting area, expressed in millimeters."""

    width_mm: float = 152.4
    height_mm: float = 152.4
    margin_mm: float = 8.0

    def validate(self) -> None:
        if self.width_mm <= 0 or self.height_mm <= 0:
            raise ValueError("Page width and height must be positive.")
        if self.margin_mm < 0:
            raise ValueError("Page margin cannot be negative.")
        if self.margin_mm * 2 >= min(self.width_mm, self.height_mm):
            raise ValueError("Page margin leaves no drawable area.")


@dataclass(frozen=True)
class PenConfig:
    """Marlin motion settings for a Z-axis pen lift."""

    z_up_mm: float = 5.0
    z_down_mm: float = 0.0
    travel_feed_mm_min: float = 3000.0
    draw_feed_mm_min: float = 1200.0
    z_feed_mm_min: float = 300.0
    home_before_plot: bool = False
    park_x_mm: float | None = None
    park_y_mm: float | None = None

    def validate(self) -> None:
        for name, value in (
            ("travel_feed_mm_min", self.travel_feed_mm_min),
            ("draw_feed_mm_min", self.draw_feed_mm_min),
            ("z_feed_mm_min", self.z_feed_mm_min),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive.")


@dataclass(frozen=True)
class StyleConfig:
    """Text appearance and deterministic per-character variation."""

    preset: Literal["clean", "human", "cursive", "robot"] = "human"
    font_family: str = "DejaVu Sans"
    font_path: str | None = None
    font_size_mm: float = 18.0
    line_spacing: float = 1.35
    letter_spacing_mm: float = 0.8
    rotation_jitter_deg: float = 1.8
    baseline_jitter_mm: float = 0.7
    x_jitter_mm: float = 0.35
    scale_jitter: float = 0.035
    seed: int = 7

    @classmethod
    def for_preset(
        cls,
        preset: Literal["clean", "human", "cursive", "robot"],
        **overrides: object,
    ) -> "StyleConfig":
        values: dict[str, object]
        if preset == "clean":
            values = {
                "preset": preset,
                "rotation_jitter_deg": 0.0,
                "baseline_jitter_mm": 0.0,
                "x_jitter_mm": 0.0,
                "scale_jitter": 0.0,
                "letter_spacing_mm": 0.5,
            }
        elif preset == "cursive":
            values = {
                "preset": preset,
                "font_family": "cursive",
                "rotation_jitter_deg": 1.0,
                "baseline_jitter_mm": 0.45,
                "x_jitter_mm": 0.2,
                "scale_jitter": 0.025,
                "letter_spacing_mm": -0.4,
            }
        elif preset == "robot":
            values = {
                "preset": preset,
                "font_family": "DejaVu Sans Mono",
                "rotation_jitter_deg": 0.0,
                "baseline_jitter_mm": 0.0,
                "x_jitter_mm": 0.0,
                "scale_jitter": 0.0,
                "letter_spacing_mm": 1.2,
            }
        else:
            values = {"preset": "human"}

        values.update(overrides)
        return cls(**values)  # type: ignore[arg-type]

    def validate(self) -> None:
        if self.font_size_mm <= 0:
            raise ValueError("Font size must be positive.")
        if self.line_spacing <= 0:
            raise ValueError("Line spacing must be positive.")
        if self.scale_jitter < 0 or self.scale_jitter >= 1:
            raise ValueError("Scale jitter must be in [0, 1).")


@dataclass(frozen=True)
class RenderedJob:
    """A fully prepared plot job."""

    polylines: Polylines
    gcode: str
    preview_svg: str
    metadata: dict[str, object] = field(default_factory=dict)
