"""Single-pass pipeline: frame routing, fault isolation (NFR 5.1), progress reporting."""

import pytest

from gameqa.config import load_settings
from gameqa.core import DefectCategory, Detection, Detector, FrameRate
from gameqa.pipeline import run_pipeline


class Counter(Detector):
    name = "test_counter"
    version = "0"
    category = DefectCategory.FPS_DROP

    def start(self, video):
        super().start(video)
        self.frames = []

    def process(self, frame):
        self.frames.append((frame.index, frame.is_sampled))

    def finish(self):
        self.summary = {"n": len(self.frames)}
        return []


class FullCounter(Counter):
    name = "test_full_counter"
    frame_rate = FrameRate.FULL


class Crashes(Detector):
    name = "test_crash"
    version = "0"
    category = DefectCategory.TEXTURE_POP_IN

    def process(self, frame):
        if frame.index >= 30:
            raise RuntimeError("boom")

    def finish(self):
        return []


class Finds(Detector):
    name = "test_finds"
    version = "0"
    category = DefectCategory.FPS_DROP
    frame_rate = FrameRate.FULL

    def process(self, frame):
        self.last = frame

    def finish(self):
        f = self.last
        return [Detection(category=self.category, subtype="frozen_frame", detector=self.name, detector_version="0",
                          start_time_s=f.timestamp_s, end_time_s=f.timestamp_s, peak_time_s=f.timestamp_s,
                          start_frame=f.index, end_frame=f.index, peak_frame=f.index, confidence=0.5)]


@pytest.fixture
def settings():
    return load_settings()


def test_frame_routing_full_vs_sampled(vids, settings):
    full, sampled = FullCounter(), Counter()
    res = run_pipeline(vids["cfr30"], settings, detectors=[full, sampled])
    assert len(full.frames) == 120                      # every frame
    assert len(sampled.frames) == 48                    # 12 FPS grid over 4 s at 30 FPS
    assert all(s for _, s in sampled.frames)
    assert res.status == "completed" and res.stream_stats["frames_decoded"] == 120
    assert {r.name: r.frames_processed for r in res.runs} == {"test_full_counter": 120, "test_counter": 48}


def test_crashing_detector_is_isolated(vids, settings):
    ok, bad, finder = FullCounter(), Crashes(), Finds()
    res = run_pipeline(vids["cfr30"], settings, detectors=[bad, ok, finder])
    assert res.status == "completed_with_warnings"
    crash = next(r for r in res.runs if r.name == "test_crash")
    assert "boom" in crash.error and "frame 30" in crash.error
    assert len(ok.frames) == 120                        # the others carried on to the end
    assert len(res.detection_set.detections) == 1      # and their results are kept
    assert any("test_crash" in w for w in res.warnings)


def test_detector_failing_in_finish_is_isolated(vids, settings):
    class BadFinish(FullCounter):
        name = "test_bad_finish"

        def finish(self):
            raise ValueError("cannot finalise")

    res = run_pipeline(vids["cfr30"], settings, detectors=[BadFinish(), Finds()])
    assert res.status == "completed_with_warnings" and len(res.detection_set.detections) == 1


def test_progress_is_reported_and_reaches_one(vids, settings):
    seen = []
    run_pipeline(vids["cfr30"], settings, detectors=[Counter()], progress=lambda f, msg: seen.append(f))
    assert seen and seen[-1] == 1.0 and all(0 <= a <= b <= 1 for a, b in zip(seen, seen[1:]))


def test_registered_detectors_run_by_name(vids, settings):
    res = run_pipeline(vids["cfr30"], settings, detector_names=["fps_drop", "animation_glitch"])
    assert res.status == "completed"
    assert {r.name for r in res.runs} == {"fps_drop", "animation_glitch"}
    assert res.detection_set.video.frame_count == 120
