# Evaluation summary

All numbers below come from running the system; nothing is estimated. Full details,
including every tuning step, are in `DEVELOPMENT_PROGRESS.md`; raw outputs are in
`evaluation/results/phase*/`.

## Data actually available

| Source | What it is | Used for |
|---|---|---|
| **Real** — 1 YouTube video (J8HB1-IQFxc, 1080p60, 199 s) | 19 s of first-person Unity gameplay in 3 edited clips + 180 s of Unity Editor screen recording | video-engine validation, false-positive review for every detector, 10 hand-labelled clipping events (needs team confirmation) |
| **Synthetic** — defects injected into the real gameplay and into two generated scenes (Mandelbrot zoom, photo-texture pan) | exact ground truth | tuning (seed 0) and **held-out** evaluation (later seeds, CRF 23, generated after tuning) |

Synthetic results show the detectors respond to the defect as defined; they do not prove
accuracy on real games. Real defect footage for FPS drops, pop-in, animation glitches and
NPC anomalies was not available.

## Per-category results

| Category | Held-out synthetic P / R / F1 | Real footage | Status |
|---|---|---|---|
| FPS drop / frozen frame | **1.00 / 0.98 / 0.99** (46 events, 8 videos) | 1 FP in 199 s (freeze before a video-editing transition); no events in gameplay | Verified (synthetic) |
| Texture pop-in / unrendered texture | **0.83 / 0.70 / 0.76** (64 events, 9 videos); weak on a zooming fractal (11/24) | 9 detections, **all false positives** on UI (editor panels, toolbar) | Verified with major limitations |
| Animation glitch (flicker, jitter, transition) | **0.94 / 0.90 / 0.92** (52 events, 9 videos) | gameplay: 1 FP jitter + 1 edit cut; editor: 25 UI discontinuities | Verified (synthetic) |
| NPC anomaly (T-pose, frozen, ragdoll; floating not feasible) | not measurable (no footage with characters) | 0 detections (correct: no characters); YOLO mistook the player's hand for a person in 2 % of frames (filtered as viewmodel) | **Blocked** — needs footage |
| Collision / clipping (first-person viewmodel) | — | 10 real events: held-out event P 0.75 / R 0.50, but **frame-level precision 0.43 vs 0.39 for "always on" (chance)** | **Failed validation**; switched off by default |

The FP/FN analysis, every threshold change and its motivation, and the tuning vs held-out
split are documented per phase.

## System requirements (SRS §5) measured on Apple M1, 8 GB RAM, no CUDA

| Requirement | Target | Measured |
|---|---|---|
| Preprocessing speed (5.3.1) | ≥ real time for 1080p | 8.9× real time (199 s 1080p60 in 22 s), memory flat ≈ 170–200 MB |
| Upload in queue (5.3.1) | ≤ 5 s | 0.3 s after a 22.7 MB upload |
| Full analysis (5.3.2, provisional) | 15-min video ≤ 45 min (≥ 0.33×) | all 5 detectors: 0.57× real time (≈ 26 min for 15 min) |
| Detection list (5.3.3) | ≤ 2 s for 500 | 7 ms for 37 (not tested with 500) |
| JSON export | ≤ 5 s | 0.02 s |
| PDF export | ≤ 30 s for 100 with screenshots | 1.1 s for 37 with screenshots (1.9 MB) |
| Upload steps / clicks to clip / export (5.2) | ≤ 3 / ≤ 2 / 1 action | 3 numbered steps / 1 click / 1 button |
| Contrast (5.2) | ≥ 4.5:1, severity colour + text | min 6.05:1 (light), 7.71:1 (dark); badges always show text |
| Security (5.4) | bcrypt, 12 h inactivity, RBAC, isolation, HTTPS, audit, cascade delete | all implemented and tested (16 API tests on SQLite and PostgreSQL 18); TLS 1.1 refused, 1.2+ accepted |
| Reliability (5.1) | detector failure → completed with warnings; re-run without re-upload | tested (fault injection, re-run, crash recovery) |

Not done / not measurable here: the usability study with people outside the group (SRS 5.2),
mAP@0.5 (no box-level ground truth for NPC/clipping), FPS MAE against profiler logs (no
profiler access, by the SRS's own scope), automated daily backups (documented command only),
performance on the SRS's CUDA target hardware.

## What would most improve the results

1. Real labelled footage per category (normal play + known defects), especially games with
   characters (unblocks NPC evaluation) and with real pop-in / frame drops.
2. A learned clipping detector (e.g. fine-tuned YOLOv8 "clipping" class) trained on a
   labelled clipping dataset instead of hand rules.
3. HUD/UI masks per game (`exclude_regions`) to remove the main false-positive source of the
   texture and animation detectors.
4. Calibrating the severity thresholds against QA testers' own ratings.
