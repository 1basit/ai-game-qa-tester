"""Shared deep-learning models: YOLOv8 (Ultralytics, COCO weights) and MediaPipe Pose.

Models are loaded lazily and once per process. Results are cached on the ``Frame``
(``frame.extras``) so that the NPC and clipping detectors share one YOLO pass per frame.

Weights live in ``data/models`` (`yolov8n.pt` from Ultralytics, `pose_landmarker_full.task`
from Google). MediaPipe 1.x only provides the Tasks API (the legacy ``mp.solutions.pose``
was removed), so ``PoseLandmarker`` is used, on person crops (it is a single-person model).

Domain caveat: both models were trained on photographs of real people. They work on
realistic humanoid game characters and degrade on stylised, non-human, very small or
heavily occluded characters.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from gameqa.config import get_settings
from gameqa.core.device import select_device
from gameqa.core.schemas import BoundingBox, Frame

_lock = threading.Lock()
_yolo = None
_pose = None

# MediaPipe 33-landmark indices used by the rules
NOSE, L_SH, R_SH, L_EL, R_EL, L_WR, R_WR = 0, 11, 12, 13, 14, 15, 16
L_HIP, R_HIP, L_KN, R_KN, L_AN, R_AN = 23, 24, 25, 26, 27, 28


@dataclass
class Detected:
    cls: int
    name: str
    conf: float
    box: BoundingBox  # normalised to the frame


@dataclass
class Pose:
    xy: np.ndarray  # (33, 2) normalised to the FRAME
    vis: np.ndarray  # (33,) visibility/presence in [0, 1]


def models_dir() -> Path:
    return get_settings().paths.models_dir


def yolo():
    global _yolo
    with _lock:
        if _yolo is None:
            from ultralytics import YOLO

            path = models_dir() / "yolov8n.pt"
            _yolo = YOLO(str(path) if path.exists() else "yolov8n.pt")
        return _yolo


def pose_landmarker():
    global _pose
    with _lock:
        if _pose is None:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

            path = models_dir() / "pose_landmarker_full.task"
            if not path.exists():
                raise FileNotFoundError(f"MediaPipe pose model missing: {path} (see README, 'ML setup')")
            opts = PoseLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(path)),
                                         running_mode=RunningMode.IMAGE, num_poses=1,
                                         min_pose_detection_confidence=0.4, min_pose_presence_confidence=0.4)
            _pose = (mp, PoseLandmarker.create_from_options(opts))
            import atexit

            atexit.register(_close_pose)
        return _pose


def _close_pose() -> None:
    """Close the landmarker before interpreter shutdown (its destructor fails late in shutdown)."""
    global _pose
    if _pose is not None:
        try:
            _pose[1].close()
        except Exception:  # noqa: BLE001
            pass
        _pose = None


def detect_objects(frame: Frame, conf: float = 0.35, imgsz: int = 640) -> list[Detected]:
    """All COCO detections for the frame (cached per frame)."""
    cached = frame.extras.get("yolo")
    if cached is not None:
        return cached
    img = frame.image
    h, w = img.shape[:2]
    res = yolo().predict(img, imgsz=imgsz, conf=conf, device=_device(), verbose=False)[0]
    out: list[Detected] = []
    names = res.names
    for b, c, k in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(),
                       res.boxes.cls.cpu().numpy().astype(int)):
        out.append(Detected(int(k), names[int(k)], float(c), BoundingBox.from_pixels(*b, w, h)))
    frame.extras["yolo"] = out
    return out


def estimate_pose(frame: Frame, box: BoundingBox, pad: float = 0.15) -> Pose | None:
    """MediaPipe pose on a padded crop around ``box``; landmarks returned in frame coords."""
    mp, landmarker = pose_landmarker()
    img = frame.image
    h, w = img.shape[:2]
    x0 = max(0.0, box.x - pad * box.w)
    y0 = max(0.0, box.y - pad * box.h)
    x1 = min(1.0, box.x + box.w * (1 + pad))
    y1 = min(1.0, box.y + box.h * (1 + pad))
    X0, Y0, X1, Y1 = int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)
    if X1 - X0 < 24 or Y1 - Y0 < 48:
        return None
    crop = np.ascontiguousarray(img[Y0:Y1, X0:X1, ::-1])  # BGR -> RGB
    result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=crop))
    if not result.pose_landmarks:
        return None
    lm = result.pose_landmarks[0]
    xy = np.array([[x0 + p.x * (x1 - x0), y0 + p.y * (y1 - y0)] for p in lm], np.float32)
    vis = np.array([min(getattr(p, "visibility", 1.0) or 0.0, getattr(p, "presence", 1.0) or 1.0) for p in lm],
                   np.float32)
    return Pose(xy, vis)


_dev: str | None = None


def _device() -> str:
    global _dev
    if _dev is None:
        _dev = select_device(get_settings().device)
    return _dev
