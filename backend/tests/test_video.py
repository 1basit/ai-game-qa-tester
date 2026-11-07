import math

import numpy as np
import pytest

from gameqa.config import VideoConfig
from gameqa.core import CorruptVideoError, UnsupportedFormatError
from gameqa.video import FrameStream, Normaliser, open_video, probe_video, read_frame_at, validate_file
from videos import decode_index

CFG = VideoConfig()  # defaults: 12 FPS sampling, 720p, upscale on
ALLOWED, LIMIT = CFG.allowed_extensions, CFG.max_upload_mb


# ---------------------------------------------------------------- validation (FR-1)

@pytest.mark.parametrize("key, family", [("cfr30", "mp4"), ("cfr60_mkv", "matroska"), ("avi", "avi")])
def test_accepted_formats(vids, key, family):
    assert validate_file(vids[key], ALLOWED, LIMIT) == family


@pytest.mark.parametrize(
    "key, message",
    [
        ("mov", "Accepted formats: .avi, .mkv, .mp4"),
        ("text_as_mp4", "not a video file"),
        ("mkv_as_mp4", "content is a matroska container"),
        ("empty", "is empty"),
    ],
)
def test_rejected_files(vids, key, message):
    with pytest.raises(UnsupportedFormatError, match=message):
        validate_file(vids[key], ALLOWED, LIMIT)


def test_size_limit(tmp_path):
    big = tmp_path / "big.mp4"
    big.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * (2 * 1024 * 1024))
    with pytest.raises(UnsupportedFormatError, match="limit is 1 MB"):
        validate_file(big, ALLOWED, max_upload_mb=1)


# ---------------------------------------------------------------- probing

def test_probe_cfr(vids):
    info = probe_video(vids["cfr30"]).info
    assert (info.width, info.height, info.fps_nominal, info.frame_count) == (320, 240, 30, 120)
    assert info.duration_s == pytest.approx(4.0, abs=1e-3)
    assert info.is_vfr is False and info.timing.irregular_intervals == 0
    assert info.codec == "h264" and info.has_audio is False and info.is_hdr is False


def test_probe_mkv_and_avi(vids):
    mkv = probe_video(vids["cfr60_mkv"]).info
    assert (mkv.fps_nominal, mkv.frame_count, mkv.is_vfr) == (60, 120, False)
    avi = probe_video(vids["avi"]).info
    assert (avi.fps_nominal, avi.frame_count, avi.codec, avi.is_vfr) == (25, 50, "mpeg4", False)


def test_probe_vfr_gap(vids):
    res = probe_video(vids["vfr"])
    info = res.info
    assert info.frame_count == 75 and info.is_vfr is True
    assert info.timing.irregular_intervals == 1
    assert info.timing.max_interval_s == pytest.approx(1.5 - 29 / 30, abs=1e-3)  # the 0.533 s gap
    assert res.pts[29] == pytest.approx(29 / 30, abs=1e-3) and res.pts[30] == pytest.approx(1.5, abs=1e-3)


def test_probe_start_offset_is_removed(vids):
    res = probe_video(vids["offset_mkv"])
    assert res.info.start_time_s == pytest.approx(2.5, abs=0.01)
    assert res.pts[0] == 0.0 and res.pts[-1] == pytest.approx(59 / 30, abs=2e-3)


def test_probe_hdr_audio_flags(vids):
    hdr = probe_video(vids["tenbit_hdr"]).info
    assert hdr.is_hdr and hdr.bit_depth == 10 and hdr.pix_fmt == "yuv420p10le"
    assert probe_video(vids["with_audio"]).info.has_audio


@pytest.mark.parametrize("key", ["trunc_nomoov", "audio_only"])
def test_probe_unreadable(vids, key):
    with pytest.raises(CorruptVideoError):
        probe_video(vids[key])


def test_fingerprint_stable_and_distinct(vids):
    a = probe_video(vids["cfr30"]).info.fingerprint
    assert a == probe_video(vids["cfr30"]).info.fingerprint
    assert a != probe_video(vids["mov"].with_name("cfr60.mkv")).info.fingerprint


# ---------------------------------------------------------------- decoding (FR-2)

@pytest.mark.parametrize("key, n", [("cfr30", 120), ("cfr60_mkv", 120), ("avi", 50), ("offset_mkv", 60)])
def test_every_frame_decoded_in_order_with_correct_timestamp(vids, key, n):
    probe = probe_video(vids[key])
    stream = FrameStream(vids[key], CFG, probe=probe)
    frames = list(stream)
    assert len(frames) == n == stream.stats.frames_decoded
    for i, f in enumerate(frames):
        assert f.index == i
        assert decode_index(f.image) == i, f"picture of frame {i} shows frame {decode_index(f.image)}"
        assert f.timestamp_s == pytest.approx(probe.pts[i], abs=1e-3)
    assert stream.stats.timestamp_mismatches == 0 and not stream.stats.truncated
    assert stream.stats.warnings == []


def test_vfr_timestamps_and_pictures(vids):
    frames = list(FrameStream(vids["vfr"], CFG))
    assert len(frames) == 75
    # file frame 30 is source frame 45, shown at 1.5 s
    assert decode_index(frames[29].image) == 29 and frames[29].timestamp_s == pytest.approx(29 / 30, abs=1e-3)
    assert decode_index(frames[30].image) == 45 and frames[30].timestamp_s == pytest.approx(1.5, abs=1e-3)
    gaps = np.diff([f.timestamp_s for f in frames])
    assert gaps.max() == pytest.approx(0.5333, abs=1e-3)


def test_sampling_30_to_12_fps(vids):
    frames = list(FrameStream(vids["cfr30"], CFG))
    sampled = [f.index for f in frames if f.is_sampled]
    # grid k/12 s -> first frame i/30 >= k/12 -> i = ceil(2.5 k)
    assert sampled == [math.ceil(2.5 * k) for k in range(48)]
    rate = (len(sampled) - 1) / (frames[sampled[-1]].timestamp_s - frames[sampled[0]].timestamp_s)
    assert rate == pytest.approx(12, abs=0.3)


def test_sampling_60_fps_every_fifth(vids):
    sampled = [f.index for f in FrameStream(vids["cfr60_mkv"], CFG) if f.is_sampled]
    assert sampled == list(range(0, 120, 5))


def test_sampling_is_time_based_across_vfr_gap(vids):
    sampled = [f for f in FrameStream(vids["vfr"], CFG) if f.is_sampled]
    ts = [f.timestamp_s for f in sampled]
    # nothing is sampled inside the gap; sampling resumes on the first frame after it
    assert not any(29 / 30 + 1e-3 < t < 1.5 - 1e-3 for t in ts)
    assert any(t == pytest.approx(1.5, abs=1e-3) for t in ts)


def test_sampled_only_and_custom_rate(vids):
    cfg = CFG.model_copy(update={"analysis_fps": 15.0})
    frames = list(FrameStream(vids["cfr30"], cfg, sampled_only=True))
    assert all(f.is_sampled for f in frames)
    assert [f.index for f in frames] == list(range(0, 120, 2))


# ---------------------------------------------------------------- normalisation

@pytest.mark.parametrize(
    "key, size", [("cfr30", (960, 720)), ("hd1080", (1280, 720))]
)
def test_normalised_frames(vids, key, size):
    f = next(iter(FrameStream(vids[key], CFG)))
    assert f.size == size and f.image.dtype == np.uint8 and f.image.shape[2] == 3
    assert f.image.flags["C_CONTIGUOUS"]
    assert decode_index(f.image) == 0


def test_no_upscale_option(vids):
    cfg = CFG.model_copy(update={"upscale": False})
    assert next(iter(FrameStream(vids["cfr30"], cfg))).size == (320, 240)


def test_normaliser_odd_inputs():
    n = Normaliser(720)
    assert n.output_size(1366, 768) == (1280, 720)  # even width
    assert n(np.zeros((10, 10), np.uint8)).shape == (720, 720, 3)          # grey -> BGR
    assert n(np.zeros((10, 10, 4), np.uint8)).shape == (720, 720, 3)       # BGRA -> BGR
    img16 = np.full((10, 10, 3), 65535, np.uint16)
    out = n(img16)
    assert out.dtype == np.uint8 and out.max() == 255                         # 16-bit -> 8-bit


def test_ten_bit_hdr_is_converted_and_flagged(vids):
    stream = FrameStream(vids["tenbit_hdr"], CFG)
    frames = list(stream)
    assert frames[0].image.dtype == np.uint8 and decode_index(frames[5].image) == 5
    assert any("HDR" in w for w in stream.stats.warnings)


# ---------------------------------------------------------------- windows & single frames

def test_time_window(vids):
    frames = list(FrameStream(vids["cfr30"], CFG, start_s=2.0, end_s=3.0))
    assert [f.index for f in frames] == list(range(60, 91))
    assert all(decode_index(f.image) == f.index for f in frames)
    assert frames[0].timestamp_s == pytest.approx(2.0, abs=1e-3)


def test_time_window_vfr_indices(vids):
    frames = list(FrameStream(vids["vfr"], CFG, start_s=1.4, end_s=1.6))
    assert frames[0].index == 30 and decode_index(frames[0].image) == 45


def test_read_frame_at_original_resolution(vids):
    f = read_frame_at(vids["cfr30"], 1.234)
    assert f.index == 37 and f.size == (320, 240) and decode_index(f.image) == 37
    f = read_frame_at(vids["vfr"], 1.2)  # inside the gap -> the frame still on screen
    assert f.index == 29 and decode_index(f.image) == 29


# ---------------------------------------------------------------- damaged input

def test_truncated_file_decodes_partially_and_warns(vids):
    stream = FrameStream(vids["trunc_faststart"], CFG)
    frames = list(stream)
    assert 0 < len(frames) < 120
    assert all(decode_index(f.image) == f.index for f in frames)
    assert stream.stats.truncated and "truncated" in stream.stats.warnings[-1]


def test_open_video_rejects_before_decoding(vids):
    with pytest.raises(UnsupportedFormatError):
        open_video(vids["text_as_mp4"], CFG)
    stream = open_video(vids["cfr30"], CFG)
    assert stream.info.frame_count == 120


def test_normalisation_is_lazy(vids):
    stream = FrameStream(vids["hd1080"], CFG)
    touched = 0
    for f in stream:
        if f.is_sampled:
            touched += 1
            assert f.image.shape[:2] == (720, 1280)
        assert f.raw.shape[:2] == (1080, 1920)
    assert stream.stats.frames_decoded == 60 and touched == stream.stats.frames_sampled == 12
    assert stream.stats.normalise_s > 0


def test_frame_requires_an_image_source():
    from gameqa.core import Frame

    with pytest.raises(ValueError):
        Frame(index=0, timestamp_s=0.0, original_size=(1, 1))


@pytest.mark.parametrize("key", ["cfr30", "cfr60_mkv", "avi", "offset_mkv", "vfr"])
def test_complete_files_not_flagged_truncated(vids, key):
    assert probe_video(vids[key]).info.truncation_suspected is False


def test_truncation_detected_from_container_declarations(vids, tmp_path):
    info = probe_video(vids["trunc_faststart"]).info
    assert info.truncation_suspected and info.declared_frame_count == 120 and info.frame_count < 120
    for key, name in [("cfr60_mkv", "t.mkv"), ("avi", "t.avi")]:  # duration-based / count-based
        data = vids[key].read_bytes()
        (tmp_path / name).write_bytes(data[: len(data) // 2])
        assert probe_video(tmp_path / name).info.truncation_suspected, name
