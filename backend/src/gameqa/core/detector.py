"""The interface every defect detector implements.

Detectors are *streaming*: the pipeline decodes the video once and pushes frames to
each enabled detector (FR-3 "single pass"). A detector never opens the video itself,
never holds the whole video in memory, and never assigns severity — that keeps the
five detectors independent and individually testable.

Lifecycle::

    det = SomeDetector(params)
    det.start(video_info)
    for frame in stream:            # sampled or full-rate, per ``frame_rate``
        det.process(frame)
    detections = det.finish()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel

from gameqa.core.schemas import DefectCategory, Detection, Frame, VideoInfo


class FrameRate(str, Enum):
    """Which frames a detector needs (FR-2)."""

    FULL = "full"  # every decoded frame (e.g. frame-timing analysis)
    SAMPLED = "sampled"  # the 10-15 FPS analysis stream


class DetectorParams(BaseModel):
    """Base class for a detector's typed parameters. Subclasses add fields."""

    model_config = {"extra": "forbid"}


class Detector(ABC):
    name: ClassVar[str]
    version: ClassVar[str]
    category: ClassVar[DefectCategory]
    frame_rate: ClassVar[FrameRate] = FrameRate.SAMPLED
    params_model: ClassVar[type[DetectorParams]] = DetectorParams

    def __init__(self, params: DetectorParams | dict[str, Any] | None = None):
        if params is None:
            params = self.params_model()
        elif isinstance(params, dict):
            params = self.params_model.model_validate(params)
        self.params = params
        self.video: VideoInfo | None = None
        # Video-level findings that are not individual defects (e.g. "estimated rendered
        # FPS"). Filled by ``finish()``; shown in reports next to the detections.
        self.summary: dict[str, Any] = {}

    def start(self, video: VideoInfo) -> None:
        """Reset internal state for a new video."""
        self.video = video
        self.summary = {}

    @abstractmethod
    def process(self, frame: Frame) -> None:
        """Consume one frame. Must not keep references to many past frames."""

    @abstractmethod
    def finish(self) -> list[Detection]:
        """Return all detections for the video (after persistence filtering)."""


_REGISTRY: dict[str, type[Detector]] = {}


def register_detector(cls: type[Detector]) -> type[Detector]:
    """Class decorator: make a detector discoverable by name (used by the pipeline
    to instantiate the detectors enabled in the configuration)."""
    for attr in ("name", "version", "category"):
        if not hasattr(cls, attr):
            raise TypeError(f"{cls.__name__} must define class attribute '{attr}'")
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        raise ValueError(f"detector name '{cls.name}' is already registered")
    _REGISTRY[cls.name] = cls
    return cls


def get_detector_class(name: str) -> type[Detector]:
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise KeyError(f"unknown detector '{name}' (registered: {known})") from None


def registered_detectors() -> dict[str, type[Detector]]:
    return dict(_REGISTRY)
