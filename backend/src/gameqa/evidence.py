"""Evidence extraction (FR-4): a screenshot and a 5–10 s clip for every detection.

* Screenshot: the frame at the detection's peak time at ORIGINAL resolution (decoded by
  the same engine, so the frame is exactly the one the detector reported), saved twice:
  plain and with the affected region outlined (SRS storyboard 8.3).
* Clip: cut with ffmpeg and re-encoded to H.264 + AAC with ``+faststart`` so it plays in
  the dashboard's HTML5 ``<video>`` element (OpenCV's VideoWriter produces MPEG-4 Part 2
  on macOS/Linux, which browsers do not play). Length = configured clip length clamped to
  5–10 s, centred on the detection and shifted to stay inside the video.
Paths are stored relative to the evidence root so the API can serve them through
authenticated endpoints only (SRS 5.4).
"""

from __future__ import annotations

import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

from gameqa.config import Settings
from gameqa.core.errors import VideoError
from gameqa.core.schemas import Detection, Evidence, VideoInfo
from gameqa.logging_setup import get_logger
from gameqa.video import ProbeResult, read_frame_at

log = get_logger("evidence")

SEVERITY_BGR = {"high": (40, 40, 220), "medium": (0, 165, 255), "low": (60, 200, 60), None: (255, 255, 0)}


def clip_window(d: Detection, duration_s: float | None, clip_len: float) -> tuple[float, float]:
    """5-10 s window covering the detection, centred, kept inside [0, duration]."""
    length = min(10.0, max(5.0, clip_len, d.duration_s + 2.0))
    centre = (d.start_time_s + d.end_time_s) / 2
    start = max(0.0, centre - length / 2)
    if duration_s is not None:
        start = max(0.0, min(start, duration_s - length))
        length = min(length, duration_s - start)
    return round(start, 3), round(start + length, 3)


def write_clip(src: Path, dst: Path, start_s: float, end_s: float, info: VideoInfo) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise VideoError("ffmpeg not found; cannot write evidence clips")
    # detection times are relative to the first frame; ffmpeg's -ss is relative to the
    # container start, which equals the first frame's PTS here (start_time_s is removed)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start_s:.3f}", "-i", str(src),
           "-t", f"{end_s - start_s:.3f}", "-map", "0:v:0", "-map", "0:a:0?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-vf", "scale='min(1920,iw)':-2", "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart", str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not dst.exists():
        raise VideoError(f"clip extraction failed: {proc.stderr.strip()[-300:]}")


def write_screenshots(src: Path, d: Detection, probe: ProbeResult, out_dir: Path, fmt: str) -> tuple[str, str]:
    frame = read_frame_at(src, d.peak_time_s, probe=probe)  # original resolution
    img = frame.image
    plain = out_dir / f"{d.id}.{fmt}"
    marked = out_dir / f"{d.id}_marked.{fmt}"
    params = [cv2.IMWRITE_JPEG_QUALITY, 92] if fmt == "jpg" else []
    cv2.imwrite(str(plain), img, params)
    ann = img.copy()
    colour = SEVERITY_BGR.get(d.severity.value if d.severity else None, SEVERITY_BGR[None])
    h, w = ann.shape[:2]
    thick = max(2, w // 400)
    if d.bbox is not None and d.bbox.area < 0.98:
        x0, y0, x1, y1 = d.bbox.to_pixels(w, h)
        cv2.rectangle(ann, (x0, y0), (x1 - 1, y1 - 1), colour, thick)
    else:
        cv2.rectangle(ann, (0, 0), (w - 1, h - 1), colour, thick * 2)
    label = f"{d.subtype} @ {d.peak_time_s:.2f}s" + (f" [{d.severity.value.upper()}]" if d.severity else "")
    scale = max(0.6, w / 1600)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    cv2.rectangle(ann, (0, 0), (tw + 16, th + 16), (0, 0, 0), -1)
    cv2.putText(ann, label, (8, th + 8), cv2.FONT_HERSHEY_SIMPLEX, scale, colour, 2, cv2.LINE_AA)
    cv2.imwrite(str(marked), ann, params)
    return plain.name, marked.name


def extract_evidence(video_path: str | Path, detections: list[Detection], probe: ProbeResult,
                     evidence_root: Path, subdir: str, settings: Settings, workers: int = 3) -> list[str]:
    """Write evidence for every detection under ``evidence_root/subdir``. Returns warnings
    (a failure for one detection does not stop the others)."""
    src = Path(video_path)
    out_dir = evidence_root / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = settings.evidence.screenshot_format
    warnings: list[str] = []
    for d in detections:  # screenshots: sequential (decoder reuse is cheap, keeps memory low)
        try:
            plain, marked = write_screenshots(src, d, probe, out_dir, fmt)
            d.evidence = Evidence(screenshot_path=f"{subdir}/{plain}")
            d.metrics["screenshot_marked"] = f"{subdir}/{marked}"
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"screenshot for {d.id} failed: {exc}")
            d.evidence = Evidence()

    def clip(d: Detection) -> str | None:
        s, e = clip_window(d, probe.info.duration_s, settings.evidence.clip_duration_s)
        name = f"{d.id}.mp4"
        try:
            write_clip(src, out_dir / name, s, e, probe.info)
        except Exception as exc:  # noqa: BLE001
            return f"clip for {d.id} failed: {exc}"
        d.evidence.clip_path = f"{subdir}/{name}"  # type: ignore[union-attr]
        d.evidence.clip_start_s, d.evidence.clip_end_s = s, e  # type: ignore[union-attr]
        return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        warnings += [w for w in pool.map(clip, detections) if w]
    for w in warnings:
        log.warning(w)
    return warnings
