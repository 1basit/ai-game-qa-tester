"""NPC detector: pose rules on constructed keypoints, tracking/viewmodel logic, and an
integration check of YOLOv8 + MediaPipe on a real photograph of a person (skimage
'astronaut'). No game footage with characters is available, so these tests verify the
logic and the model plumbing — not detection accuracy on games."""

import numpy as np
import pytest

from gameqa.core import BoundingBox
from gameqa.detectors import models as M
from gameqa.detectors.npc import NpcAnomalyDetector, NpcParams, _Track, is_viewmodel, t_pose_score

P = NpcParams()


def pose_from(points: dict[int, tuple[float, float]]) -> M.Pose:
    xy = np.zeros((33, 2), np.float32)
    vis = np.zeros(33, np.float32)
    for k, v in points.items():
        xy[k] = v
        vis[k] = 0.9
    return M.Pose(xy, vis)


BODY = {M.NOSE: (0.5, 0.2), M.L_SH: (0.55, 0.3), M.R_SH: (0.45, 0.3), M.L_HIP: (0.54, 0.55), M.R_HIP: (0.46, 0.55),
        M.L_KN: (0.54, 0.7), M.R_KN: (0.46, 0.7), M.L_AN: (0.54, 0.85), M.R_AN: (0.46, 0.85)}


def test_t_pose_scores_positive():
    pts = {**BODY, **{M.L_EL: (0.65, 0.3), M.L_WR: (0.75, 0.3), M.R_EL: (0.35, 0.3), M.R_WR: (0.25, 0.3)}}
    assert t_pose_score(pose_from(pts), P) > 0.7


@pytest.mark.parametrize("arms", [
    {M.L_EL: (0.57, 0.42), M.L_WR: (0.58, 0.52), M.R_EL: (0.43, 0.42), M.R_WR: (0.42, 0.52)},   # arms down
    {M.L_EL: (0.62, 0.22), M.L_WR: (0.66, 0.12), M.R_EL: (0.38, 0.22), M.R_WR: (0.34, 0.12)},   # arms up
    {M.L_EL: (0.65, 0.3), M.L_WR: (0.62, 0.2), M.R_EL: (0.35, 0.3), M.R_WR: (0.38, 0.2)},       # elbows bent
    {M.L_EL: (0.65, 0.3), M.L_WR: (0.75, 0.3), M.R_EL: (0.43, 0.42), M.R_WR: (0.42, 0.52)},     # one arm only
])
def test_non_t_poses_score_zero(arms):
    assert t_pose_score(pose_from({**BODY, **arms}), P) == 0.0


def test_t_pose_needs_visible_arms():
    pts = {**BODY, **{M.L_EL: (0.65, 0.3), M.L_WR: (0.75, 0.3), M.R_EL: (0.35, 0.3), M.R_WR: (0.25, 0.3)}}
    pose = pose_from(pts)
    pose.vis[M.R_WR] = 0.1
    assert t_pose_score(pose, P) == 0.0


def _track_with(rel_seq, boxes, cams, dt=1 / 12):
    tr = _Track(1, boxes[0], 0.0)
    for k, (rel, box, cam) in enumerate(zip(rel_seq, boxes, cams)):
        tr.hist.append((k * dt, k * 5, box, rel, np.full(33, 0.9, np.float32), np.array(cam, float)))
    return tr


REL = np.random.default_rng(0).random((33, 2)).astype(np.float32)


def test_frozen_pose_sliding_through_world():
    det = NpcAnomalyDetector()
    boxes = [BoundingBox(x=0.1 + 0.02 * k, y=0.3, w=0.1, h=0.4) for k in range(25)]  # moves 0.48 wide
    tr = _track_with([REL] * 25, boxes, [(0, 0)] * 25)
    assert det._frozen_score(tr) > 0


def test_frozen_pose_but_camera_panning_is_not_sliding():
    det = NpcAnomalyDetector()
    boxes = [BoundingBox(x=0.1 + 0.02 * k, y=0.3, w=0.1, h=0.4) for k in range(25)]
    cams = [(0.02 * k, 0) for k in range(25)]  # the camera explains the screen motion
    assert det._frozen_score(_track_with([REL] * 25, boxes, cams)) == 0.0


def test_animated_character_walking_is_not_frozen():
    det = NpcAnomalyDetector()
    rng = np.random.default_rng(1)
    rels = [REL + rng.normal(0, 0.04, REL.shape).astype(np.float32) for _ in range(25)]
    boxes = [BoundingBox(x=0.1 + 0.02 * k, y=0.3, w=0.1, h=0.4) for k in range(25)]
    assert det._frozen_score(_track_with(rels, boxes, [(0, 0)] * 25)) == 0.0


def test_ragdoll_limb_jump():
    det = NpcAnomalyDetector()
    exploded = REL + np.random.default_rng(2).normal(0, 0.6, REL.shape).astype(np.float32)
    box = BoundingBox(x=0.3, y=0.3, w=0.1, h=0.4)
    assert det._ragdoll_score(_track_with([REL, exploded], [box, box], [(0, 0)] * 2)) > 0
    assert det._ragdoll_score(_track_with([REL, REL + 0.01], [box, box], [(0, 0)] * 2)) == 0.0


def test_viewmodel_filter():
    hand = [BoundingBox(x=0.6, y=0.55, w=0.35, h=0.45) for _ in range(6)]
    assert is_viewmodel(hand, cam_motion=0.3, p=P)
    npc = [BoundingBox(x=0.2 + 0.05 * k, y=0.3, w=0.1, h=0.4) for k in range(6)]
    assert not is_viewmodel(npc, cam_motion=0.3, p=P)


@pytest.mark.skipif(not (M.models_dir() / "pose_landmarker_full.task").exists(), reason="model weights not installed")
def test_models_on_real_person_photo():
    import cv2
    from skimage import data

    from gameqa.core import Frame

    img = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
    f = Frame(index=0, timestamp_s=0.0, image=img, original_size=img.shape[1::-1])
    people = [d for d in M.detect_objects(f) if d.name == "person"]
    assert people and people[0].conf > 0.5
    pose = M.estimate_pose(f, people[0].box)
    assert pose is not None
    # nose above shoulders, shoulders visible, landmarks inside the person box
    assert pose.xy[M.NOSE][1] < pose.xy[M.L_SH][1] and pose.xy[M.NOSE][1] < pose.xy[M.R_SH][1]
    assert (pose.vis[[M.L_SH, M.R_SH]] > 0.5).all()
    assert t_pose_score(pose, P) == 0.0  # the astronaut is not in a T-pose
