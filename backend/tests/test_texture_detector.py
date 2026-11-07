"""Rule-level tests of the texture pop-in detector on generated frame sequences
(a camera panning across a real photographic texture from scikit-image)."""

import cv2
import numpy as np
import pytest
from skimage import data

from gameqa.core import Frame, VideoInfo
from gameqa.detectors.texture import TexturePopInDetector

W, H = 640, 360
_tiles = [cv2.cvtColor(getattr(data, n)(), cv2.COLOR_RGB2BGR) for n in ("coffee", "chelsea", "astronaut")]
_tiles += [cv2.cvtColor(getattr(data, n)(), cv2.COLOR_GRAY2BGR) for n in ("brick", "gravel", "grass")]
MOSAIC = np.concatenate([cv2.resize(t, (int(t.shape[1] * 400 / t.shape[0]), 400)) for t in _tiles], axis=1)
REGION = (200, 120, 360, 260)  # x0, y0, x1, y1 on screen


def view(k: int, speed: float = 2.0) -> np.ndarray:
    x = 50 + k * speed
    return cv2.getRectSubPix(MOSAIC, (W, H), (x + W / 2, 200.0))


def run(n=120, edit=None, params=None):
    det = TexturePopInDetector(params or {})
    det.start(VideoInfo(source_path="synthetic", width=W, height=H, fps_nominal=60))
    for k in range(n):
        img = view(k).copy()
        if edit:
            img = edit(k, img)
        det.process(Frame(index=k, timestamp_s=k / 60, image=img, original_size=(W, H)))
    return det.finish()


def blurred_until(snap):
    def edit(k, img):
        if k < snap:
            x0, y0, x1, y1 = REGION
            img[y0:y1, x0:x1] = cv2.GaussianBlur(img[y0:y1, x0:x1], (31, 31), 0)
        return img
    return edit


def test_camera_pan_alone_has_no_detections():
    assert run() == []


def test_blurred_region_snapping_sharp_is_pop_in():
    dets = run(edit=blurred_until(60))
    pops = [d for d in dets if d.subtype == "texture_pop_in"]
    assert len(pops) == 1
    d = pops[0]
    assert d.peak_frame == 60 and d.metrics["direction"] == "sharpened" and d.metrics["detail_ratio"] >= 2
    # the reported box overlaps the edited region
    x0, y0, x1, y1 = d.bbox.to_pixels(W, H)
    assert x0 < REGION[2] and x1 > REGION[0] and y0 < REGION[3] and y1 > REGION[1]


def test_flicker_is_not_a_pop_in():
    def flicker(k, img):
        if 40 <= k < 90:
            x0, y0, x1, y1 = REGION
            img[y0:y1, x0:x1] = np.clip(img[y0:y1, x0:x1].astype(int) + (50 if k % 2 else -50), 0, 255)
        return img
    assert [d for d in run(edit=flicker) if d.subtype == "texture_pop_in"] == []


@pytest.mark.parametrize("style", ["flat", "checker"])
def test_magenta_patch_is_unrendered_texture(style):
    def magenta(k, img):
        if k >= 50:
            x0, y0, x1, y1 = REGION
            if style == "flat":
                img[y0:y1, x0:x1] = (255, 0, 255)
            else:
                yy, xx = np.mgrid[y0:y1, x0:x1]
                on = ((yy // 16 + xx // 16) % 2).astype(bool)
                patch = np.zeros((y1 - y0, x1 - x0, 3), np.uint8)
                patch[on] = (255, 0, 255)
                img[y0:y1, x0:x1] = patch
        return img
    dets = [d for d in run(edit=magenta) if d.subtype == "unrendered_texture"]
    assert len(dets) == 1 and dets[0].peak_frame == 50


def test_natural_magenta_gradient_is_not_unrendered():
    def gradient(k, img):
        if k >= 50:
            x0, y0, x1, y1 = REGION
            hue = np.linspace(135, 170, x1 - x0, dtype=np.float32)[None, :].repeat(y1 - y0, 0)
            hsv = np.dstack([hue, np.full_like(hue, 220), np.full_like(hue, 220)]).astype(np.uint8)
            img[y0:y1, x0:x1] = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        return img
    assert [d for d in run(edit=gradient) if d.subtype == "unrendered_texture"] == []


def test_excluded_region_is_ignored():
    excl = [(REGION[0] / W - 0.02, REGION[1] / H - 0.02, (REGION[2] - REGION[0]) / W + 0.04,
             (REGION[3] - REGION[1]) / H + 0.04)]
    assert run(edit=blurred_until(60), params={"exclude_regions": excl}) == []
