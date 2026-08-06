"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import PageConfig, PenConfig, StyleConfig
from .pipeline import render_svg_job, render_text_job, write_job
from .sender import MarlinSender


def _page(args: argparse.Namespace) -> PageConfig:
    return PageConfig(args.page_width, args.page_height, args.margin)


def _pen(args: argparse.Namespace) -> PenConfig:
    return PenConfig(
        z_up_mm=args.z_up,
        z_down_mm=args.z_down,
        travel_feed_mm_min=args.travel_feed,
        draw_feed_mm_min=args.draw_feed,
        z_feed_mm_min=args.z_feed,
        home_before_plot=args.home,
    )


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", default="out/plot.gcode")
    parser.add_argument("--preview", default="out/plot.svg")
    parser.add_argument("--page-width", type=float, default=152.4)
    parser.add_argument("--page-height", type=float, default=152.4)
    parser.add_argument("--margin", type=float, default=8.0)
    parser.add_argument("--z-up", type=float, default=5.0)
    parser.add_argument("--z-down", type=float, default=0.0)
    parser.add_argument("--travel-feed", type=float, default=3000.0)
    parser.add_argument("--draw-feed", type=float, default=1200.0)
    parser.add_argument("--z-feed", type=float, default=300.0)
    parser.add_argument("--home", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="printrbot-plotter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    text_parser = subparsers.add_parser("text", help="Render text to SVG and G-code.")
    text_parser.add_argument("text", nargs="?", help="Text to draw.")
    text_parser.add_argument("--file", help="Read UTF-8 text from a file.")
    text_parser.add_argument(
        "--preset", choices=("clean", "human", "cursive", "robot"), default="human"
    )
    text_parser.add_argument("--font-family", default="DejaVu Sans")
    text_parser.add_argument("--font-path")
    text_parser.add_argument("--font-size", type=float, default=18.0)
    text_parser.add_argument("--seed", type=int, default=7)
    _add_output_options(text_parser)

    svg_parser = subparsers.add_parser("svg", help="Render SVG paths to G-code.")
    svg_parser.add_argument("source")
    _add_output_options(svg_parser)

    send_parser = subparsers.add_parser("send", help="Send a reviewed G-code file to Marlin.")
    send_parser.add_argument("gcode")
    send_parser.add_argument("--port", required=True)
    send_parser.add_argument("--baudrate", type=int, default=115200)
    send_parser.add_argument(
        "--confirm",
        required=True,
        help="Must be exactly DRAW after the workspace has been checked.",
    )

    serve_parser = subparsers.add_parser("serve", help="Run the local web interface.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "text":
        if bool(args.text) == bool(args.file):
            raise SystemExit("Provide exactly one of TEXT or --file.")
        text = args.text if args.text is not None else Path(args.file).read_text(encoding="utf-8")
        style = StyleConfig.for_preset(
            args.preset,
            font_family=args.font_family,
            font_path=args.font_path,
            font_size_mm=args.font_size,
            seed=args.seed,
        )
        job = render_text_job(text, page=_page(args), pen=_pen(args), style=style)
        write_job(job, args.output, args.preview)
        print(f"G-code: {args.output}")
        print(f"Preview: {args.preview}")
        print(f"Strokes: {job.metadata['strokes']}")
        return 0

    if args.command == "svg":
        job = render_svg_job(args.source, page=_page(args), pen=_pen(args))
        write_job(job, args.output, args.preview)
        print(f"G-code: {args.output}")
        print(f"Preview: {args.preview}")
        print(f"Strokes: {job.metadata['strokes']}")
        return 0

    if args.command == "send":
        if args.confirm != "DRAW":
            raise SystemExit("Refusing to move hardware: --confirm must be exactly DRAW.")
        with MarlinSender(args.port, baudrate=args.baudrate) as sender:
            commands = sender.send_file(args.gcode, log=sys.stdout)
        print(f"Completed: {commands} commands acknowledged by Marlin.")
        return 0

    if args.command == "serve":
        import uvicorn

        uvicorn.run("printrbot_penplotter.web:app", host=args.host, port=args.port)
        return 0

    return 2
