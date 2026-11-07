"""Recurrence grouping and rule-based severity (FR-5).

The SRS defines the bands by what a defect means for a player:
  Low    — visual-only, does not affect gameplay
  Medium — affects gameplay without blocking it
  High   — a collision problem or a severe performance issue
and asks for rules based on affected area, duration and recurrence. Gameplay impact is
not observable from pixels, so the category gives the starting band (the SRS's own
mapping) and measurable properties move a detection up. Every decision is stored as a
human-readable reason.

The numeric thresholds are configuration (``severity`` section). They encode the SRS
definitions; they could not be calibrated against human severity ratings because no
labelled severities exist for this project — that is a documented limitation.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from pydantic import BaseModel, Field

from gameqa.core.schemas import BoundingBox, DefectCategory, Detection, Severity

ORDER = [Severity.LOW, Severity.MEDIUM, Severity.HIGH]


class SeverityConfig(BaseModel):
    large_area: float = Field(default=0.25, description="affected area share that counts as large")
    long_s: float = Field(default=2.0, description="duration that counts as long")
    recurrent_count: int = Field(default=3, description="occurrences of the same defect that count as recurring")
    severe_freeze_s: float = Field(default=1.0, description="frozen picture this long = severe performance issue")
    severe_drop_ratio: float = Field(default=0.5, description="effective FPS below this share of target = severe")
    severe_drop_s: float = Field(default=3.0, description="FPS drop lasting this long = severe")
    group_iou: float = Field(default=0.3, description="boxes overlapping this much are the same place on screen")


def _iou(a: BoundingBox | None, b: BoundingBox | None) -> float:
    if a is None or b is None:
        return 1.0  # whole-frame defects (no box) recur by definition of category
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def group_recurrences(detections: list[Detection], cfg: SeverityConfig) -> None:
    """Same category + subtype + overlapping screen region (or no region) = same defect
    recurring. Sets ``occurrence_group`` and ``metrics['recurrence_count']``."""
    groups: dict[tuple[str, str], list[list[Detection]]] = defaultdict(list)
    for d in sorted(detections, key=lambda x: x.start_time_s):
        key = (d.category.value, d.subtype)
        for g in groups[key]:
            if _iou(g[0].bbox, d.bbox) >= cfg.group_iou:
                g.append(d)
                break
        else:
            groups[key].append([d])
    for gl in groups.values():
        for g in gl:
            gid = uuid.uuid4().hex[:12]
            for i, d in enumerate(g):
                d.occurrence_group = gid
                d.metrics["recurrence_count"] = len(g)
                d.metrics["recurrence_index"] = i + 1


def _area(d: Detection) -> float:
    if d.affected_area_ratio is not None:
        return d.affected_area_ratio
    return d.bbox.area if d.bbox else 1.0


def classify(d: Detection, cfg: SeverityConfig) -> tuple[Severity, str]:
    reasons: list[str] = []
    cat, sub = d.category, d.subtype
    area, dur = _area(d), d.duration_s
    rec = int(d.metrics.get("recurrence_count", 1))

    if cat is DefectCategory.COLLISION_CLIPPING:
        return Severity.HIGH, "collision / clipping problem (SRS: High)"

    if cat is DefectCategory.FPS_DROP:
        level = Severity.MEDIUM
        reasons.append("performance issue (affects gameplay)")
        if sub == "frozen_frame":
            hold_s = float(d.metrics.get("hold_ms", dur * 1000)) / 1000
            if hold_s >= cfg.severe_freeze_s:
                level = Severity.HIGH
                reasons.append(f"picture frozen {hold_s:.1f} s >= {cfg.severe_freeze_s:g} s (severe)")
        else:
            eff, target = d.metrics.get("min_effective_fps"), d.metrics.get("target_fps")
            if isinstance(eff, (int, float)) and isinstance(target, (int, float)) and target \
                    and eff < cfg.severe_drop_ratio * target:
                level = Severity.HIGH
                reasons.append(f"effective {eff:.0f} FPS < {cfg.severe_drop_ratio:.0%} of {target:.0f} FPS target (severe)")
            if dur >= cfg.severe_drop_s:
                level = Severity.HIGH
                reasons.append(f"drop lasted {dur:.1f} s >= {cfg.severe_drop_s:g} s (severe)")
        return level, "; ".join(reasons)

    if cat is DefectCategory.NPC_ANOMALY:
        level, reasons = Severity.MEDIUM, ["character behaviour broken (affects gameplay)"]
    elif cat is DefectCategory.TEXTURE_POP_IN:
        if sub == "unrendered_texture":
            level, reasons = Severity.MEDIUM, ["missing texture (visible content error)"]
        else:
            level, reasons = Severity.LOW, ["visual only"]
    else:  # animation glitch
        level, reasons = Severity.LOW, ["visual only"]

    bump = []
    if area >= cfg.large_area:
        bump.append(f"large area {area:.0%} >= {cfg.large_area:.0%}")
    if dur >= cfg.long_s:
        bump.append(f"lasted {dur:.1f} s >= {cfg.long_s:g} s")
    if rec >= cfg.recurrent_count:
        bump.append(f"recurs {rec}x >= {cfg.recurrent_count}")
    if bump:
        new = ORDER[min(len(ORDER) - 1, ORDER.index(level) + 1)]
        if new is not level:
            reasons.append("raised: " + ", ".join(bump))
        level = new
    return level, "; ".join(reasons)


def apply_severity(detections: list[Detection], cfg: SeverityConfig | None = None) -> list[Detection]:
    cfg = cfg or SeverityConfig()
    group_recurrences(detections, cfg)
    for d in detections:
        d.severity, d.severity_reason = classify(d, cfg)
    return detections
