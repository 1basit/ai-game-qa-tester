"""Single-pass detection pipeline (FR-3 "single pass", NFR 5.1 fault isolation).

The video is decoded once. Every frame goes to detectors that declared
``FrameRate.FULL``; frames on the sampled grid also go to ``FrameRate.SAMPLED``
detectors. If a detector raises, it is disabled for the rest of the video, the error is
logged and recorded, and the other detectors carry on — the job then completes "with
warnings" instead of failing.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import gameqa.detectors  # noqa: F401  (registers detectors)
from gameqa.config import Settings, get_settings
from gameqa.core.detector import Detector, FrameRate, get_detector_class
from gameqa.core.schemas import Detection, DetectionSet
from gameqa.evidence import extract_evidence
from gameqa.logging_setup import get_logger
from gameqa.severity import apply_severity
from gameqa.video import open_video

log = get_logger("pipeline")

ProgressCallback = Callable[[float, str], None]


@dataclass
class DetectorRun:
    name: str
    version: str
    frames_processed: int = 0
    seconds: float = 0.0
    detections: int = 0
    error: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    detection_set: DetectionSet
    runs: list[DetectorRun]
    stream_stats: dict[str, Any]
    wall_s: float
    warnings: list[str]

    @property
    def status(self) -> str:
        return "completed_with_warnings" if self.warnings else "completed"

    @property
    def throughput_fps(self) -> float | None:
        n = self.stream_stats.get("frames_decoded") or 0
        return n / self.wall_s if self.wall_s > 0 else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "wall_s": round(self.wall_s, 3),
            "throughput_fps": round(self.throughput_fps, 1) if self.throughput_fps else None,
            "realtime_factor": self.stream_stats.get("realtime_factor"),
            "warnings": self.warnings,
            "detectors": [r.__dict__ for r in self.runs],
            "stream": {k: v for k, v in self.stream_stats.items() if k != "warnings"},
        }


def build_detectors(settings: Settings, names: Sequence[str] | None = None) -> list[Detector]:
    names = list(names) if names else settings.enabled_detectors()
    out = []
    for name in names:
        cls = get_detector_class(name)
        cfg = settings.detectors.get(name)
        params = dict(cfg.params) if cfg else {}
        out.append(cls(params))
    return out


def run_pipeline(
    video_path: str | Path,
    settings: Settings | None = None,
    detector_names: Sequence[str] | None = None,
    detectors: Sequence[Detector] | None = None,
    video_id: str | None = None,
    progress: ProgressCallback | None = None,
    start_s: float | None = None,
    end_s: float | None = None,
    evidence_dir: str | Path | None = None,
    evidence_subdir: str | None = None,
) -> PipelineResult:
    settings = settings or get_settings()
    t_start = time.perf_counter()
    stream = open_video(video_path, settings.video, start_s=start_s, end_s=end_s)
    info = stream.info
    dets = list(detectors) if detectors is not None else build_detectors(settings, detector_names)
    runs = {id(d): DetectorRun(d.name, d.version) for d in dets}
    active: list[Detector] = []
    for d in dets:
        try:
            d.start(info)
            active.append(d)
        except Exception as exc:  # noqa: BLE001 - isolation is the point
            _record_failure(runs[id(d)], exc, "start")

    duration = (end_s or info.duration_s or 0) - (start_s or 0)
    last_report = 0.0
    for frame in stream:
        for d in list(active):
            if d.frame_rate is FrameRate.SAMPLED and not frame.is_sampled:
                continue
            r = runs[id(d)]
            t0 = time.perf_counter()
            try:
                d.process(frame)
                r.frames_processed += 1
            except Exception as exc:  # noqa: BLE001
                _record_failure(r, exc, f"frame {frame.index} ({frame.timestamp_s:.3f}s)")
                active.remove(d)
            r.seconds += time.perf_counter() - t0
        if progress and duration > 0 and frame.timestamp_s - last_report >= 1.0:
            last_report = frame.timestamp_s
            progress(min(0.99, (frame.timestamp_s - (start_s or 0)) / duration), "analysing")

    detections: list[Detection] = []
    for d in active:
        r = runs[id(d)]
        t0 = time.perf_counter()
        try:
            found = d.finish()
            r.detections = len(found)
            r.summary = dict(d.summary)
            detections.extend(found)
        except Exception as exc:  # noqa: BLE001
            _record_failure(r, exc, "finish")
        r.seconds += time.perf_counter() - t0

    detections.sort(key=lambda x: (x.start_time_s, x.category.value))
    warnings = list(stream.stats.warnings)
    warnings += [f"detector '{r.name}' failed: {r.error}" for r in runs.values() if r.error]
    apply_severity(detections, settings.severity)  # FR-5
    if evidence_dir is not None and detections:  # FR-4
        if progress:
            progress(0.99, "extracting evidence")
        warnings += extract_evidence(video_path, detections, stream.probe, Path(evidence_dir),
                                     evidence_subdir or (video_id or Path(video_path).stem), settings)
    if progress:
        progress(1.0, "done")
    result = PipelineResult(
        detection_set=DetectionSet(
            video_id=video_id or Path(video_path).stem, video=info, detections=detections
        ),
        runs=list(runs.values()),
        stream_stats=stream.stats.as_dict(),
        wall_s=time.perf_counter() - t_start,
        warnings=warnings,
    )
    log.info("pipeline finished: %d detections, status %s, %.1fs",
             len(detections), result.status, result.wall_s)
    return result


def _record_failure(run: DetectorRun, exc: Exception, where: str) -> None:
    run.error = f"{type(exc).__name__}: {exc} (during {where})"
    log.error("detector %s failed during %s: %s\n%s", run.name, where, exc, traceback.format_exc())
