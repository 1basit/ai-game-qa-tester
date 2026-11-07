"""Rule-level tests of the FPS-drop / frozen-frame detector on generated frame sequences.

A random texture panning sideways gives a scene that is 'moving' on every frame; the
tests then hold, decimate, slow down or remove frames in known places."""

import cv2
import numpy as np
import pytest

from gameqa.core import Frame, VideoInfo
from gameqa.detectors.fps import FpsDropDetector

FPS = 60
RNG = np.random.default_rng(0)
# Smooth texture (blurred noise): like real game images, the frame difference grows
# with camera speed instead of saturating at the first pixel of movement.
TEXTURE = cv2.GaussianBlur((RNG.random((90, 4000)) * 255).astype(np.float32), (0, 0), 4)
TEXTURE = cv2.normalize(TEXTURE, None, 0, 255, cv2.NORM_MINMAX)


def pan(i: int, speed: float = 6.0) -> np.ndarray:
    return _at(i * speed)


def run(frames, times=None, nominal=FPS):
    det = FpsDropDetector()
    det.start(VideoInfo(source_path="synthetic", width=160, height=90, fps_nominal=nominal))
    for k, img in enumerate(frames):
        t = times[k] if times is not None else k / FPS
        det.process(Frame(index=k, timestamp_s=t, image=img, original_size=(160, 90)))
    return det.finish(), det.summary


def sequence(n=600, hold=None, decimate=None, stop=None):
    """hold=(start, length): repeat a frame; decimate=(start, length, keep_every);
    stop=(start, length): camera decelerates to rest, then accelerates again."""
    frames, src = [], 0.0
    for k in range(n):
        speed = 6.0
        if stop and stop[0] - 6 <= k < stop[0] + stop[1] + 6:
            # smooth deceleration / rest / acceleration
            d = min(abs(k - stop[0]), abs(k - (stop[0] + stop[1])))
            speed = 0.0 if stop[0] <= k < stop[0] + stop[1] else 6.0 * min(1.0, d / 6) ** 2
        src += speed
        if hold and hold[0] <= k < hold[0] + hold[1]:
            frames.append(frames[-1])
            continue
        if decimate and decimate[0] <= k < decimate[0] + decimate[1] and (k - decimate[0]) % decimate[2]:
            frames.append(frames[-1])
            continue
        frames.append(_at(src))
    return frames


def _at(src: float) -> np.ndarray:
    """160x90 view at sub-pixel horizontal offset ``src``."""
    x = (src % (TEXTURE.shape[1] - 200)) + 80
    g = cv2.getRectSubPix(TEXTURE, (160, 90), (x + 0.5, 45.0)).astype(np.uint8)
    return np.dstack([g, g, g])


def test_smooth_motion_has_no_detections():
    dets, summary = run(sequence())
    assert dets == []
    assert summary["estimated_render_fps_median"] == pytest.approx(60, abs=1)
    assert summary["measurable_fraction"] > 0.95


def test_held_frame_is_frozen_frame():
    dets, _ = run(sequence(hold=(200, 30)))  # 0.5 s hold
    (d,) = dets
    assert d.subtype == "frozen_frame"
    assert d.start_time_s == pytest.approx(199 / 60, abs=0.02)
    assert d.metrics["hold_ms"] == pytest.approx(31 / 60 * 1000, abs=20)


def test_short_hold_below_threshold_is_not_frozen():
    dets, _ = run(sequence(hold=(200, 8)))  # 150 ms < 250 ms
    assert [d.subtype for d in dets] == []


@pytest.mark.parametrize("keep, expect_drop", [(2, True), (3, True), (4, True)])
def test_decimation_is_fps_drop(keep, expect_drop):
    dets, _ = run(sequence(decimate=(150, 120, keep)))  # 2 s at 60/keep FPS
    drops = [d for d in dets if d.subtype == "fps_drop"]
    assert bool(drops) == expect_drop
    d = drops[0]
    assert d.metrics["min_effective_fps"] == pytest.approx(60 / keep, abs=3)
    assert d.start_time_s < 150 / 60 + 0.2 and d.end_time_s > 270 / 60 - 0.2


def test_mild_slowdown_above_threshold_not_reported():
    dets, _ = run(sequence(decimate=(150, 120, 6)))  # 5 of 6 repeated? no: keep 1 in 6 -> 10 FPS
    assert any(d.subtype == "fps_drop" for d in dets)
    # 50 FPS (one repeat every 6 frames) is above 0.75 x 60 = 45
    frames = sequence()
    for k in range(150, 270, 6):
        frames[k] = frames[k - 1]
    dets, _ = run(frames)
    assert dets == []


def test_player_stopping_is_not_a_freeze():
    dets, _ = run(sequence(stop=(200, 60)))  # decelerate, rest 1 s, accelerate
    assert dets == []


def test_static_scene_is_not_measured():
    still = [pan(0)] * 300
    dets, summary = run(still)
    assert dets == [] and summary["measurable_fraction"] == 0.0


def test_ui_style_discrete_updates_are_not_freezes():
    # static screen that changes in single jumps every 0.4 s (editor / menu footage)
    frames, img = [], pan(0)
    for k in range(600):
        if k % 24 == 0:
            img = pan(k * 37)
        frames.append(img)
    dets, _ = run(frames)
    assert dets == []


def test_vfr_gap_is_frozen_frame():
    frames = sequence(400)
    times = [k / FPS for k in range(400)]
    keep = [k for k in range(400) if not (200 <= k < 230)]  # 0.5 s of frames missing
    dets, _ = run([frames[k] for k in keep], [times[k] for k in keep])
    (d,) = dets
    assert d.subtype == "frozen_frame" and d.metrics["hold_ms"] == pytest.approx(516, abs=20)


def test_target_fps_auto_and_override():
    det = FpsDropDetector()
    det.start(VideoInfo(source_path="s", width=1, height=1, fps_nominal=30))
    assert det._target() == 30
    det = FpsDropDetector({"target_fps": 60})
    det.start(VideoInfo(source_path="s", width=1, height=1, fps_nominal=30))
    assert det._target() == 60
