import json

import numpy as np
import pytest
from pydantic import ValidationError

from gameqa.core import BoundingBox, DefectCategory, Detection, DetectionSet, Frame, Severity


def make_det(**kw):
    base = dict(
        category=DefectCategory.FPS_DROP,
        subtype="frozen_frame",
        detector="fps_drop",
        detector_version="0.1",
        start_time_s=10.0,
        end_time_s=11.0,
        peak_time_s=10.5,
        start_frame=600,
        end_frame=660,
        peak_frame=630,
        confidence=0.9,
    )
    base.update(kw)
    return Detection(**base)


def test_detection_roundtrip_json():
    d = make_det(bbox=BoundingBox(x=0.1, y=0.2, w=0.5, h=0.4), metrics={"fps": 12.5})
    restored = Detection.model_validate_json(d.model_dump_json())
    assert restored == d
    assert restored.duration_s == pytest.approx(1.0)
    assert restored.affected_area_ratio == pytest.approx(0.2)  # derived from bbox


def test_subtype_must_belong_to_category():
    with pytest.raises(ValidationError, match="not valid for fps_drop"):
        make_det(subtype="t_pose")


def test_subtype_is_normalised():
    assert make_det(subtype="  Frozen_Frame ").subtype == "frozen_frame"


@pytest.mark.parametrize(
    "kw, msg",
    [
        (dict(end_time_s=9.0, peak_time_s=9.0), "end_time_s"),
        (dict(peak_time_s=12.0), "peak_time_s"),
        (dict(end_frame=500, peak_frame=500), "end_frame"),
        (dict(peak_frame=700), "peak_frame"),
        (dict(confidence=1.5), "confidence"),
    ],
)
def test_invalid_detections_rejected(kw, msg):
    with pytest.raises(ValidationError, match=msg):
        make_det(**kw)


def test_bbox_must_lie_inside_frame():
    with pytest.raises(ValidationError, match="outside the frame"):
        BoundingBox(x=0.8, y=0.0, w=0.5, h=0.5)


def test_bbox_pixel_conversion_and_clipping():
    b = BoundingBox.from_pixels(-10, 50, 700, 250, width=640, height=360)
    assert (b.x, b.w) == (0.0, 1.0)  # clipped to the frame
    assert b.to_pixels(640, 360) == (0, 50, 640, 250)
    # resolution independence: same box on the 1080p original
    assert b.to_pixels(1920, 1080) == (0, 150, 1920, 750)


def test_severity_not_set_by_default_and_enum_values():
    d = make_det()
    assert d.severity is None
    assert {s.value for s in Severity} == {"low", "medium", "high"}


def test_detection_set_serialises():
    ds = DetectionSet(video_id="v1", detections=[make_det(), make_det()])
    data = json.loads(ds.model_dump_json())
    assert data["video_id"] == "v1" and len(data["detections"]) == 2
    assert len({d["id"] for d in data["detections"]}) == 2  # ids are unique


def test_frame_gray_is_cached():
    img = np.zeros((4, 6, 3), dtype=np.uint8)
    img[..., 2] = 255  # pure red in BGR
    f = Frame(index=0, timestamp_s=0.0, image=img, original_size=(1920, 1080))
    g1 = f.gray()
    assert g1.shape == (4, 6) and int(g1[0, 0]) == 76  # ITU-R BT.601 luma of red
    assert f.gray() is g1
    assert f.size == (6, 4)
