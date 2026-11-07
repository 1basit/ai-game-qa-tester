"""Texture pop-in / unrendered-texture detector (FR-3 b).

Definition of a positive
------------------------
* ``texture_pop_in`` — a region suddenly changes its level of detail (blurry
  low-resolution texture → sharp, or the reverse) between two consecutive frames, while
  its colour layout stays the same (same surface, different resolution), and the region
  is quiet afterwards (a one-off snap, not an animation or effect).
* ``unrendered_texture`` — a region suddenly turns into the engine's missing-texture
  colour (magenta, solid or checkered; configurable) and stays that way.

Method (as proposed: SSIM between consecutive frames)
-----------------------------------------------------
Runs on every frame (consecutive frames are 1/60 s apart, so camera motion between them
is small and can be cancelled well; at the 12 FPS sampled rate the residual camera
motion in flat-shaded games hid the defects — see the Phase 4 report).
1. 480×270 greyscale; previous frame warped onto the current one (phase correlation,
   ORB + RANSAC fallback; `motion.py`). Unaligned frames are skipped.
2. SSIM map → mean dissimilarity per grid cell; cells far above the frame's own typical
   level (median + k·MAD) are candidates; frames with a high typical level (cuts, fast
   motion, transitions) are skipped.
3. The changed area is traced at pixel level inside the candidate cells.
4. In that area, at the normalised (720p) resolution: low-pass difference must be small
   and high-frequency energy must change by ≥ ``detail_ratio`` (either direction).
5. Confirmation over ``confirm_s``: the region must stay quiet.
Unrendered texture uses its own path: newly appearing magenta areas (gaps between
checker cells closed morphologically) that persist for ``confirm_s``.

What it cannot do: tell a pop-in from an intended one-frame sharpening effect; see
pop-in on flat, untextured surfaces; separate LOD mesh swaps from texture swaps (both
reported as ``texture_pop_in``); see pop-in during cuts or very fast camera motion.
The convolutional-autoencoder alternative named in the SRS was not built: it needs a
per-game corpus of clean footage for training that the project does not have.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from pydantic import Field
from skimage.metrics import structural_similarity

from gameqa.core.detector import Detector, DetectorParams, FrameRate, register_detector
from gameqa.core.schemas import BoundingBox, DefectCategory, Detection, Frame, VideoInfo
from gameqa.detectors.common import clamp01
from gameqa.detectors.motion import MotionEstimator


class TextureParams(DetectorParams):
    width: int = 480
    height: int = 270
    grid_cols: int = 16
    grid_rows: int = 9
    cell_outlier_k: float = Field(default=6.0, description="cell dssim > median + k * MAD")
    cell_min_dssim: float = Field(default=0.12, description="absolute floor for a candidate cell")
    frame_max_median_dssim: float = Field(
        default=0.25, description="skip frames above (cuts, fast motion). 0.12 skipped 38 % of a continuously "
        "zooming scene in the tuning set")
    min_cells: int = 2
    max_area: float = Field(default=0.35, description="max region area fraction (bigger = scene change)")
    detail_ratio: float = Field(default=2.0, gt=1, description="high-frequency energy change factor")
    lowfreq_max_diff: float = Field(default=14.0, description="max mean |low-pass difference| (grey levels)")
    lowpass_sigma: float = Field(
        default=2.0, description="detail = RMS of (image - Gaussian(sigma)) at 720p (sigma 1 was tried on the "
        "tuning set and lowered recall 0.59 -> 0.44)")
    min_detail_energy: float = Field(default=6.0, description="sharper side must have this detail RMS (grey levels)")
    confirm_s: float = Field(default=0.15, description="region must stay quiet / magenta this long")
    quiet_ratio: float = 0.5
    magenta_hue: tuple[int, int] = (140, 165)  # OpenCV hue 0-180
    magenta_min_sat: int = 150
    magenta_min_val: int = 100
    magenta_min_area: float = Field(default=0.004, description="min new magenta area fraction")
    magenta_close_px: int = 15
    magenta_min_fill: float = Field(default=0.4, description="magenta pixels / box area (checker ~0.5, solid ~1)")
    magenta_max_hue_std: float = Field(
        default=4.0, description="max hue std over the magenta pixels: missing-texture colours are flat "
        "(measured <= 1.2 after H.264 encoding), natural magenta content has hue gradients. Brightness is "
        "not used: chroma subsampling blends checker cells with black at their edges")
    merge_s: float = 1.0
    exclude_regions: list[tuple[float, float, float, float]] = Field(
        default_factory=list,
        description="Normalised (x, y, w, h) screen regions to ignore, e.g. HUD, minimap, editor chrome. "
        "UI text appearing on a flat panel is indistinguishable from a sharpening texture (real-footage review)")


@dataclass
class _Pending:
    subtype: str
    t: float
    t_prev: float
    idx: int
    idx_prev: int
    bbox: BoundingBox
    cells: np.ndarray | None
    score: float
    snap_dssim: float
    metrics: dict = field(default_factory=dict)
    ok: bool = True


@register_detector
class TexturePopInDetector(Detector):
    name = "texture_pop_in"
    version = "1.1"
    category = DefectCategory.TEXTURE_POP_IN
    frame_rate = FrameRate.FULL
    params_model = TextureParams

    def start(self, video: VideoInfo) -> None:
        super().start(video)
        self.motion = MotionEstimator(phase_first=True)
        self._prev: Frame | None = None
        self._prev_gray: np.ndarray | None = None
        self._prev_mag: np.ndarray | None = None
        self._pending: list[_Pending] = []
        self._out: list[Detection] = []
        self._frames = self._skipped = 0

    # ------------------------------------------------------------------ helpers
    def _small(self, frame: Frame) -> tuple[np.ndarray, np.ndarray]:
        p = self.params
        src = frame.raw if frame.raw is not None else frame.image
        bgr = cv2.resize(src, (p.width, p.height), interpolation=cv2.INTER_AREA)
        return bgr, cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    def _magenta_map(self, bgr: np.ndarray) -> np.ndarray:
        p = self.params
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        return ((hsv[..., 0] >= p.magenta_hue[0]) & (hsv[..., 0] <= p.magenta_hue[1])
                & (hsv[..., 1] >= p.magenta_min_sat) & (hsv[..., 2] >= p.magenta_min_val))

    def _cells(self, dmap: np.ndarray, valid: np.ndarray) -> np.ndarray:
        p = self.params
        h, w = dmap.shape
        ch, cw = h // p.grid_rows, w // p.grid_cols
        d = dmap[: ch * p.grid_rows, : cw * p.grid_cols].reshape(p.grid_rows, ch, p.grid_cols, cw)
        v = valid[: ch * p.grid_rows, : cw * p.grid_cols].reshape(p.grid_rows, ch, p.grid_cols, cw)
        vsum = v.sum(axis=(1, 3))
        out = np.full((p.grid_rows, p.grid_cols), np.nan, np.float32)
        ok = vsum >= 0.8 * ch * cw
        out[ok] = (d * v).sum(axis=(1, 3))[ok] / vsum[ok]
        return out

    def _refine(self, dmap: np.ndarray, region: np.ndarray, thr: float):
        """Pixel-accurate changed area inside the candidate cells (grown by one cell)."""
        p = self.params
        grown = cv2.dilate(region.astype(np.uint8), np.ones((3, 3), np.uint8))
        ch, cw = p.height // p.grid_rows, p.width // p.grid_cols
        roi = np.zeros((p.height, p.width), bool)
        roi[: ch * p.grid_rows, : cw * p.grid_cols] = cv2.resize(
            grown, (cw * p.grid_cols, ch * p.grid_rows), interpolation=cv2.INTER_NEAREST).astype(bool)
        mask = ((cv2.blur(dmap, (7, 7)) > 0.6 * thr) & roi).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n <= 1:
            return None
        k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, w, h, _ = stats[k]
        return lab == k, int(x), int(y), int(x + w), int(y + h)

    def _classify(self, prev_g: np.ndarray, cur_g: np.ndarray, mask: np.ndarray):
        p = self.params
        a, b = prev_g.astype(np.float32), cur_g.astype(np.float32)
        la = cv2.GaussianBlur(a, (0, 0), p.lowpass_sigma)
        lb = cv2.GaussianBlur(b, (0, 0), p.lowpass_sigma)
        sel = mask if mask.any() else np.ones(a.shape, bool)
        low = float(np.abs(la - lb)[sel].mean())
        ea = float(np.sqrt(((a - la)[sel] ** 2).mean()))
        eb = float(np.sqrt(((b - lb)[sel] ** 2).mean()))
        ratio = (max(ea, eb) + 1e-3) / (min(ea, eb) + 1e-3)
        m = {"lowfreq_diff": round(low, 2), "hf_before": round(ea, 2), "hf_after": round(eb, 2),
             "detail_ratio": round(ratio, 2), "direction": "sharpened" if eb > ea else "blurred"}
        if ratio >= p.detail_ratio and low <= p.lowfreq_max_diff and max(ea, eb) >= p.min_detail_energy:
            score = clamp01(0.4 + 0.15 * (ratio - p.detail_ratio) + 0.3 * (1 - low / p.lowfreq_max_diff))
            return True, score, m
        return False, 0.0, m

    # ------------------------------------------------------------------ main
    def process(self, frame: Frame) -> None:
        p = self.params
        bgr, gray = self._small(frame)
        self._cur_bgr = bgr
        mag = self._magenta_map(bgr)
        self._frames += 1
        if self._prev is None:
            self._store(frame, gray, mag)
            return
        al = self.motion.align(self._prev_gray, gray, prev_key=self._prev.index, cur_key=frame.index)
        self._check_magenta(frame, mag, al)
        if not al.reliable:
            self._skip(frame, gray, mag)
            return
        _, smap = structural_similarity(al.warped_prev, gray, data_range=255, full=True, win_size=7)
        dmap = np.clip((1.0 - smap) / 2.0, 0, 1).astype(np.float32)
        dmap[~al.valid] = 0
        cells = self._cells(dmap, al.valid)
        finite = cells[np.isfinite(cells)]
        if finite.size < cells.size * 0.5:
            self._skip(frame, gray, mag)
            return
        med = float(np.median(finite))
        mad = float(np.median(np.abs(finite - med))) + 1e-4
        self._update_pending(frame, cells, mag)
        if med > p.frame_max_median_dssim:
            self._skip(frame, gray, mag, update=False)
            return
        thr = max(med + p.cell_outlier_k * mad, p.cell_min_dssim)
        cand = np.nan_to_num(cells, nan=0.0) > thr
        if cand.any():
            self._candidates(frame, al, dmap, cells, cand, thr, med)
        self._store(frame, gray, mag)

    def _candidates(self, frame, al, dmap, cells, cand, thr, med) -> None:
        p = self.params
        # clusters separated by a single cell belong to one change (one surface)
        joined = cv2.dilate(cand.astype(np.uint8), np.ones((3, 3), np.uint8))
        n, labels = cv2.connectedComponents(joined, connectivity=8)
        full_cur = frame.gray()  # normalised resolution (lazily computed only here)
        full_prev = self._prev.gray()
        if full_prev.shape != full_cur.shape:
            return
        fh, fw = full_cur.shape
        sx, sy = fw / p.width, fh / p.height
        m_full = al.matrix.copy()
        m_full[0, 2] *= sx
        m_full[1, 2] *= sy
        warped_full = cv2.warpAffine(full_prev, m_full, (fw, fh))
        for k in range(1, n):
            region = (labels == k) & cand
            if region.sum() < p.min_cells or region.mean() > p.max_area:
                continue
            refined = self._refine(dmap, region, thr)
            if refined is None:
                continue
            pmask, x0, y0, x1, y1 = refined
            if (x1 - x0) * (y1 - y0) / (p.width * p.height) > p.max_area:
                continue
            X0, Y0, X1, Y1 = int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy)
            big = cv2.resize(pmask[y0:y1, x0:x1].astype(np.uint8), (X1 - X0, Y1 - Y0),
                             interpolation=cv2.INTER_NEAREST) > 0
            ok, score, metrics = self._classify(warped_full[Y0:Y1, X0:X1], full_cur[Y0:Y1, X0:X1], big)
            if not ok:
                continue
            box = BoundingBox.from_pixels(x0, y0, x1, y1, p.width, p.height)
            if self._excluded(box):
                continue
            snap = float(np.nanmean(cells[region]))
            metrics.update(region_dssim=round(snap, 3), frame_median_dssim=round(med, 3), align=al.method)
            self._pending.append(_Pending(
                "texture_pop_in", frame.timestamp_s, self._prev.timestamp_s, frame.index, self._prev.index,
                box, region, score, snap, metrics))

    def _check_magenta(self, frame: Frame, mag: np.ndarray, al) -> None:
        """Newly appearing missing-texture colour (independent of SSIM / alignment)."""
        p = self.params
        prev = self._prev_mag
        if prev is not None and al.reliable:
            prev = cv2.warpAffine(prev.astype(np.uint8), al.matrix, (p.width, p.height)) > 0
        k = np.ones((p.magenta_close_px, p.magenta_close_px), np.uint8)
        cur_c = cv2.morphologyEx(mag.astype(np.uint8), cv2.MORPH_CLOSE, k).astype(bool)
        prev_c = cv2.morphologyEx(prev.astype(np.uint8), cv2.MORPH_CLOSE, k).astype(bool)
        new = cur_c & ~prev_c
        n, _, stats, _ = cv2.connectedComponentsWithStats(new.astype(np.uint8), connectivity=8)
        for c in range(1, n):
            x, y, w, h, area = stats[c]
            if area < p.magenta_min_area * p.width * p.height:
                continue
            if self._excluded(BoundingBox.from_pixels(x, y, x + w, y + h, p.width, p.height)):
                continue
            box = mag[y:y + h, x:x + w]
            frac_now = float(box.mean())
            if frac_now < p.magenta_min_fill:
                continue
            hsv = cv2.cvtColor(self._cur_bgr[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)[box]
            if hsv.size == 0 or hsv[:, 0].std() > p.magenta_max_hue_std:
                continue
            self._pending.append(_Pending(
                "unrendered_texture", frame.timestamp_s, self._prev.timestamp_s, frame.index, self._prev.index,
                BoundingBox.from_pixels(x, y, x + w, y + h, p.width, p.height), None,
                clamp01(0.5 + frac_now), 0.0, {"magenta_fraction": round(frac_now, 3)}))

    def _update_pending(self, frame: Frame, cells: np.ndarray | None, mag: np.ndarray) -> None:
        p = self.params
        keep = []
        for pd in self._pending:
            if pd.idx == frame.index:
                keep.append(pd)
                continue
            if pd.subtype == "unrendered_texture":
                x0, y0, x1, y1 = pd.bbox.to_pixels(p.width, p.height)
                frac = float(mag[y0:y1, x0:x1].mean()) if (x1 > x0 and y1 > y0) else 0.0
                pd.ok &= frac >= 0.75 * pd.metrics["magenta_fraction"]
            elif cells is None:
                pd.ok = False  # cannot confirm across an unaligned frame / cut
            else:
                vals = cells[pd.cells]
                region_d = float(np.nanmean(vals)) if np.isfinite(vals).any() else np.inf
                pd.ok &= region_d < max(p.quiet_ratio * pd.snap_dssim, p.cell_min_dssim)
            if not pd.ok:
                continue
            if frame.timestamp_s - pd.t >= p.confirm_s:
                self._emit(pd)
            else:
                keep.append(pd)
        self._pending = keep

    def _excluded(self, box: BoundingBox) -> bool:
        """True if more than half of ``box`` lies inside an excluded screen region."""
        for (x, y, w, h) in self.params.exclude_regions:
            ix = max(0.0, min(box.x + box.w, x + w) - max(box.x, x))
            iy = max(0.0, min(box.y + box.h, y + h) - max(box.y, y))
            if ix * iy > 0.5 * box.area:
                return True
        return False

    def _emit(self, pd: _Pending) -> None:
        for d in self._out:  # same region again within merge_s -> one detection
            if d.subtype == pd.subtype and pd.t - d.end_time_s <= self.params.merge_s and d.bbox and \
                    _iou(d.bbox, pd.bbox) > 0.3:
                return
        self._out.append(Detection(
            category=self.category, subtype=pd.subtype, detector=self.name, detector_version=self.version,
            start_time_s=pd.t_prev, end_time_s=pd.t, peak_time_s=pd.t,
            start_frame=pd.idx_prev, end_frame=pd.idx, peak_frame=pd.idx,
            confidence=round(pd.score, 3), bbox=pd.bbox,
            description=("Region turned into the missing-texture colour" if pd.subtype == "unrendered_texture"
                         else f"Texture detail {pd.metrics.get('direction')} suddenly "
                              f"(x{pd.metrics.get('detail_ratio')}) with unchanged colour layout"),
            metrics=pd.metrics,
        ))

    def _skip(self, frame: Frame, gray, mag, update: bool = True) -> None:
        self._skipped += 1
        if update:
            self._update_pending(frame, None, mag)
        else:  # cut / fast motion: pop-in candidates cannot be confirmed
            self._pending = [pd for pd in self._pending if pd.subtype == "unrendered_texture" or pd.idx == frame.index]
        self._store(frame, gray, mag)

    def _store(self, frame: Frame, gray, mag) -> None:
        self._prev, self._prev_gray, self._prev_mag = frame, gray, mag

    def finish(self) -> list[Detection]:
        self._pending = []  # unconfirmed at the end of the video are not reported
        self._prev = None
        self.summary = {"frames_analysed": self._frames, "frames_skipped_unaligned_or_cut": self._skipped,
                        "skipped_fraction": round(self._skipped / max(1, self._frames), 3)}
        out, self._out = sorted(self._out, key=lambda d: d.start_time_s), []
        return out


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0
