"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import LayoutConfig, MachineConfig, PageConfig, PenConfig, StyleConfig
from .optimize import MotionConfig
from .pipeline import (
    render_calibration_job,
    render_handwriting_job,
    render_image_job,
    render_svg_job,
    render_text_job,
    write_job,
)
from .preflight import run_preflight
from .raster import RasterTraceConfig, editable_trace_svg, trace_raster
from .sender import MarlinSender
from .stroke_fonts import available_stroke_fonts, get_builtin_stroke_font, load_stroke_font


def _machine(args: argparse.Namespace) -> MachineConfig:
    return MachineConfig(
        x_min_mm=args.machine_x_min,
        x_max_mm=args.machine_x_max,
        y_min_mm=args.machine_y_min,
        y_max_mm=args.machine_y_max,
        z_min_mm=args.machine_z_min,
        z_max_mm=args.machine_z_max,
    )


def _page(args: argparse.Namespace) -> PageConfig:
    return PageConfig(
        width_mm=args.page_width,
        height_mm=args.page_height,
        margin_mm=args.margin,
        origin_x_mm=args.page_origin_x,
        origin_y_mm=args.page_origin_y,
    )


def _layout(args: argparse.Namespace) -> LayoutConfig:
    return LayoutConfig(
        fit_mode=args.fit_mode,
        horizontal_align=args.horizontal_align,
        vertical_align=args.vertical_align,
        scale=args.scale,
        offset_x_mm=args.offset_x,
        offset_y_mm=args.offset_y,
    )


def _pen(args: argparse.Namespace) -> PenConfig:
    return PenConfig(
        z_up_mm=args.z_up,
        z_down_mm=args.z_down,
        travel_feed_mm_min=args.travel_feed,
        draw_feed_mm_min=args.draw_feed,
        corner_feed_mm_min=args.corner_feed,
        corner_angle_deg=args.corner_angle,
        z_feed_mm_min=args.z_feed,
        home_before_plot=args.home,
        air_plot=args.air_plot,
    )


def _motion(args: argparse.Namespace) -> MotionConfig:
    return MotionConfig(
        route_mode=args.motion_route,
        allow_reverse=args.motion_reverse,
        join_tolerance_mm=args.join_tolerance,
        rdp_tolerance_mm=args.rdp_tolerance,
        resample_spacing_mm=args.resample_spacing,
        smooth_passes=args.smooth_passes,
        two_opt_passes=args.two_opt_passes,
    )


def _style(args: argparse.Namespace) -> StyleConfig:
    overrides: dict[str, object] = {
        "font_size_mm": args.font_size,
        "seed": args.seed,
        "writing_backend": args.writing_backend,
        "neural_style": args.neural_style,
        "neural_bias": args.neural_bias,
    }
    optional = {
        "engine": args.engine,
        "font_family": args.font_family,
        "font_path": args.font_path,
        "stroke_font": args.stroke_font,
        "stroke_font_path": args.stroke_font_path,
        "wrap_width_mm": args.wrap_width,
        "connect_letters": args.connect_letters,
        "word_spacing_em": args.word_spacing,
        "letter_spacing_mm": args.letter_spacing,
        "variant_mode": args.variant_mode,
        "stroke_order": args.stroke_order,
        "slant_deg": args.slant,
    }
    overrides.update({key: value for key, value in optional.items() if value is not None})
    return StyleConfig.for_preset(args.preset, **overrides)


def _raster_trace(args: argparse.Namespace) -> RasterTraceConfig:
    return RasterTraceConfig(
        mode=args.trace_mode,
        threshold=args.threshold,
        invert=args.invert,
        blur_radius_px=args.blur_radius,
        min_component_px=args.min_component,
        max_dimension_px=args.max_dimension,
        simplify_px=args.simplify_px,
    )


def _add_machine_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--machine-x-min", type=float, default=0.0)
    parser.add_argument("--machine-x-max", type=float, default=152.4)
    parser.add_argument("--machine-y-min", type=float, default=0.0)
    parser.add_argument("--machine-y-max", type=float, default=152.4)
    parser.add_argument("--machine-z-min", type=float, default=0.0)
    parser.add_argument("--machine-z-max", type=float, default=152.4)


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", default="out/plot.gcode")
    parser.add_argument("--preview", default="out/plot.svg")
    parser.add_argument("--page-width", type=float, default=152.4)
    parser.add_argument("--page-height", type=float, default=152.4)
    parser.add_argument("--page-origin-x", type=float, default=0.0)
    parser.add_argument("--page-origin-y", type=float, default=0.0)
    parser.add_argument("--margin", type=float, default=8.0)
    parser.add_argument("--fit-mode", choices=("none", "downscale", "fit"), default="downscale")
    parser.add_argument("--horizontal-align", choices=("left", "center", "right"), default="center")
    parser.add_argument("--vertical-align", choices=("bottom", "center", "top"), default="center")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--offset-x", type=float, default=0.0)
    parser.add_argument("--offset-y", type=float, default=0.0)
    parser.add_argument("--z-up", type=float, default=5.0)
    parser.add_argument("--z-down", type=float, default=0.0)
    parser.add_argument("--travel-feed", type=float, default=3000.0)
    parser.add_argument("--draw-feed", type=float, default=1200.0)
    parser.add_argument(
        "--corner-feed",
        type=float,
        default=650.0,
        help="Drawing feed for segments touching corners sharper than --corner-angle.",
    )
    parser.add_argument(
        "--corner-angle",
        type=float,
        default=70.0,
        help="Interior angle in degrees at or below which corner feed is used.",
    )
    parser.add_argument("--z-feed", type=float, default=300.0)
    parser.add_argument("--home", action="store_true")
    parser.add_argument(
        "--air-plot",
        action="store_true",
        help="Trace XY paths while keeping the pen at the configured Z-up height.",
    )

    motion = parser.add_argument_group("Release 0.6 motion quality")
    motion.add_argument(
        "--motion-route",
        choices=("authored", "nearest", "two_opt"),
        default="authored",
        help="Stroke route optimization. Authored is the safe/default writing order.",
    )
    motion.add_argument(
        "--motion-reverse",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow route optimization to reverse independent stroke direction.",
    )
    motion.add_argument(
        "--join-tolerance",
        type=float,
        default=0.0,
        help="Join consecutive endpoints within this many mm; may add a tiny drawn connector.",
    )
    motion.add_argument(
        "--rdp-tolerance",
        type=float,
        default=0.0,
        help="Ramer-Douglas-Peucker simplification tolerance in mm.",
    )
    motion.add_argument(
        "--resample-spacing",
        type=float,
        default=0.0,
        help="Split long segments to approximately this spacing in mm.",
    )
    motion.add_argument(
        "--smooth-passes",
        type=int,
        default=0,
        help="Endpoint-preserving smoothing passes; 0 leaves geometry untouched.",
    )
    motion.add_argument(
        "--two-opt-passes",
        type=int,
        default=8,
        help="Maximum deterministic route-improvement passes for two_opt mode.",
    )
    _add_machine_options(parser)


def _add_text_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--preset", choices=("standard", "clean", "human", "cursive", "robot"), default="human"
    )
    parser.add_argument(
        "--engine",
        choices=("stroke", "outline"),
        default=None,
        help="Use centerline writing or conventional TTF/OTF outlines.",
    )
    parser.add_argument(
        "--writing-backend",
        choices=("stroke", "neural"),
        default="stroke",
        help="Use authored strokes or the optional neural trajectory worker.",
    )
    parser.add_argument("--neural-style", type=int, default=9, choices=range(13))
    parser.add_argument("--neural-bias", type=float, default=0.75)
    parser.add_argument("--font-family", default=None, help="Outline-engine font family.")
    parser.add_argument("--font-path", default=None, help="Outline-engine TTF/OTF path.")
    parser.add_argument("--stroke-font", choices=available_stroke_fonts(), default=None)
    parser.add_argument("--stroke-font-path", default=None, help="Custom JSON stroke-font pack.")
    parser.add_argument("--font-size", type=float, default=18.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--wrap-width", type=float, default=None, help="Word-wrap width in mm.")
    parser.add_argument(
        "--connect-letters",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Add baseline joins between glyphs that expose entry/exit anchors.",
    )
    parser.add_argument("--word-spacing", type=float, default=None, help="Space width in em units.")
    parser.add_argument("--letter-spacing", type=float, default=None, help="Tracking in mm.")
    parser.add_argument("--variant-mode", choices=("first", "seeded", "cycle"), default=None)
    parser.add_argument("--stroke-order", choices=("authored", "nearest"), default=None)
    parser.add_argument("--slant", type=float, default=None, help="Writing slant in degrees.")


def _add_raster_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--trace-mode",
        choices=("centerline", "contour"),
        default="contour",
        help="Trace stroke centers or the foreground outline.",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="0-255 foreground threshold. Omit for deterministic Otsu auto-thresholding.",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="Treat light marks on a dark background as foreground.",
    )
    parser.add_argument("--blur-radius", type=float, default=0.0, help="Gaussian blur radius in px.")
    parser.add_argument(
        "--min-component",
        type=int,
        default=8,
        help="Remove connected foreground components smaller than this many pixels.",
    )
    parser.add_argument(
        "--max-dimension",
        type=int,
        default=1200,
        help="Downsample so the longest processed image side does not exceed this many pixels.",
    )
    parser.add_argument(
        "--simplify-px",
        type=float,
        default=1.0,
        help="Pre-placement polyline simplification tolerance in processed pixels.",
    )
    parser.add_argument(
        "--trace-svg",
        default=None,
        help="Also save the raw traced paths as an editable SVG before machine placement.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="printrbot-plotter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    text_parser = subparsers.add_parser("text", help="Render centerline or outline text.")
    text_parser.add_argument("text", nargs="?", help="Text to draw.")
    text_parser.add_argument("--file", help="Read UTF-8 text from a file.")
    _add_text_options(text_parser)
    _add_output_options(text_parser)

    fonts_parser = subparsers.add_parser("fonts", help="List or inspect stroke fonts.")
    fonts_parser.add_argument("--font", choices=available_stroke_fonts())
    fonts_parser.add_argument("--file", help="Inspect a custom JSON stroke-font pack.")

    svg_parser = subparsers.add_parser("svg", help="Render SVG paths to G-code.")
    svg_parser.add_argument("source")
    _add_output_options(svg_parser)
    svg_parser.set_defaults(fit_mode="fit")

    image_parser = subparsers.add_parser(
        "image",
        help="Trace a PNG/JPEG/WebP/TIFF/BMP image into plotter geometry.",
    )
    image_parser.add_argument("source")
    _add_raster_options(image_parser)
    _add_output_options(image_parser)
    image_parser.set_defaults(trace_mode="contour", fit_mode="fit")

    handwriting_parser = subparsers.add_parser(
        "handwriting",
        help="Centerline-trace photographed or scanned handwriting without OCR.",
    )
    handwriting_parser.add_argument("source")
    _add_raster_options(handwriting_parser)
    _add_output_options(handwriting_parser)
    handwriting_parser.set_defaults(
        trace_mode="centerline",
        blur_radius=0.3,
        min_component=4,
        simplify_px=0.6,
        fit_mode="fit",
    )

    calibration_parser = subparsers.add_parser(
        "calibrate",
        help="Generate a known-size square/cross/octagon air-plot job.",
    )
    calibration_parser.add_argument("--size", type=float, default=10.0)
    _add_output_options(calibration_parser)
    calibration_parser.set_defaults(
        output="out/calibration.gcode",
        preview="out/calibration.svg",
        fit_mode="none",
        air_plot=True,
    )
    calibration_parser.add_argument(
        "--pen-plot",
        action="store_false",
        dest="air_plot",
        help="Lower the pen during calibration. Use only after a successful air plot.",
    )

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Run non-moving M115/M119/M114/M503 checks.",
    )
    preflight_parser.add_argument("--port", required=True)
    preflight_parser.add_argument("--baudrate", type=int, default=115200)

    send_parser = subparsers.add_parser("send", help="Send a reviewed G-code file to Marlin.")
    send_parser.add_argument("gcode")
    send_parser.add_argument("--port", required=True)
    send_parser.add_argument("--baudrate", type=int, default=115200)
    send_parser.add_argument("--safe-z-up", type=float, default=5.0)
    send_parser.add_argument(
        "--confirm",
        required=True,
        help="Must be exactly DRAW after the workspace has been checked.",
    )

    serve_parser = subparsers.add_parser("serve", help="Run the local web interface.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    return parser


def _print_job(job: object, output: str, preview: str) -> None:
    metadata = getattr(job, "metadata")
    print(f"G-code: {output}")
    print(f"Preview: {preview}")
    print(json.dumps(metadata, indent=2, sort_keys=True))


def _write_raw_trace(source: str, config: RasterTraceConfig, target: str | None) -> None:
    if target is None:
        return
    traced = trace_raster(source, config)
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(editable_trace_svg(traced.polylines), encoding="utf-8")
    print(f"Editable trace: {destination}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "text":
        if bool(args.text) == bool(args.file):
            raise SystemExit("Provide exactly one of TEXT or --file.")
        text = args.text if args.text is not None else Path(args.file).read_text(encoding="utf-8")
        job = render_text_job(
            text,
            page=_page(args),
            machine=_machine(args),
            pen=_pen(args),
            style=_style(args),
            layout=_layout(args),
            motion=_motion(args),
        )
        write_job(job, args.output, args.preview)
        _print_job(job, args.output, args.preview)
        return 0

    if args.command == "fonts":
        if args.file:
            font = load_stroke_font(args.file)
        elif args.font:
            font = get_builtin_stroke_font(args.font)
        else:
            for name in available_stroke_fonts():
                font = get_builtin_stroke_font(name)
                print(f"{font.name}: {font.description}")
            return 0
        print(
            json.dumps(
                {
                    "name": font.name,
                    "description": font.description,
                    "glyphs": len(font.glyphs),
                    "variant_counts": {
                        character: len(variants) for character, variants in font.glyphs.items()
                    },
                    "fallback": font.fallback,
                    "line_height": font.line_height,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "svg":
        job = render_svg_job(
            args.source,
            page=_page(args),
            machine=_machine(args),
            pen=_pen(args),
            layout=_layout(args),
            motion=_motion(args),
        )
        write_job(job, args.output, args.preview)
        _print_job(job, args.output, args.preview)
        return 0

    if args.command in ("image", "handwriting"):
        trace = _raster_trace(args)
        if args.command == "handwriting" and trace.mode != "centerline":
            raise SystemExit("The handwriting command requires --trace-mode centerline.")
        renderer = render_image_job if args.command == "image" else render_handwriting_job
        job = renderer(
            args.source,
            trace=trace,
            page=_page(args),
            machine=_machine(args),
            pen=_pen(args),
            layout=_layout(args),
            motion=_motion(args),
        )
        write_job(job, args.output, args.preview)
        _write_raw_trace(args.source, trace, args.trace_svg)
        _print_job(job, args.output, args.preview)
        return 0

    if args.command == "calibrate":
        job = render_calibration_job(
            size_mm=args.size,
            page=_page(args),
            machine=_machine(args),
            pen=_pen(args),
            layout=_layout(args),
        )
        write_job(job, args.output, args.preview)
        _print_job(job, args.output, args.preview)
        return 0

    if args.command == "preflight":
        with MarlinSender(args.port, baudrate=args.baudrate) as sender:
            report = run_preflight(sender)
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.passed else 1

    if args.command == "send":
        if args.confirm != "DRAW":
            raise SystemExit("Refusing to move hardware: --confirm must be exactly DRAW.")
        with MarlinSender(args.port, baudrate=args.baudrate) as sender:
            try:
                commands = sender.send_file(
                    args.gcode,
                    log=sys.stdout,
                    safe_z_up_mm=args.safe_z_up,
                )
            except KeyboardInterrupt:
                sender.safe_stop(args.safe_z_up, log=sys.stdout)
                raise SystemExit("Plot cancelled; orderly pen-up stop attempted.")
        print(f"Completed: {commands} commands acknowledged by Marlin.")
        return 0

    if args.command == "serve":
        import uvicorn

        uvicorn.run("printrbot_penplotter.web:app", host=args.host, port=args.port)
        return 0

    return 2
