"""Ground-truth label format for detector evaluation.

One JSON file per video in ``evaluation/ground_truth/``. A label file records which
categories a human actually *reviewed* for that video: a reviewed category with no
events means "this footage is clean for that category", so any prediction there is a
false positive. Categories that were not reviewed are not scored at all — this lets a
team label one category at a time without corrupting the metrics of the others.

Example::

    {
      "video_id": "skyrim_cave_01",
      "video_file": "evaluation/videos/skyrim_cave_01.mp4",
      "duration_s": 182.4,
      "reviewed_categories": ["fps_drop", "texture_pop_in"],
      "annotator": "Husnain",
      "events": [
        {"category": "fps_drop", "subtype": "frozen_frame", "start_s": 41.2, "end_s": 42.0},
        {"category": "texture_pop_in", "start_s": 77.5, "end_s": 77.9,
         "bbox": {"x": 0.4, "y": 0.2, "w": 0.2, "h": 0.3}, "notes": "rock texture"}
      ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from gameqa.core.schemas import SUBTYPES, BoundingBox, DefectCategory


class GroundTruthEvent(BaseModel):
    category: DefectCategory
    subtype: str | None = None
    start_s: float = Field(ge=0.0)
    end_s: float = Field(ge=0.0)
    bbox: BoundingBox | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> GroundTruthEvent:
        if self.end_s < self.start_s:
            raise ValueError("end_s must be >= start_s")
        if self.subtype is not None:
            self.subtype = self.subtype.strip().lower()
            if self.subtype not in SUBTYPES[self.category]:
                raise ValueError(f"subtype '{self.subtype}' invalid for {self.category.value}")
        return self


class IgnoreInterval(BaseModel):
    """A stretch where the defect definition does not apply (e.g. a video-editing cut in
    third-party footage). Predictions overlapping it are neither TP nor FP."""

    start_s: float = Field(ge=0.0)
    end_s: float = Field(ge=0.0)
    category: DefectCategory | None = None  # None = all categories
    reason: str = ""


class GroundTruthFile(BaseModel):
    video_id: str
    video_file: str | None = None
    duration_s: float | None = Field(default=None, gt=0.0)
    reviewed_categories: list[DefectCategory]
    annotator: str = ""
    source: str = Field(default="", description="e.g. self-recorded, public (URL), synthetic")
    synthetic: bool = Field(default=False, description="True if defects were injected artificially")
    events: list[GroundTruthEvent] = Field(default_factory=list)
    ignore: list[IgnoreInterval] = Field(default_factory=list)

    @model_validator(mode="after")
    def _events_in_reviewed(self) -> GroundTruthFile:
        reviewed = set(self.reviewed_categories)
        for ev in self.events:
            if ev.category not in reviewed:
                raise ValueError(
                    f"event of category {ev.category.value} is labelled but the category "
                    "is not listed in reviewed_categories"
                )
            if self.duration_s is not None and ev.end_s > self.duration_s + 1e-3:
                raise ValueError(f"event ends at {ev.end_s}s, after video end {self.duration_s}s")
        return self


def load_ground_truth(path: str | Path) -> GroundTruthFile:
    with open(path, encoding="utf-8") as f:
        return GroundTruthFile.model_validate(json.load(f))
