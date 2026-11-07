"""Streaming decode → normalise → sample (FR-2).

``FrameStream`` decodes a video once with OpenCV and yields every frame as a
``gameqa.core.Frame``:

* ``timestamp_s`` is the decoder's presentation timestamp (relative to the first
  frame). It was verified against ffprobe's packet timestamps, including on
  variable-frame-rate files, and the stream re-checks the two agree while decoding.
* ``index`` is the frame's position in the original full-rate sequence.
* ``image`` is normalised: BGR, 8-bit, scaled to ``normalized_height`` with the aspect
  ratio kept. OpenCV already converts any pixel format / colour range (limited or full,
  8- or 10-bit) to 8-bit BGR; HDR tone mapping is *not* performed (flagged in metadata).
  Normalisation is lazy: it only runs when a detector reads ``frame.image``.
* ``is_sampled`` marks the frames on the 10-15 FPS analysis grid. Detectors that need
  every frame (frame timing) receive all frames; the others only the sampled ones.
  Sampling is by timestamp, not by frame count, so it stays correct for VFR footage.

Nothing is buffered: memory use is one frame at a time regardless of video length.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from gameqa.config import VideoConfig
from gameqa.core.errors import CorruptVideoError
from gameqa.core.schemas import Frame
from gameqa.logging_setup import get_logger
from gameqa.video.probe import ProbeResult, probe_video

log = get_logger("video.stream")

TIMESTAMP_TOLERANCE_S = 0.002


class Normaliser:
    """Resize to a fixed height (aspect kept, even width) and force BGR uint8."""

    def __init__(self, target_height: int, upscale: bool = True):
        self.target_height = target_height
        self.upscale = upscale

    def output_size(self, width: int, height: int) -> tuple[int, int]:
        if height <= self.target_height and not self.upscale:
            return width, height
        h = self.target_height
        w = int(round(width * h / height / 2.0)) * 2
        return max(w, 2), h

    def __call__(self, img: np.ndarray) -> np.ndarray:
        if img.dtype != np.uint8:  # e.g. 16-bit decode -> 8-bit
            img = (img >> 8).astype(np.uint8) if img.dtype == np.uint16 else cv2.convertScaleAbs(img)
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        h, w = img.shape[:2]
        tw, th = self.output_size(w, h)
        if (tw, th) != (w, h):
            interp = cv2.INTER_AREA if th < h else cv2.INTER_LINEAR
            img = cv2.resize(img, (tw, th), interpolation=interp)
        return np.ascontiguousarray(img)


@dataclass
class StreamStats:
    frames_decoded: int = 0
    frames_sampled: int = 0
    expected_frames: int | None = None
    first_timestamp_s: float | None = None
    last_timestamp_s: float | None = None
    decode_s: float = 0.0
    normalise_s: float = 0.0
    wall_s: float = 0.0
    timestamp_mismatches: int = 0
    truncated: bool = False
    output_size: tuple[int, int] | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def video_seconds(self) -> float:
        if self.first_timestamp_s is None or self.last_timestamp_s is None:
            return 0.0
        return self.last_timestamp_s - self.first_timestamp_s

    @property
    def realtime_factor(self) -> float | None:
        """> 1.0 means faster than real time."""
        return self.video_seconds / self.wall_s if self.wall_s > 0 and self.video_seconds > 0 else None

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["video_seconds"] = round(self.video_seconds, 4)
        d["realtime_factor"] = round(self.realtime_factor, 3) if self.realtime_factor else None
        return d


class FrameStream:
    """Iterate over the frames of one video (optionally a time window)."""

    def __init__(
        self,
        path: str | Path,
        video_cfg: VideoConfig | None = None,
        probe: ProbeResult | None = None,
        start_s: float | None = None,
        end_s: float | None = None,
        sampled_only: bool = False,
    ):
        self.path = Path(path)
        self.cfg = video_cfg or VideoConfig()
        self.probe = probe or probe_video(self.path)
        self.start_s = max(0.0, start_s or 0.0)
        self.end_s = end_s
        self.sampled_only = sampled_only
        self.normaliser = Normaliser(self.cfg.normalized_height, self.cfg.upscale)
        self.sample_period = 1.0 / self.cfg.analysis_fps
        self.stats = StreamStats()
        info = self.probe.info
        # A frame up to 40 % of a frame interval *before* a grid point is the nearest
        # frame to it. Needed because containers round timestamps (Matroska stores
        # whole milliseconds: 60 FPS frame 5 is at 0.083 s, grid point 0.0833 s).
        interval = (info.timing.median_interval_s if info.timing and info.timing.median_interval_s
                    else 1.0 / info.fps_nominal)
        self.sample_tolerance = 0.4 * interval
        if info.truncation_suspected:
            self.stats.truncated = True
            self.stats.warnings.append(
                f"container declares {info.declared_frame_count or '?'} frames / "
                f"{info.declared_duration_s or '?'} s but only {info.frame_count} frames / "
                f"{info.duration_s} s are present: file is probably truncated"
            )
        if info.is_hdr:
            self.stats.warnings.append(
                f"HDR video ({info.color_transfer}): converted to 8-bit without tone mapping; "
                "colours will look washed out and brightness-based thresholds may be unreliable"
            )

    @property
    def info(self):
        return self.probe.info

    def _open(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(str(self.path), cv2.CAP_FFMPEG)
        if not cap.isOpened():
            raise CorruptVideoError(f"OpenCV could not open '{self.path.name}'")
        return cap

    def _timed_normalise(self, raw: np.ndarray) -> np.ndarray:
        t = time.perf_counter()
        img = self.normaliser(raw)
        self.stats.normalise_s += time.perf_counter() - t
        self.stats.output_size = (img.shape[1], img.shape[0])
        return img

    def _decoder_origin(self) -> float:
        """Decoder timestamp of the file's first frame, so windowed reads use the same
        time origin as a full read."""
        cap = self._open()
        try:
            ok, _ = cap.read()
            return cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0 if ok else 0.0
        finally:
            cap.release()

    def __iter__(self) -> Iterator[Frame]:
        cap = self._open()
        pts = self.probe.pts
        windowed = self.start_s > 0 or self.end_s is not None
        stats = self.stats
        stats.expected_frames = self.info.frame_count
        origin: float | None = None  # decoder time of the first frame of the file
        next_sample = 0.0
        index = -1
        t_wall = time.perf_counter()
        try:
            if self.start_s > 0:
                origin = self._decoder_origin()
                # Seek a little early (keyframe-based seek), then decode forward.
                cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, self.start_s - 1.0) * 1000.0)
            while True:
                t0 = time.perf_counter()
                ok, raw = cap.read()
                stats.decode_s += time.perf_counter() - t0
                if not ok or raw is None:
                    break
                dec_ts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                if origin is None:
                    origin = dec_ts
                ts = dec_ts - origin
                if windowed:
                    index = self.probe.index_at(ts)
                else:
                    index += 1
                    if pts is not None and index < len(pts) and abs(pts[index] - ts) > TIMESTAMP_TOLERANCE_S:
                        stats.timestamp_mismatches += 1
                        if stats.timestamp_mismatches == 1:
                            log.warning("decoder/ffprobe timestamp mismatch at frame %d: %.4f vs %.4f",
                                        index, ts, pts[index])
                if ts < self.start_s - 1e-6:
                    continue
                if self.end_s is not None and ts > self.end_s + 1e-6:
                    break

                if stats.first_timestamp_s is None:
                    stats.first_timestamp_s = ts
                    next_sample = ts
                stats.last_timestamp_s = ts
                stats.frames_decoded += 1

                is_sampled = ts + self.sample_tolerance >= next_sample
                if is_sampled:
                    stats.frames_sampled += 1
                    while next_sample <= ts + self.sample_tolerance:
                        next_sample += self.sample_period
                elif self.sampled_only:
                    continue

                yield Frame(
                    index=index,
                    timestamp_s=round(ts, 6),
                    original_size=(raw.shape[1], raw.shape[0]),
                    is_sampled=is_sampled,
                    raw=raw,
                    normalise=self._timed_normalise,
                )
        finally:
            cap.release()
            stats.wall_s = time.perf_counter() - t_wall
            self._finalise_stats(windowed)

    def _finalise_stats(self, windowed: bool) -> None:
        s = self.stats
        if s.timestamp_mismatches:
            s.warnings.append(
                f"{s.timestamp_mismatches} frames had decoder timestamps that differ from the "
                "container by > 2 ms (possible decode errors or dropped frames in the file)"
            )
        if not windowed and s.expected_frames and s.frames_decoded < s.expected_frames:
            missing = s.expected_frames - s.frames_decoded
            # A few frames can legitimately be undecodable at the very end of a recording.
            if missing > max(2, 0.005 * s.expected_frames):
                s.truncated = True
                s.warnings.append(
                    f"decoding stopped after {s.frames_decoded} of {s.expected_frames} frames "
                    f"(at {s.last_timestamp_s or 0:.2f}s): file may be truncated or damaged"
                )
        for w in s.warnings:
            log.warning(w)


def read_frame_at(path: str | Path, timestamp_s: float, video_cfg: VideoConfig | None = None,
                  probe: ProbeResult | None = None, normalise: bool = False) -> Frame:
    """Decode the single frame presented at ``timestamp_s``. With ``normalise=False``
    (default) ``frame.image`` is the original resolution — used for screenshots in
    Phase 9 and for spot checks."""
    cfg = video_cfg or VideoConfig()
    if not normalise:
        cfg = cfg.model_copy(update={"upscale": False, "normalized_height": 2160})
    probe = probe or probe_video(path)
    target = probe.pts[probe.index_at(timestamp_s)] if probe.pts is not None and len(probe.pts) else timestamp_s
    stream = FrameStream(path, cfg, probe=probe, start_s=float(target), end_s=float(target) + 0.5)
    for frame in stream:
        if frame.timestamp_s + 1e-4 >= target:
            return frame
    raise CorruptVideoError(f"no frame found at {timestamp_s:.3f}s in '{Path(path).name}'")
