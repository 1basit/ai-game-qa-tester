#!/usr/bin/env python3
"""AI Game QA Tester — FPS analysis prototype.

    python main.py analyze --video "path/to/gameplay.mp4" [--target-fps 60]
    python main.py --gui

Both use the same analysis engine (backend/src/gameqa/fps_service).
Run with the project's Python environment:  source backend/.venv/bin/activate
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

try:
    from gameqa.config import FpsServiceConfig, get_settings
    from gameqa.core.errors import GameQAError
    from gameqa.fps_service import analyze_video, output_folder, save_results
except ImportError as exc:  # wrong interpreter / environment not installed
    sys.stderr.write(
        f"Missing dependency ({exc.name}). Use the project's Python environment:\n\n"
        f"    cd {ROOT}\n    source backend/.venv/bin/activate\n    python main.py ...\n\n"
        "First-time setup: backend/scripts/install.sh\n")
    sys.exit(3)

EVENT_LABEL = {"freeze": "FREEZE ", "fps_drop": "DROP   ", "stutter": "STUTTER"}


class Progress:
    """One-line progress bar on a terminal; plain lines when output is redirected."""

    def __init__(self, quiet: bool = False):
        self.quiet, self.tty, self.last, self.t0 = quiet, sys.stdout.isatty(), -1.0, time.perf_counter()

    def __call__(self, frac: float, msg: str) -> None:
        if self.quiet:
            return
        if self.tty:
            bar = "#" * int(frac * 30)
            sys.stdout.write(f"\r  [{bar:<30}] {frac:4.0%}  {msg[:48]:<48}")
            sys.stdout.flush()
            if frac >= 1.0:
                sys.stdout.write(f"\r  [{'#' * 30}] 100%  done in {time.perf_counter() - self.t0:.1f} s{' ' * 30}\n")
        elif frac - self.last >= 0.1 or frac >= 1.0 or frac == 0:
            print(f"  {frac:4.0%}  {msg}")
            self.last = frac


def fmt_t(s: float) -> str:
    m = int(s // 60)
    return f"{m:02d}:{s - 60 * m:06.3f}"


def cmd_analyze(args: argparse.Namespace) -> int:
    base = get_settings().fps_service
    cfg = FpsServiceConfig(**{**base.model_dump(),
                              **{k: v for k, v in {"target_fps": args.target_fps, "drop_ratio": args.drop_ratio,
                                                   "freeze_ms": args.freeze_ms,
                                                   "stutter_min_missed": args.stutter_min_missed}.items()
                                 if v is not None}})
    video = Path(args.video).expanduser()
    print(f"\nAI Game QA Tester — FPS analysis\n  video : {video}\n  target: {cfg.target_fps:g} FPS "
          f"(drop < {cfg.drop_ratio * cfg.target_fps:g} FPS, freeze >= {cfg.freeze_ms:g} ms, "
          f"stutter >= {cfg.stutter_min_missed} missed/s)\n")
    try:
        result, timeline = analyze_video(video, cfg, progress=Progress(args.quiet))
    except GameQAError as exc:
        sys.stdout.flush()  # keep the banner above the error when output is redirected
        print(f"\n  ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output:
        folder = Path(args.output).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
    else:
        folder = output_folder(result.video_name, cfg)
    if not args.quiet:
        print("  writing results" + ("" if args.no_report else " and Word report") + " ...")
    files = save_results(result, timeline, folder, report=not args.no_report)

    m, e, f, c = result.metadata, result.effective_fps, result.frame_times, result.counts
    print("\n  VIDEO")
    print(f"    {m['resolution']}, {m['duration_s']} s, {m['frame_count']:,} frames, {m['codec']}")
    print(f"    nominal {m['nominal_fps']:g} FPS | average {m['average_fps']} FPS | "
          f"{'variable' if m['variable_frame_rate'] else 'constant'} frame rate")
    print("\n  FRAME RATE (while the picture moves)")
    print(f"    effective FPS  median {e['median']} | mean {e['mean']} | min {e['min']}")
    print(f"    frame time     p50 {f['p50_ms']} ms | p99 {f['p99_ms']} ms | 1% low {f['one_percent_low_fps']} FPS")
    print(f"    measurable     {e['measurable_fraction']:.0%} of the video")
    print(f"\n  EVENTS  freezes {c['freezes']} | drops {c['fps_drops']} | stutters {c['stutters']} "
          f"| missed frames while moving {c['missed_frames_while_moving']}")
    for ev in result.events[: args.max_events]:
        print(f"    {EVENT_LABEL[ev.type]} {fmt_t(ev.start_s)} - {fmt_t(ev.end_s)}  {ev.description}")
    if len(result.events) > args.max_events:
        print(f"    ... {len(result.events) - args.max_events} more in the report")
    print(f"\n  RESULT  {result.verdict}")
    for w in result.warnings:
        print(f"  warning: {w}")
    print(f"\n  output folder: {folder}")
    if "report_docx" in files:
        print(f"  Word report  : {files['report_docx']}")
    print("  note: effective FPS is measured from the recording; it is not the game's internal FPS.\n")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from gameqa.webgui.app import run
    except ImportError as exc:
        print(f"  ERROR: the local web GUI needs FastAPI and uvicorn ({exc}).\n"
              "  Install them with:  pip install -e \"backend[api]\"", file=sys.stderr)
        return 3
    return run(host=args.host, port=args.port, open_browser=not args.no_browser)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="main.py", description="AI Game QA Tester — FPS analysis prototype")
    p.add_argument("--gui", action="store_true", help="start the local web GUI and open it in the browser")
    p.add_argument("--host", default=None, help="GUI host (default from config: 127.0.0.1)")
    p.add_argument("--port", type=int, default=None, help="GUI port (default from config: 8765)")
    p.add_argument("--no-browser", action="store_true", help="GUI: do not open the browser automatically")
    sub = p.add_subparsers(dest="command")
    a = sub.add_parser("analyze", help="analyse one gameplay video")
    a.add_argument("--video", required=True, help="path to an .mp4, .mkv or .avi file")
    a.add_argument("--target-fps", type=float, default=None, help="frame rate the game should hold (e.g. 30 or 60)")
    a.add_argument("--drop-ratio", type=float, default=None, help="drop if effective FPS < ratio x target (default 0.75)")
    a.add_argument("--freeze-ms", type=float, default=None, help="freeze if a picture is held this long (default 250)")
    a.add_argument("--stutter-min-missed", type=int, default=None, help="missed frames per second for a stutter (default 3)")
    a.add_argument("--output", default=None, help="output folder (default: outputs/<date-time>_<video>)")
    a.add_argument("--no-report", action="store_true", help="skip the Word report")
    a.add_argument("--max-events", type=int, default=15, help="events to list in the terminal")
    a.add_argument("--quiet", action="store_true", help="no progress output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.gui:
        s = get_settings().fps_service
        args.host, args.port = args.host or s.gui_host, args.port or s.gui_port
        return cmd_gui(args)
    if args.command == "analyze":
        if args.target_fps is not None and args.target_fps <= 0:
            print("  ERROR: --target-fps must be positive", file=sys.stderr)
            return 2
        if args.drop_ratio is not None and not 0 < args.drop_ratio < 1:
            print("  ERROR: --drop-ratio must be between 0 and 1", file=sys.stderr)
            return 2
        return cmd_analyze(args)
    build_parser().print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
