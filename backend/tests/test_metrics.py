"""Metric tests use small cases whose answers were worked out by hand."""

import pytest
from pydantic import ValidationError

from gameqa.core import DefectCategory, Detection
from gameqa.evaluation import GroundTruthFile, aggregate, evaluate_video, temporal_iou

FPS = DefectCategory.FPS_DROP
TEX = DefectCategory.TEXTURE_POP_IN


def det(start, end, peak=None, cat=FPS, subtype="fps_drop", conf=0.8):
    peak = (start + end) / 2 if peak is None else peak
    return Detection(
        category=cat, subtype=subtype, detector="t", detector_version="0",
        start_time_s=start, end_time_s=end, peak_time_s=peak,
        start_frame=int(start * 60), end_frame=int(end * 60), peak_frame=int(peak * 60),
        confidence=conf,
    )


def gt(events, reviewed=(FPS,), duration=120.0, **kw):
    return GroundTruthFile(
        video_id="v", duration_s=duration, reviewed_categories=list(reviewed), events=events, **kw
    )


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ((0, 10), (0, 10), 1.0),
        ((0, 10), (5, 15), 5 / 15),
        ((0, 1), (2, 3), 0.0),
        ((10.5, 12.5), (10, 12), 1.5 / 2.5),
        ((3, 3), (3, 3), 1.0),
        ((3, 3), (2, 4), 0.0),
    ],
)
def test_temporal_iou(a, b, expected):
    assert temporal_iou(*a, *b) == pytest.approx(expected)


def test_hand_computed_case():
    truth = gt(
        [
            {"category": "fps_drop", "start_s": 10, "end_s": 12},
            {"category": "fps_drop", "start_s": 30, "end_s": 31},
            {"category": "fps_drop", "start_s": 50, "end_s": 50.1},
        ]
    )
    preds = [
        det(10.5, 12.5),        # IoU 0.6 -> TP
        det(30.9, 30.9),        # zero-length, peak inside [30, 31] -> TP via peak rule
        det(70, 71),            # nothing there -> FP
    ]                           # GT at 50 s never found -> FN
    r = evaluate_video(preds, truth, iou_threshold=0.3, peak_tolerance_s=0.5).per_category["fps_drop"]
    assert (r.tp, r.fp, r.fn) == (2, 1, 1)
    assert r.precision == pytest.approx(2 / 3)
    assert r.recall == pytest.approx(2 / 3)
    assert r.f1 == pytest.approx(2 / 3)
    assert r.fp_per_minute == pytest.approx(1 / 2)  # 1 FP in 2 minutes
    assert r.false_negatives[0].start_s == 50
    assert r.false_positives[0].start_s == 70


def test_duplicate_predictions_count_as_false_positive():
    truth = gt([{"category": "fps_drop", "start_s": 10, "end_s": 12}])
    r = evaluate_video([det(10, 12), det(10.2, 11.8)], truth).per_category["fps_drop"]
    assert (r.tp, r.fp, r.fn) == (1, 1, 0)


def test_greedy_prefers_best_overlap():
    truth = gt([{"category": "fps_drop", "start_s": 10, "end_s": 12},
                {"category": "fps_drop", "start_s": 12.3, "end_s": 13}])
    # B is a candidate for both GT events (IoU 0.167 with GT0 via the peak rule, 0.467
    # with GT1); A only matches GT0 (IoU 1.0). B is listed first, so a naive
    # first-come assignment would give B->GT0 and leave A unmatched (1 TP).
    b, a = det(11.5, 13), det(10, 12)
    r = evaluate_video([b, a], truth).per_category["fps_drop"]
    assert (r.tp, r.fp, r.fn) == (2, 0, 0)
    pairs = {m.detection_id: m.gt_index for m in r.matches}
    assert pairs == {a.id: 0, b.id: 1}


def test_peak_tolerance_boundary():
    truth = gt([{"category": "fps_drop", "start_s": 10, "end_s": 10.2}])
    near = evaluate_video([det(10.6, 10.6)], truth, peak_tolerance_s=0.5).per_category["fps_drop"]
    far = evaluate_video([det(10.8, 10.8)], truth, peak_tolerance_s=0.5).per_category["fps_drop"]
    assert near.tp == 1 and far.tp == 0


def test_clean_footage_precision_zero_recall_undefined():
    r = evaluate_video([det(5, 6), det(40, 41)], gt([], duration=60.0)).per_category["fps_drop"]
    assert (r.tp, r.fp, r.fn) == (0, 2, 0)
    assert r.precision == 0.0 and r.recall is None and r.f1 is None
    assert r.fp_per_minute == pytest.approx(2.0)


def test_no_predictions_no_gt_everything_undefined():
    r = evaluate_video([], gt([])).per_category["fps_drop"]
    assert (r.precision, r.recall, r.f1) == (None, None, None)


def test_unreviewed_categories_are_not_scored():
    ev = evaluate_video([det(1, 2, cat=TEX, subtype="texture_pop_in")], gt([]))
    assert "texture_pop_in" not in ev.per_category
    assert ev.unscored_predictions == 1


def test_subtype_matching_option():
    truth = gt([{"category": "fps_drop", "subtype": "frozen_frame", "start_s": 10, "end_s": 12}])
    p = [det(10, 12, subtype="fps_drop")]
    assert evaluate_video(p, truth, match_subtype=False).per_category["fps_drop"].tp == 1
    assert evaluate_video(p, truth, match_subtype=True).per_category["fps_drop"].tp == 0


def test_aggregate_micro_average():
    v1 = evaluate_video([det(10, 12), det(70, 71)],
                        gt([{"category": "fps_drop", "start_s": 10, "end_s": 12}], duration=60))
    v2 = evaluate_video([], gt([{"category": "fps_drop", "start_s": 5, "end_s": 6}], duration=60))
    a = aggregate([v1, v2])["fps_drop"]
    assert (a.videos, a.tp, a.fp, a.fn) == (2, 1, 1, 1)
    assert a.precision == pytest.approx(0.5) and a.recall == pytest.approx(0.5)
    assert a.total_minutes == pytest.approx(2.0) and a.fp_per_minute == pytest.approx(0.5)


def test_ground_truth_validation():
    with pytest.raises(ValidationError, match="not listed in reviewed_categories"):
        gt([{"category": "texture_pop_in", "start_s": 1, "end_s": 2}])
    with pytest.raises(ValidationError, match="after video end"):
        gt([{"category": "fps_drop", "start_s": 1, "end_s": 200}], duration=120)
    with pytest.raises(ValidationError, match="invalid for fps_drop"):
        gt([{"category": "fps_drop", "subtype": "t_pose", "start_s": 1, "end_s": 2}])


def test_ignore_intervals_need_majority_overlap():
    truth = gt([{"category": "fps_drop", "start_s": 10, "end_s": 12}],
               ignore=[{"start_s": 11.9, "end_s": 30, "reason": "editor footage"}])
    long_pred = det(10.0, 12.0)        # 0.1 s of 2 s inside the ignore interval -> scored
    inside = det(20.0, 21.0)           # fully inside -> ignored
    point = det(25.0, 25.0)            # zero-length, peak inside -> ignored
    ev = evaluate_video([long_pred, inside, point], truth)
    r = ev.per_category["fps_drop"]
    assert (r.tp, r.fp, r.fn) == (1, 0, 0) and ev.ignored_predictions == 2
