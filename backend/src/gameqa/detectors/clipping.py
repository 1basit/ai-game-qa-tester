"""Collision / geometry clipping detector (FR-3 e).

Why not "bounding-box overlap with static geometry" as written in the SRS
------------------------------------------------------------------------
COCO-trained YOLO has no classes for walls, floors or terrain, so there is no geometry
box to overlap with; and in a single 2-D view a box overlap looks the same whether an
object is *behind* a wall (correct occlusion) or *inside* it (clipping). Two things that
ARE observable are implemented instead:

1. ``character_geometry`` — **first-person viewmodel clipping** (weapon / hands passing
   into walls). The viewmodel is drawn at a fixed screen position while the world moves,
   so its pixels can be learned without any engine data: pixels whose value stays the
   same on frames where the rest of the image moves. The weapon's *tip* (the viewmodel
   part farthest from where it touches the screen edge) reaches walls first. Positive:
   the tip stops matching its learned appearance while the body of the viewmodel still
   matches (so it is not a weapon switch, reload or cut), for ≥ ``min_s``.
2. ``character_character`` — two tracked people (YOLO ``person``) overlapping with
   IoU ≥ ``person_iou`` for ≥ ``person_min_s``. 2-D overlap also happens when one stands
   behind the other; this is reported at low confidence and was not validated (no
   footage with characters was available).

Not detectable: third-person characters or objects inside static geometry (no geometry
model, no depth), clipping that is not visible on screen.
"""

from __future__ import annotations

import cv2
import numpy as np
from pydantic import Field

from gameqa.core.detector import Detector, DetectorParams, FrameRate, register_detector
from gameqa.core.events import EventAccumulator, PersistenceRule
from gameqa.core.schemas import BoundingBox, DefectCategory, Detection, Frame, VideoInfo
from gameqa.detectors import models as M
from gameqa.detectors.common import clamp01


class ClippingParams(DetectorParams):
    viewmodel_clipping: bool = Field(
        default=False, description="EXPERIMENTAL, off by default: failed validation (held-out real footage: "
        "frame-level precision 0.43 vs 0.39 for always-on; spurious detections on a clean synthetic sequence)")
    width: int = 480  # 320x180 made the weapon's front-sight post ~3 px wide
    height: int = 270
    match_tol: float = Field(default=18.0, description="grey levels: pixel matches its learned viewmodel value")
    sway_px: int = Field(default=2, description="a learned pixel is visible if any pixel within +-sway_px matches "
                         "(idle weapon sway moves thin parts by 1-2 px)")
    texture_grad: float = Field(default=12.0, description="gradient magnitude for a pixel to count as textured")
    learn_rate: float = 0.15
    memory_decay: float = Field(default=0.97, description="per moving frame (~3 s memory)")
    stable_ratio_min: float = Field(default=0.6, description="textured pixel matched on >= this share of moving frames")
    min_seen: float = 6.0
    min_camera_px: float = Field(default=1.5, description="camera shift needed for a frame to teach the model")
    min_learn_frames: int = 8
    far_min: float = Field(default=0.7, description="occlusion must lie in the far part of the viewmodel "
                           "(>= this fraction of its extent from the screen-edge anchor): the tip reaches walls first")
    min_occluded_px: int = Field(default=12, description="contiguous learned viewmodel pixels hidden (480x270)")
    body_visible_min: float = Field(default=0.85, description="near part of the viewmodel must still be visible")
    lost_body_vis: float = 0.4
    lost_frames: int = 6
    min_viewmodel_px: int = 600
    min_s: float = 0.15
    max_gap_s: float = 0.2
    cut_change: float = Field(default=0.75, description="share of all pixels changing at once = cut / scene change "
                              "(fast pans reached 0.58 in the test footage)")
    use_people: bool = True
    person_iou: float = 0.5
    person_min_s: float = 1.0
    person_min_height: float = 0.15


@register_detector
class ClippingDetector(Detector):
    name = "collision_clipping"
    version = "1.2"
    category = DefectCategory.COLLISION_CLIPPING
    frame_rate = FrameRate.SAMPLED
    params_model = ClippingParams

    def start(self, video: VideoInfo) -> None:
        super().start(video)
        self._reset_model()
        self._lost = 0
        rule = PersistenceRule(min_frames=2, min_duration_s=self.params.min_s, max_gap_s=self.params.max_gap_s)
        self._acc = EventAccumulator(rule)
        self._pacc = EventAccumulator(PersistenceRule(min_frames=3, min_duration_s=self.params.person_min_s,
                                                      max_gap_s=0.35))
        self._events, self._pevents = [], []
        self._prev: np.ndarray | None = None
        self._stats = {"frames": 0, "moving_frames": 0, "cuts": 0, "frames_with_viewmodel": 0}

    def _reset_model(self) -> None:
        p = self.params
        self._ref = np.zeros((p.height, p.width), np.float32)
        self._match = np.zeros((p.height, p.width), np.float32)  # decayed matches (textured, moving frames)
        self._seen_px = np.zeros((p.height, p.width), np.float32)  # decayed observations
        self._seen = 0

    # ------------------------------------------------------------------ viewmodel model
    def _viewmodel(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """(viewmodel mask, distance-from-anchor map normalised to the viewmodel's extent)."""
        p = self.params
        if self._seen < p.min_learn_frames:
            return None, None
        ratio = np.where(self._seen_px >= p.min_seen, self._match / np.maximum(self._seen_px, 1e-6), 0)
        stable = (ratio >= p.stable_ratio_min).astype(np.uint8)
        # textured stable pixels are the viewmodel's edges/details: close them into a body
        # only informative (textured) viewmodel pixels give evidence, so the evidence is
        # sparse: join it into a body and fill enclosed holes
        vm = cv2.morphologyEx(stable, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        filled = vm.copy()
        ff = np.zeros((p.height + 2, p.width + 2), np.uint8)
        cv2.floodFill(filled, ff, (0, 0), 1)
        vm = vm | (1 - filled)
        vm = cv2.morphologyEx(vm, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        # the viewmodel = the largest stable component touching the bottom/side screen edge
        # (smaller static components are HUD text such as health/ammo counters)
        vm[-4:, :] = 0  # bottom HUD strip
        full_vm = vm
        # thin static lines (window borders, status bars) would join the weapon and move its
        # "far end" to the screen corners: select the body on an opened mask, then re-attach
        # thin parts that touch the body (e.g. the front-sight post)
        vm = cv2.morphologyEx(vm, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(vm, connectivity=8)
        best, best_area = 0, 0
        for k in range(1, n):
            x, y, w, h, area = stats[k]
            # a first-person viewmodel hangs from the BOTTOM of the view and does not reach
            # the top (side-touching static bands were the Unity Editor toolbar in the test video)
            touches = y + h >= p.height - 6 and y > 0.25 * p.height
            if touches and area > best_area:
                best, best_area = k, area
        if best_area < p.min_viewmodel_px:
            return None, None
        body = (lab == best).astype(np.uint8)
        keep = (cv2.dilate(body, np.ones((9, 9), np.uint8)) & full_vm).astype(bool) | body.astype(bool)
        ys, xs = np.nonzero(body)
        edge = ys >= p.height - 8
        anchor = np.array([xs[edge].mean(), ys[edge].mean()]) if edge.any() else np.array([xs.mean(), p.height])
        yy, xx = np.mgrid[0:p.height, 0:p.width]
        dist = np.hypot(xx - anchor[0], yy - anchor[1])
        dnorm = dist / max(float(dist[keep].max()), 1.0)
        return keep, dnorm

    def process(self, frame: Frame) -> None:
        p = self.params
        self._stats["frames"] += 1
        g = cv2.cvtColor(cv2.resize(frame.image, (p.width, p.height), interpolation=cv2.INTER_AREA),
                         cv2.COLOR_BGR2GRAY)
        g = cv2.GaussianBlur(g, (3, 3), 0).astype(np.float32)
        t, idx = frame.timestamp_s, frame.index
        if self.params.use_people:
            self._people(frame)
        if self._prev is None:
            self._prev = g
            self._ref = g.copy()
            return
        changed = np.abs(g - self._prev) > p.match_tol
        prev, self._prev = self._prev, g
        gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
        textured = cv2.magnitude(gx, gy) > p.texture_grad
        if changed.mean() >= p.cut_change:  # cut / scene change: the viewmodel may change too
            self._stats["cuts"] += 1
            self._reset_model()
            self._ref = g.copy()
            self._feed(idx, t, False, 0.0, None)
            return
        if not p.viewmodel_clipping:
            return
        vm, dnorm = self._viewmodel()
        diff = np.abs(g - self._ref)
        matches = diff <= p.match_tol  # exact position (used for learning)
        active, score, box = False, 0.0, None
        if vm is not None:
            self._stats["frames_with_viewmodel"] += 1
            # sway-tolerant visibility: a learned pixel is visible if a nearby pixel matches it
            best = diff.copy()
            for dy in range(-p.sway_px, p.sway_px + 1):
                for dx in range(-p.sway_px, p.sway_px + 1):
                    if dx or dy:
                        best = np.minimum(best, np.abs(np.roll(g, (dy, dx), axis=(0, 1)) - self._ref))
            visible = best <= p.match_tol
            # interior only: edge pixels mix weapon and moving background after resize/blur
            interior = cv2.erode(vm.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
            learned = interior & (self._seen_px >= p.min_seen) & \
                (self._match / np.maximum(self._seen_px, 1e-6) >= p.stable_ratio_min)
            near = learned & (dnorm < p.far_min - 0.1)
            far = learned & (dnorm >= p.far_min)
            body_vis = float(visible[near].mean()) if near.sum() >= 40 else 0.0
            if near.sum() >= 40 and body_vis < p.lost_body_vis:
                self._lost += 1
                if self._lost >= p.lost_frames:  # viewmodel replaced (cut, weapon switch): relearn
                    self._stats["relearned"] = self._stats.get("relearned", 0) + 1
                    self._reset_model()
                    self._ref = g.copy()
                    self._lost = 0
                    self._feed(idx, t, False, 0.0, None)
                    return
            else:
                self._lost = 0
            hidden = (far & ~visible).astype(np.uint8)
            if body_vis >= p.body_visible_min and hidden.any():
                hidden = cv2.dilate(hidden, np.ones((3, 3), np.uint8)) & far.astype(np.uint8)
                n, lab, stats, _ = cv2.connectedComponentsWithStats(hidden, connectivity=8)
                if n > 1:
                    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
                    x, y, w, h, area = stats[k]
                    if area >= p.min_occluded_px:
                        active = True
                        frac = area / max(1, int(far.sum()))
                        score = clamp01(0.5 * body_vis + 0.5 * min(1.0, frac * 4))
                        box = BoundingBox.from_pixels(x, y, x + w, y + h, p.width, p.height)
        self._feed(idx, t, active, score, box)
        # Learning. Each textured pixel is tested against two explanations of the new frame:
        # "it stayed still" (|g - prev|) and "it moved with the camera" (|g - prev shifted by
        # the camera motion|). Viewmodel evidence = still fits, camera motion does not. Pixels
        # where both fit (smooth texture moving slowly) carry no information — counting them
        # as "static" taught the model the background (45k px) in the unit test.
        shift = self._camera_shift(prev, g, textured)
        if shift is not None and np.hypot(*shift) >= p.min_camera_px:
            m = np.float32([[1, 0, shift[0]], [0, 1, shift[1]]])
            moved = cv2.warpAffine(prev, m, (p.width, p.height), borderMode=cv2.BORDER_REPLICATE)
            ds, dm = np.abs(g - prev), np.abs(g - moved)
            informative = textured & ((ds > p.match_tol) | (dm > p.match_tol))
            static_win = informative & (ds <= p.match_tol) & (dm > p.match_tol)
            self._stats["moving_frames"] += 1
            self._seen += 1
            self._match = self._match * p.memory_decay + static_win
            self._seen_px = self._seen_px * p.memory_decay + informative
            lr = p.learn_rate
            self._ref = np.where(static_win, (1 - lr) * self._ref + lr * g, self._ref)
            fresh = static_win & (self._seen_px < p.min_seen)
            self._ref = np.where(fresh, g, self._ref)

    def _camera_shift(self, prev: np.ndarray, cur: np.ndarray, textured: np.ndarray):
        """Camera translation (px at analysis resolution) = median dense flow over textured
        pixels, computed at half resolution."""
        a = cv2.resize(prev, (self.params.width // 2, self.params.height // 2)).astype(np.uint8)
        b = cv2.resize(cur, (self.params.width // 2, self.params.height // 2)).astype(np.uint8)
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        tex = cv2.resize(textured.astype(np.uint8), (a.shape[1], a.shape[0])) > 0
        if tex.sum() < 100:
            return None
        return 2 * float(np.median(flow[..., 0][tex])), 2 * float(np.median(flow[..., 1][tex]))

    def _feed(self, idx, t, active, score, box) -> None:
        self._events += self._acc.update(idx, t, active, score=score, bbox=box)

    # ------------------------------------------------------------------ people overlap
    def _people(self, frame: Frame) -> None:
        p = self.params
        people = [d for d in M.detect_objects(frame) if d.name == "person" and d.conf >= 0.4
                  and d.box.h >= p.person_min_height and d.box.y + d.box.h < 0.97]  # not the viewmodel
        best, pair = 0.0, None
        for i in range(len(people)):
            for j in range(i + 1, len(people)):
                iou = _iou(people[i].box, people[j].box)
                if iou > best:
                    best, pair = iou, (people[i].box, people[j].box)
        active = best >= p.person_iou
        box = _union(*pair) if (active and pair) else None
        self._pevents += self._pacc.update(frame.index, frame.timestamp_s, active, score=best, bbox=box)

    def finish(self) -> list[Detection]:
        self._events += self._acc.flush()
        self._pevents += self._pacc.flush()
        out = [Detection(
            category=self.category, subtype="character_geometry", detector=self.name, detector_version=self.version,
            start_time_s=ev.start_time_s, end_time_s=ev.end_time_s, peak_time_s=ev.peak_time_s,
            start_frame=ev.start_frame, end_frame=ev.end_frame, peak_frame=ev.peak_frame,
            confidence=round(clamp01(0.3 + 0.6 * ev.mean_score), 3), bbox=ev.peak_bbox,
            description="First-person weapon/hands passing into geometry: the far end of the viewmodel is "
                        "hidden while the rest of it is visible",
            metrics={"duration_s": round(ev.duration_s, 2), "frames": ev.n_active}) for ev in self._events]
        out += [Detection(
            category=self.category, subtype="character_character", detector=self.name, detector_version=self.version,
            start_time_s=ev.start_time_s, end_time_s=ev.end_time_s, peak_time_s=ev.peak_time_s,
            start_frame=ev.start_frame, end_frame=ev.end_frame, peak_frame=ev.peak_frame,
            confidence=round(clamp01(0.2 + 0.4 * ev.mean_score), 3), bbox=ev.peak_bbox,
            description="Two characters overlap on screen for a sustained time (possible interpenetration; "
                        "could also be one standing behind the other)",
            metrics={"max_iou": round(ev.peak_score, 3), "duration_s": round(ev.duration_s, 2)}) for ev in self._pevents]
        self.summary = dict(self._stats)
        self._events, self._pevents = [], []
        return sorted(out, key=lambda d: d.start_time_s)


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def _union(a: BoundingBox, b: BoundingBox) -> BoundingBox:
    x0, y0 = min(a.x, b.x), min(a.y, b.y)
    x1, y1 = max(a.x + a.w, b.x + b.w), max(a.y + a.h, b.y + b.h)
    return BoundingBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0)
