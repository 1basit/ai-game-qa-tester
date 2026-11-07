"""Synthetic test videos with the frame index encoded into every picture.

Each frame shows 10 vertical bands; band b is white if bit b of the source frame
number is set. Decoding the bands recovers the frame number exactly, regardless of
resolution, scaling or (mild) compression, so tests can prove that no frame was
dropped, duplicated or reordered and that timestamps belong to the right picture.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

BITS = 10
_PATTERN = f"if(mod(floor(N/pow(2\\,floor(X*{BITS}/W)))\\,2)\\,235\\,16)"

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def pattern_source(width: int, height: int, fps: float, duration: float) -> str:
    return (
        f"nullsrc=size={width}x{height}:rate={fps}:duration={duration},"
        f"format=yuv420p,geq=lum='{_PATTERN}':cb=128:cr=128"
    )


def make_video(path: Path, *, width=320, height=240, fps=30, duration=4.0,
               vf: str | None = None, codec_args: list[str] | None = None,
               extra_in: list[str] | None = None, extra_out: list[str] | None = None) -> Path:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", pattern_source(width, height, fps, duration)]
    cmd += extra_in or []
    if vf:
        cmd += ["-vf", vf]
    cmd += codec_args if codec_args is not None else ["-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p"]
    cmd += extra_out or []
    cmd.append(str(path))
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def decode_index(img: np.ndarray) -> int:
    """Recover the encoded source frame number from a BGR image."""
    h, w = img.shape[:2]
    gray = img.mean(axis=2) if img.ndim == 3 else img
    value = 0
    for b in range(BITS):
        x0, x1 = int((b + 0.3) * w / BITS), int((b + 0.7) * w / BITS)
        if gray[h // 4: 3 * h // 4, x0:x1].mean() > 128:
            value |= 1 << b
    return value
