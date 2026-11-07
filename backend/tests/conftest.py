import shutil
import subprocess

import pytest

from videos import HAVE_FFMPEG, make_video


@pytest.fixture(scope="session")
def vids(tmp_path_factory):
    """Generate the synthetic test videos once per test session."""
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not installed")
    d = tmp_path_factory.mktemp("videos")
    v = {}
    v["cfr30"] = make_video(d / "cfr30.mp4", fps=30, duration=4)                      # 120 frames, B-frames
    v["cfr60_mkv"] = make_video(d / "cfr60.mkv", fps=60, duration=2)                  # 120 frames
    v["avi"] = make_video(d / "clip25.avi", fps=25, duration=2,
                          codec_args=["-c:v", "mpeg4", "-q:v", "2"])                  # 50 frames
    # VFR: source frames 30..44 removed but timestamps kept -> 0.5 s gap after 0.967 s
    v["vfr"] = make_video(d / "vfr.mp4", fps=30, duration=3,
                          vf="select='not(between(n\\,30\\,44))'", extra_out=["-fps_mode", "passthrough"])
    v["offset_mkv"] = make_video(d / "offset.mkv", fps=30, duration=2, extra_out=["-output_ts_offset", "2.5"])
    v["hd1080"] = make_video(d / "hd1080.mp4", width=1920, height=1080, fps=60, duration=1,
                             codec_args=["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"])
    v["tenbit_hdr"] = make_video(d / "hdr.mp4", fps=30, duration=1,
                                 vf="setparams=color_trc=smpte2084:color_primaries=bt2020:colorspace=bt2020nc",
                                 codec_args=["-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p10le"])
    v["with_audio"] = make_video(d / "audio.mp4", fps=30, duration=1,
                                 extra_in=["-f", "lavfi", "-i", "sine=duration=1"],
                                 extra_out=["-c:a", "aac", "-shortest"])
    # Truncated files: with the index (moov) first, the first 50 % stays decodable;
    # with the index at the end, nothing is readable.
    fs = make_video(d / "faststart.mp4", fps=30, duration=4,
                    codec_args=["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-g", "15"],
                    extra_out=["-movflags", "+faststart"])
    data = fs.read_bytes()
    (d / "trunc_faststart.mp4").write_bytes(data[: len(data) // 2])
    v["trunc_faststart"] = d / "trunc_faststart.mp4"
    data = v["cfr30"].read_bytes()
    (d / "trunc_nomoov.mp4").write_bytes(data[: len(data) // 2])
    v["trunc_nomoov"] = d / "trunc_nomoov.mp4"
    # Wrong content / wrong extension
    (d / "notes.mp4").write_text("this is not a video\n" * 50)
    v["text_as_mp4"] = d / "notes.mp4"
    shutil.copy(v["cfr60_mkv"], d / "mkv_named.mp4")
    v["mkv_as_mp4"] = d / "mkv_named.mp4"
    shutil.copy(v["cfr30"], d / "screen.mov")
    v["mov"] = d / "screen.mov"
    (d / "empty.mkv").write_bytes(b"")
    v["empty"] = d / "empty.mkv"
    # An mp4 with only an audio stream
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "sine=duration=1", "-c:a", "aac", str(d / "audio_only.mp4")], check=True)
    v["audio_only"] = d / "audio_only.mp4"
    return v
