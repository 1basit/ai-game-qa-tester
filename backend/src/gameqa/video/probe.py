"""Video metadata and frame timestamps via ffprobe.

ffprobe is used for metadata because OpenCV's properties are unreliable for exactly
the cases this project cares about: ``CAP_PROP_FPS`` reports the *average* rate of a
variable-frame-rate file and ``CAP_PROP_FRAME_COUNT`` is an estimate for many
containers. Reading the packet timestamps does not decode any pixels, so it is fast
(a 15-minute 60 FPS recording has ~54 000 packets).

Timestamps returned here are seconds relative to the first video frame, sorted into
presentation order (B-frames make packet order differ from display order).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from gameqa.core.errors import CorruptVideoError, VideoError
from gameqa.core.schemas import TimingStats, VideoInfo

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # PQ (HDR10) and HLG
IRREGULAR_TOLERANCE = 0.25  # interval deviates > 25 % from the median
VFR_MIN_IRREGULAR_FRACTION = 0.001
_FINGERPRINT_CHUNK = 4 * 1024 * 1024


@dataclass
class ProbeResult:
    info: VideoInfo
    pts: np.ndarray | None  # float64 seconds from first frame, presentation order

    def index_at(self, timestamp_s: float) -> int:
        """Original frame index of the frame presented at ``timestamp_s``."""
        if self.pts is None or len(self.pts) == 0:
            return round(timestamp_s * self.info.fps_nominal)
        i = int(np.searchsorted(self.pts, timestamp_s + 1e-6, side="right")) - 1
        return max(i, 0)


def _ffprobe() -> str:
    exe = shutil.which("ffprobe")
    if exe is None:
        raise VideoError("ffprobe not found on PATH; install ffmpeg")
    return exe


def _run(args: list[str], timeout: float) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise CorruptVideoError(f"ffprobe timed out after {timeout:.0f}s") from exc
    if proc.returncode != 0:
        msg = proc.stderr.strip().splitlines()
        raise CorruptVideoError(
            "cannot read video: " + (msg[-1] if msg else f"ffprobe exit code {proc.returncode}")
        )
    return proc.stdout


def _rate(text: str | None) -> float | None:
    if not text or text in ("0/0", "N/A"):
        return None
    try:
        value = float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def _float(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _rotation(stream: dict[str, Any]) -> int:
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            return int(round(float(sd["rotation"]))) % 360
    tag = (stream.get("tags") or {}).get("rotate")
    return int(tag) % 360 if tag else 0


def fingerprint(path: Path) -> str:
    """Fast identity hash: size + first and last 4 MiB. Not a full-file checksum."""
    h = hashlib.sha256()
    size = path.stat().st_size
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(_FINGERPRINT_CHUNK))
        if size > _FINGERPRINT_CHUNK:
            f.seek(max(size - _FINGERPRINT_CHUNK, _FINGERPRINT_CHUNK))
            h.update(f.read(_FINGERPRINT_CHUNK))
    return h.hexdigest()


def read_packet_timestamps(path: Path, timeout: float = 300) -> np.ndarray:
    """Presentation timestamps (seconds, absolute) of all non-empty video packets."""
    out = _run(
        [_ffprobe(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time,dts_time,size", "-of", "csv=p=0", str(path)],
        timeout,
    )
    values: list[float] = []
    for line in out.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 3:
            continue
        pts, dts, size = parts[0], parts[1], parts[2]
        if size.strip() in ("0", ""):
            continue  # empty packet (e.g. AVI "dropped frame" marker): no new picture
        t = _float(pts) if pts != "N/A" else _float(dts)
        if t is not None:
            values.append(t)
    arr = np.asarray(values, dtype=np.float64)
    arr.sort()
    return arr


def timing_stats(pts: np.ndarray) -> TimingStats:
    if len(pts) < 2:
        return TimingStats(n_intervals=0)
    d = np.diff(pts)
    med = float(np.median(d))
    irregular = int(np.count_nonzero(np.abs(d - med) > IRREGULAR_TOLERANCE * med)) if med > 0 else 0
    return TimingStats(
        n_intervals=len(d),
        median_interval_s=med,
        min_interval_s=float(d.min()),
        max_interval_s=float(d.max()),
        irregular_intervals=irregular,
        irregular_fraction=irregular / len(d),
    )


def probe_video(path: str | Path, with_timestamps: bool = True, timeout: float = 300) -> ProbeResult:
    path = Path(path)
    if not path.is_file():
        raise VideoError(f"video not found: {path}")
    meta = json.loads(
        _run(
            [_ffprobe(), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            timeout=60,
        )
        or "{}"
    )
    streams = meta.get("streams", [])
    video = next(
        (
            s for s in streams
            if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    if video is None:
        raise CorruptVideoError(f"'{path.name}' contains no video stream")
    fmt = meta.get("format", {})

    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise CorruptVideoError(f"'{path.name}': video stream has no valid frame size")
    rotation = _rotation(video)
    if rotation in (90, 270):
        width, height = height, width

    r_rate = _rate(video.get("r_frame_rate"))
    avg_rate = _rate(video.get("avg_frame_rate"))

    pts_abs = read_packet_timestamps(path, timeout) if with_timestamps else None
    start = float(pts_abs[0]) if pts_abs is not None and len(pts_abs) else (
        _float(video.get("start_time")) or 0.0
    )
    pts = pts_abs - start if pts_abs is not None else None
    timing = timing_stats(pts) if pts is not None else None

    if pts is not None and len(pts) > 1:
        frame_count = len(pts)
        fps_average = (len(pts) - 1) / float(pts[-1]) if pts[-1] > 0 else None
        duration = float(pts[-1]) + (timing.median_interval_s or 0.0)  # type: ignore[union-attr]
    else:
        nb = video.get("nb_frames")
        frame_count = int(nb) if nb and str(nb).isdigit() else (len(pts) if pts is not None else None)
        duration = _float(video.get("duration")) or _float(fmt.get("duration"))
        fps_average = avg_rate

    fps_nominal = r_rate or avg_rate or fps_average
    if not fps_nominal:
        raise CorruptVideoError(f"'{path.name}': cannot determine the frame rate")
    if frame_count == 0:
        raise CorruptVideoError(f"'{path.name}' contains no decodable video frames")

    is_vfr: bool | None = None
    if timing is not None and timing.n_intervals > 0:
        rate_mismatch = bool(avg_rate and r_rate and abs(avg_rate - r_rate) / r_rate > 0.02)
        is_vfr = timing.irregular_fraction >= VFR_MIN_IRREGULAR_FRACTION or (
            rate_mismatch and timing.irregular_intervals > 0
        )

    # Truncation: compare what is physically present with what the container declares.
    # MP4/AVI declare a frame count; Matroska only a duration (its end time includes
    # the start offset, hence the subtraction).
    nb = video.get("nb_frames")
    declared_frames = int(nb) if nb and str(nb).isdigit() else None
    declared_duration = _float(video.get("duration"))
    if declared_duration is None:
        fdur, fstart = _float(fmt.get("duration")), _float(fmt.get("start_time")) or 0.0
        declared_duration = fdur - fstart if fdur is not None else None
    truncation_suspected = False
    if pts is not None and len(pts):
        if declared_frames and frame_count is not None:
            truncation_suspected |= frame_count < declared_frames - max(2, 0.01 * declared_frames)
        if declared_duration and duration is not None:
            truncation_suspected |= duration < declared_duration - max(0.5, 0.02 * declared_duration)

    bits = video.get("bits_per_raw_sample")
    transfer = video.get("color_transfer")
    info = VideoInfo(
        source_path=str(path.resolve()),
        container=fmt.get("format_name"),
        codec=video.get("codec_name"),
        width=width,
        height=height,
        fps_nominal=round(fps_nominal, 4),
        frame_count=frame_count,
        duration_s=round(duration, 4) if duration is not None else None,
        is_vfr=is_vfr,
        rotation=rotation,
        fps_average=round(fps_average, 4) if fps_average else None,
        start_time_s=round(start, 6),
        file_size_bytes=path.stat().st_size,
        fingerprint=fingerprint(path),
        pix_fmt=video.get("pix_fmt"),
        bit_depth=int(bits) if bits and str(bits).isdigit() else None,
        color_transfer=transfer,
        is_hdr=transfer in HDR_TRANSFERS,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        timing=timing,
        declared_frame_count=declared_frames,
        declared_duration_s=round(declared_duration, 4) if declared_duration is not None else None,
        truncation_suspected=truncation_suspected,
    )
    return ProbeResult(info=info, pts=pts)
