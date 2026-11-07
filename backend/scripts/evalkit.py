"""Shared helpers for the per-detector evaluation scripts (Phases 3-7)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gameqa.config import PROJECT_ROOT, get_settings
from gameqa.core.schemas import DetectionSet
from gameqa.evaluation import aggregate, evaluate_video, format_markdown, load_ground_truth  # noqa: F401 (re-exported)
from gameqa.logging_setup import configure_logging
from gameqa.pipeline import run_pipeline

V1 = PROJECT_ROOT / "evaluation" / "videos" / (
    "YTDown.com_YouTube_Media_J8HB1-IQFxc_How-to-fix-Weapons-Hands-Clipping-Into-Walls-in-Unity-URP-SRP_001_1080p.mp4"
)
SYN_DIR = PROJECT_ROOT / "evaluation" / "synthetic"          # generated videos (git-ignored *.mp4)
GT_SYN_DIR = PROJECT_ROOT / "evaluation" / "ground_truth_synthetic"
GT_REAL_DIR = PROJECT_ROOT / "evaluation" / "ground_truth"
RESULTS = PROJECT_ROOT / "evaluation" / "results"

configure_logging("WARNING")


def make_generated_base(path: Path, seconds: float = 20.0) -> Path:
    """A fully generated, continuously moving scene (Mandelbrot zoom), 720p60."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", f"mandelbrot=size=1280x720:rate=60:start_scale=3:end_scale=0.02:inner=mincol",
             "-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", str(path)],
            check=True,
        )
    return path


def vfr_from(src: Path, dst: Path, select_expr: str) -> Path:
    """Remove frames with ffmpeg's select filter while keeping original timestamps (VFR)."""
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
         "-vf", f"select='{select_expr}'", "-fps_mode", "passthrough",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(dst)],
        check=True,
    )
    return dst


def run_and_score(pairs: list[tuple[Path, Path | None]], detectors: list[str], out_dir: Path,
                  title: str) -> tuple[str, list]:
    """Run ``detectors`` on each video, score against its label file (if any), write
    predictions + per-video and aggregate results. Returns (markdown, evaluations)."""
    cfg = get_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    evals, lines = [], [f"## {title}", ""]
    run_rows = ["| video | detections | wall s | frames/s | detector summary |", "|---|---|---|---|---|"]
    for video, gt_path in pairs:
        gt = load_ground_truth(gt_path) if gt_path else None
        vid = gt.video_id if gt else video.stem
        res = run_pipeline(video, cfg, detector_names=detectors, video_id=vid)
        (out_dir / f"{vid}.predictions.json").write_text(res.detection_set.model_dump_json(indent=2))
        summ = "; ".join(json.dumps(r.summary, default=str) for r in res.runs if r.summary)
        run_rows.append(f"| {vid} | {len(res.detection_set.detections)} | {res.wall_s:.1f} | "
                        f"{res.throughput_fps or 0:.0f} | {summ[:300]} |")
        if gt:
            ev = evaluate_video(res.detection_set.detections, gt, cfg.evaluation.iou_threshold,
                                cfg.evaluation.peak_tolerance_s, match_subtype=True)
            evals.append(ev)
            (out_dir / f"{vid}.evaluation.json").write_text(ev.model_dump_json(indent=2))
            for cat, r in ev.per_category.items():
                lines.append(f"- **{vid}** [{cat}]: TP {r.tp}, FP {r.fp}, FN {r.fn}")
                for fp in r.false_positives:
                    lines.append(f"  - FP {fp.subtype} {fp.start_s:.2f}-{fp.end_s:.2f}s (conf {fp.confidence:.2f})")
                for fn in r.false_negatives:
                    lines.append(f"  - FN {fn.subtype} {fn.start_s:.2f}-{fn.end_s:.2f}s")
    md = "\n".join(lines + ["", *run_rows, ""])
    if evals:
        md += "\n### Aggregate (subtype must match)\n\n" + format_markdown(aggregate(evals)) + "\n"
    return md, evals


def subtype_table(evals: list) -> str:
    """Recall per GT subtype and FP per predicted subtype (for detectors with sub-types)."""
    from collections import Counter

    tp, fn, fp = Counter(), Counter(), Counter()
    for ev in evals:
        for r in ev.per_category.values():
            for m in r.matches:
                pass
            for f in r.false_negatives:
                fn[f.subtype or "?"] += 1
            for f in r.false_positives:
                fp[f.subtype] += 1
    # true positives by GT subtype
    for ev in evals:
        for r in ev.per_category.values():
            for m in r.matches:
                tp["matched"] += 1
    keys = sorted(set(fn) | set(fp))
    rows = ["| subtype | FN | FP |", "|---|---|---|"] + [f"| {k} | {fn[k]} | {fp[k]} |" for k in keys]
    return "\n".join(rows)


def make_photo_pan_base(path: Path, seconds: float = 20.0, fps: int = 60, seed: int = 0) -> Path:
    """Generated 'camera' panning (with slight zoom) over a mosaic of real photographic
    textures shipped with scikit-image (brick, gravel, grass, coffee, rocket, ...)."""
    if path.exists():
        return path
    import cv2
    import numpy as np
    from skimage import data

    tiles = []
    for name in ["brick", "gravel", "grass", "coffee", "rocket", "chelsea", "astronaut", "colorwheel", "camera"]:
        img = getattr(data, name)()
        if img.ndim == 2:
            img = np.dstack([img] * 3)
        img = cv2.cvtColor(img[..., :3].astype(np.uint8), cv2.COLOR_RGB2BGR)
        h = 900
        tiles.append(cv2.resize(img, (int(img.shape[1] * h / img.shape[0]), h), interpolation=cv2.INTER_CUBIC))
    mosaic = np.concatenate(tiles, axis=1).astype(np.float32)
    rng = np.random.default_rng(seed)
    n = int(seconds * fps)
    # smooth random camera path: sum of low-frequency sines
    t = np.arange(n) / fps
    vx = 160 + 120 * np.sin(2 * np.pi * t / 7.0 + rng.uniform(0, 6)) + 60 * np.sin(2 * np.pi * t / 2.3)
    x = 700 + np.cumsum(vx) / fps
    y = 450 + 60 * np.sin(2 * np.pi * t / 5.0)
    zoom = 1.0 + 0.08 * np.sin(2 * np.pi * t / 6.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", "1280x720", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for k in range(n):
        w, h = int(1280 * zoom[k]), int(720 * zoom[k])
        patch = cv2.getRectSubPix(mosaic, (w, h), (float(x[k] % (mosaic.shape[1] - 1500) + 750), float(y[k])))
        proc.stdin.write(cv2.resize(patch, (1280, 720), interpolation=cv2.INTER_AREA).astype(np.uint8).tobytes())
    proc.stdin.close()
    proc.wait()
    return path


def region_detail(video: Path, t: float, region, height: int = 720) -> float:
    """High-frequency std (grey levels) of ``region`` in the frame at ``t`` — used to only
    inject pop-in where there is visible detail to change."""
    import cv2
    import numpy as np

    from gameqa.video import read_frame_at

    f = read_frame_at(video, t)
    img = cv2.resize(f.image, (int(f.size[0] * height / f.size[1]), height))
    x0, y0, x1, y1 = region.px(img.shape[1], img.shape[0])
    g = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    # same measure as the detector's definition of detail: RMS of (image - Gaussian(sigma 2)) at 720p
    return float(np.sqrt(((g - cv2.GaussianBlur(g, (0, 0), 2)) ** 2).mean()))
