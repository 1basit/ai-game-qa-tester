"""Detector evaluation: temporal matching and precision / recall / F1.

Matching rule (per category, one-to-one, greedy):
  a prediction and a ground-truth event of the same category match if
    temporal IoU >= ``iou_threshold``   OR
    the prediction's peak time lies within the GT interval widened by ``peak_tolerance_s``.
  Short defects (a single frozen frame, a 0.3 s pop-in) have near-zero-length intervals
  where IoU is unstable, which is why the peak rule exists.
  Pairs are matched in order of decreasing IoU, then increasing peak distance.
  Unmatched predictions are false positives; unmatched GT events are false negatives.
  Two predictions for one GT event = 1 TP + 1 FP (detectors must merge duplicates).

Only categories listed in the label file's ``reviewed_categories`` are scored.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field

from gameqa.core.schemas import DefectCategory, Detection
from gameqa.evaluation.ground_truth import GroundTruthEvent, GroundTruthFile


def temporal_iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """IoU of two closed time intervals.

    A zero-length interval has zero intersection with anything except an identical
    point (IoU 1.0); such detections are matched through the peak rule instead."""
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    if union <= 0.0:  # both intervals are the same single point
        return 1.0
    return inter / union


def _safe_div(n: float, d: float) -> float | None:
    return n / d if d > 0 else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None:
        return None
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


class MatchRecord(BaseModel):
    detection_id: str
    gt_index: int
    tiou: float
    peak_error_s: float = Field(description="prediction peak minus GT interval centre")


class PredictionSummary(BaseModel):
    detection_id: str
    subtype: str
    start_s: float
    end_s: float
    peak_s: float
    confidence: float


class CategoryResult(BaseModel):
    category: DefectCategory
    n_predictions: int
    n_ground_truth: int
    tp: int
    fp: int
    fn: int
    precision: float | None
    recall: float | None
    f1: float | None
    fp_per_minute: float | None = None
    matches: list[MatchRecord] = Field(default_factory=list)
    false_positives: list[PredictionSummary] = Field(default_factory=list)
    false_negatives: list[GroundTruthEvent] = Field(default_factory=list)


class VideoEvaluation(BaseModel):
    video_id: str
    synthetic: bool
    duration_s: float | None
    per_category: dict[str, CategoryResult]
    unscored_predictions: int = Field(description="Predictions in categories not reviewed")
    ignored_predictions: int = Field(default=0, description="Predictions inside ignore intervals")


class AggregateResult(BaseModel):
    category: DefectCategory
    videos: int
    tp: int
    fp: int
    fn: int
    precision: float | None
    recall: float | None
    f1: float | None
    total_minutes: float | None
    fp_per_minute: float | None


def _match_category(
    preds: Sequence[Detection],
    gts: Sequence[GroundTruthEvent],
    iou_threshold: float,
    peak_tolerance_s: float,
    match_subtype: bool,
) -> tuple[list[MatchRecord], list[int], list[int]]:
    candidates: list[tuple[float, float, int, int]] = []
    for i, p in enumerate(preds):
        for j, g in enumerate(gts):
            if match_subtype and g.subtype is not None and g.subtype != p.subtype:
                continue
            iou = temporal_iou(p.start_time_s, p.end_time_s, g.start_s, g.end_s)
            peak_ok = g.start_s - peak_tolerance_s <= p.peak_time_s <= g.end_s + peak_tolerance_s
            if iou >= iou_threshold or peak_ok:
                dist = abs(p.peak_time_s - (g.start_s + g.end_s) / 2)
                candidates.append((iou, dist, i, j))
    candidates.sort(key=lambda c: (-c[0], c[1]))

    used_p: set[int] = set()
    used_g: set[int] = set()
    matches: list[MatchRecord] = []
    for iou, _dist, i, j in candidates:
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        g = gts[j]
        matches.append(
            MatchRecord(
                detection_id=preds[i].id,
                gt_index=j,
                tiou=round(iou, 4),
                peak_error_s=round(preds[i].peak_time_s - (g.start_s + g.end_s) / 2, 4),
            )
        )
    unmatched_p = [i for i in range(len(preds)) if i not in used_p]
    unmatched_g = [j for j in range(len(gts)) if j not in used_g]
    return matches, unmatched_p, unmatched_g


def evaluate_video(
    detections: Iterable[Detection],
    ground_truth: GroundTruthFile,
    iou_threshold: float = 0.3,
    peak_tolerance_s: float = 0.5,
    match_subtype: bool = False,
) -> VideoEvaluation:
    detections = list(detections)
    reviewed = list(dict.fromkeys(ground_truth.reviewed_categories))
    per_cat: dict[str, CategoryResult] = {}
    minutes = ground_truth.duration_s / 60 if ground_truth.duration_s else None

    def ignored(d: Detection) -> bool:
        """Ignored if at least half of the prediction (or its peak, for zero-length
        predictions) lies inside an ignore interval. Touching an interval is not enough:
        a 3 s detection overlapping an ignore interval by 0.05 s must still be scored."""
        for ig in ground_truth.ignore:
            if ig.category is not None and ig.category != d.category:
                continue
            dur = d.end_time_s - d.start_time_s
            if dur <= 0:
                if ig.start_s <= d.peak_time_s <= ig.end_s:
                    return True
                continue
            inter = max(0.0, min(d.end_time_s, ig.end_s) - max(d.start_time_s, ig.start_s))
            if inter >= 0.5 * dur:
                return True
        return False

    n_ignored = sum(1 for d in detections if ignored(d))
    detections = [d for d in detections if not ignored(d)]
    for cat in reviewed:
        preds = [d for d in detections if d.category == cat]
        gts = [e for e in ground_truth.events if e.category == cat]
        matches, fp_idx, fn_idx = _match_category(
            preds, gts, iou_threshold, peak_tolerance_s, match_subtype
        )
        tp, fp, fn = len(matches), len(fp_idx), len(fn_idx)
        p, r = _safe_div(tp, tp + fp), _safe_div(tp, tp + fn)
        per_cat[cat.value] = CategoryResult(
            category=cat,
            n_predictions=len(preds),
            n_ground_truth=len(gts),
            tp=tp,
            fp=fp,
            fn=fn,
            precision=p,
            recall=r,
            f1=_f1(p, r),
            fp_per_minute=(fp / minutes) if minutes else None,
            matches=matches,
            false_positives=[
                PredictionSummary(
                    detection_id=preds[i].id,
                    subtype=preds[i].subtype,
                    start_s=preds[i].start_time_s,
                    end_s=preds[i].end_time_s,
                    peak_s=preds[i].peak_time_s,
                    confidence=preds[i].confidence,
                )
                for i in fp_idx
            ],
            false_negatives=[gts[j] for j in fn_idx],
        )

    reviewed_set = set(reviewed)
    return VideoEvaluation(
        video_id=ground_truth.video_id,
        synthetic=ground_truth.synthetic,
        duration_s=ground_truth.duration_s,
        per_category=per_cat,
        unscored_predictions=sum(1 for d in detections if d.category not in reviewed_set),
        ignored_predictions=n_ignored,
    )


def aggregate(evaluations: Iterable[VideoEvaluation]) -> dict[str, AggregateResult]:
    """Micro-average (sum TP/FP/FN) across videos, per category."""
    acc: dict[str, dict[str, float]] = {}
    for ev in evaluations:
        for cat, res in ev.per_category.items():
            a = acc.setdefault(cat, {"videos": 0, "tp": 0, "fp": 0, "fn": 0, "minutes": 0.0, "timed": 1})
            a["videos"] += 1
            a["tp"] += res.tp
            a["fp"] += res.fp
            a["fn"] += res.fn
            if ev.duration_s:
                a["minutes"] += ev.duration_s / 60
            else:
                a["timed"] = 0
    out: dict[str, AggregateResult] = {}
    for cat, a in acc.items():
        tp, fp, fn = int(a["tp"]), int(a["fp"]), int(a["fn"])
        p, r = _safe_div(tp, tp + fp), _safe_div(tp, tp + fn)
        minutes = a["minutes"] if a["timed"] else None
        out[cat] = AggregateResult(
            category=DefectCategory(cat),
            videos=int(a["videos"]),
            tp=tp,
            fp=fp,
            fn=fn,
            precision=p,
            recall=r,
            f1=_f1(p, r),
            total_minutes=minutes,
            fp_per_minute=(fp / minutes) if minutes else None,
        )
    return out


def format_markdown(results: dict[str, AggregateResult]) -> str:
    def f(v: float | None) -> str:
        return "n/a" if v is None else f"{v:.3f}"

    lines = [
        "| Category | Videos | TP | FP | FN | Precision | Recall | F1 | FP/min |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for cat, r in sorted(results.items()):
        lines.append(
            f"| {cat} | {r.videos} | {r.tp} | {r.fp} | {r.fn} | {f(r.precision)} | "
            f"{f(r.recall)} | {f(r.f1)} | {f(r.fp_per_minute)} |"
        )
    return "\n".join(lines)
