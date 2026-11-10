"""FPS analysis service — the ONE engine behind both the CLI (`main.py analyze`) and the
local web GUI (`main.py --gui`).

It wraps the validated video engine (`gameqa.video`) and FPS detector
(`gameqa.detectors.fps`) and adds what a prototype report needs: metadata, frame-interval
statistics, frame-time percentiles ("1 % low" FPS), stutter periods and a per-frame
timeline for charts.

What is measured (equations in the project documentation)
--------------------------------------------------------
* Nominal FPS f_n — declared by the container.
* Average FPS f_avg = (N − 1) / (t_(N−1) − t_0) from frame presentation timestamps.
* Frame interval Δt_i = t_i − t_(i−1).
* Repeated frame: MAD_i = mean |G_i − G_(i−1)| (160×90 grey) < 0.25.
* Missed render: a repeated frame (or a VFR gap) while the scene is visibly moving.
* Effective FPS in a 1 s window = new pictures / 1 s (moving windows only).
* FPS drop: effective FPS < drop_ratio × target in ≥ 2 consecutive windows.
* Freeze: one picture held ≥ freeze_ms while moving.
* Stutter: ≥ stutter_min_missed missed frames in a 1 s window while the effective FPS
  stays at or above the drop threshold (uneven pacing, not a drop), in ≥ 2 consecutive
  windows, not overlapping a freeze or drop.

What is NOT measured: the game's true rendering FPS. A recording only shows the pictures
the recorder captured; see ``LIMITATIONS``.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from gameqa import __version__
from gameqa.config import PROJECT_ROOT, FpsServiceConfig, get_settings
from gameqa.core.errors import VideoError
from gameqa.core.events import EventAccumulator, PersistenceRule
from gameqa.detectors.fps import FpsDropDetector
from gameqa.video import FrameStream, probe_video, probe_video_opencv, validate_file

ProgressFn = Callable[[float, str], None]

LIMITATIONS = [
    "The game's true rendering FPS cannot be recovered from an ordinary recording: the video only "
    "contains the pictures the recorder captured. Ground truth needs engine profiler logs or an "
    "on-screen FPS counter, which were not available.",
    "The recording frame rate caps what can be measured: a 60 FPS recording cannot show the game "
    "dropping from 144 to 90 FPS.",
    "FPS can only be measured while the picture is moving. In still stretches (menus, paused game, "
    "camera at rest) a repeated frame is indistinguishable from a normal one; these stretches are "
    "excluded and reported as 'not measurable'.",
    "Video-editing cuts and intentional game pauses (hit-stop, cut-scenes) can look like freezes.",
    "Repeated frames are detected on a 160x90 grey thumbnail with a small tolerance for compression "
    "noise; extremely small on-screen motion may be read as a repeat only when the surrounding frames "
    "are clearly moving.",
]


class FpsEvent(BaseModel):
    type: Literal["fps_drop", "freeze", "stutter"]
    start_s: float
    end_s: float
    duration_s: float
    start_frame: int
    end_frame: int
    description: str
    metrics: dict = Field(default_factory=dict)


class FpsAnalysisResult(BaseModel):
    tool: str = f"AI Game QA Tester {__version__} — FPS analysis service"
    analysed_at: datetime
    video_path: str
    video_name: str
    settings: dict
    metadata: dict
    frame_intervals: dict
    effective_fps: dict
    frame_times: dict
    counts: dict
    events: list[FpsEvent]
    verdict: str
    limitations: list[str]
    processing: dict
    warnings: list[str]


def _pct(a: np.ndarray, q: float) -> float | None:
    return float(np.percentile(a, q)) if len(a) else None


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(float(x), nd)


def _stutter_events(tl: dict, cfg: FpsServiceConfig, exclude: list[tuple[float, float]]) -> list[FpsEvent]:
    t = np.asarray(tl["time_s"])
    idx = np.asarray(tl["frame_index"])
    acc = EventAccumulator(PersistenceRule(min_frames=2, max_gap_s=0.26))
    raw = []
    for w in tl["windows"]:
        centre = (w["start_s"] + w["end_s"]) / 2
        overlap = any(a <= w["end_s"] and w["start_s"] <= b for a, b in exclude)
        active = (w["measurable"] and not overlap and w["missed_frames"] >= cfg.stutter_min_missed
                  and w["effective_fps"] >= tl["threshold_fps"])
        ci = min(int(np.searchsorted(t, centre)), len(t) - 1)
        raw += acc.update(int(idx[ci]), centre, active, score=float(w["missed_frames"]),
                          data={"eff": w["effective_fps"], "missed": w["missed_frames"]})
    raw += acc.flush()
    out = []
    for ev in raw:
        s, e = max(float(t[0]), ev.start_time_s - 0.5), min(float(t[-1]), ev.end_time_s + 0.5)
        si = int(np.searchsorted(t, s))
        ei = min(int(np.searchsorted(t, e, side="right")) - 1, len(t) - 1)
        out.append(FpsEvent(
            type="stutter", start_s=round(s, 3), end_s=round(e, 3), duration_s=round(e - s, 3),
            start_frame=int(idx[si]), end_frame=int(idx[ei]),
            description=f"Uneven frame pacing: up to {int(ev.peak_score)} missed frames per second while the "
                        f"average stayed at {ev.peak_data['eff']:.0f} FPS",
            metrics={"max_missed_per_s": int(ev.peak_score), "effective_fps_at_peak": ev.peak_data["eff"]}))
    return out


def analyze_video(video_path: str | Path, cfg: FpsServiceConfig | None = None,
                  progress: ProgressFn | None = None) -> tuple[FpsAnalysisResult, dict]:
    """Analyse one recording. Returns (result, timeline). Raises ``gameqa.core.GameQAError``
    subclasses with a user-readable message for missing / unsupported / damaged files."""
    settings = get_settings()
    cfg = cfg or settings.fps_service
    path = Path(video_path).expanduser()
    t_start = time.perf_counter()
    say = progress or (lambda f, m: None)
    warnings: list[str] = []

    say(0.0, "checking file")
    validate_file(path, settings.video.allowed_extensions, settings.video.max_upload_mb)
    say(0.02, "reading metadata")
    if shutil.which("ffprobe"):
        probe, ts_source = probe_video(path), "container timestamps (ffprobe), cross-checked with the OpenCV decoder"
    else:
        probe, ts_source = probe_video_opencv(path), "OpenCV decoder timestamps (ffprobe not installed)"
        warnings.append("ffprobe not found: metadata read with OpenCV only (frame count may be an estimate)")
    info = probe.info

    detector = FpsDropDetector({"target_fps": cfg.target_fps, "drop_ratio": cfg.drop_ratio,
                                "freeze_min_s": cfg.freeze_ms / 1000.0})
    detector.start(info)
    stream = FrameStream(path, settings.video, probe=probe)
    total = info.frame_count or 1
    for k, frame in enumerate(stream):  # every frame (full rate): frame timing needs all of them
        detector.process(frame)
        if k % 60 == 0:
            say(0.05 + 0.85 * min(1.0, k / total), f"analysing frame {k:,} of ~{total:,}")
    warnings += stream.stats.warnings
    say(0.92, "computing statistics")
    detections = detector.finish()
    tl = detector.timeline
    if not tl:
        raise VideoError("video too short to analyse (fewer than 3 frames)")

    t = np.asarray(tl["time_s"])
    dt = np.diff(t)
    missed = np.asarray(tl["missed"], bool)
    moving = np.asarray(tl["moving"], bool)
    repeated = np.asarray(tl["repeated"], bool)
    n = len(t)

    # frame times of the pictures actually shown while moving (new picture -> next new picture)
    new_idx = np.flatnonzero(~missed)
    frame_times = []
    gap_v = np.asarray(tl.get("gap_virtual", [0] * n))
    gap_m = np.asarray(tl["gap_missing"])
    for a, b in zip(new_idx[:-1], new_idx[1:]):
        still_gap = gap_v[b] > 0 and gap_m[b] == 0  # VFR gap during a still stretch: like CFR repeats
        if moving[a] and moving[b] and not still_gap:
            frame_times.append(t[b] - t[a])
    ft = np.asarray(frame_times)
    eff = np.asarray([w["effective_fps"] for w in tl["windows"] if w["measurable"]], float)
    measurable = (sum(w["measurable"] for w in tl["windows"]) / len(tl["windows"])) if tl["windows"] else 0.0

    events: list[FpsEvent] = []
    for d in detections:
        typ = "freeze" if d.subtype == "frozen_frame" else "fps_drop"
        events.append(FpsEvent(type=typ, start_s=round(d.start_time_s, 3), end_s=round(d.end_time_s, 3),
                               duration_s=round(d.duration_s, 3), start_frame=d.start_frame, end_frame=d.end_frame,
                               description=d.description, metrics=d.metrics))
    events += _stutter_events(tl, cfg, [(e.start_s, e.end_s) for e in events])
    events.sort(key=lambda e: e.start_s)

    avg_fps = (n - 1) / (t[-1] - t[0]) if n > 1 and t[-1] > t[0] else None
    med_dt = float(np.median(dt)) if len(dt) else None
    irregular = int(np.sum(np.abs(dt - med_dt) > 0.25 * med_dt)) if med_dt else 0
    counts = {
        "frames_analysed": n,
        "repeated_frames": int(repeated.sum()),
        "missed_frames_while_moving": int(missed.sum() + np.asarray(tl["gap_missing"]).sum()),
        "freezes": sum(e.type == "freeze" for e in events),
        "fps_drops": sum(e.type == "fps_drop" for e in events),
        "stutters": sum(e.type == "stutter" for e in events),
    }
    eff_stats = {
        "target_fps": cfg.target_fps,
        "drop_threshold_fps": round(cfg.drop_ratio * cfg.target_fps, 2),
        "mean": _r(eff.mean() if len(eff) else None, 1),
        "median": _r(_pct(eff, 50), 1),
        "min": _r(eff.min() if len(eff) else None, 1),
        "p5": _r(_pct(eff, 5), 1),
        "measurable_fraction": round(measurable, 3),
    }
    ft_stats = {
        "count": int(len(ft)),
        "mean_ms": _r(ft.mean() * 1000 if len(ft) else None),
        "p50_ms": _r(_pct(ft, 50) * 1000 if len(ft) else None),
        "p95_ms": _r(_pct(ft, 95) * 1000 if len(ft) else None),
        "p99_ms": _r(_pct(ft, 99) * 1000 if len(ft) else None),
        "max_ms": _r(ft.max() * 1000 if len(ft) else None),
        "one_percent_low_fps": _r(1.0 / _pct(ft, 99) if len(ft) else None, 1),
    }
    meta = {
        "file_name": path.name, "file_size_mb": round((info.file_size_bytes or 0) / 1024**2, 2),
        "container": info.container, "codec": info.codec, "resolution": f"{info.width}x{info.height}",
        "nominal_fps": info.fps_nominal, "average_fps": _r(avg_fps, 3), "frame_count": n,
        "duration_s": _r(info.duration_s if info.duration_s else (t[-1] - t[0]), 3),
        "variable_frame_rate": bool(irregular > 0) if info.is_vfr is None else info.is_vfr,
        "has_audio": info.has_audio, "timestamp_source": ts_source,
    }
    intervals = {
        "expected_ms": _r(1000.0 / info.fps_nominal, 3), "median_ms": _r(med_dt * 1000 if med_dt else None, 3),
        "min_ms": _r(dt.min() * 1000 if len(dt) else None, 3), "max_ms": _r(dt.max() * 1000 if len(dt) else None, 3),
        "p99_ms": _r(_pct(dt, 99) * 1000 if len(dt) else None, 3), "irregular_intervals": irregular,
    }
    elapsed = time.perf_counter() - t_start
    result = FpsAnalysisResult(
        analysed_at=datetime.now(timezone.utc), video_path=str(path.resolve()), video_name=path.name,
        settings={"target_fps": cfg.target_fps, "drop_ratio": cfg.drop_ratio, "freeze_ms": cfg.freeze_ms,
                  "stutter_min_missed": cfg.stutter_min_missed},
        metadata=meta, frame_intervals=intervals, effective_fps=eff_stats, frame_times=ft_stats, counts=counts,
        events=events, verdict=_verdict(counts, eff_stats), limitations=LIMITATIONS,
        processing={"seconds": round(elapsed, 2),
                    "realtime_factor": _r((t[-1] - t[0]) / elapsed if elapsed > 0 else None, 2),
                    "engine": f"gameqa.detectors.fps v{FpsDropDetector.version}"},
        warnings=warnings,
    )
    say(1.0, "done")
    return result, tl


def _verdict(c: dict, e: dict) -> str:
    if e["measurable_fraction"] == 0:
        return "Not measurable: the picture never moved enough to measure frame pacing."
    parts = []
    if c["freezes"]:
        parts.append(f"{c['freezes']} freeze(s)")
    if c["fps_drops"]:
        parts.append(f"{c['fps_drops']} FPS drop(s) below {e['drop_threshold_fps']:g} FPS")
    if c["stutters"]:
        parts.append(f"{c['stutters']} stutter period(s)")
    scope = f"in the {e['measurable_fraction']:.0%} of the video that could be measured"
    if not parts:
        return f"No freezes, drops or stutters detected {scope}."
    return "Detected " + ", ".join(parts) + f" {scope}."


def output_folder(video_name: str, cfg: FpsServiceConfig | None = None) -> Path:
    cfg = cfg or get_settings().fps_service
    root = cfg.output_dir if cfg.output_dir.is_absolute() else PROJECT_ROOT / cfg.output_dir
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in Path(video_name).stem)[:60]
    folder = root / f"{stamp}_{safe}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder
