"""Charts for the FPS analysis (PNG): used by the web GUI and embedded in the DOCX report."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from gameqa.fps_service.analysis import FpsAnalysisResult  # noqa: E402

EVENT_COLOURS = {"freeze": "#b42318", "fps_drop": "#b54708", "stutter": "#6941c6"}


def _events(ax, result: FpsAnalysisResult) -> None:
    for e in result.events:
        ax.axvspan(e.start_s, max(e.end_s, e.start_s + 0.05), color=EVENT_COLOURS[e.type], alpha=0.18, lw=0)


def make_charts(result: FpsAnalysisResult, tl: dict, folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    t = np.asarray(tl["time_s"])
    out: dict[str, Path] = {}

    # 1. effective FPS over time (moving windows) vs target and drop threshold
    fig, ax = plt.subplots(figsize=(10, 3.4), dpi=120)
    ws = [w for w in tl["windows"]]
    xs = [(w["start_s"] + w["end_s"]) / 2 for w in ws]
    ys = [w["effective_fps"] if w["measurable"] else np.nan for w in ws]
    ax.plot(xs, ys, color="#1d4ed8", lw=1.6, label="effective FPS (1 s window)")
    ax.axhline(result.settings["target_fps"], color="#027a48", ls="--", lw=1, label=f"target {result.settings['target_fps']:g} FPS")
    ax.axhline(result.effective_fps["drop_threshold_fps"], color="#b54708", ls=":", lw=1.2,
               label=f"drop threshold {result.effective_fps['drop_threshold_fps']:g} FPS")
    _events(ax, result)
    ax.set_xlabel("time in video (s)"); ax.set_ylabel("FPS"); ax.set_ylim(bottom=0)
    ax.set_title("Effective frame rate (gaps = not measurable: picture not moving)")
    ax.legend(loc="lower right", fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); out["effective_fps"] = folder / "effective_fps.png"; fig.savefig(out["effective_fps"]); plt.close(fig)

    # 2. frame intervals (presentation timing from timestamps)
    fig, ax = plt.subplots(figsize=(10, 3.0), dpi=120)
    expected = result.frame_intervals["expected_ms"]
    top = 2 * expected  # headroom: a constant-frame-rate file is a flat line at `expected`, not on the top edge
    if len(t) > 1:
        iv = np.diff(t) * 1000
        ax.plot(t[1:], iv, color="#475467", lw=1.2, label="time between pictures", zorder=3)
        if iv.size and np.isfinite(iv).any():
            top = max(top, float(np.nanmax(iv)) * 1.1)
    ax.axhline(expected, color="#027a48", ls="--", lw=1,
               label=f"expected {expected:.2f} ms ({result.metadata['nominal_fps']:g} FPS)")
    _events(ax, result)
    ax.set_xlabel("time in video (s)"); ax.set_ylabel("interval (ms)"); ax.set_ylim(0, top)
    ax.set_title("Frame presentation intervals from timestamps (constant in constant-frame-rate files)")
    ax.legend(loc="upper right", fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); out["frame_intervals"] = folder / "frame_intervals.png"; fig.savefig(out["frame_intervals"]); plt.close(fig)

    # 3. frame-to-frame change with repeated / missed frames marked
    fig, ax = plt.subplots(figsize=(10, 3.0), dpi=120)
    mad = np.asarray([np.nan if m is None else m for m in tl["mad"]], float)
    ax.plot(t, mad, color="#98a2b3", lw=0.7, label="difference to previous frame")
    missed = np.asarray(tl["missed"], bool)
    rep = np.asarray(tl["repeated"], bool) & ~missed
    ax.scatter(t[rep], np.zeros(rep.sum()), s=6, color="#98a2b3", marker="|", label="repeated (still picture)")
    ax.scatter(t[missed], np.zeros(missed.sum()), s=18, color="#b42318", marker="|", label="repeated while moving (missed render)")
    _events(ax, result)
    ax.set_yscale("symlog", linthresh=1); ax.set_xlabel("time in video (s)"); ax.set_ylabel("mean abs. difference")
    ax.set_title("Frame-to-frame change and repeated frames")
    ax.legend(loc="upper right", fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); out["frame_changes"] = folder / "frame_changes.png"; fig.savefig(out["frame_changes"]); plt.close(fig)
    return out
