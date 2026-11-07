"""Video processing engine (Phase 2): validation, metadata, streaming decode."""

from gameqa.video.probe import ProbeResult, probe_video, timing_stats
from gameqa.video.stream import FrameStream, Normaliser, StreamStats, read_frame_at
from gameqa.video.validation import sniff_container, validate_file, validate_filename

__all__ = [
    "FrameStream",
    "Normaliser",
    "open_video",
    "ProbeResult",
    "StreamStats",
    "probe_video",
    "read_frame_at",
    "sniff_container",
    "timing_stats",
    "validate_file",
    "validate_filename",
]


def open_video(path, video_cfg, **stream_kwargs) -> FrameStream:  # type: ignore[no-untyped-def]
    """Validate + probe + open: the single entry point the pipeline and worker use."""
    validate_file(path, video_cfg.allowed_extensions, video_cfg.max_upload_mb)
    return FrameStream(path, video_cfg, probe=probe_video(path), **stream_kwargs)
