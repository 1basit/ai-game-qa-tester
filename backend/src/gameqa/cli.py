"""`gameqa` command-line interface.

Phase 1 commands:
  gameqa doctor [--json]           environment check
  gameqa config [--json]           print the effective configuration
  gameqa evaluate -p PRED.json... -g GT_DIR_OR_FILE [-o OUT_DIR]
                                   score detector output against labelled ground truth
Phase 2 commands:
  gameqa probe VIDEO [--json]      validate + metadata + frame-timing statistics
  gameqa extract VIDEO -o DIR      write normalised (sampled) frames + index.json
  gameqa bench VIDEO               decode/normalise throughput vs real time, peak memory
Later phases add: detect (Phases 3-8), serve / worker (10).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gameqa import __version__


def _cmd_doctor(args: argparse.Namespace) -> int:
    from gameqa.doctor import as_dicts, run_all

    results = run_all()
    if args.json:
        print(json.dumps(as_dicts(results), indent=2))
    else:
        icon = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL", "info": "info"}
        width = max(len(r.name) for r in results)
        for r in results:
            print(f"[{icon[r.status]}] {r.name:<{width}}  {r.detail}")
        n_fail = sum(r.status == "fail" for r in results)
        n_warn = sum(r.status == "warn" for r in results)
        print(f"\n{len(results)} checks: {n_fail} failed, {n_warn} warnings")
    return 1 if any(r.status == "fail" for r in results) else 0


def _cmd_config(args: argparse.Namespace) -> int:
    from gameqa.config import load_settings

    s = load_settings(args.config) if args.config else load_settings()
    data = s.model_dump(mode="json")
    data["_config_file"] = str(s.config_file)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        import yaml

        print(yaml.safe_dump(data, sort_keys=False))
    return 0


def _collect_gt(path: Path) -> dict[str, Path]:
    from gameqa.evaluation import load_ground_truth

    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    return {load_ground_truth(f).video_id: f for f in files}


def _cmd_evaluate(args: argparse.Namespace) -> int:
    from gameqa.config import load_settings
    from gameqa.core.schemas import DetectionSet
    from gameqa.evaluation import aggregate, evaluate_video, format_markdown, load_ground_truth

    cfg = load_settings().evaluation
    gt_index = _collect_gt(Path(args.ground_truth))
    evaluations = []
    for pred_path in args.predictions:
        detset = DetectionSet.model_validate_json(Path(pred_path).read_text(encoding="utf-8"))
        gt_path = gt_index.get(detset.video_id)
        if gt_path is None:
            print(f"warning: no ground truth for video_id '{detset.video_id}' ({pred_path}); skipped",
                  file=sys.stderr)
            continue
        evaluations.append(
            evaluate_video(
                detset.detections,
                load_ground_truth(gt_path),
                iou_threshold=cfg.iou_threshold,
                peak_tolerance_s=cfg.peak_tolerance_s,
                match_subtype=cfg.match_subtype,
            )
        )
    if not evaluations:
        print("error: nothing to evaluate", file=sys.stderr)
        return 1
    summary = aggregate(evaluations)
    table = format_markdown(summary)
    print(table)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "per_video.json").write_text(
            json.dumps([e.model_dump(mode="json") for e in evaluations], indent=2), encoding="utf-8"
        )
        (out / "summary.json").write_text(
            json.dumps({k: v.model_dump(mode="json") for k, v in summary.items()}, indent=2),
            encoding="utf-8",
        )
        (out / "summary.md").write_text(table + "\n", encoding="utf-8")
        print(f"\nwritten to {out}")
    return 0


def _setup_logging() -> None:
    from gameqa.config import get_settings
    from gameqa.logging_setup import configure_from_settings

    configure_from_settings(get_settings())


def _print_kv(rows: list[tuple[str, object]]) -> None:
    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"{k:<{width}}  {v}")


def _cmd_probe(args: argparse.Namespace) -> int:
    from gameqa.config import get_settings
    from gameqa.video import probe_video, validate_file

    _setup_logging()
    cfg = get_settings().video
    family = validate_file(args.video, cfg.allowed_extensions, cfg.max_upload_mb)
    res = probe_video(args.video)
    info = res.info
    if args.json:
        print(json.dumps({"container_family": family, **info.model_dump(mode="json")}, indent=2))
        return 0
    t = info.timing
    rows: list[tuple[str, object]] = [
        ("file", info.source_path),
        ("container", f"{info.container} (sniffed: {family})"),
        ("codec / pix_fmt", f"{info.codec} / {info.pix_fmt} ({info.bit_depth or '?'}-bit)"),
        ("resolution", f"{info.width}x{info.height}" + (f" (rotated {info.rotation})" if info.rotation else "")),
        ("nominal fps", info.fps_nominal),
        ("average fps", info.fps_average),
        ("frames", info.frame_count),
        ("duration", f"{info.duration_s:.3f} s" if info.duration_s is not None else "?"),
        ("variable frame rate", info.is_vfr),
        ("HDR", f"{info.is_hdr} ({info.color_transfer})"),
        ("audio", info.has_audio),
        ("size", f"{(info.file_size_bytes or 0) / 1024**2:.1f} MB"),
    ]
    if t and t.n_intervals:
        rows += [
            ("frame interval", f"median {t.median_interval_s * 1000:.2f} ms, "
                               f"min {t.min_interval_s * 1000:.2f} ms, max {t.max_interval_s * 1000:.2f} ms"),
            ("irregular intervals", f"{t.irregular_intervals} ({t.irregular_fraction:.2%})"),
        ]
    _print_kv(rows)
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    import cv2

    from gameqa.config import get_settings
    from gameqa.video import open_video

    _setup_logging()
    cfg = get_settings().video
    stream = open_video(args.video, cfg, start_s=args.start, end_s=args.end,
                        sampled_only=not args.all_frames)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for frame in stream:
        name = f"f{frame.index:07d}_{frame.timestamp_s:010.3f}.{args.format}"
        cv2.imwrite(str(out / name), frame.image)
        index.append({"file": name, "index": frame.index, "timestamp_s": frame.timestamp_s,
                      "is_sampled": frame.is_sampled})
        if args.limit and len(index) >= args.limit:
            break
    (out / "index.json").write_text(json.dumps({
        "video": stream.info.model_dump(mode="json"),
        "stats": stream.stats.as_dict(),
        "frames": index,
    }, indent=2, default=str), encoding="utf-8")
    print(f"wrote {len(index)} frames to {out} "
          f"(decoded {stream.stats.frames_decoded}, size {stream.stats.output_size})")
    for w in stream.stats.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 0


def _peak_rss_mb() -> float:
    import resource

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 1024**2 if sys.platform == "darwin" else rss / 1024  # bytes on macOS, KiB on Linux


def _cmd_bench(args: argparse.Namespace) -> int:
    from gameqa.config import get_settings
    from gameqa.video import open_video

    _setup_logging()
    cfg = get_settings().video
    stream = open_video(args.video, cfg, end_s=args.seconds)
    for frame in stream:
        # What the pipeline does: sampled frames are normalised for the detectors;
        # --normalise-all forces it for every frame (worst case).
        if frame.is_sampled or args.normalise_all:
            _ = frame.image
    s = stream.stats
    result = {
        "video": Path(args.video).name,
        "source": f"{stream.info.width}x{stream.info.height} @ {stream.info.fps_nominal} fps",
        "normalised": s.output_size,
        "normalise_mode": "all frames" if args.normalise_all else "sampled frames",
        "frames_decoded": s.frames_decoded,
        "frames_sampled": s.frames_sampled,
        "video_seconds": round(s.video_seconds, 3),
        "wall_seconds": round(s.wall_s, 3),
        "decode_seconds": round(s.decode_s, 3),
        "normalise_seconds": round(s.normalise_s, 3),
        "decode_fps": round(s.frames_decoded / s.wall_s, 1) if s.wall_s else None,
        "realtime_factor": round(s.realtime_factor, 3) if s.realtime_factor else None,
        "peak_rss_mb": round(_peak_rss_mb(), 1),
        "truncated": s.truncated,
        "warnings": s.warnings,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_kv(list(result.items()))
    return 0


def _cmd_detect(args: argparse.Namespace) -> int:
    from gameqa.config import get_settings
    from gameqa.pipeline import run_pipeline

    _setup_logging()
    names = [n.strip() for n in args.detectors.split(",")] if args.detectors else None
    res = run_pipeline(args.video, get_settings(), detector_names=names, video_id=args.video_id,
                       start_s=args.start, end_s=args.end, evidence_dir=args.evidence)
    ds = res.detection_set
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(ds.model_dump_json(indent=2), encoding="utf-8")
    if args.run_info:
        Path(args.run_info).write_text(json.dumps(res.as_dict(), indent=2, default=str), encoding="utf-8")
    for d in ds.detections:
        sev = d.severity.value.upper() if d.severity else "-"
        print(f"{d.start_time_s:8.3f}-{d.end_time_s:8.3f}s  {sev:<6} {d.category.value:<18} {d.subtype:<20} "
              f"conf {d.confidence:.2f}  {d.description}")
    print(f"\n{len(ds.detections)} detections, status {res.status}, {res.wall_s:.1f}s "
          f"({res.throughput_fps or 0:.0f} frames/s)")
    for r in res.runs:
        if r.summary:
            print(f"{r.name} summary: {json.dumps(r.summary, default=str)}")
    for w in res.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from gameqa.api.app import create_app
    from gameqa.config import get_settings

    _setup_logging()
    app = create_app(get_settings())
    ssl = {}
    if args.ssl_cert and args.ssl_key:  # SRS 5.4: HTTPS (TLS >= 1.2 is uvicorn/OpenSSL's minimum by default)
        ssl = {"ssl_certfile": args.ssl_cert, "ssl_keyfile": args.ssl_key}
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", **ssl)
    return 0


def _cmd_worker(args: argparse.Namespace) -> int:
    from gameqa.api.models import init_db, make_engine, make_sessionmaker
    from gameqa.config import get_settings
    from gameqa.worker import Worker

    _setup_logging()
    s = get_settings()
    engine = make_engine(s.database.url)
    init_db(engine)
    s.paths.ensure()
    w = Worker(s, make_sessionmaker(engine))
    if args.once:
        w.recover()
        print(w.process_one() or "queue empty")
        return 0
    w.run_forever()
    return 0


def _cmd_create_user(args: argparse.Namespace) -> int:
    import getpass
    import os

    from sqlalchemy import func, select

    from gameqa.api.models import Role, User, init_db, make_engine, make_sessionmaker
    from gameqa.api.security import hash_password
    from gameqa.config import get_settings

    s = get_settings()
    password = os.environ.get("GAMEQA_NEW_USER_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < s.api.min_password_length:
        print(f"error: password must be at least {s.api.min_password_length} characters", file=sys.stderr)
        return 2
    engine = make_engine(s.database.url)
    init_db(engine)
    with make_sessionmaker(engine)() as db:
        if db.scalar(select(User).where(func.lower(User.email) == args.email.lower())):
            print("error: email already registered", file=sys.stderr)
            return 2
        db.add(User(email=args.email.lower(), full_name=args.name or "", password_hash=hash_password(password),
                    role=Role(args.role)))
        db.commit()
    print(f"created {args.role} {args.email}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gameqa", description="AI Game QA Tester")
    p.add_argument("--version", action="version", version=f"gameqa {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="check the environment")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=_cmd_doctor)

    c = sub.add_parser("config", help="show the effective configuration")
    c.add_argument("--json", action="store_true")
    c.add_argument("--config", help="YAML file to load instead of config/default.yaml")
    c.set_defaults(func=_cmd_config)

    e = sub.add_parser("evaluate", help="score detections against ground truth")
    e.add_argument("-p", "--predictions", nargs="+", required=True, help="DetectionSet JSON file(s)")
    e.add_argument("-g", "--ground-truth", required=True, help="label file or directory of label files")
    e.add_argument("-o", "--out", help="directory for per-video and summary results")
    e.set_defaults(func=_cmd_evaluate)

    pr = sub.add_parser("probe", help="validate a video and show its metadata")
    pr.add_argument("video")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=_cmd_probe)

    ex = sub.add_parser("extract", help="write normalised frames to image files")
    ex.add_argument("video")
    ex.add_argument("-o", "--out", required=True)
    ex.add_argument("--start", type=float, default=None, help="seconds")
    ex.add_argument("--end", type=float, default=None, help="seconds")
    ex.add_argument("--all-frames", action="store_true", help="every frame, not only the sampled stream")
    ex.add_argument("--format", choices=["jpg", "png"], default="jpg")
    ex.add_argument("--limit", type=int, default=0, help="stop after N frames")
    ex.set_defaults(func=_cmd_extract)

    b = sub.add_parser("bench", help="measure decode + normalise throughput and memory")
    b.add_argument("video")
    b.add_argument("--seconds", type=float, default=None, help="only the first N seconds")
    b.add_argument("--normalise-all", action="store_true", help="normalise every frame (worst case)")
    b.add_argument("--json", action="store_true")
    b.set_defaults(func=_cmd_bench)

    dt = sub.add_parser("detect", help="run the detectors on a video")
    dt.add_argument("video")
    dt.add_argument("--detectors", help="comma-separated names (default: enabled in config)")
    dt.add_argument("--video-id", default=None)
    dt.add_argument("--start", type=float, default=None)
    dt.add_argument("--end", type=float, default=None)
    dt.add_argument("-o", "--out", help="write the DetectionSet JSON here")
    dt.add_argument("--run-info", help="write timing / status JSON here")
    dt.add_argument("--evidence", help="directory for screenshots and 5-10 s clips (FR-4)")
    dt.set_defaults(func=_cmd_detect)

    sv = sub.add_parser("serve", help="run the REST API (and the built dashboard, if present)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--ssl-cert")
    sv.add_argument("--ssl-key")
    sv.set_defaults(func=_cmd_serve)

    wk = sub.add_parser("worker", help="process queued analysis jobs")
    wk.add_argument("--once", action="store_true", help="process one job and exit")
    wk.set_defaults(func=_cmd_worker)

    cu = sub.add_parser("create-user", help="create a user (e.g. the first admin)")
    cu.add_argument("--email", required=True)
    cu.add_argument("--role", choices=["tester", "developer", "qa_lead", "admin"], default="tester")
    cu.add_argument("--name", default="")
    cu.set_defaults(func=_cmd_create_user)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from gameqa.core.errors import GameQAError

    try:
        return int(args.func(args))
    except GameQAError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
