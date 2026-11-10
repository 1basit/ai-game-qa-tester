"""Prototype Phase 2 evaluation: the FPS analysis service (freeze / drop / NEW stutter events).

Clean generated bases (Mandelbrot zoom, photo-texture pan) — the real gameplay already
stutters, so it cannot serve as a base for stutter ground truth. Random freezes, drops and
stutters; seed 0 = tuning, later seeds = held-out (generated after the design was fixed).
Matching: same event type and (temporal IoU >= 0.3 or prediction centre inside the GT
interval +/- 0.5 s), one-to-one.
"""

from __future__ import annotations

import json
import random
import sys

from evalkit import RESULTS, SYN_DIR, make_generated_base, make_photo_pan_base

from gameqa.evaluation.metrics import temporal_iou
from gameqa.evaluation.synthetic import Drop, Freeze, Stutter, render
from gameqa.fps_service import analyze_video

OUT = SYN_DIR / "prototype_fps"


def build(seed: int) -> list[tuple]:
    rng = random.Random(seed + 900)
    bases = {"mandel": make_generated_base(SYN_DIR / "phase3" / "mandel_base.mp4"),
             "photo": make_photo_pan_base(SYN_DIR / "phase4" / "photo_base.mp4")}
    out = []
    for name, src in bases.items():
        ops, busy, gt = [], [], []
        for _ in range(60):
            if len(ops) >= 6:
                break
            kind = rng.choice(["stutter", "stutter", "freeze", "drop"])
            dur = {"stutter": rng.uniform(1.5, 3.0), "freeze": rng.uniform(0.3, 1.0), "drop": rng.uniform(1.0, 2.0)}[kind]
            t0 = round(rng.uniform(1.0, 18.5 - dur), 2)
            if any(t0 < b + 1.5 and a < t0 + dur + 1.5 for a, b in busy):
                continue
            busy.append((t0, t0 + dur))
            if kind == "stutter":
                ops.append(Stutter(t0, round(dur, 2), every=rng.choice([5, 6, 8, 10, 15])))
            elif kind == "freeze":
                ops.append(Freeze(t0, round(dur, 2)))
            else:
                ops.append(Drop(t0, round(dur, 2), keep_every=rng.choice([2, 3, 4])))
            gt.append({"type": {"stutter": "stutter", "freeze": "freeze", "drop": "fps_drop"}[kind],
                       "start_s": t0, "end_s": round(t0 + dur, 2),
                       "detail": f"every={getattr(ops[-1], 'every', getattr(ops[-1], 'keep_every', ''))}"})
        path = OUT / f"{name}_s{seed}.mp4"
        render(src, path, ops, 0.0, None, crf=18 if seed == 0 else 23)
        out.append((path, gt))
        if seed == 0:
            clean = OUT / f"{name}_clean.mp4"
            render(src, clean, [], 0.0, None)
            out.append((clean, []))
    return out


def score(preds, gts):
    cands = []
    for i, p in enumerate(preds):
        for j, g in enumerate(gts):
            if p.type != g["type"]:
                continue
            iou = temporal_iou(p.start_s, p.end_s, g["start_s"], g["end_s"])
            c = (p.start_s + p.end_s) / 2
            if iou >= 0.3 or g["start_s"] - 0.5 <= c <= g["end_s"] + 0.5:
                cands.append((iou, i, j))
    used_p, used_g, tp = set(), set(), []
    for iou, i, j in sorted(cands, reverse=True):
        if i not in used_p and j not in used_g:
            used_p.add(i); used_g.add(j); tp.append((i, j))
    fps_ = [preds[i] for i in range(len(preds)) if i not in used_p]
    fns = [gts[j] for j in range(len(gts)) if j not in used_g]
    return tp, fps_, fns


def main():
    seeds = [int(a) for a in sys.argv[1:]] or [0]
    OUT.mkdir(parents=True, exist_ok=True)
    totals = {t: {"tp": 0, "fp": 0, "fn": 0} for t in ("stutter", "freeze", "fps_drop")}
    lines = [f"# Prototype FPS service evaluation — seeds {seeds}", ""]
    for sd in seeds:
        for path, gt in build(sd):
            res, _ = analyze_video(path)
            tp, fps_, fns = score(res.events, gt)
            for i, j in tp:
                totals[gt[j]["type"]]["tp"] += 1
            for p in fps_:
                totals[p.type]["fp"] += 1
            for g in fns:
                totals[g["type"]]["fn"] += 1
            lines.append(f"- **{path.stem}**: GT {len(gt)}, TP {len(tp)}, FP {len(fps_)}, FN {len(fns)}")
            lines += [f"  - FP {p.type} {p.start_s:.2f}-{p.end_s:.2f}s ({p.description})" for p in fps_]
            lines += [f"  - FN {g['type']} {g['start_s']}-{g['end_s']}s ({g['detail']})" for g in fns]
    lines += ["", "| Event | TP | FP | FN | Precision | Recall |", "|---|---|---|---|---|---|"]
    for t, c in totals.items():
        p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else float("nan")
        r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else float("nan")
        lines.append(f"| {t} | {c['tp']} | {c['fp']} | {c['fn']} | {p:.3f} | {r:.3f} |")
    md = "\n".join(lines)
    (RESULTS / "prototype_fps").mkdir(parents=True, exist_ok=True)
    (RESULTS / "prototype_fps" / f"report_seeds_{'_'.join(map(str, seeds))}.md").write_text(md + "\n")
    print(md)


if __name__ == "__main__":
    main()
