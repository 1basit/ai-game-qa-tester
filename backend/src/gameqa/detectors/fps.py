"""FPS-drop and frozen-frame detector (FR-3 c).

What can and cannot be measured from a recording
------------------------------------------------
The game's real frame times are not in the file. What *is* in the file:

* **Variable-frame-rate recordings** (ShadowPlay, phones): a frame the game did not
  render simply is not there → longer presentation intervals.
* **Constant-frame-rate recordings** (OBS, YouTube re-encodes): the recorder repeats
  the previous picture → consecutive frames are (near) identical.

Both are reduced to one timeline of *new pictures*. A repeated picture only counts as a
missed render when the scene is visibly moving immediately before *and* after it:
an identical frame during a static menu, a paused game or a player standing still
says nothing about the render rate, so static stretches are excluded from
measurement rather than reported as drops. This rule came from the real test footage,
where 91 % of frames in the editor segment are identical and the player regularly
stops moving.

Outputs
-------
* ``frozen_frame`` — one picture held for ≥ ``freeze_min_s`` while the scene is moving
  (a stall / hitch).
* ``fps_drop`` — sliding-window effective FPS below ``drop_ratio`` × target FPS for at
  least ``min_drop_s``.
* ``summary`` — estimated rendered FPS of the moving parts of the video, the share of
  time that could be measured, and the target used.

Limits: the recording rate caps what is measurable (a 60 FPS recording cannot show a
drop from 144 to 90); motion below ``motion_mad`` cannot be measured; a game that
deliberately holds frames (cut-scene pauses, hit-stop effects) will be reported.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import Field

from gameqa.core.detector import Detector, DetectorParams, FrameRate, register_detector
from gameqa.core.events import EventAccumulator, PersistenceRule
from gameqa.core.schemas import DefectCategory, Detection, Frame, VideoInfo
from gameqa.detectors.common import clamp01, thumbnail_gray


class FpsParams(DetectorParams):
    target_fps: float | Literal["auto"] = Field(
        default="auto", description="auto: 60 if the recording is >= 50 FPS, else 30"
    )
    thumb_width: int = Field(default=160, ge=32)
    thumb_height: int = Field(default=90, ge=18)
    duplicate_mad: float = Field(
        default=0.25, gt=0,
        description="Mean abs grey difference below which two frames show the same picture. "
        "Repeated frames are not bit-identical after lossy encoding (measured 0.02-0.14 at CRF 18); "
        "calibrated 0.05 -> 0.25 on the Phase 3 tuning set",
    )
    motion_mad: float = Field(
        default=1.0, gt=0, description="Mean abs grey difference above which the scene counts as moving"
    )
    window_s: float = Field(default=1.0, gt=0)
    step_s: float = Field(default=0.25, gt=0)
    min_moving_fraction: float = Field(
        default=0.5, ge=0, le=1, description="Window is measurable only if this share of frames is moving"
    )
    drop_ratio: float = Field(default=0.75, gt=0, lt=1, description="drop if effective FPS < ratio x target")
    min_drop_s: float = Field(default=0.5, ge=0)
    freeze_min_s: float = Field(default=0.25, gt=0)
    context_frames: int = Field(
        default=3, ge=1,
        description="Changing frames on each side whose median motion must exceed motion_mad. "
        "Rejects UI-style discrete updates (one change, hold, one change)",
    )
    context_s: float = Field(default=0.25, gt=0, description="How far to look for those frames")


@register_detector
class FpsDropDetector(Detector):
    name = "fps_drop"
    version = "1.0"
    category = DefectCategory.FPS_DROP
    frame_rate = FrameRate.FULL
    params_model = FpsParams

    def start(self, video: VideoInfo) -> None:
        super().start(video)
        self._t: list[float] = []
        self._idx: list[int] = []
        self._mad: list[float] = []
        self._prev: np.ndarray | None = None

    def process(self, frame: Frame) -> None:
        p = self.params
        thumb = thumbnail_gray(frame, (p.thumb_width, p.thumb_height))
        mad = float(np.abs(thumb - self._prev).mean()) if self._prev is not None else np.nan
        self._prev = thumb
        self._t.append(frame.timestamp_s)
        self._idx.append(frame.index)
        self._mad.append(mad)

    # ------------------------------------------------------------------ analysis

    def _target(self) -> float:
        p = self.params
        if p.target_fps != "auto":
            return float(p.target_fps)
        nominal = self.video.fps_nominal if self.video else 60.0
        if nominal >= 50:
            return 60.0
        return 30.0 if nominal >= 30 else nominal

    def finish(self) -> list[Detection]:
        p = self.params
        t = np.asarray(self._t, dtype=np.float64)
        idx = np.asarray(self._idx, dtype=np.int64)
        mad = np.asarray(self._mad, dtype=np.float64)
        n = len(t)
        self._prev = None
        if n < 3:
            self.summary = {"measurable_fraction": 0.0, "note": "too few frames"}
            return []

        dt = np.diff(t)
        base_dt = float(np.median(dt)) if len(dt) else 1 / 60
        recording_fps = 1.0 / base_dt if base_dt > 0 else 0.0
        dup = mad < p.duplicate_mad  # dup[i]: frame i repeats frame i-1 (dup[0] is False: nan)

        changing = np.flatnonzero(~dup & np.isfinite(mad))  # frames showing a new picture

        def sustained(edge: int, direction: int) -> float:
            """Median motion of up to ``context_frames`` changing frames on one side of
            ``edge`` (inclusive), within ``context_s``; nan if too few."""
            pos = int(np.searchsorted(changing, edge, side="right" if direction < 0 else "left"))
            sel = changing[max(0, pos - p.context_frames):pos] if direction < 0 else changing[pos:pos + p.context_frames]
            sel = sel[np.abs(t[sel] - t[edge]) <= p.context_s]
            return float(np.median(mad[sel])) if len(sel) >= p.context_frames else np.nan

        # missed[i] = frame i is a repeated picture *during motion* (a render the game skipped)
        missed = np.zeros(n, dtype=bool)
        freezes: list[tuple[int, int, float, float]] = []  # (first held frame, last held frame, hold_s, motion)
        i = 1
        while i < n:
            if not dup[i]:
                i += 1
                continue
            a = i
            while i < n and dup[i]:
                i += 1
            b = i - 1  # frames a..b repeat the picture of frame a-1
            if a - 1 < 1 or b + 1 >= n:
                continue
            # Abrupt edges: the picture right before the hold and the one right after must
            # both be moving. A player stopping decelerates (e.g. 5.7, 3.9, 0.33, hold) and
            # fails this; a stalled renderer stops and restarts in a single frame.
            abrupt = mad[a - 1] >= p.motion_mad and mad[b + 1] >= p.motion_mad
            before, after = sustained(a - 1, -1), sustained(b + 1, +1)
            if abrupt and np.isfinite(before) and np.isfinite(after) and before >= p.motion_mad and after >= p.motion_mad:
                missed[a : b + 1] = True
                hold = t[b + 1] - t[a - 1]
                if hold >= p.freeze_min_s:
                    freezes.append((a, b, hold, float(min(before, after))))

        # VFR recordings: a long interval between two different, moving pictures is a hold too
        for k in range(2, n):
            gap = t[k] - t[k - 1]
            if gap >= p.freeze_min_s and gap > 1.5 * base_dt and not dup[k]:
                before, after = sustained(k - 1, -1), sustained(k, +1)
                abrupt = mad[k - 1] >= p.motion_mad and mad[k] >= p.motion_mad
                if abrupt and np.isfinite(before) and np.isfinite(after) and min(before, after) >= p.motion_mad:
                    freezes.append((k, k - 1, gap, float(min(before, after))))

        moving = (mad >= p.motion_mad) | missed
        new_picture = ~missed

        # Sliding windows of effective FPS (new pictures per second), moving windows only
        target = self._target()
        threshold = p.drop_ratio * target
        # Persistence (FR-3): at least two consecutive windows below threshold, i.e. the
        # shortfall is seen in two overlapping 1 s measurements, and the union of the
        # windows must last >= min_drop_s.
        acc = EventAccumulator(PersistenceRule(
            min_frames=2, min_duration_s=max(0.0, p.min_drop_s - p.window_s), max_gap_s=p.step_s * 1.01))
        raw_events = []
        eff_values = []
        measured = 0
        n_windows = 0
        w0 = t[0]
        lo = hi = 0
        while w0 + p.window_s <= t[-1] + base_dt / 2:
            w1 = w0 + p.window_s
            while lo < n and t[lo] < w0:
                lo += 1
            while hi < n and t[hi] < w1:
                hi += 1
            sl = slice(lo, hi)
            n_windows += 1
            centre = w0 + p.window_s / 2
            if hi - lo >= 2 and moving[sl].mean() >= p.min_moving_fraction:
                measured += 1
                eff = float(new_picture[sl].sum()) / p.window_s
                eff_values.append(eff)
                active = eff < threshold
                ci = min(max(lo, int(np.searchsorted(t, centre))), n - 1)
                raw_events += acc.update(
                    int(idx[ci]), centre, active, score=1.0 - eff / target,
                    data={"eff": eff, "w0": w0, "w1": w1, "lo": lo, "hi": hi - 1},
                )
            else:
                raw_events += acc.update(int(idx[min(lo, n - 1)]), centre, False)
            w0 += p.step_s
        raw_events += acc.flush()

        detections: list[Detection] = []
        freeze_spans: list[tuple[float, float]] = []
        for a, b, hold, motion in freezes:
            # CFR: frames a..b repeat frame a-1, new picture at b+1.  VFR: (k, k-1) -> k-1 .. k
            start_t, end_t = float(t[a - 1]), float(t[min(b + 1, n - 1)])
            freeze_spans.append((start_t, end_t))
            detections.append(
                Detection(
                    category=self.category, subtype="frozen_frame", detector=self.name,
                    detector_version=self.version,
                    start_time_s=start_t, end_time_s=end_t, peak_time_s=start_t,
                    start_frame=int(idx[a - 1]), end_frame=int(idx[min(b + 1, n - 1)]),
                    peak_frame=int(idx[a - 1]),
                    confidence=round(clamp01(0.5 + 0.5 * motion / (4 * p.motion_mad)), 3),
                    affected_area_ratio=1.0,
                    description=f"Picture held for {hold * 1000:.0f} ms while the scene was moving",
                    metrics={"hold_ms": round(hold * 1000, 1), "held_frames": max(1, b - a + 2),
                             "motion_mad_around": round(motion, 2)},
                )
            )

        for ev in raw_events:
            # event spans the union of its measurement windows
            start_t = max(float(t[0]), ev.start_time_s - p.window_s / 2)
            end_t = min(float(t[-1]), ev.end_time_s + p.window_s / 2)
            min_eff = float(ev.peak_data["eff"])
            # a drop that is entirely explained by a frozen frame is reported once (as the freeze)
            # (every low window contained the freeze)
            slack = p.window_s / 2 + p.step_s
            explained = any(fs - slack <= ev.start_time_s and ev.end_time_s <= fe + slack
                            for fs, fe in freeze_spans)
            if explained:
                continue
            si = int(np.searchsorted(t, start_t))
            ei = min(int(np.searchsorted(t, end_t, side="right")) - 1, n - 1)
            peak_t = float(np.clip(ev.peak_time_s, start_t, end_t))
            pi = min(int(np.searchsorted(t, peak_t)), n - 1)
            peak_t = float(np.clip(t[pi], start_t, end_t))
            detections.append(
                Detection(
                    category=self.category, subtype="fps_drop", detector=self.name,
                    detector_version=self.version,
                    start_time_s=float(t[si]), end_time_s=max(float(t[ei]), float(t[si])),
                    peak_time_s=float(np.clip(peak_t, t[si], max(t[ei], t[si]))),
                    start_frame=int(idx[si]), end_frame=int(max(idx[ei], idx[si])),
                    peak_frame=int(np.clip(idx[pi], idx[si], max(idx[ei], idx[si]))),
                    confidence=round(clamp01(0.5 + 0.5 * (1 - min_eff / threshold)), 3),
                    affected_area_ratio=1.0,
                    description=f"Effective frame rate fell to {min_eff:.0f} FPS (target {target:.0f})",
                    metrics={"min_effective_fps": round(min_eff, 1), "target_fps": target,
                             "threshold_fps": round(threshold, 1), "mean_score": round(ev.mean_score, 3)},
                )
            )

        detections.sort(key=lambda d: d.start_time_s)
        self.summary = {
            "recording_fps": round(recording_fps, 2),
            "target_fps": target,
            "estimated_render_fps_median": round(float(np.median(eff_values)), 1) if eff_values else None,
            "estimated_render_fps_p10": round(float(np.percentile(eff_values, 10)), 1) if eff_values else None,
            "measurable_fraction": round(measured / n_windows, 3) if n_windows else 0.0,
            "missed_frames": int(missed.sum()),
            "note": "FPS can only be measured while the scene is moving; static stretches are excluded",
        }
        return detections
