"""Small helpers shared by the detectors."""

from __future__ import annotations

import cv2
import numpy as np

from gameqa.core.schemas import Frame


def thumbnail_gray(frame: Frame, size: tuple[int, int], key: str | None = None) -> np.ndarray:
    """Small float32 greyscale version of the *original* frame, cached per frame.

    Built from ``frame.raw`` when available so full-rate detectors do not force the
    (more expensive) 720p normalisation of every frame. INTER_AREA averages pixel
    blocks, which also suppresses encoder noise.
    """
    key = key or f"thumb_gray_{size[0]}x{size[1]}"
    cached = frame.extras.get(key)
    if cached is not None:
        return cached
    src = frame.raw if frame.raw is not None else frame.image
    gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY) if src.ndim == 3 else src
    thumb = cv2.resize(gray, size, interpolation=cv2.INTER_AREA).astype(np.float32)
    frame.extras[key] = thumb
    return thumb


def clamp01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))
