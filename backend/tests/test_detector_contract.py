"""Exercises the Detector interface end-to-end with a minimal toy detector, to prove
the contract (params validation, lifecycle, persistence helper, Detection output)
works before real detectors are built on it. The toy detector is test-only."""

import numpy as np
import pytest
from pydantic import ValidationError

from gameqa.core import (
    DefectCategory,
    Detection,
    Detector,
    DetectorParams,
    EventAccumulator,
    Frame,
    FrameRate,
    PersistenceRule,
    VideoInfo,
    get_detector_class,
    register_detector,
)
from gameqa.core.detector import _REGISTRY


class BlackScreenParams(DetectorParams):
    max_mean_luma: float = 5.0


class BlackScreenDetector(Detector):
    """Flags runs of near-black frames as 'frozen_frame' — a stand-in, not a real detector."""

    name = "test_black_screen"
    version = "0.0"
    category = DefectCategory.FPS_DROP
    frame_rate = FrameRate.FULL
    params_model = BlackScreenParams

    def start(self, video):
        super().start(video)
        self.acc = EventAccumulator(PersistenceRule(min_frames=3))
        self.events = []

    def process(self, frame):
        luma = float(frame.gray().mean())
        self.events += self.acc.update(
            frame.index, frame.timestamp_s, luma <= self.params.max_mean_luma, score=1 - luma / 255
        )

    def finish(self):
        self.events += self.acc.flush()
        return [
            Detection(
                category=self.category, subtype="frozen_frame", detector=self.name,
                detector_version=self.version, start_time_s=e.start_time_s,
                end_time_s=e.end_time_s, peak_time_s=e.peak_time_s, start_frame=e.start_frame,
                end_frame=e.end_frame, peak_frame=e.peak_frame, confidence=e.peak_score,
            )
            for e in self.events
        ]


@pytest.fixture
def registered():
    register_detector(BlackScreenDetector)
    yield
    _REGISTRY.pop(BlackScreenDetector.name, None)


def test_lifecycle_produces_valid_detections(registered):
    cls = get_detector_class("test_black_screen")
    det = cls({"max_mean_luma": 10})
    det.start(VideoInfo(source_path="synthetic", width=8, height=8, fps_nominal=30))
    bright = np.full((8, 8, 3), 128, np.uint8)
    black = np.zeros((8, 8, 3), np.uint8)
    seq = [bright] * 5 + [black] * 6 + [bright] * 5 + [black] * 1  # one real run, one blip
    for i, img in enumerate(seq):
        det.process(Frame(index=i, timestamp_s=i / 30, image=img, original_size=(8, 8)))
    (d,) = det.finish()
    assert (d.start_frame, d.end_frame) == (5, 10)
    assert d.start_time_s == pytest.approx(5 / 30)


def test_params_are_validated(registered):
    with pytest.raises(ValidationError):
        BlackScreenDetector({"max_mean_luma": 10, "typo_param": 1})


def test_unknown_detector_name():
    with pytest.raises(KeyError, match="unknown detector"):
        get_detector_class("does_not_exist")


def test_duplicate_registration_rejected(registered):
    class Other(BlackScreenDetector):
        pass

    with pytest.raises(ValueError, match="already registered"):
        register_detector(Other)
