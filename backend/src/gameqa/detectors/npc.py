"""NPC anomaly detector (FR-3 a): YOLOv8 person detection + MediaPipe pose.

Definitions of a positive (per tracked character)
------------------------------------------------
* ``t_pose`` — both arms straight (elbow angle ≥ 150°), raised ~90° from the torso
  (70–110°), wrist-to-wrist span ≥ 2.2 × shoulder width, held ≥ ``t_pose_min_s``.
  The engine's default bind pose shown when animation fails.
* ``frozen_npc`` — the body pose is frozen (keypoints in box-relative coordinates barely
  change) while the character moves through the world (box displacement after removing
  camera motion ≥ ``slide_min_heights`` box heights) over ``frozen_window_s``: a
  character sliding without its walk animation. A character standing still with a frozen
  pose is NOT reported — idle NPCs look exactly like that.
* ``ragdoll`` — limbs teleport: mean visible-keypoint displacement in box-relative
  coordinates ≥ ``ragdoll_jump`` box heights per analysed frame for ≥ ``ragdoll_min_s``.
  A heuristic for broken ragdoll physics (flailing / exploding limbs), not a physics check.
* ``floating`` — NOT implemented: a single 2-D view has no ground plane or depth, so
  whether feet touch the ground cannot be established from pixels; any rule would be a
  guess. (Possible future work: shadow-contact heuristics for games with shadows.)

Domain limits: YOLO (COCO) and MediaPipe were trained on real people; stylised,
non-human, small (< ``min_height`` of the frame) or heavily occluded characters are
missed. MediaPipe is single-person, so it runs on each YOLO crop; overlapping
characters can confuse it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np
from pydantic import Field

from gameqa.core.detector import Detector, DetectorParams, FrameRate, register_detector
from gameqa.core.events import Event, EventAccumulator, PersistenceRule
from gameqa.core.schemas import BoundingBox, DefectCategory, Detection, Frame, VideoInfo
from gameqa.detectors import models as M
from gameqa.detectors.common import clamp01


class NpcParams(DetectorParams):
    person_conf: float = 0.4
    min_height: float = Field(default=0.12, description="ignore characters smaller than this (frame heights)")
    max_people: int = 6
    track_iou: float = 0.3
    track_max_gap_s: float = 0.5
    vis_min: float = 0.5
    t_pose_min_s: float = 1.0
    t_pose_abduction: tuple[float, float] = (70.0, 110.0)
    t_pose_elbow_min: float = 150.0
    t_pose_span_ratio: float = 2.2
    frozen_window_s: float = 2.0
    frozen_pose_std: float = Field(default=0.012, description="box-relative keypoint std over the window")
    slide_min_heights: float = 0.5
    ragdoll_jump: float = 0.35
    ragdoll_min_s: float = 0.25
    viewmodel_bottom: float = Field(default=0.97, description="box bottom >= this touches the screen edge")
    viewmodel_min_obs: int = 4


def _angle(a, b, c) -> float:
    """Angle ABC in degrees."""
    v1, v2 = a - b, c - b
    n = np.linalg.norm(v1) * np.linalg.norm(v2)
    return float(np.degrees(np.arccos(np.clip(np.dot(v1, v2) / n, -1, 1)))) if n > 0 else 0.0


def t_pose_score(pose: M.Pose, p: NpcParams) -> float:
    """0 if not a T-pose, else a score in (0, 1]. Coordinates are frame-normalised."""
    need = [M.L_SH, M.R_SH, M.L_EL, M.R_EL, M.L_WR, M.R_WR]
    if (pose.vis[need] < p.vis_min).any():
        return 0.0
    xy = pose.xy.copy()
    mid_sh = (xy[M.L_SH] + xy[M.R_SH]) / 2
    if (pose.vis[[M.L_HIP, M.R_HIP]] >= p.vis_min).all():
        down = (xy[M.L_HIP] + xy[M.R_HIP]) / 2 - mid_sh
    else:
        down = np.array([0.0, 1.0], np.float32)
    down = down / (np.linalg.norm(down) + 1e-9)
    sw = np.linalg.norm(xy[M.L_SH] - xy[M.R_SH])
    if sw <= 0:
        return 0.0
    scores = []
    for sh, el, wr in ((M.L_SH, M.L_EL, M.L_WR), (M.R_SH, M.R_EL, M.R_WR)):
        abd = _angle(xy[sh] + down, xy[sh], xy[el])
        elbow = _angle(xy[sh], xy[el], xy[wr])
        lo, hi = p.t_pose_abduction
        if not (lo <= abd <= hi) or elbow < p.t_pose_elbow_min:
            return 0.0
        scores.append(1 - abs(abd - 90) / 45 * 0.5 - (180 - elbow) / 180)
    span = np.linalg.norm(xy[M.L_WR] - xy[M.R_WR]) / sw
    if span < p.t_pose_span_ratio:
        return 0.0
    return clamp01(float(np.mean(scores)))


def is_viewmodel(boxes: list[BoundingBox], cam_motion: float, p: NpcParams) -> bool:
    """First-person hands/weapon: box touches the bottom edge of the screen in most
    observations and stays fixed on screen while the camera moves. (Real footage: all 48
    YOLO 'person' hits in the test video were the player's gloved hand.)"""
    if len(boxes) < p.viewmodel_min_obs:
        return False
    bottom = np.mean([b.y + b.h >= p.viewmodel_bottom for b in boxes])
    centres = np.array([[b.x + b.w / 2, b.y + b.h / 2] for b in boxes])
    screen_static = float(centres.std(axis=0).max()) < 0.06
    return bottom >= 0.8 and (screen_static or cam_motion > 0.05)


@dataclass
class _Track:
    tid: int
    box: BoundingBox
    last_t: float
    hist: deque = field(default_factory=lambda: deque(maxlen=64))  # (t, idx, box, rel_kp, vis, cam_xy)
    acc: dict = field(default_factory=dict)


@register_detector
class NpcAnomalyDetector(Detector):
    name = "npc_anomaly"
    version = "1.0"
    category = DefectCategory.NPC_ANOMALY
    frame_rate = FrameRate.SAMPLED
    params_model = NpcParams

    def start(self, video: VideoInfo) -> None:
        super().start(video)
        self._tracks: list[_Track] = []
        self._next_id = 1
        self._events: list[tuple[str, int, Event]] = []
        self._cam = np.zeros(2, np.float64)  # accumulated camera translation (frame-normalised)
        self._prev_small: np.ndarray | None = None
        self._stats = {"frames": 0, "person_detections": 0, "poses": 0, "tracks": 0}
        self._viewmodel_tracks: set[int] = set()

    def _camera_step(self, frame: Frame) -> None:
        small = cv2.cvtColor(cv2.resize(frame.image, (320, 180), interpolation=cv2.INTER_AREA),
                             cv2.COLOR_BGR2GRAY).astype(np.float32)
        if self._prev_small is not None:
            (dx, dy), resp = cv2.phaseCorrelate(self._prev_small, small)
            if resp > 0.1:
                self._cam += (dx / 320, dy / 180)
        self._prev_small = small

    def process(self, frame: Frame) -> None:
        p = self.params
        self._stats["frames"] += 1
        self._camera_step(frame)
        people = [d for d in M.detect_objects(frame) if d.name == "person" and d.conf >= p.person_conf]
        people = sorted(people, key=lambda d: -d.box.area)[: p.max_people]
        self._stats["person_detections"] += len(people)
        t = frame.timestamp_s
        alive = []
        for tr in self._tracks:
            if t - tr.last_t <= p.track_max_gap_s:
                alive.append(tr)
            else:
                self._expire(tr)
        self._tracks = alive
        used: set[int] = set()
        for det in people:
            best, best_iou = None, p.track_iou
            for tr in self._tracks:
                if tr.tid in used:
                    continue
                iou = _iou(tr.box, det.box)
                if iou > best_iou:
                    best, best_iou = tr, iou
            if best is None:
                best = _Track(self._next_id, det.box, t)
                self._next_id += 1
                self._stats["tracks"] += 1
                rule = lambda s: PersistenceRule(min_frames=2, min_duration_s=s, max_gap_s=0.35)  # noqa: E731
                best.acc = {"t_pose": EventAccumulator(rule(p.t_pose_min_s)),
                            "frozen_npc": EventAccumulator(rule(0.0)),
                            "ragdoll": EventAccumulator(rule(p.ragdoll_min_s))}
                self._tracks.append(best)
            used.add(best.tid)
            best.box, best.last_t = det.box, t
            self._analyse(best, frame, det)

    def _analyse(self, tr: _Track, frame: Frame, det: M.Detected) -> None:
        p = self.params
        t, idx = frame.timestamp_s, frame.index
        box = det.box
        pose = M.estimate_pose(frame, box) if box.h >= p.min_height else None
        rel = vis = None
        if pose is not None:
            self._stats["poses"] += 1
            rel = (pose.xy - np.array([box.x, box.y])) / np.array([box.w, box.h])
            vis = pose.vis
        tr.hist.append((t, idx, box, rel, vis, self._cam.copy()))
        # T-pose
        tp = t_pose_score(pose, p) if pose is not None else 0.0
        self._feed(tr, "t_pose", idx, t, tp > 0, tp, box)
        # frozen while sliding
        fz = self._frozen_score(tr)
        self._feed(tr, "frozen_npc", idx, t, fz > 0, fz, box)
        # ragdoll
        rd = self._ragdoll_score(tr)
        self._feed(tr, "ragdoll", idx, t, rd > 0, rd, box)

    def _frozen_score(self, tr: _Track) -> float:
        p = self.params
        if not tr.hist:
            return 0.0
        t_now = tr.hist[-1][0]
        win = [h for h in tr.hist if t_now - h[0] <= p.frozen_window_s and h[3] is not None]
        if len(win) < 6 or t_now - win[0][0] < 0.8 * p.frozen_window_s:
            return 0.0
        vis = np.min(np.stack([h[4] for h in win]), axis=0) >= p.vis_min
        if vis.sum() < 8:
            return 0.0
        kp = np.stack([h[3][vis] for h in win])  # (T, K, 2)
        pose_std = float(kp.std(axis=0).mean())
        if pose_std > p.frozen_pose_std:
            return 0.0
        # world displacement of the box centre (screen displacement minus camera motion)
        c0 = np.array([win[0][2].x + win[0][2].w / 2, win[0][2].y + win[0][2].h / 2]) - win[0][5]
        c1 = np.array([win[-1][2].x + win[-1][2].w / 2, win[-1][2].y + win[-1][2].h / 2]) - win[-1][5]
        slide = float(np.linalg.norm(c1 - c0)) / max(win[-1][2].h, 1e-3)
        if slide < p.slide_min_heights:
            return 0.0
        return clamp01(0.5 + 0.5 * min(1.0, slide / (3 * p.slide_min_heights)))

    def _ragdoll_score(self, tr: _Track) -> float:
        p = self.params
        if len(tr.hist) < 2:
            return 0.0
        a, b = tr.hist[-2], tr.hist[-1]
        if a[3] is None or b[3] is None or b[0] - a[0] > 0.2:
            return 0.0
        vis = (a[4] >= p.vis_min) & (b[4] >= p.vis_min)
        if vis.sum() < 8:
            return 0.0
        rel_a = a[3][vis] - a[3][vis].mean(axis=0)  # remove whole-body translation
        rel_b = b[3][vis] - b[3][vis].mean(axis=0)
        jump = float(np.linalg.norm(rel_b - rel_a, axis=1).mean())
        return clamp01(jump / (2 * p.ragdoll_jump)) if jump >= p.ragdoll_jump else 0.0

    def _feed(self, tr: _Track, kind: str, idx: int, t: float, active: bool, score: float, box) -> None:
        for ev in tr.acc[kind].update(idx, t, active, score=score, bbox=box):
            self._events.append((kind, tr.tid, ev))

    def _expire(self, tr: _Track) -> None:
        for kind, acc in tr.acc.items():
            for ev in acc.flush():
                self._events.append((kind, tr.tid, ev))
        boxes = [h[2] for h in tr.hist]
        cams = [h[5] for h in tr.hist]
        cam_motion = float(np.linalg.norm(cams[-1] - cams[0])) if cams else 0.0
        if is_viewmodel(boxes, cam_motion, self.params):
            self._viewmodel_tracks.add(tr.tid)

    def finish(self) -> list[Detection]:
        for tr in self._tracks:
            self._expire(tr)
        self._events = [e for e in self._events if e[1] not in self._viewmodel_tracks]
        desc = {"t_pose": "Character held a T-pose (arms straight out, animation not applied)",
                "frozen_npc": "Character moved through the scene with a frozen pose (no animation)",
                "ragdoll": "Character's limbs jumped implausibly between frames (ragdoll / pose failure)"}
        out = [Detection(
            category=self.category, subtype=kind, detector=self.name, detector_version=self.version,
            start_time_s=ev.start_time_s, end_time_s=ev.end_time_s, peak_time_s=ev.peak_time_s,
            start_frame=ev.start_frame, end_frame=ev.end_frame, peak_frame=ev.peak_frame,
            confidence=round(clamp01(0.3 + 0.7 * ev.mean_score), 3), bbox=ev.peak_bbox,
            description=desc[kind], metrics={"track_id": tid, "duration_s": round(ev.duration_s, 2),
                                              "frames": ev.n_active})
            for kind, tid, ev in self._events]
        self.summary = dict(self._stats, viewmodel_tracks_ignored=len(self._viewmodel_tracks),
                            floating="not implemented (no ground plane / depth in 2-D video)")
        self._events, self._tracks = [], []
        return sorted(out, key=lambda d: d.start_time_s)


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0
