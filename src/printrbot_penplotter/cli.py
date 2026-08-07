"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import LayoutConfig, MachineConfig, PageConfig, PenConfig, StyleConfig
from .pipeline import render_calibration_job, render_svg_job, render_text_job, write_job
from .preflight import run_preflight
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
        z_feed_mm_min=args.z_feed,
        home_before_plot=args.home,
        air_plot=args.air_plot,
    )


def _style(args: argparse.Namespace) -> StyleConfig:
    overrides: dict[str, object] = {
        "font_size_mm": args.font_size,
        "seed": args.seed,
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
    parser.add_argument("--z-feed", type=float, default=300.0)
    parser.add_argument("--home", action="store_true")
    parser.add_argument(
        "--air-plot",
        action="store_true",
        help="Trace XY paths while keeping the pen at the configured Z-up height.",
    )
    _add_machine_options(parser)


def _add_text_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--preset", choices=("clean", "human", "cursive", "robot"), default="human"
    )
    parser.add_argument(
        "--engine",
        choices=("stroke", "outline"),
        default=None,
        help="Use centerline writing or conventional TTF/OTF outlines.",
    )
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
        )
        write_job(job, args.output, args.preview)
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
