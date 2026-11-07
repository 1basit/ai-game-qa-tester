"""Clipping detector: the viewmodel-occlusion mechanism on generated sequences (a static
first-person 'weapon' over a panning photographic background) and the person-overlap
rule with stubbed YOLO detections. The viewmodel tests are marked xfail: the experimental
viewmodel path failed both these synthetic checks and the real held-out validation
(see DEVELOPMENT_PROGRESS.md, Phase 7) and is switched off by default."""

import cv2
import numpy as np
import pytest
from skimage import data

from gameqa.core import BoundingBox, Frame, VideoInfo
from gameqa.detectors import models as M
from gameqa.detectors.clipping import ClippingDetector

W, H = 640, 360
_t = [cv2.cvtColor(getattr(data, n)(), cv2.COLOR_RGB2BGR) for n in ("coffee", "chelsea", "astronaut", "rocket")]
MOSAIC = np.concatenate([cv2.resize(t, (int(t.shape[1] * 400 / t.shape[0]), 400)) for t in _t], axis=1)

# a textured "rifle" hanging from the bottom-right of the screen, pointing up-left
WEAPON = np.zeros((H, W), np.uint8)
cv2.fillConvexPoly(WEAPON, np.array([[620, 360], [430, 360], [330, 200], [350, 185]]), 255)
_rng = np.random.default_rng(0)
WEAPON_TEX = cv2.GaussianBlur((_rng.random((H, W)) * 120 + 30).astype(np.uint8), (0, 0), 1.5)
TIP = np.zeros((H, W), np.uint8)
cv2.circle(TIP, (340, 195), 40, 255, -1)  # far end of the weapon


def frame_at(k: int, occlude_tip: bool = False, other_weapon: bool = False) -> np.ndarray:
    img = cv2.getRectSubPix(MOSAIC, (W, H), (50 + 6 * k + W / 2, 200.0)).copy()
    mask = WEAPON > 0
    tex = WEAPON_TEX if not other_weapon else 255 - WEAPON_TEX
    img[mask] = np.dstack([tex, tex, tex])[mask]
    if occlude_tip:  # the world (wall) is drawn over the weapon's far end
        m = (TIP > 0) & mask
        img[m] = (60, 70, 110)
    return img


XFAIL = pytest.mark.xfail(strict=False, reason="viewmodel clipping is experimental and failed validation "
                          "(Phase 7): spurious detections on clean input, occlusion missed")


def run(edit=lambda k: {}, n=160):
    det = ClippingDetector({"use_people": False, "viewmodel_clipping": True})
    det.start(VideoInfo(source_path="synthetic", width=W, height=H, fps_nominal=12))
    for k in range(n):
        det.process(Frame(index=k, timestamp_s=k / 12, image=frame_at(k, **edit(k)), original_size=(W, H)))
    return det.finish()


def test_viewmodel_path_is_off_by_default():
    det = ClippingDetector({"use_people": False})
    det.start(VideoInfo(source_path="synthetic", width=W, height=H, fps_nominal=12))
    for k in range(120):
        det.process(Frame(index=k, timestamp_s=k / 12, image=frame_at(k, occlude_tip=k > 60), original_size=(W, H)))
    assert det.finish() == []


@XFAIL
def test_static_weapon_without_occlusion_is_clean():
    assert run() == []


@XFAIL
def test_occluded_weapon_tip_is_clipping():
    dets = run(lambda k: {"occlude_tip": 90 <= k < 110})
    assert [d.subtype for d in dets] == ["character_geometry"]
    d = dets[0]
    assert 90 / 12 - 0.2 <= d.start_time_s <= 92 / 12 and d.end_time_s >= 105 / 12
    x0, y0, x1, y1 = d.bbox.to_pixels(W, H)
    assert x0 < 380 and y1 > 160  # the reported box is at the weapon's far end


@XFAIL
def test_weapon_switch_is_not_clipping():
    # the whole viewmodel changes (weapon switch / cut): body visibility collapses -> relearn
    dets = run(lambda k: {"other_weapon": k >= 90})
    assert [d for d in dets if d.subtype == "character_geometry"] == []


def test_person_overlap_rule(monkeypatch):
    a = BoundingBox(x=0.3, y=0.2, w=0.2, h=0.5)
    b = BoundingBox(x=0.32, y=0.22, w=0.2, h=0.5)  # IoU ~0.7 with a
    apart = BoundingBox(x=0.7, y=0.2, w=0.2, h=0.5)

    def fake(frame, *args, **kw):
        second = b if frame.index >= 10 else apart
        return [M.Detected(0, "person", 0.9, a), M.Detected(0, "person", 0.9, second)]

    monkeypatch.setattr(M, "detect_objects", fake)
    det = ClippingDetector({"use_people": True})
    det.start(VideoInfo(source_path="synthetic", width=W, height=H, fps_nominal=12))
    for k in range(40):
        det.process(Frame(index=k, timestamp_s=k / 12, image=frame_at(k), original_size=(W, H)))
    cc = [d for d in det.finish() if d.subtype == "character_character"]
    assert len(cc) == 1 and cc[0].start_time_s >= 10 / 12 - 1e-6 and cc[0].metrics["max_iou"] > 0.5
