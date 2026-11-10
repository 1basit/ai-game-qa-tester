"""Controlled defect injection for detector evaluation.

Real footage with labelled defects is scarce, so known defects are injected into
real (or generated) footage. Ground truth is then exact. Results on injected footage
are ALWAYS reported separately from real-footage results and the label files carry
``synthetic: true`` — injected defects are idealised and do not prove real-world
accuracy.

Each operation works in *output* time and returns the ground-truth event(s) it
created. Frames are streamed (never all held in memory) into ffmpeg (H.264, CFR).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from gameqa.config import VideoConfig
from gameqa.video import FrameStream, Normaliser


@dataclass
class Op:
    t0: float
    dur: float

    def active(self, t: float) -> bool:
        return self.t0 <= t < self.t0 + self.dur

    def gt(self) -> list[dict]:
        return []


@dataclass
class Freeze(Op):
    """Hold the picture shown at t0 for ``dur`` seconds (source keeps advancing)."""

    def gt(self):
        return [{"category": "fps_drop", "subtype": "frozen_frame", "start_s": self.t0, "end_s": self.t0 + self.dur}]


@dataclass
class Drop(Op):
    """Only every ``keep_every``-th frame is new during the op (e.g. 60 -> 20 FPS)."""

    keep_every: int = 3

    def gt(self):
        return [{"category": "fps_drop", "subtype": "fps_drop", "start_s": self.t0, "end_s": self.t0 + self.dur}]


@dataclass
class Stutter(Op):
    """Uneven pacing: one frame in every ``every`` repeats the previous picture (e.g. every
    6th frame at 60 FPS = 10 missed frames/s, effective 50 FPS: above a 45 FPS drop threshold)."""

    every: int = 6

    def gt(self):
        return [{"category": "fps_drop", "subtype": "fps_drop", "start_s": self.t0, "end_s": self.t0 + self.dur,
                 "notes": "stutter"}]


@dataclass
class Region:
    x: float
    y: float
    w: float
    h: float

    def px(self, W: int, H: int) -> tuple[int, int, int, int]:
        return int(self.x * W), int(self.y * H), int((self.x + self.w) * W), int((self.y + self.h) * H)

    def bbox(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass
class PopIn(Op):
    """Region is shown at low detail (heavy blur = low-resolution mip) for ``dur``, then
    snaps to full detail: the visible defect is the sudden snap at t0 + dur."""

    region: Region = field(default_factory=lambda: Region(0.3, 0.3, 0.3, 0.3))
    blur: int = 31

    def gt(self):
        # two visible resolution changes: sharp -> blurred at t0, blurred -> sharp at t0 + dur
        return [{"category": "texture_pop_in", "subtype": "texture_pop_in", "start_s": round(t - 0.05, 4),
                 "end_s": round(t + 0.1, 4), "bbox": self.region.bbox()} for t in (self.t0, self.t0 + self.dur)]


@dataclass
class MissingTexture(Op):
    """Region rendered as a flat magenta/black checkerboard (unrendered texture)."""

    region: Region = field(default_factory=lambda: Region(0.3, 0.3, 0.25, 0.25))
    style: str = "checker"  # "checker" (Unreal-style) or "flat" (Unity-style solid magenta)

    def gt(self):
        return [{"category": "texture_pop_in", "subtype": "unrendered_texture", "start_s": self.t0,
                 "end_s": self.t0 + self.dur, "bbox": self.region.bbox()}]


@dataclass
class Flicker(Op):
    """Region brightness alternates every frame by ``amp`` grey levels."""

    region: Region = field(default_factory=lambda: Region(0.25, 0.25, 0.4, 0.4))
    amp: int = 60

    def gt(self):
        return [{"category": "animation_glitch", "subtype": "flicker", "start_s": self.t0,
                 "end_s": self.t0 + self.dur, "bbox": self.region.bbox()}]


@dataclass
class Jitter(Op):
    """Region (default: whole frame) shifts back and forth by ``amp_px`` each frame."""

    region: Region | None = None
    amp_px: int = 6

    def gt(self):
        ev = {"category": "animation_glitch", "subtype": "jitter", "start_s": self.t0, "end_s": self.t0 + self.dur}
        if self.region:
            ev["bbox"] = self.region.bbox()
        return [ev]


@dataclass
class Teleport(Op):
    """At t0 the source jumps ``dur`` seconds ahead (an unnatural discontinuity)."""

    def gt(self):
        return [{"category": "animation_glitch", "subtype": "unnatural_transition",
                 "start_s": self.t0 - 0.05, "end_s": self.t0 + 0.05}]


def _checker(h: int, w: int, cell: int = 16) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    on = ((yy // cell + xx // cell) % 2).astype(bool)
    img = np.zeros((h, w, 3), np.uint8)
    img[on] = (255, 0, 255)
    return img


def render(
    src: str | Path,
    dst: str | Path,
    ops: list[Op],
    start_s: float = 0.0,
    end_s: float | None = None,
    height: int = 720,
    fps: float = 60.0,
    crf: int = 18,
    ignore_source: list[tuple[float, float, str]] | None = None,
) -> dict:
    """Write ``dst`` (CFR H.264) from ``src[start_s:end_s]`` with ``ops`` applied.
    Returns a ground-truth dict (in output time)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cfg = VideoConfig(normalized_height=height, upscale=True, analysis_fps=12)
    norm = Normaliser(height, True)
    stream = FrameStream(src, cfg, start_s=start_s or None, end_s=end_s)
    proc = None
    held: np.ndarray | None = None
    out_i = 0
    skip_until = -1.0
    teleports = sorted([o for o in ops if isinstance(o, Teleport)], key=lambda o: o.t0)
    tp_done: set[int] = set()
    src_t0: float | None = None
    src_of_out: list[float] = []  # source time (relative to start_s) of every output frame
    last_out: np.ndarray | None = None
    try:
        for frame in stream:
            if src_t0 is None:
                src_t0 = frame.timestamp_s
            src_rel = frame.timestamp_s - src_t0
            if src_rel < skip_until:
                continue
            t = out_i / fps
            for k, tp in enumerate(teleports):
                if k not in tp_done and t >= tp.t0:
                    tp_done.add(k)
                    skip_until = src_rel + tp.dur
            if src_rel < skip_until:
                continue
            img = norm(frame.raw)
            H, W = img.shape[:2]
            if proc is None:
                proc = subprocess.Popen(
                    [shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                     "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
                     str(dst)],
                    stdin=subprocess.PIPE,
                )
            out = img.copy()
            for op in ops:
                if not op.active(t):
                    continue
                rel = int(round((t - op.t0) * fps))
                if isinstance(op, Freeze):
                    if held is None or rel == 0:
                        held = img.copy() if rel == 0 or held is None else held
                    out = held.copy()
                elif isinstance(op, Stutter):
                    if rel % op.every == op.every - 1 and last_out is not None:
                        out = last_out.copy()
                elif isinstance(op, Drop):
                    if rel % op.keep_every == 0 or held is None:
                        held = img.copy()
                    out = held.copy()
                elif isinstance(op, PopIn):
                    x0, y0, x1, y1 = op.region.px(W, H)
                    k = op.blur | 1
                    out[y0:y1, x0:x1] = cv2.GaussianBlur(out[y0:y1, x0:x1], (k, k), 0)
                elif isinstance(op, MissingTexture):
                    x0, y0, x1, y1 = op.region.px(W, H)
                    if op.style == "flat":
                        out[y0:y1, x0:x1] = (255, 0, 255)
                    else:
                        out[y0:y1, x0:x1] = _checker(y1 - y0, x1 - x0)
                elif isinstance(op, Flicker):
                    x0, y0, x1, y1 = op.region.px(W, H)
                    sign = 1 if rel % 2 == 0 else -1
                    patch = out[y0:y1, x0:x1].astype(np.int16) + sign * op.amp
                    out[y0:y1, x0:x1] = np.clip(patch, 0, 255).astype(np.uint8)
                elif isinstance(op, Jitter):
                    dx = op.amp_px if rel % 2 == 0 else -op.amp_px
                    M = np.float32([[1, 0, dx], [0, 1, dx // 2]])
                    if op.region is None:
                        out = cv2.warpAffine(out, M, (W, H), borderMode=cv2.BORDER_REPLICATE)
                    else:
                        x0, y0, x1, y1 = op.region.px(W, H)
                        out[y0:y1, x0:x1] = cv2.warpAffine(out[y0:y1, x0:x1], M, (x1 - x0, y1 - y0),
                                                           borderMode=cv2.BORDER_REPLICATE)
            proc.stdin.write(out.tobytes())  # type: ignore[union-attr]
            last_out = out
            src_of_out.append(src_rel)
            out_i += 1
    finally:
        if proc is not None:
            proc.stdin.close()  # type: ignore[union-attr]
            proc.wait()
    duration = out_i / fps
    events = [e for op in ops for e in op.gt() if e["end_s"] <= duration]
    for e in events:
        e["start_s"] = round(max(0.0, e["start_s"]), 4)
        e["end_s"] = round(min(duration, e["end_s"]), 4)
    ignore = []
    for a, b, reason in ignore_source or []:
        outs = [k / fps for k, sr in enumerate(src_of_out) if a <= sr <= b]
        if outs:
            ignore.append({"start_s": round(max(0.0, min(outs) - 0.1), 4),
                           "end_s": round(min(duration, max(outs) + 0.1), 4), "reason": reason})
    return {"duration_s": round(duration, 4), "events": events, "frames": out_i, "ignore": ignore}


def write_ground_truth(path: str | Path, video_id: str, video_file: str, gt: dict,
                       reviewed: list[str], source: str, annotator: str = "injection script") -> None:
    data = {
        "video_id": video_id,
        "video_file": video_file,
        "duration_s": gt["duration_s"],
        "reviewed_categories": reviewed,
        "annotator": annotator,
        "source": source,
        "synthetic": True,
        "events": gt["events"],
        "ignore": gt.get("ignore", []),
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
