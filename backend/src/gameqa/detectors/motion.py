"""Global (camera) motion compensation shared by the texture and animation detectors.

Pixel differences between consecutive frames are dominated by camera movement. To see
*local* defects, the previous frame is warped onto the current one using a global
similarity transform (translation + rotation + scale) estimated from ORB feature
matches with RANSAC. Low-texture scenes (flat-shaded games, sky) often have too few
features; then phase correlation (pure translation) is used, and if that is also
unreliable the frame pair is marked unaligned so detectors can skip it instead of
reporting camera motion as a defect.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Alignment:
    warped_prev: np.ndarray  # previous frame in current-frame coordinates
    valid: np.ndarray  # bool mask of pixels covered by the warped previous frame
    matrix: np.ndarray  # 2x3 affine prev -> cur
    method: str  # "orb", "phase", "identity"
    reliable: bool
    inliers: int = 0

    @property
    def translation(self) -> tuple[float, float]:
        return float(self.matrix[0, 2]), float(self.matrix[1, 2])


class MotionEstimator:
    def __init__(self, n_features: int = 600, min_inliers: int = 15, min_inlier_ratio: float = 0.3,
                 phase_min_response: float = 0.15, phase_first: bool = False):
        """``phase_first``: try (cheap) phase correlation before ORB. Suited to full-rate
        analysis, where consecutive frames differ by a small, mostly translational shift."""
        self.phase_first = phase_first
        self.orb = cv2.ORB_create(nfeatures=n_features, fastThreshold=10)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.min_inliers = min_inliers
        self.min_inlier_ratio = min_inlier_ratio
        self.phase_min_response = phase_min_response
        self._cache_key: object = None
        self._cache: tuple = (None, None)

    def align(self, prev: np.ndarray, cur: np.ndarray, prev_key: object = None,
              cur_key: object = None) -> Alignment:
        """``prev``/``cur`` are uint8 greyscale images of equal size. If keys are given,
        features of ``cur`` are cached and reused when it becomes ``prev`` next time."""
        h, w = cur.shape
        m, method, inliers = None, "phase", 0
        if self.phase_first:
            m, method = self._phase(prev, cur)
        if m is None:
            m, method, inliers = self._orb(prev, cur, prev_key, cur_key)
        if m is None and not self.phase_first:
            m, method = self._phase(prev, cur)
        reliable = m is not None
        if m is None:
            m, method = np.float32([[1, 0, 0], [0, 1, 0]]), "identity"
        warped = cv2.warpAffine(prev, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        mask = cv2.warpAffine(np.full((h, w), 255, np.uint8), m, (w, h), flags=cv2.INTER_NEAREST)
        mask = cv2.erode(mask, np.ones((5, 5), np.uint8)) > 0
        return Alignment(warped, mask, m, method, reliable, inliers)

    def _orb(self, prev, cur, prev_key, cur_key):
        if prev_key is not None and prev_key == self._cache_key:
            kp1, des1 = self._cache
        else:
            kp1, des1 = self.orb.detectAndCompute(prev, None)
        kp2, des2 = self.orb.detectAndCompute(cur, None)
        self._cache_key, self._cache = cur_key, (kp2, des2)
        if des1 is None or des2 is None or len(kp1) < self.min_inliers or len(kp2) < self.min_inliers:
            return None, "orb", 0
        matches = self.matcher.match(des1, des2)
        if len(matches) < self.min_inliers:
            return None, "orb", 0
        src = np.float32([kp1[mt.queryIdx].pt for mt in matches])
        dst = np.float32([kp2[mt.trainIdx].pt for mt in matches])
        m, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=2.0,
                                             maxIters=500, confidence=0.98)
        if m is None or inl is None:
            return None, "orb", 0
        n_in = int(inl.sum())
        if n_in < self.min_inliers or n_in / len(matches) < self.min_inlier_ratio:
            return None, "orb", n_in
        return m.astype(np.float32), "orb", n_in

    def _phase(self, prev, cur):
        if getattr(self, "_win_shape", None) != cur.shape:
            self._win = cv2.createHanningWindow(cur.shape[::-1], cv2.CV_32F)
            self._win_shape = cur.shape
        win = self._win
        (dx, dy), response = cv2.phaseCorrelate(prev.astype(np.float32), cur.astype(np.float32), win)
        if response < self.phase_min_response:
            return None, "phase"
        return np.float32([[1, 0, dx], [0, 1, dy]]), "phase"


def to_gray_small(img: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv2.resize(g, size, interpolation=cv2.INTER_AREA)
