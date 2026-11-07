"""FR-5 severity rules / recurrence grouping and FR-4 evidence extraction."""

import json
import subprocess

import cv2
import pytest

from gameqa.config import load_settings
from gameqa.core import BoundingBox, DefectCategory, Detection, Severity
from gameqa.evidence import clip_window, extract_evidence
from gameqa.severity import SeverityConfig, apply_severity, classify, group_recurrences
from gameqa.video import FrameStream, probe_video
from videos import decode_index

CFG = SeverityConfig()


def det(cat, sub, start=10.0, end=10.5, bbox=None, **metrics):
    return Detection(category=cat, subtype=sub, detector="t", detector_version="0", start_time_s=start,
                     end_time_s=end, peak_time_s=start, start_frame=int(start * 30), end_frame=int(end * 30),
                     peak_frame=int(start * 30), confidence=0.8, bbox=bbox, metrics=metrics)


SMALL = BoundingBox(x=0.1, y=0.1, w=0.1, h=0.1)


@pytest.mark.parametrize("d, expected", [
    (det(DefectCategory.COLLISION_CLIPPING, "character_geometry", bbox=SMALL), Severity.HIGH),
    (det(DefectCategory.FPS_DROP, "frozen_frame", hold_ms=400.0), Severity.MEDIUM),
    (det(DefectCategory.FPS_DROP, "frozen_frame", hold_ms=1500.0), Severity.HIGH),
    (det(DefectCategory.FPS_DROP, "fps_drop", min_effective_fps=40.0, target_fps=60.0), Severity.MEDIUM),
    (det(DefectCategory.FPS_DROP, "fps_drop", min_effective_fps=20.0, target_fps=60.0), Severity.HIGH),
    (det(DefectCategory.FPS_DROP, "fps_drop", 0, 4, min_effective_fps=40.0, target_fps=60.0), Severity.HIGH),
    (det(DefectCategory.TEXTURE_POP_IN, "texture_pop_in", bbox=SMALL), Severity.LOW),
    (det(DefectCategory.TEXTURE_POP_IN, "texture_pop_in", bbox=BoundingBox(x=0, y=0, w=0.6, h=0.6)), Severity.MEDIUM),
    (det(DefectCategory.TEXTURE_POP_IN, "unrendered_texture", bbox=SMALL), Severity.MEDIUM),
    (det(DefectCategory.ANIMATION_GLITCH, "flicker", bbox=SMALL), Severity.LOW),
    (det(DefectCategory.ANIMATION_GLITCH, "jitter", 0, 3, bbox=SMALL), Severity.MEDIUM),
    (det(DefectCategory.NPC_ANOMALY, "t_pose", bbox=SMALL), Severity.MEDIUM),
    (det(DefectCategory.NPC_ANOMALY, "t_pose", 0, 5, bbox=SMALL), Severity.HIGH),
])
def test_severity_rules(d, expected):
    sev, reason = classify(d, CFG)
    assert sev is expected and reason


def test_recurrence_groups_same_place_and_raises_severity():
    a = [det(DefectCategory.ANIMATION_GLITCH, "flicker", t, t + 0.2, bbox=SMALL) for t in (1, 5, 9)]
    other_place = det(DefectCategory.ANIMATION_GLITCH, "flicker", 3, 3.2, bbox=BoundingBox(x=0.7, y=0.7, w=0.1, h=0.1))
    apply_severity(a + [other_place], CFG)
    assert len({d.occurrence_group for d in a}) == 1 and other_place.occurrence_group != a[0].occurrence_group
    assert all(d.metrics["recurrence_count"] == 3 for d in a) and other_place.metrics["recurrence_count"] == 1
    assert all(d.severity is Severity.MEDIUM and "recurs 3x" in d.severity_reason for d in a)
    assert other_place.severity is Severity.LOW


@pytest.mark.parametrize("start, end, dur, expected", [
    (10.0, 10.5, 60.0, (6.25, 14.25)),   # 8 s centred
    (0.2, 0.3, 60.0, (0.0, 8.0)),        # shifted inside the video start
    (59.5, 59.9, 60.0, (52.0, 60.0)),    # shifted inside the video end
    (10.0, 19.0, 60.0, (9.5, 19.5)),     # long defect: clamped to 10 s
    (1.0, 1.2, 4.0, (0.0, 4.0)),         # video shorter than 5 s
])
def test_clip_window(start, end, dur, expected):
    d = det(DefectCategory.FPS_DROP, "frozen_frame", start, end)
    assert clip_window(d, dur, 8.0) == pytest.approx(expected)


@pytest.mark.parametrize("key", ["cfr30", "offset_mkv"])
def test_evidence_files_are_exact_and_playable(vids, tmp_path, key):
    settings = load_settings()
    probe = probe_video(vids[key])
    peak = 37
    d = det(DefectCategory.FPS_DROP, "frozen_frame", float(probe.pts[peak]), float(probe.pts[peak + 3]))
    d.peak_time_s = float(probe.pts[peak])
    d.peak_frame = peak
    apply_severity([d])
    warnings = extract_evidence(vids[key], [d], probe, tmp_path, "job1", settings)
    assert warnings == []
    shot = cv2.imread(str(tmp_path / d.evidence.screenshot_path))
    assert shot.shape[:2] == (240, 320) and decode_index(shot) == peak  # exact frame, original size
    assert (tmp_path / d.metrics["screenshot_marked"]).exists()
    clip = tmp_path / d.evidence.clip_path
    meta = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                                      str(clip)], capture_output=True, text=True).stdout)
    v = next(s for s in meta["streams"] if s["codec_type"] == "video")
    assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p"
    assert abs(float(meta["format"]["duration"]) - (d.evidence.clip_end_s - d.evidence.clip_start_s)) < 0.15
    assert clip.read_bytes().find(b"moov") < clip.read_bytes().find(b"mdat")  # faststart (browser streaming)
    first = next(iter(FrameStream(clip)))
    expected_first = int(round(d.evidence.clip_start_s * 30))
    assert abs(decode_index(first.image) - expected_first) <= 1  # clip starts where it says


def test_pipeline_attaches_severity_and_evidence(vids, tmp_path):
    from gameqa.pipeline import run_pipeline

    res = run_pipeline(vids["vfr"], load_settings(), detector_names=["fps_drop"], evidence_dir=tmp_path)
    dets = res.detection_set.detections
    assert dets and all(d.severity is not None and d.severity_reason for d in dets)
    assert all(d.evidence and (tmp_path / d.evidence.clip_path).exists() for d in dets)
