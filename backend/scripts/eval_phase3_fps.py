"""Phase 3 evaluation: FPS-drop / frozen-frame detector.

Sets (all synthetic sets are labelled ``synthetic: true``):
  real   v1 full video (199 s)            — no labels: false-positive review only
  syn    v1 gameplay 0-18.5 s, re-encoded — clean control (expect 0)
  syn    v1 gameplay + 3 freezes + 3 drops (CFR: repeated frames)
  syn    v1 gameplay + 2 gaps + 2 decimations (VFR: missing frames, timestamps kept)
  syn    generated Mandelbrot zoom — clean / CFR-injected / VFR-injected
"""

from __future__ import annotations

from evalkit import GT_SYN_DIR, RESULTS, SYN_DIR, V1, make_generated_base, run_and_score, vfr_from

from gameqa.evaluation.synthetic import Drop, Freeze, render, write_ground_truth

OUT = SYN_DIR / "phase3"
GT = GT_SYN_DIR / "phase3"
REVIEWED = ["fps_drop"]


def build() -> list:
    OUT.mkdir(parents=True, exist_ok=True)
    pairs = []
    bases = {
        "v1game": (V1, 0.0, 18.5, "public: YouTube J8HB1-IQFxc gameplay 0-18.5 s"),
        "mandel": (make_generated_base(OUT / "mandel_base.mp4"), 0.0, None, "generated: ffmpeg mandelbrot zoom"),
    }
    plans = {
        "v1game": [Freeze(1.0, 0.3), Drop(4.3, 1.2, keep_every=3), Freeze(7.1, 0.6),
                   Drop(9.6, 1.5, keep_every=2), Freeze(13.2, 1.0), Drop(15.5, 1.5, keep_every=4)],
        "mandel": [Freeze(2.0, 0.3), Drop(5.0, 1.5, keep_every=3), Freeze(9.0, 0.6),
                   Drop(12.0, 1.5, keep_every=2), Freeze(15.0, 1.0), Drop(17.0, 1.5, keep_every=4)],
    }
    vfr_plans = {  # (select expression removing frames, GT events)
        "v1game": ("not(between(t,1.0,1.4)+between(t,7.1,7.8)+between(t,13.2,14.7)*not(eq(mod(n,3),0))"
                   "+between(t,15.5,17.0)*not(eq(mod(n,2),0)))",
                   [("frozen_frame", 1.0, 1.4), ("frozen_frame", 7.1, 7.8),
                    ("fps_drop", 13.2, 14.7), ("fps_drop", 15.5, 17.0)]),
        "mandel": ("not(between(t,2.0,2.4)+between(t,9.0,9.7)+between(t,12.0,13.5)*not(eq(mod(n,3),0))"
                   "+between(t,16.0,17.5)*not(eq(mod(n,2),0)))",
                   [("frozen_frame", 2.0, 2.4), ("frozen_frame", 9.0, 9.7),
                    ("fps_drop", 12.0, 13.5), ("fps_drop", 16.0, 17.5)]),
    }
    for name, (src, s0, s1, source) in bases.items():
        clean = OUT / f"{name}_clean.mp4"
        gt = render(src, clean, [], s0, s1)
        write_ground_truth(GT / f"p3_{name}_clean.json", f"p3_{name}_clean", str(clean), gt, REVIEWED, source)
        pairs.append((clean, GT / f"p3_{name}_clean.json"))

        cfr = OUT / f"{name}_cfr.mp4"
        gt = render(src, cfr, plans[name], s0, s1)
        write_ground_truth(GT / f"p3_{name}_cfr.json", f"p3_{name}_cfr", str(cfr), gt, REVIEWED, source)
        pairs.append((cfr, GT / f"p3_{name}_cfr.json"))

        expr, events = vfr_plans[name]
        vfr = vfr_from(clean, OUT / f"{name}_vfr.mp4", expr)
        gt_v = {"duration_s": gt["duration_s"], "events": [
            {"category": "fps_drop", "subtype": st, "start_s": a, "end_s": b} for st, a, b in events]}
        write_ground_truth(GT / f"p3_{name}_vfr.json", f"p3_{name}_vfr", str(vfr), gt_v, REVIEWED, source)
        pairs.append((vfr, GT / f"p3_{name}_vfr.json"))
    return pairs


# Continuously moving stretches of the real gameplay (measured in Phase 3 analysis)
V1_MOVING = [(0.5, 2.0), (4.5, 5.5), (7.0, 8.0), (9.5, 11.5), (13.0, 18.0)]


def build_heldout(seed: int) -> list:
    """Randomly placed defects (seeded), heavier compression (CRF 23). A NEW seed is used
    for each evaluation round after any tuning, so the reported set was never seen
    while choosing thresholds."""
    import random

    rng = random.Random(seed)
    pairs = []
    for name, src, s0, s1, windows in [
        ("v1game", V1, 0.0, 18.5, V1_MOVING),
        ("mandel", make_generated_base(OUT / "mandel_base.mp4"), 0.0, None, [(0.5, 19.0)]),
    ]:
        ops, busy = [], []
        for _ in range(40):
            if len(ops) >= 6:
                break
            w0, w1 = rng.choice(windows)
            freeze = rng.random() < 0.5
            dur = rng.uniform(0.3, 1.2) if freeze else rng.uniform(1.0, 2.0)
            if w1 - w0 < (dur if freeze else 0.6):
                continue
            t0 = round(rng.uniform(w0, max(w0, w1 - (dur if freeze else 0.6))), 2)
            if any(t0 < b + 1.2 and a < t0 + dur + 1.2 for a, b in busy):
                continue
            busy.append((t0, t0 + dur))
            ops.append(Freeze(t0, round(dur, 2)) if freeze else Drop(t0, round(dur, 2), keep_every=rng.choice([2, 3, 4, 5])))
        path = OUT / f"{name}_heldout_s{seed}.mp4"
        gt = render(src, path, ops, s0, s1, crf=23)
        vid = f"p3_{name}_heldout_s{seed}"
        write_ground_truth(GT / f"{vid}.json", vid, str(path), gt, REVIEWED, f"held-out random injection seed {seed}, CRF 23")
        pairs.append((path, GT / f"{vid}.json"))
    return pairs


def main() -> None:
    import sys

    from evalkit import aggregate, format_markdown

    seeds = [int(a) for a in sys.argv[1:]] or [1]
    held_pairs = [p for sd in seeds for p in build_heldout(sd)]
    md_held, evals = run_and_score(held_pairs, ["fps_drop"], RESULTS / "phase3",
                                   f"HELD-OUT synthetic, seeds {seeds} (generated after tuning) — fps_drop")
    pairs = build()
    md_syn, _ = run_and_score(pairs, ["fps_drop"], RESULTS / "phase3", "TUNING set — synthetic (injected) — fps_drop")
    md_real, _ = run_and_score([(V1, None)], ["fps_drop"], RESULTS / "phase3", "Real footage (unlabelled) — fps_drop")
    report = "# Phase 3 evaluation — FPS drop / frozen frame\n\n" + md_held + "\n" + md_syn + "\n" + md_real
    (RESULTS / "phase3" / "report.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
