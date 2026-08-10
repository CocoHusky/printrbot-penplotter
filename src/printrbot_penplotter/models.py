"""Core data models for rendering and plotting jobs."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

Point: TypeAlias = tuple[float, float]
Polyline: TypeAlias = list[Point]
Polylines: TypeAlias = list[Polyline]
HorizontalAlign: TypeAlias = Literal["left", "center", "right"]
VerticalAlign: TypeAlias = Literal["bottom", "center", "top"]
FitMode: TypeAlias = Literal["none", "downscale", "fit"]
TextEngine: TypeAlias = Literal["stroke", "outline"]
VariantMode: TypeAlias = Literal["first", "seeded", "cycle"]
StrokeOrder: TypeAlias = Literal["authored", "nearest"]


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite.")


@dataclass(frozen=True)
class MachineConfig:
    """Absolute Marlin machine limits in millimeters."""

    x_min_mm: float = 0.0
    x_max_mm: float = 152.4
    y_min_mm: float = 0.0
    y_max_mm: float = 152.4
    z_min_mm: float = 0.0
    z_max_mm: float = 152.4

    def validate(self) -> None:
        for name, value in self.__dict__.items():
            _require_finite(name, value)
        if self.x_max_mm <= self.x_min_mm:
            raise ValueError("Machine X maximum must exceed X minimum.")
        if self.y_max_mm <= self.y_min_mm:
            raise ValueError("Machine Y maximum must exceed Y minimum.")
        if self.z_max_mm <= self.z_min_mm:
            raise ValueError("Machine Z maximum must exceed Z minimum.")

    @property
    def width_mm(self) -> float:
        return self.x_max_mm - self.x_min_mm

    @property
    def height_mm(self) -> float:
        return self.y_max_mm - self.y_min_mm


@dataclass(frozen=True)
class PageConfig:
    """Paper rectangle placed in absolute machine coordinates."""

    width_mm: float = 152.4
    height_mm: float = 152.4
    margin_mm: float = 8.0
    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0

    def validate(self, machine: MachineConfig | None = None) -> None:
        for name, value in self.__dict__.items():
            _require_finite(name, value)
        if self.width_mm <= 0 or self.height_mm <= 0:
            raise ValueError("Page width and height must be positive.")
        if self.margin_mm < 0:
            raise ValueError("Page margin cannot be negative.")
        if self.margin_mm * 2 >= min(self.width_mm, self.height_mm):
            raise ValueError("Page margin leaves no drawable area.")
        if machine is not None:
            machine.validate()
            if self.origin_x_mm < machine.x_min_mm or self.origin_y_mm < machine.y_min_mm:
                raise ValueError("Page origin is outside the machine minimum bounds.")
            if self.origin_x_mm + self.width_mm > machine.x_max_mm:
                raise ValueError("Page extends beyond the machine X maximum.")
            if self.origin_y_mm + self.height_mm > machine.y_max_mm:
                raise ValueError("Page extends beyond the machine Y maximum.")

    @property
    def drawable_width_mm(self) -> float:
        return self.width_mm - 2 * self.margin_mm

    @property
    def drawable_height_mm(self) -> float:
        return self.height_mm - 2 * self.margin_mm


@dataclass(frozen=True)
class LayoutConfig:
    """Placement rules that preserve physical size unless fitting is requested."""

    fit_mode: FitMode = "downscale"
    horizontal_align: HorizontalAlign = "center"
    vertical_align: VerticalAlign = "center"
    scale: float = 1.0
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0

    def validate(self) -> None:
        for name in ("scale", "offset_x_mm", "offset_y_mm"):
            _require_finite(name, getattr(self, name))
        if self.scale <= 0:
            raise ValueError("Layout scale must be positive.")


@dataclass(frozen=True)
class PenConfig:
    """Marlin motion settings for a Z-axis pen lift."""

    z_up_mm: float = 5.0
    z_down_mm: float = 0.0
    travel_feed_mm_min: float = 3000.0
    draw_feed_mm_min: float = 1200.0
    corner_feed_mm_min: float = 650.0
    corner_angle_deg: float = 70.0
    z_feed_mm_min: float = 300.0
    home_before_plot: bool = False
    air_plot: bool = False
    park_x_mm: float | None = None
    park_y_mm: float | None = None

    def validate(self, machine: MachineConfig | None = None) -> None:
        for name, value in (
            ("z_up_mm", self.z_up_mm),
            ("z_down_mm", self.z_down_mm),
            ("travel_feed_mm_min", self.travel_feed_mm_min),
            ("draw_feed_mm_min", self.draw_feed_mm_min),
            ("corner_feed_mm_min", self.corner_feed_mm_min),
            ("corner_angle_deg", self.corner_angle_deg),
            ("z_feed_mm_min", self.z_feed_mm_min),
        ):
            _require_finite(name, value)
        for name, value in (
            ("travel_feed_mm_min", self.travel_feed_mm_min),
            ("draw_feed_mm_min", self.draw_feed_mm_min),
            ("corner_feed_mm_min", self.corner_feed_mm_min),
            ("z_feed_mm_min", self.z_feed_mm_min),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive.")
        if not 0 < self.corner_angle_deg < 180:
            raise ValueError("corner_angle_deg must be between 0 and 180 degrees.")
        if self.corner_feed_mm_min > self.draw_feed_mm_min:
            raise ValueError("corner feed must not exceed the normal drawing feed.")
        if self.park_x_mm is None and self.park_y_mm is not None:
            raise ValueError("Park X and Y must either both be set or both be unset.")
        if self.park_y_mm is None and self.park_x_mm is not None:
            raise ValueError("Park X and Y must either both be set or both be unset.")
        if machine is not None:
            machine.validate()
            for name, value in (("z_up_mm", self.z_up_mm), ("z_down_mm", self.z_down_mm)):
                if not machine.z_min_mm <= value <= machine.z_max_mm:
                    raise ValueError(f"{name} is outside the machine Z limits.")
            if self.park_x_mm is not None and self.park_y_mm is not None:
                if not machine.x_min_mm <= self.park_x_mm <= machine.x_max_mm:
                    raise ValueError("Park X is outside machine limits.")
                if not machine.y_min_mm <= self.park_y_mm <= machine.y_max_mm:
                    raise ValueError("Park Y is outside machine limits.")


@dataclass(frozen=True)
class StyleConfig:
    """Text appearance for native centerline writing or outline compatibility."""

    preset: Literal["standard", "clean", "human", "cursive", "robot"] = "human"
    engine: TextEngine = "stroke"
    writing_backend: Literal["stroke", "neural"] = "stroke"
    neural_style: int = 9
    neural_bias: float = 0.75

    # Outline-engine compatibility.
    font_family: str = "DejaVu Sans"
    font_path: str | None = None

    # Centerline stroke-font selection and layout.
    stroke_font: str = "hand"
    stroke_font_path: str | None = None
    wrap_width_mm: float | None = None
    connect_letters: bool = False
    word_spacing_em: float = 0.42
    variant_mode: VariantMode = "seeded"
    stroke_order: StrokeOrder = "authored"
    slant_deg: float = 2.0

    font_size_mm: float = 18.0
    line_spacing: float = 1.0
    letter_spacing_mm: float = 0.55
    rotation_jitter_deg: float = 1.4
    baseline_jitter_mm: float = 0.45
    x_jitter_mm: float = 0.2
    scale_jitter: float = 0.025
    seed: int = 7

    @classmethod
    def for_preset(
        cls,
        preset: Literal["standard", "clean", "human", "cursive", "robot"],
        **overrides: object,
    ) -> "StyleConfig":
        values: dict[str, object]
        if preset == "standard":
            values = {
                "preset": preset,
                "engine": "outline",
                "writing_backend": "stroke",
                "font_family": "Arial",
                "stroke_font": "robot",
                "variant_mode": "first",
                "connect_letters": False,
                "slant_deg": 0.0,
                "rotation_jitter_deg": 0.0,
                "baseline_jitter_mm": 0.0,
                "x_jitter_mm": 0.0,
                "scale_jitter": 0.0,
                "letter_spacing_mm": 0.0,
            }
        elif preset == "clean":
            values = {
                "preset": preset,
                "engine": "stroke",
                "stroke_font": "hand",
                "variant_mode": "first",
                "connect_letters": False,
                "slant_deg": 0.0,
                "rotation_jitter_deg": 0.0,
                "baseline_jitter_mm": 0.0,
                "x_jitter_mm": 0.0,
                "scale_jitter": 0.0,
                "letter_spacing_mm": 0.45,
            }
        elif preset == "cursive":
            values = {
                "preset": preset,
                "engine": "stroke",
                "stroke_font": "hand",
                "variant_mode": "seeded",
                "connect_letters": True,
                "slant_deg": 9.0,
                "rotation_jitter_deg": 0.7,
                "baseline_jitter_mm": 0.25,
                "x_jitter_mm": 0.12,
                "scale_jitter": 0.018,
                "letter_spacing_mm": -0.08,
            }
        elif preset == "robot":
            values = {
                "preset": preset,
                "engine": "stroke",
                "stroke_font": "robot",
                "variant_mode": "first",
                "connect_letters": False,
                "stroke_order": "nearest",
                "slant_deg": 0.0,
                "rotation_jitter_deg": 0.0,
                "baseline_jitter_mm": 0.0,
                "x_jitter_mm": 0.0,
                "scale_jitter": 0.0,
                "letter_spacing_mm": 1.2,
            }
        else:
            values = {
                "preset": "human",
                "engine": "stroke",
                "stroke_font": "hand",
                "variant_mode": "seeded",
                "connect_letters": False,
                "slant_deg": 3.0,
            }

        values.update(overrides)
        return cls(**values)  # type: ignore[arg-type]

    def validate(self) -> None:
        for name, value in (
            ("font_size_mm", self.font_size_mm),
            ("line_spacing", self.line_spacing),
            ("letter_spacing_mm", self.letter_spacing_mm),
            ("word_spacing_em", self.word_spacing_em),
            ("slant_deg", self.slant_deg),
            ("rotation_jitter_deg", self.rotation_jitter_deg),
            ("baseline_jitter_mm", self.baseline_jitter_mm),
            ("x_jitter_mm", self.x_jitter_mm),
            ("scale_jitter", self.scale_jitter),
            ("neural_bias", self.neural_bias),
        ):
            _require_finite(name, value)
        if self.wrap_width_mm is not None:
            _require_finite("wrap_width_mm", self.wrap_width_mm)
            if self.wrap_width_mm <= 0:
                raise ValueError("Wrap width must be positive when supplied.")
        if self.font_size_mm <= 0:
            raise ValueError("Font size must be positive.")
        if self.line_spacing <= 0:
            raise ValueError("Line spacing must be positive.")
        if self.word_spacing_em <= 0:
            raise ValueError("Word spacing must be positive.")
        if self.scale_jitter < 0 or self.scale_jitter >= 1:
            raise ValueError("Scale jitter must be in [0, 1).")
        if self.engine not in ("stroke", "outline"):
            raise ValueError("Text engine must be 'stroke' or 'outline'.")
        if self.writing_backend not in ("stroke", "neural"):
            raise ValueError("Writing backend must be 'stroke' or 'neural'.")
        if not 0 <= self.neural_style <= 12:
            raise ValueError("Neural style must be between 0 and 12.")
        if not 0 <= self.neural_bias <= 1:
            raise ValueError("Neural bias must be between 0 and 1.")
        if self.variant_mode not in ("first", "seeded", "cycle"):
            raise ValueError("Variant mode must be first, seeded, or cycle.")
        if self.stroke_order not in ("authored", "nearest"):
            raise ValueError("Stroke order must be authored or nearest.")
        if not self.stroke_font.strip():
            raise ValueError("Stroke font name cannot be empty.")


@dataclass(frozen=True)
class RenderedJob:
    """A fully prepared plot job."""

    polylines: Polylines
    gcode: str
    preview_svg: str
    metadata: dict[str, object] = field(default_factory=dict)
