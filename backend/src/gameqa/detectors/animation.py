"""Animation-glitch detector (FR-3 d): flicker, jitter, unnatural transitions.

Definitions of a positive (all after cancelling camera motion)
--------------------------------------------------------------
* ``flicker`` — a screen region's brightness alternates up/down on consecutive frames:
  at least ``flicker_min_alternations`` sign changes of magnitude ≥ ``flicker_amp`` grey
  levels within the last ``window`` frames. One-off flashes (muzzle flash, lightning) do
  not alternate.
* ``jitter`` — motion that reverses direction frame after frame: either the camera
  (global translation) or a region's residual Farneback optical flow alternates in
  direction with magnitude ≥ ``jitter_px`` for ≥ ``jitter_min_alternations`` of the last
  ``window`` frames. Normal movement keeps its direction for many frames.
* ``unnatural_transition`` — a one-frame discontinuity: the image change (after
  alignment) spikes far above its recent level and returns to normal on the next frame
  (camera teleport / snap). ``missing_keyframe`` cannot be told apart from this in video
  and is reported under the same subtype.

Runs at full frame rate on 320×180: flicker and jitter alternate every frame and would
be aliased away at 12 FPS.

Cannot do: tell intended effects (screen shake, strobe lights, hit-flash, scripted camera
cuts, edited video cuts) from defects; detect a single character's pose snapping unless it
changes a large enough screen region; work during very fast camera motion when alignment
fails.
"""

from __future__ import annotations

from collections import deque

import cv2
import numpy as np
from pydantic import Field

from gameqa.core.detector import Detector, DetectorParams, FrameRate, register_detector
from gameqa.core.events import Event, EventAccumulator, PersistenceRule
from gameqa.core.schemas import BoundingBox, DefectCategory, Detection, Frame, VideoInfo
from gameqa.detectors.common import clamp01


class AnimationParams(DetectorParams):
    width: int = 320
    height: int = 180
    grid_cols: int = 16
    grid_rows: int = 9
    window: int = 8
    flicker_amp: float = Field(
        default=20.0, description="per-frame change of a cell's mean brightness. Shifting texture back and forth "
        "(jitter) changes the mean by <= ~10; a brightness flicker changes it by the full swing")
    flicker_min_alternations: int = 4
    jitter_px: float = Field(
        default=1.5, description="residual / global motion per frame, px at 320x180 (optical-flow noise on "
        "flat surfaces measured ~0.5 px)")
    jitter_min_alternations: int = 5
    min_region_cells: int = 2
    spike_k: float = Field(default=5.0, description="change must exceed k x recent median")
    spike_min: float = Field(default=12.0, description="absolute floor (mean abs grey difference after alignment)")
    spike_history_s: float = 0.5
    spike_neighbour_ratio: float = Field(
        default=3.0, description="spike must be >= ratio x the change of BOTH neighbouring frames: a teleport is "
        "an isolated jump, a fast camera flick ramps up and down (real footage: 9 -> 47 -> 22)")
    min_event_frames: int = 3
    max_gap_s: float = 0.25
    exclude_regions: list[tuple[float, float, float, float]] = Field(default_factory=list)


@register_detector
class AnimationGlitchDetector(Detector):
    name = "animation_glitch"
    version = "1.0"
    category = DefectCategory.ANIMATION_GLITCH
    frame_rate = FrameRate.FULL
    params_model = AnimationParams

    def start(self, video: VideoInfo) -> None:
        super().start(video)
        p = self.params
        self._prev = None
        self._prev_t = 0.0
        self._prev_idx = 0
        self._dlum: deque[np.ndarray] = deque(maxlen=p.window)  # signed per-cell brightness change
        self._flow: deque[np.ndarray] = deque(maxlen=p.window)  # per-cell residual flow (rows, cols, 2)
        self._glob: deque[np.ndarray] = deque(maxlen=p.window)  # global translation per frame
        self._resid: deque[tuple[float, float]] = deque()  # (t, residual change) history
        self._spike_cand: tuple | None = None
        rule = PersistenceRule(min_frames=p.min_event_frames, max_gap_s=p.max_gap_s)
        self._acc = {"flicker": EventAccumulator(rule), "jitter": EventAccumulator(rule)}
        self._events: list[tuple[str, Event]] = []
        self._spikes: list[Detection] = []
        self._excl = self._exclusion_mask()
        self._frames = self._unaligned = 0

    def _exclusion_mask(self) -> np.ndarray:
        p = self.params
        m = np.zeros((p.grid_rows, p.grid_cols), bool)
        for (x, y, w, h) in p.exclude_regions:
            c0, c1 = int(x * p.grid_cols), int(np.ceil((x + w) * p.grid_cols))
            r0, r1 = int(y * p.grid_rows), int(np.ceil((y + h) * p.grid_rows))
            m[r0:r1, c0:c1] = True
        return m

    def _cell_mean(self, img: np.ndarray, valid: np.ndarray) -> np.ndarray:
        p = self.params
        ch, cw = p.height // p.grid_rows, p.width // p.grid_cols
        a = img[: ch * p.grid_rows, : cw * p.grid_cols].reshape(p.grid_rows, ch, p.grid_cols, cw, *img.shape[2:])
        v = valid[: ch * p.grid_rows, : cw * p.grid_cols].reshape(p.grid_rows, ch, p.grid_cols, cw)
        if img.ndim == 3:
            v = v[..., None]
        num = (a * v).sum(axis=(1, 3))
        den = np.maximum(v.sum(axis=(1, 3)), 1)
        return num / den

    @staticmethod
    def _alternations(series: np.ndarray, min_mag: float) -> np.ndarray:
        """series: (T, ...) signed scalars; count sign flips between consecutive entries
        where both have magnitude >= min_mag."""
        a, b = series[1:], series[:-1]
        return ((np.sign(a) != np.sign(b)) & (np.abs(a) >= min_mag) & (np.abs(b) >= min_mag)).sum(axis=0)

    @staticmethod
    def _vec_alternations(series: np.ndarray, min_mag: float) -> np.ndarray:
        """series: (T, ..., 2) vectors; count consecutive pairs pointing in opposite directions."""
        a, b = series[1:], series[:-1]
        dot = (a * b).sum(axis=-1)
        mag_a, mag_b = np.linalg.norm(a, axis=-1), np.linalg.norm(b, axis=-1)
        return ((dot < -0.5 * mag_a * mag_b) & (mag_a >= min_mag) & (mag_b >= min_mag)).sum(axis=0)

    def _region_box(self, mask: np.ndarray) -> BoundingBox | None:
        p = self.params
        if mask.sum() < p.min_region_cells:
            return None
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        if n <= 1:
            return None
        k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, w, h, area = stats[k]
        if area < p.min_region_cells:
            return None
        return BoundingBox(x=x / p.grid_cols, y=y / p.grid_rows, w=w / p.grid_cols, h=h / p.grid_rows)

    def process(self, frame: Frame) -> None:
        p = self.params
        src = frame.raw if frame.raw is not None else frame.image
        g = cv2.cvtColor(cv2.resize(src, (p.width, p.height), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        self._frames += 1
        if self._prev is None:
            self._prev, self._prev_t, self._prev_idx = g, frame.timestamp_s, frame.index
            return
        t, idx = frame.timestamp_s, frame.index
        # Dense flow on the raw pair; camera motion = median flow vector. The median follows
        # the dominant (background) motion and does not switch between competing motions
        # (moving world vs screen-fixed weapon/HUD), which a single phase-correlation /
        # feature estimate did on first-person footage (Phase 5 tuning set: 14 FPs).
        flow = cv2.calcOpticalFlowFarneback(self._prev, g, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        # median over *textured* pixels: on flat surfaces dense flow is ~0 whatever the camera
        # does (aperture problem), which made the plain median 0 on flat-shaded games
        gmag = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
        tex = gmag > max(20.0, float(np.percentile(gmag, 75)))
        if tex.sum() < 200:
            tex = np.ones_like(tex)
        gx, gy = float(np.median(flow[..., 0][tex])), float(np.median(flow[..., 1][tex]))
        m = np.float32([[1, 0, gx], [0, 1, gy]])  # move prev content by the camera motion
        h, w = g.shape
        warped = cv2.warpAffine(self._prev, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        valid = cv2.warpAffine(np.full((h, w), 255, np.uint8), m, (w, h), flags=cv2.INTER_NEAREST) > 0
        valid = cv2.erode(valid.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        cur_f, prev_f = g.astype(np.float32), warped.astype(np.float32)
        resid = float(np.abs(cur_f - prev_f)[valid].mean()) if valid.any() else 255.0
        dl = self._cell_mean(cur_f - prev_f, valid)
        dl[self._excl] = 0
        self._dlum.append(dl)
        rflow = flow - np.array([gx, gy], np.float32)
        cf = self._cell_mean(rflow, valid)
        cf[self._excl] = 0
        self._flow.append(cf)
        self._glob.append(np.array([gx, gy], np.float32))
        flicker_box = jitter_box = None
        jit_score = flick_score = 0.0
        if len(self._dlum) >= 3:
            alt = self._alternations(np.stack(self._dlum), p.flicker_amp)
            # flicker has priority: brightness flips also fool optical flow into reporting
            # back-and-forth motion, so jitter is only reported where there is no flicker
            flick = alt >= p.flicker_min_alternations
            flicker_box = self._region_box(flick)
            flick_score = float(alt.max()) / (p.window - 1)
            alt_j = self._vec_alternations(np.stack(self._flow), p.jitter_px)
            jit = alt_j >= p.jitter_min_alternations
            jitter_box = self._region_box(jit & ~flick)  # brightness flicker also disturbs flow
            jit_score = float(alt_j.max()) / (p.window - 1)
            galt = int(self._vec_alternations(np.stack(self._glob), p.jitter_px))
            if galt >= p.jitter_min_alternations:
                jitter_box = BoundingBox(x=0, y=0, w=1, h=1)
                jit_score = galt / (p.window - 1)
        self._feed(frame, flicker_box, jitter_box, flick_score, jit_score)
        self._spike_step(t, idx, resid, None)
        self._prev, self._prev_t, self._prev_idx = g, t, idx

    def _feed(self, frame: Frame, flicker_box, jitter_box, flick_score=0.0, jit_score=0.0) -> None:
        for name, box, score in (("flicker", flicker_box, flick_score), ("jitter", jitter_box, jit_score)):
            for ev in self._acc[name].update(frame.index, frame.timestamp_s, box is not None, score=score,
                                             bbox=box):
                self._events.append((name, ev))

    def _spike_step(self, t: float, idx: int, resid: float, al) -> None:
        """One-frame discontinuity: residual change at frame k far above the recent level
        and back to normal at k+1 (decided one frame late)."""
        p = self.params
        cand = self._spike_cand
        self._spike_cand = None
        hist = [r for (tt, r) in self._resid if t - tt <= p.spike_history_s]
        base = float(np.median(hist)) if hist else 0.0
        if cand is not None:
            ct, cidx, cr, cprev_t, cprev_idx, cbase, cbefore = cand
            if resid * p.spike_neighbour_ratio <= cr and cbefore * p.spike_neighbour_ratio <= cr:
                self._spikes.append(Detection(
                    category=self.category, subtype="unnatural_transition", detector=self.name,
                    detector_version=self.version, start_time_s=cprev_t, end_time_s=ct, peak_time_s=ct,
                    start_frame=cprev_idx, end_frame=cidx, peak_frame=cidx,
                    confidence=round(clamp01(0.4 + 0.6 * min(1.0, cr / (p.spike_k * max(cbase, 1.0) * 3))), 3),
                    affected_area_ratio=1.0,
                    description="One-frame discontinuity: the image jumped and motion continued normally",
                    metrics={"change": round(cr, 2), "recent_median_change": round(cbase, 2)},
                ))
        before = self._resid[-1][1] if self._resid else 0.0
        if resid >= max(p.spike_min, p.spike_k * base) and len(hist) >= 3:
            self._spike_cand = (t, idx, resid, self._prev_t, self._prev_idx, base, before)
        self._resid.append((t, min(resid, 255.0)))
        while self._resid and t - self._resid[0][0] > p.spike_history_s:
            self._resid.popleft()

    def finish(self) -> list[Detection]:
        out = list(self._spikes)
        for name, acc in self._acc.items():
            for ev in acc.flush():
                self._events.append((name, ev))
        for name, ev in self._events:
            out.append(Detection(
                category=self.category, subtype=name, detector=self.name, detector_version=self.version,
                start_time_s=ev.start_time_s, end_time_s=ev.end_time_s, peak_time_s=ev.peak_time_s,
                start_frame=ev.start_frame, end_frame=ev.end_frame, peak_frame=ev.peak_frame,
                confidence=round(clamp01(0.3 + 0.7 * ev.peak_score), 3), bbox=ev.peak_bbox,
                description=("Region brightness alternates frame to frame" if name == "flicker"
                             else "Motion reverses direction frame to frame"),
                metrics={"duration_s": round(ev.duration_s, 3), "frames": ev.n_active,
                         "alternation_score": round(ev.peak_score, 3)},
            ))
        # jitter reported at the border of a flicker is the same defect (flow is fooled by
        # the brightness flips): keep the flicker only
        flickers = [d for d in out if d.subtype == "flicker"]
        out = [d for d in out if not (d.subtype == "jitter" and any(
            f.start_time_s - 0.25 <= d.end_time_s and d.start_time_s <= f.end_time_s + 0.25
            and _boxes_touch(f.bbox, d.bbox) for f in flickers))]
        self.summary = {"frames": self._frames}
        self._events, self._spikes = [], []
        return sorted(out, key=lambda d: d.start_time_s)


def _boxes_touch(a: BoundingBox | None, b: BoundingBox | None, margin: float = 0.07) -> bool:
    if a is None or b is None:
        return True
    return (a.x - margin <= b.x + b.w and b.x - margin <= a.x + a.w
            and a.y - margin <= b.y + b.h and b.y - margin <= a.y + a.h)
