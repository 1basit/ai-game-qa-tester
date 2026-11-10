"""FPS analysis service (prototype engine shared by the CLI and the web GUI)."""

import json

import pytest

from gameqa.config import FpsServiceConfig
from gameqa.core import CorruptVideoError, UnsupportedFormatError, VideoError
from gameqa.evaluation.synthetic import Drop, Stutter, render
from gameqa.fps_service import analyze_video, output_folder, save_results
from videos import make_video


@pytest.fixture(scope="module")
def moving_base(tmp_path_factory):
    # 8 s, 60 FPS, every frame different (frame-index stripe pattern) = continuously "moving"
    d = tmp_path_factory.mktemp("svc")
    return make_video(d / "base.mp4", width=320, height=240, fps=60, duration=8)


def test_missing_file_message(tmp_path):
    with pytest.raises(UnsupportedFormatError, match="does not exist"):
        analyze_video(tmp_path / "nope.mp4")


@pytest.mark.parametrize("key, err", [("mov", UnsupportedFormatError), ("text_as_mp4", UnsupportedFormatError),
                                      ("trunc_nomoov", CorruptVideoError)])
def test_bad_inputs_raise_clear_errors(vids, key, err):
    with pytest.raises(err):
        analyze_video(vids[key])


def test_clean_cfr_video_statistics(vids):
    r, tl = analyze_video(vids["cfr30"], FpsServiceConfig(target_fps=30))
    assert r.metadata["nominal_fps"] == 30 and r.metadata["frame_count"] == 120
    assert r.metadata["average_fps"] == pytest.approx(30, abs=0.01) and not r.metadata["variable_frame_rate"]
    assert r.frame_intervals["expected_ms"] == pytest.approx(33.333, abs=0.01) and r.frame_intervals["irregular_intervals"] == 0
    assert r.events == [] and r.counts["missed_frames_while_moving"] == 0
    assert r.effective_fps["median"] == pytest.approx(30, abs=0.5)
    assert r.frame_times["p50_ms"] == pytest.approx(33.33, abs=0.1)
    assert "No freezes, drops or stutters" in r.verdict and r.limitations
    assert len(tl["time_s"]) == 120


def test_vfr_gap_reported_as_freeze(vids):
    r, _ = analyze_video(vids["vfr"], FpsServiceConfig(target_fps=30))
    assert r.metadata["variable_frame_rate"] is True and r.frame_intervals["max_ms"] == pytest.approx(533.3, abs=1)
    assert [e.type for e in r.events] == ["freeze"] and r.events[0].start_s == pytest.approx(29 / 30, abs=0.02)


def test_stutter_detected_and_separated_from_drop(moving_base, tmp_path):
    stut = tmp_path / "stutter.mp4"
    render(moving_base, stut, [Stutter(2.0, 3.0, every=6)], height=240)    # 10 missed/s -> 50 FPS
    r, _ = analyze_video(stut)
    assert [e.type for e in r.events] == ["stutter"]
    e = r.events[0]
    assert e.start_s < 2.6 and e.end_s > 4.4 and e.metrics["max_missed_per_s"] >= 8
    drop = tmp_path / "drop.mp4"
    render(moving_base, drop, [Drop(2.0, 3.0, keep_every=2)], height=240)  # 30 FPS < 45 threshold
    assert [e.type for e in analyze_video(drop)[0].events] == ["fps_drop"]


def test_thresholds_are_configurable(moving_base, tmp_path):
    stut = tmp_path / "stutter.mp4"
    render(moving_base, stut, [Stutter(2.0, 3.0, every=6)], height=240)
    strict = analyze_video(stut, FpsServiceConfig(stutter_min_missed=20))[0]
    assert [e.type for e in strict.events] == []  # 10 missed/s is below a 20/s stutter threshold


def test_opencv_only_fallback(vids, monkeypatch):
    import gameqa.fps_service.analysis as A

    monkeypatch.setattr(A.shutil, "which", lambda name: None)  # as if ffprobe were not installed
    r, _ = analyze_video(vids["cfr30"], FpsServiceConfig(target_fps=30))
    assert "OpenCV" in r.metadata["timestamp_source"] and r.warnings
    assert r.metadata["frame_count"] == 120 and r.events == []


def test_results_saved(vids, tmp_path):
    r, tl = analyze_video(vids["vfr"], FpsServiceConfig(target_fps=30))
    files = save_results(r, tl, tmp_path / "out")
    data = json.loads(files["analysis_json"].read_text())
    assert data["counts"]["freezes"] == 1 and data["events"][0]["type"] == "freeze"
    rows = files["timeline_csv"].read_text().splitlines()
    assert rows[0].startswith("frame_index,time_s,interval_ms") and len(rows) == 76
    for k in ("chart_effective_fps", "chart_frame_intervals", "chart_frame_changes"):
        assert files[k].stat().st_size > 10_000 and files[k].read_bytes()[:4] == b"\x89PNG"


def test_output_folder_names_are_safe(tmp_path):
    f = output_folder("../weird name?.mp4", FpsServiceConfig(output_dir=tmp_path))
    assert f.parent == tmp_path and "?" not in f.name and ".." not in f.name


def test_too_short(tmp_path):
    p = make_video(tmp_path / "one.mp4", fps=30, duration=1 / 30)
    with pytest.raises(VideoError):
        analyze_video(p)


def _pan_with_stop(path, vfr: bool):
    """A camera pan that slows to a stop, stays still for 0.7 s, then moves again (60 FPS).
    vfr=True stores it like a recorder that writes no frame while nothing changes."""
    import subprocess

    import cv2
    import numpy as np

    # smooth texture + sub-pixel pan: a 6 px step differs by ~12 grey levels, a 0.25 px creep by
    # ~0.5 (below the 1.0 motion threshold), like a real camera coming to rest
    tex = cv2.GaussianBlur(np.random.default_rng(0).integers(0, 256, (180, 1700)).astype(np.float32), (0, 0), 8)
    tex = (tex - tex.min()) / (tex.max() - tex.min()) * 255
    speeds = [6] * 60 + [3, 1, 0.25] + [0] * 42 + [6] * 90  # move, slow down, hold 0.7 s, move
    x, frames = 0.0, []
    for v in speeds:
        x += v
        img = cv2.warpAffine(tex, np.float32([[1, 0, -x], [0, 1, 0]]), (320, 180))
        frames.append(np.clip(img, 0, 255).astype(np.uint8))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "320x180",
           "-r", "60", "-i", "-"]
    # VFR: drop exactly the 42 identical frames of the hold (63..104), keep the timestamps
    cmd += (["-vf", "select='not(between(n\\,63\\,104))'", "-fps_mode", "passthrough"] if vfr else [])
    cmd += ["-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, input=b"".join(f.tobytes() for f in frames), check=True)
    return path


@pytest.mark.parametrize("vfr", [False, True])
def test_player_stopping_is_not_a_drop_in_cfr_or_vfr(tmp_path, vfr):
    """Phase 6 regression: a still stretch stored as a timestamp gap (VFR) must be treated
    like the same stretch stored as repeated frames (CFR): not measurable, not an FPS drop."""
    r, tl = analyze_video(_pan_with_stop(tmp_path / f"stop_{vfr}.mp4", vfr))
    assert r.metadata["variable_frame_rate"] is vfr
    assert [e.type for e in r.events] == []
    assert r.effective_fps["min"] >= 45
    assert r.frame_times["max_ms"] < 100  # the 0.7 s still gap is not a frame time
