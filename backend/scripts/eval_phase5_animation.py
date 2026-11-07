"""Phase 5 evaluation: animation glitches (flicker, jitter, unnatural transition).

Bases: real gameplay (v1 0-18.5 s), generated Mandelbrot zoom, generated photo-texture pan.
Seed 0 = tuning set (+ clean controls); later seeds = held-out. Real v1 = unlabelled FP review.
"""

from __future__ import annotations

import random
import sys

from evalkit import GT_SYN_DIR, RESULTS, SYN_DIR, V1, make_generated_base, make_photo_pan_base, run_and_score

from gameqa.evaluation.synthetic import Flicker, Jitter, Region, Teleport, render, write_ground_truth

OUT = SYN_DIR / "phase5"
GT = GT_SYN_DIR / "phase5"
REVIEWED = ["animation_glitch"]
DET = ["animation_glitch"]


# Video-editing cut (verified visually) and one ambiguous one-frame jump in v1 0-18.5 s:
# the unnatural-transition definition cannot separate them from defects -> ignored.
V1_IGNORE = [(4.35, 4.38, "video-editing cut (tutorial clip boundary)"),
             (10.88, 10.92, "one-frame jump: cut or real hitch, ambiguous")]


def bases():
    OUT.mkdir(parents=True, exist_ok=True)
    return {
        "v1game": (V1, 0.0, 18.5),
        "mandel": (make_generated_base(SYN_DIR / "phase3" / "mandel_base.mp4"), 0.0, None),
        "photo": (make_photo_pan_base(SYN_DIR / "phase4" / "photo_base.mp4"), 0.0, None),
    }


def build(seed: int) -> list:
    rng = random.Random(seed + 500)
    pairs = []
    for name, (src, s0, s1) in bases().items():
        if seed == 0:
            clean = OUT / f"{name}_clean.mp4"
            gt = render(src, clean, [], s0, s1, ignore_source=V1_IGNORE if name == "v1game" else None)
            write_ground_truth(GT / f"p5_{name}_clean.json", f"p5_{name}_clean", str(clean), gt, REVIEWED, "clean control")
            pairs.append((clean, GT / f"p5_{name}_clean.json"))
        length = (s1 or 20.0) - s0
        ops, busy = [], []
        for _ in range(80):
            if len(ops) >= 6:
                break
            kind = rng.choice(["flicker", "jitter_region", "jitter_global", "teleport"])
            dur = round(rng.uniform(0.3, 1.0), 2) if kind != "teleport" else round(rng.uniform(0.5, 2.0), 2)
            t0 = round(rng.uniform(0.8, length - 2.5), 2)
            span = (t0, t0 + (dur if kind != "teleport" else 0.1))
            if any(span[0] < b + 1.0 and a < span[1] + 1.0 for a, b in busy):
                continue
            w, h = rng.uniform(0.15, 0.35), rng.uniform(0.15, 0.4)
            reg = Region(round(rng.uniform(0.05, 0.95 - w), 3), round(rng.uniform(0.05, 0.9 - h), 3), round(w, 3), round(h, 3))
            if kind == "flicker":
                op = Flicker(t0, dur, region=reg, amp=rng.randint(25, 60))
            elif kind == "jitter_region":
                op = Jitter(t0, dur, region=reg, amp_px=rng.randint(4, 8))
            elif kind == "jitter_global":
                op = Jitter(t0, dur, region=None, amp_px=rng.randint(4, 8))
            else:
                op = Teleport(t0, dur)
            busy.append(span)
            ops.append(op)
        path = OUT / f"{name}_s{seed}.mp4"
        gt = render(src, path, ops, s0, s1, crf=18 if seed == 0 else 23,
                    ignore_source=V1_IGNORE if name == "v1game" else None)
        vid = f"p5_{name}_s{seed}"
        write_ground_truth(GT / f"{vid}.json", vid, str(path), gt, REVIEWED, f"random injection seed {seed}")
        pairs.append((path, GT / f"{vid}.json"))
    return pairs


def main() -> None:
    seeds = [int(a) for a in sys.argv[1:]] or [0]
    pairs = [p for sd in seeds for p in build(sd)]
    label = "TUNING set (seed 0)" if seeds == [0] else f"HELD-OUT seeds {seeds}"
    md, _ = run_and_score(pairs, DET, RESULTS / "phase5", f"{label} — animation_glitch")
    md_real = ""
    if seeds == [0]:
        md_real, _ = run_and_score([(V1, None)], DET, RESULTS / "phase5", "Real footage (unlabelled) — animation_glitch")
    report = f"# Phase 5 evaluation — animation glitches ({label})\n\n" + md + "\n" + md_real
    (RESULTS / "phase5" / f"report_{'tuning' if seeds == [0] else 'heldout'}.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
