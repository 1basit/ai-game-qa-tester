"""Phase 4 evaluation: texture pop-in / unrendered texture.

Bases: real gameplay (v1 0-18.5 s), generated Mandelbrot zoom, generated photo-texture pan.
Tuning set = seed 0 (+ clean controls); held-out = later seeds generated after tuning.
Real v1 (199 s incl. Unity Editor UI) = unlabelled false-positive review.
"""

from __future__ import annotations

import random
import sys

from evalkit import (GT_SYN_DIR, RESULTS, SYN_DIR, V1, make_generated_base, make_photo_pan_base,
                     region_detail, run_and_score)

from gameqa.evaluation.synthetic import MissingTexture, PopIn, Region, render, write_ground_truth

OUT = SYN_DIR / "phase4"
GT = GT_SYN_DIR / "phase4"
REVIEWED = ["texture_pop_in"]
DET = ["texture_pop_in"]


def bases():
    OUT.mkdir(parents=True, exist_ok=True)
    return {
        "v1game": (V1, 0.0, 18.5),
        "mandel": (make_generated_base(SYN_DIR / "phase3" / "mandel_base.mp4"), 0.0, None),
        "photo": (make_photo_pan_base(OUT / "photo_base.mp4"), 0.0, None),
    }


def build(seed: int) -> list:
    rng = random.Random(seed)
    pairs = []
    for name, (src, s0, s1) in bases().items():
        if seed == 0:  # clean controls belong to the tuning set
            clean = OUT / f"{name}_clean.mp4"
            gt = render(src, clean, [], s0, s1)
            write_ground_truth(GT / f"p4_{name}_clean.json", f"p4_{name}_clean", str(clean), gt, REVIEWED, "clean control")
            pairs.append((clean, GT / f"p4_{name}_clean.json"))
        length = (s1 or 20.0) - s0
        ops, busy = [], []
        for _ in range(60):
            if len(ops) >= 6:
                break
            w, h = rng.uniform(0.12, 0.3), rng.uniform(0.15, 0.35)
            reg = Region(round(rng.uniform(0.05, 0.95 - w), 3), round(rng.uniform(0.05, 0.9 - h), 3), round(w, 3), round(h, 3))
            missing = rng.random() < 0.35
            dur = round(rng.uniform(0.5, 1.5), 2)
            t0 = round(rng.uniform(0.6, length - dur - 0.6), 2)
            if any(t0 < b + 1.0 and a < t0 + dur + 1.0 for a, b in busy):
                continue
            if not missing:
                # only where the surface has visible detail at both transitions (blurring a
                # flat or smooth surface changes nothing a viewer could see)
                # positive definition: the sharp state has HF RMS >= 6 (detector's min_detail_energy);
                # 8 gives a margin so borderline-invisible injections are not counted
                if min(region_detail(src, s0 + t0, reg), region_detail(src, s0 + t0 + dur, reg)) < 8.0:
                    continue
            busy.append((t0, t0 + dur))
            ops.append(MissingTexture(t0, dur, region=reg, style=rng.choice(["checker", "flat"]))
                       if missing else PopIn(t0, dur, region=reg))
        path = OUT / f"{name}_s{seed}.mp4"
        gt = render(src, path, ops, s0, s1, crf=18 if seed == 0 else 23)
        vid = f"p4_{name}_s{seed}"
        write_ground_truth(GT / f"{vid}.json", vid, str(path), gt, REVIEWED, f"random injection seed {seed}")
        pairs.append((path, GT / f"{vid}.json"))
    return pairs


def main() -> None:
    seeds = [int(a) for a in sys.argv[1:]] or [0]
    pairs = [p for sd in seeds for p in build(sd)]
    label = "TUNING set (seed 0)" if seeds == [0] else f"HELD-OUT seeds {seeds}"
    md, _ = run_and_score(pairs, DET, RESULTS / "phase4", f"{label} — texture_pop_in")
    md_real = ""
    if seeds == [0]:
        md_real, _ = run_and_score([(V1, None)], DET, RESULTS / "phase4", "Real footage (unlabelled) — texture_pop_in")
    report = f"# Phase 4 evaluation — texture pop-in ({label})\n\n" + md + "\n" + md_real
    (RESULTS / "phase4" / f"report_{'tuning' if seeds == [0] else 'heldout'}.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
