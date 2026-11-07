"""The shared data contract used by all detectors, the pipeline, the API and reports.

Every detector — whatever algorithm it uses — must return ``Detection`` objects. This
is what lets the pipeline, the severity engine, the database layer, the dashboard and
the JSON/PDF exports treat all five defect categories uniformly (SRS FR-3 … FR-6).

Conventions
-----------
* Times are seconds from the start of the *original* video, taken from the
  decoder's presentation timestamps (FR-2).
* Frame indices refer to the *original full-rate* frame sequence, even when a
  detector only sees sub-sampled frames. This keeps every detection traceable to the
  original footage (FR-4).
* Bounding boxes are normalised to [0, 1] relative to the frame, so they stay valid
  regardless of the resolution the detector worked at.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DefectCategory(str, Enum):
    """The five defect categories in scope (SRS §3, FR-3 a–e)."""

    NPC_ANOMALY = "npc_anomaly"
    TEXTURE_POP_IN = "texture_pop_in"
    FPS_DROP = "fps_drop"
    ANIMATION_GLITCH = "animation_glitch"
    COLLISION_CLIPPING = "collision_clipping"


# Sub-types named in FR-3. A detection's subtype must belong to its category.
SUBTYPES: dict[DefectCategory, frozenset[str]] = {
    DefectCategory.NPC_ANOMALY: frozenset({"t_pose", "frozen_npc", "floating", "ragdoll"}),
    DefectCategory.TEXTURE_POP_IN: frozenset(
        {"texture_pop_in", "unrendered_texture", "mesh_lod_change"}
    ),
    DefectCategory.FPS_DROP: frozenset({"fps_drop", "frozen_frame"}),
    DefectCategory.ANIMATION_GLITCH: frozenset(
        {"unnatural_transition", "missing_keyframe", "flicker", "jitter"}
    ),
    DefectCategory.COLLISION_CLIPPING: frozenset(
        {"character_character", "character_object", "character_geometry"}
    ),
}


class Severity(str, Enum):
    """FR-5 severity bands. Assigned in Phase 9, never by detectors themselves."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class BoundingBox(BaseModel):
    """Axis-aligned box, normalised to the frame: (x, y) top-left, (w, h) size."""

    model_config = ConfigDict(frozen=True)

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _inside_frame(self) -> BoundingBox:
        eps = 1e-6
        if self.x + self.w > 1.0 + eps or self.y + self.h > 1.0 + eps:
            raise ValueError("bounding box extends outside the frame")
        return self

    @property
    def area(self) -> float:
        return self.w * self.h

    @classmethod
    def from_pixels(
        cls, x1: float, y1: float, x2: float, y2: float, width: int, height: int
    ) -> BoundingBox:
        """Build from pixel corner coordinates, clipping to the frame."""
        x1, x2 = sorted((max(0.0, min(x1, width)), max(0.0, min(x2, width))))
        y1, y2 = sorted((max(0.0, min(y1, height)), max(0.0, min(y2, height))))
        return cls(x=x1 / width, y=y1 / height, w=(x2 - x1) / width, h=(y2 - y1) / height)

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Return (x1, y1, x2, y2) in pixels for a frame of the given size."""
        return (
            round(self.x * width),
            round(self.y * height),
            round((self.x + self.w) * width),
            round((self.y + self.h) * height),
        )


class Evidence(BaseModel):
    """Evidence artefacts attached in Phase 9 (FR-4). Paths are relative to the
    evidence storage root so they can be served by authenticated endpoints."""

    screenshot_path: str | None = None
    clip_path: str | None = None
    clip_start_s: float | None = Field(default=None, ge=0.0)
    clip_end_s: float | None = Field(default=None, ge=0.0)


MetricValue = float | int | str | bool


class Detection(BaseModel):
    """One defect found in a video. The unit of output for every detector."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    category: DefectCategory
    subtype: str
    detector: str
    detector_version: str

    start_time_s: float = Field(ge=0.0)
    end_time_s: float = Field(ge=0.0)
    peak_time_s: float = Field(ge=0.0, description="Most representative moment; screenshot time")
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    peak_frame: int = Field(ge=0)

    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BoundingBox | None = Field(default=None, description="Affected region at the peak frame")
    affected_area_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    description: str = ""
    metrics: dict[str, MetricValue] = Field(
        default_factory=dict, description="Detector-specific measurements behind the decision"
    )

    # Filled in later phases — never by detectors.
    severity: Severity | None = None
    severity_reason: str | None = None
    occurrence_group: str | None = Field(default=None, description="Recurrence group id (Phase 9)")
    evidence: Evidence | None = None

    @field_validator("subtype")
    @classmethod
    def _normalise_subtype(cls, v: str) -> str:
        return v.strip().lower()

    @model_validator(mode="after")
    def _check_consistency(self) -> Detection:
        if self.subtype not in SUBTYPES[self.category]:
            allowed = ", ".join(sorted(SUBTYPES[self.category]))
            raise ValueError(
                f"subtype '{self.subtype}' is not valid for {self.category.value}; allowed: {allowed}"
            )
        if self.end_time_s < self.start_time_s:
            raise ValueError("end_time_s must be >= start_time_s")
        if not (self.start_time_s <= self.peak_time_s <= self.end_time_s):
            raise ValueError("peak_time_s must lie within [start_time_s, end_time_s]")
        if self.end_frame < self.start_frame:
            raise ValueError("end_frame must be >= start_frame")
        if not (self.start_frame <= self.peak_frame <= self.end_frame):
            raise ValueError("peak_frame must lie within [start_frame, end_frame]")
        if self.affected_area_ratio is None and self.bbox is not None:
            self.affected_area_ratio = round(self.bbox.area, 6)
        return self

    @property
    def duration_s(self) -> float:
        return self.end_time_s - self.start_time_s


class TimingStats(BaseModel):
    """Frame presentation-interval statistics from container timestamps (FR-2).

    For a constant-frame-rate recording every interval equals 1/fps and
    ``irregular_intervals`` is 0. Gaps in a variable-frame-rate recording show up as
    irregular intervals — the raw material for FPS-drop analysis (Phase 3)."""

    n_intervals: int = Field(ge=0)
    median_interval_s: float | None = None
    min_interval_s: float | None = None
    max_interval_s: float | None = None
    irregular_intervals: int = Field(default=0, ge=0, description="|d - median| > 25% of median")
    irregular_fraction: float = Field(default=0.0, ge=0.0, le=1.0)


class VideoInfo(BaseModel):
    """Metadata of a source video. Populated by the video engine (Phase 2)."""

    source_path: str
    container: str | None = None
    codec: str | None = None
    width: int = Field(gt=0, description="Displayed width (after rotation)")
    height: int = Field(gt=0, description="Displayed height (after rotation)")
    fps_nominal: float = Field(gt=0.0, description="Container/stream frame rate")
    frame_count: int | None = Field(default=None, ge=0)
    duration_s: float | None = Field(default=None, ge=0.0)
    is_vfr: bool | None = Field(default=None, description="Variable frame rate recording")
    rotation: int = 0
    # Added in Phase 2
    fps_average: float | None = Field(default=None, description="frames / duration")
    start_time_s: float = Field(default=0.0, description="PTS of first frame in the container")
    file_size_bytes: int | None = Field(default=None, ge=0)
    fingerprint: str | None = Field(
        default=None, description="sha256 of size + first/last 4 MiB (fast identity check)"
    )
    pix_fmt: str | None = None
    bit_depth: int | None = None
    color_transfer: str | None = None
    is_hdr: bool = False
    has_audio: bool = False
    timing: TimingStats | None = None
    declared_frame_count: int | None = Field(default=None, description="Frame count in the container index")
    declared_duration_s: float | None = Field(default=None, description="Duration in the container header")
    truncation_suspected: bool = Field(
        default=False, description="Fewer frames / shorter span present than the container declares"
    )


class DetectionSet(BaseModel):
    """A list of detections for one video — the format consumed by evaluation and,
    later, by the reporting layer."""

    video_id: str
    video: VideoInfo | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    detections: list[Detection] = Field(default_factory=list)


class Frame:
    """A decoded, normalised frame handed to detectors.

    A plain class with ``__slots__`` (not pydantic): it carries a numpy image and is
    created thousands of times per video.

    ``image`` (normalised BGR uint8) is computed lazily on first access: the decoder
    yields every frame for full-rate analysis, but most detectors only look at the
    sampled frames, and resizing every 60 FPS 1080p frame would dominate the cost.
    ``raw`` is the decoded frame at original resolution.
    """

    __slots__ = ("index", "timestamp_s", "original_size", "is_sampled", "extras",
                 "raw", "_image", "_normalise")

    def __init__(
        self,
        index: int,
        timestamp_s: float,
        original_size: tuple[int, int],
        image: np.ndarray | None = None,
        is_sampled: bool = True,
        extras: dict[str, Any] | None = None,
        raw: np.ndarray | None = None,
        normalise: Callable[[np.ndarray], np.ndarray] | None = None,
    ):
        if image is None and (raw is None or normalise is None):
            raise ValueError("Frame needs either image, or raw + normalise")
        self.index = index  # index in the original full-rate stream
        self.timestamp_s = timestamp_s  # presentation timestamp, seconds from first frame
        self.original_size = original_size  # (width, height) of the source frame
        self.is_sampled = is_sampled  # on the 10-15 FPS analysis grid
        self.extras: dict[str, Any] = extras if extras is not None else {}  # per-frame cache
        self.raw = raw
        self._image = image
        self._normalise = normalise

    @property
    def image(self) -> np.ndarray:
        if self._image is None:
            self._image = self._normalise(self.raw)  # type: ignore[misc]
        return self._image

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.image.shape[:2]
        return w, h

    def gray(self) -> np.ndarray:
        """Greyscale of the normalised image, computed once and shared by detectors."""
        g = self.extras.get("gray")
        if g is None:
            import cv2

            g = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
            self.extras["gray"] = g
        return g

    def __repr__(self) -> str:
        return (f"Frame(index={self.index}, t={self.timestamp_s:.3f}s, "
                f"sampled={self.is_sampled}, original={self.original_size})")
