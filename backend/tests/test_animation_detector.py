"""Rule-level tests of the animation-glitch detector on generated frame sequences
(a camera panning across a real photographic texture)."""

import cv2
import numpy as np
from skimage import data

from gameqa.core import Frame, VideoInfo
from gameqa.detectors.animation import AnimationGlitchDetector

W, H = 640, 360
_t = [cv2.cvtColor(getattr(data, n)(), cv2.COLOR_RGB2BGR) for n in ("coffee", "chelsea", "astronaut", "rocket")]
MOSAIC = np.concatenate([cv2.resize(t, (int(t.shape[1] * 400 / t.shape[0]), 400)) for t in _t], axis=1)
REGION = (200, 120, 380, 260)


def view(x: float) -> np.ndarray:
    return cv2.getRectSubPix(MOSAIC, (W, H), (x + W / 2, 200.0))


def run(n=150, pos=lambda k: 50 + 3 * k, edit=None):
    det = AnimationGlitchDetector()
    det.start(VideoInfo(source_path="synthetic", width=W, height=H, fps_nominal=60))
    for k in range(n):
        img = view(pos(k)).copy()
        if edit:
            img = edit(k, img)
        det.process(Frame(index=k, timestamp_s=k / 60, image=img, original_size=(W, H)))
    return det.finish()


def subtypes(dets):
    return sorted({d.subtype for d in dets})


def test_smooth_pan_has_no_detections():
    assert run() == []


def test_region_flicker():
    def edit(k, img):
        if 50 <= k < 90:
            x0, y0, x1, y1 = REGION
            img[y0:y1, x0:x1] = np.clip(img[y0:y1, x0:x1].astype(int) + (40 if k % 2 else -40), 0, 255)
        return img
    dets = run(edit=edit)
    assert subtypes(dets) == ["flicker"]
    d = dets[0]
    assert 50 / 60 - 0.1 <= d.start_time_s <= 60 / 60 and d.end_time_s >= 85 / 60


def test_single_flash_is_not_flicker():
    def edit(k, img):
        if k in (60, 61, 62):
            img = np.clip(img.astype(int) + 80, 0, 255).astype(np.uint8)
        return img
    assert [d for d in run(edit=edit) if d.subtype == "flicker"] == []


def test_region_jitter():
    def edit(k, img):
        if 50 <= k < 90:
            x0, y0, x1, y1 = REGION
            dx = 6 if k % 2 else -6
            M = np.float32([[1, 0, dx], [0, 1, 0]])
            img[y0:y1, x0:x1] = cv2.warpAffine(img[y0:y1, x0:x1], M, (x1 - x0, y1 - y0), borderMode=cv2.BORDER_REPLICATE)
        return img
    assert subtypes(run(edit=edit)) == ["jitter"]


def test_camera_shake_is_global_jitter():
    dets = run(pos=lambda k: 50 + 3 * k + (8 if (50 <= k < 90 and k % 2) else 0))
    assert subtypes(dets) == ["jitter"]
    assert dets[0].bbox.w == 1.0  # whole frame


def test_teleport_is_unnatural_transition():
    dets = run(pos=lambda k: 50 + 3 * k + (700 if k >= 75 else 0))
    assert subtypes(dets) == ["unnatural_transition"]
    assert dets[0].peak_frame == 75


def test_fast_flick_ramp_is_not_a_teleport():
    # speed ramps 3 -> 40 -> 3 px/frame over ~10 frames: fast but continuous
    speeds = [3 + 37 * np.exp(-((k - 75) / 4) ** 2) for k in range(150)]
    xs = np.cumsum(speeds)
    assert [d for d in run(pos=lambda k: 50 + xs[k]) if d.subtype == "unnatural_transition"] == []
