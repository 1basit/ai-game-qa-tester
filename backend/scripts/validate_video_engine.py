"""Phase 2 completion-gate check on real footage.

For every video given (default: evaluation/videos/*), checks:
  1. validation + probe succeed (or the file is rejected with a clear reason);
  2. full decode yields exactly the number of frames the container lists;
  3. decoder timestamps agree with container timestamps and increase strictly;
  4. the sampled stream runs at the configured 10-15 FPS;
  5. random-access reads return the *identical* frame (pixel hash) as the full decode;
  6. throughput (decode + normalising sampled frames) vs real time, and peak memory.
Writes a Markdown report. Nothing here is hard-coded per video: every number comes
from running the engine.

usage: python scripts/validate_video_engine.py [VIDEO ...] [-o REPORT.md]
"""

from __future__ import annotations

import argparse
import hashlib
import random
import resource
import sys
from pathlib import Path

import numpy as np

from gameqa.config import PROJECT_ROOT, get_settings
from gameqa.core import GameQAError
from gameqa.logging_setup import configure_logging
from gameqa.video import FrameStream, probe_video, read_frame_at, validate_file

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"}


def peak_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 1024**2 if sys.platform == "darwin" else rss / 1024


def check_video(path: Path, n_random: int = 5) -> dict:
    cfg = get_settings().video
    row: dict = {"file": path.name}
    try:
        row["family"] = validate_file(path, cfg.allowed_extensions, cfg.max_upload_mb)
        probe = probe_video(path)
    except GameQAError as exc:
        row["rejected"] = str(exc)
        return row
    info = probe.info
    row.update(
        res=f"{info.width}x{info.height}", fps=info.fps_nominal, vfr=info.is_vfr,
        duration=info.duration_s, frames_expected=info.frame_count, codec=info.codec,
        hdr=info.is_hdr, truncation=info.truncation_suspected, irregular=info.timing.irregular_intervals if info.timing else None,
        max_gap_ms=round(info.timing.max_interval_s * 1000, 1) if info.timing and info.timing.max_interval_s else None,
    )
    rng = random.Random(0)
    picks = sorted(rng.sample(range(info.frame_count), min(n_random, info.frame_count)))
    hashes: dict[int, str] = {}
    stream = FrameStream(path, cfg, probe=probe)
    prev_ts, monotonic, sampled_ts = -1.0, True, []
    for f in stream:
        monotonic &= f.timestamp_s > prev_ts
        prev_ts = f.timestamp_s
        if f.is_sampled:
            _ = f.image  # normalise as the pipeline will
            sampled_ts.append(f.timestamp_s)
        if f.index in picks:
            hashes[f.index] = hashlib.md5(f.raw.tobytes()).hexdigest()
    s = stream.stats
    sampled_fps = (len(sampled_ts) - 1) / (sampled_ts[-1] - sampled_ts[0]) if len(sampled_ts) > 1 else None
    row.update(
        frames_decoded=s.frames_decoded, ts_mismatch=s.timestamp_mismatches, monotonic=monotonic,
        truncated=s.truncated, sampled_fps=round(sampled_fps, 2) if sampled_fps else None,
        realtime_x=round(s.realtime_factor, 2) if s.realtime_factor else None,
        peak_mb=round(peak_rss_mb()),
        warnings=s.warnings,
    )
    seek_ok = 0
    for idx in picks:
        t = float(probe.pts[idx])
        try:
            fr = read_frame_at(path, t, cfg, probe=probe)
        except GameQAError:
            continue  # counted as a failure (e.g. frame lies in a damaged part of the file)
        seek_ok += fr.index == idx and hashlib.md5(fr.raw.tobytes()).hexdigest() == hashes.get(idx)
    row["seek_exact"] = f"{seek_ok}/{len(picks)}"
    lo, hi = 10.0, 15.0
    row["pass"] = bool(
        s.frames_decoded == info.frame_count and s.timestamp_mismatches == 0 and monotonic
        and not s.truncated and seek_ok == len(picks)
        and (sampled_fps is None or lo - 0.5 <= sampled_fps <= hi + 0.5 or sampled_fps <= info.fps_nominal + 0.5 < lo)
    )
    return row


def to_markdown(rows: list[dict]) -> str:
    cols = ["file", "res", "fps", "vfr", "codec", "duration", "frames_expected", "frames_decoded",
            "ts_mismatch", "monotonic", "truncation", "irregular", "max_gap_ms", "sampled_fps", "seek_exact",
            "realtime_x", "peak_mb", "pass"]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        if "rejected" in r:
            out.append(f"| {r['file']} | rejected: {r['rejected']} |")
        else:
            out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    notes = [f"- **{r['file']}**: {w}" for r in rows for w in r.get("warnings", [])]
    return "\n".join(out + ([""] + ["Warnings:"] + notes if notes else []))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="*")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()
    configure_logging("ERROR")
    paths = [Path(v) for v in args.videos] or sorted(
        p for p in (PROJECT_ROOT / "evaluation" / "videos").iterdir() if p.suffix.lower() in VIDEO_EXT
    )
    if not paths:
        print("no videos found in evaluation/videos/", file=sys.stderr)
        return 1
    rows = []
    for p in paths:
        print(f"checking {p.name} ...", file=sys.stderr, flush=True)
        rows.append(check_video(p))
    md = to_markdown(rows)
    print(md)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md + "\n", encoding="utf-8")
    failed = [r["file"] for r in rows if r.get("pass") is False]
    return 1 if failed else 0


if __name__ == "__main__":
    np.seterr(all="ignore")
    raise SystemExit(main())
