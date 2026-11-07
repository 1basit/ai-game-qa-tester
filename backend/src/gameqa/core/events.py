"""Temporal persistence: turning per-frame candidate signals into events.

FR-3 requires that "a candidate detection shall be reported only if it persists across
consecutive frames or frame pairs, so that single-frame noise is suppressed". Every
detector needs the same logic, so it lives here once instead of five times.

A detector calls ``update()`` for each frame it analyses, saying whether the defect
condition was active on that frame and how strongly. The accumulator groups active
frames into events, tolerates short dropouts (``max_gap_s``) and only emits events that
lasted long enough (``min_frames`` active observations and ``min_duration_s``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from gameqa.core.schemas import BoundingBox


class PersistenceRule(BaseModel):
    """Configurable persistence thresholds (see config/default.yaml)."""

    min_frames: int = Field(default=2, ge=1, description="Minimum active observations")
    min_duration_s: float = Field(
        default=0.0, ge=0.0, description="Minimum time between first and last active frame"
    )
    max_gap_s: float = Field(
        default=0.0,
        ge=0.0,
        description="Inactive time tolerated inside one event before it is closed",
    )


@dataclass
class Event:
    """A persistent run of active frames."""

    start_frame: int
    start_time_s: float
    end_frame: int
    end_time_s: float
    peak_frame: int
    peak_time_s: float
    peak_score: float
    n_active: int
    peak_bbox: BoundingBox | None = None
    peak_data: dict[str, Any] = field(default_factory=dict)
    score_sum: float = 0.0

    @property
    def duration_s(self) -> float:
        return self.end_time_s - self.start_time_s

    @property
    def mean_score(self) -> float:
        return self.score_sum / self.n_active if self.n_active else 0.0


class EventAccumulator:
    """Streaming grouping of active frames into persistent events.

    Frames must be fed in increasing timestamp order. ``update`` returns the events
    that were *closed* by that call (usually none), so a detector can emit results
    incrementally; ``flush`` closes whatever is still open at the end of the video.
    """

    def __init__(self, rule: PersistenceRule | None = None):
        self.rule = rule or PersistenceRule()
        self._open: Event | None = None
        self._last_ts: float | None = None

    def update(
        self,
        frame_index: int,
        timestamp_s: float,
        active: bool,
        score: float = 1.0,
        bbox: BoundingBox | None = None,
        data: dict[str, Any] | None = None,
    ) -> list[Event]:
        if self._last_ts is not None and timestamp_s < self._last_ts:
            raise ValueError(
                f"frames must be in timestamp order ({timestamp_s} < {self._last_ts})"
            )
        self._last_ts = timestamp_s
        closed: list[Event] = []

        if not active:
            ev = self._open
            if ev is not None and timestamp_s - ev.end_time_s > self.rule.max_gap_s:
                closed.extend(self._close())
            return closed

        ev = self._open
        if ev is None:
            self._open = Event(
                start_frame=frame_index,
                start_time_s=timestamp_s,
                end_frame=frame_index,
                end_time_s=timestamp_s,
                peak_frame=frame_index,
                peak_time_s=timestamp_s,
                peak_score=score,
                n_active=1,
                peak_bbox=bbox,
                peak_data=dict(data or {}),
                score_sum=score,
            )
            return closed

        ev.end_frame = frame_index
        ev.end_time_s = timestamp_s
        ev.n_active += 1
        ev.score_sum += score
        if score > ev.peak_score:
            ev.peak_score = score
            ev.peak_frame = frame_index
            ev.peak_time_s = timestamp_s
            ev.peak_bbox = bbox
            ev.peak_data = dict(data or {})
        return closed

    def flush(self) -> list[Event]:
        """Close any open event (call once at the end of the video)."""
        return self._close()

    def _close(self) -> list[Event]:
        ev, self._open = self._open, None
        if ev is None:
            return []
        if ev.n_active < self.rule.min_frames or ev.duration_s < self.rule.min_duration_s:
            return []
        return [ev]
