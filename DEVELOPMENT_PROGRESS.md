# Development Progress — AI Game QA Tester

Status values: **Not Started** · **In Progress** · **Blocked** · **Verified**.
A phase is marked Verified only after its completion gate (docs/ROADMAP.md §4) has
been met with real executions and recorded results.

| # | Phase | Status |
|---|-------|--------|
| 1 | Project foundation | **Verified** (approved 2026-11-06) |
| 2 | Video processing engine | **Verified** (2026-11-07, real footage: 1 YouTube 1080p60 recording) |
| 3 | FPS-drop & frozen-frame detector | **Verified** (synthetic-injection metrics; no real labelled drops available) |
| 4 | Texture pop-in detector | **Verified with major limitations** (synthetic F1 0.76; UI/HUD false positives on real footage) |
| 5 | Animation glitch detector | **Verified** (synthetic F1 0.92; real-footage FPs at UI/edit discontinuities) |
| 6 | NPC anomaly detector | **Blocked** — implemented and unit-tested; no footage with characters to validate on |
| 7 | Collision & clipping detector | **Failed validation** — viewmodel clipping experimental/off; character overlap unvalidated |
| 8 | Unified detection pipeline | **Verified** (all 5 detectors on real video: 0.57x real time, meets SRS 5.3.2 provisional target) |
| 9 | Evidence & severity | **Verified** (exact frames, browser-playable 5-10 s clips; severity rules not calibrated against human ratings) |
| 10 | Backend & database | **Verified** (16 API tests on SQLite and on PostgreSQL 18; live HTTPS run) |
| 11 | Authentication & security | **Verified** (bcrypt, 12 h inactivity, RBAC, isolation, signed links, audit, TLS >= 1.2) |
| 12 | Frontend dashboard | **Verified** (all 4 storyboard screens with live data; contrast >= 6:1; usability study with outside users not done) |
| 13 | Reporting (JSON / PDF) | **Verified** (JSON 0.02 s, PDF 1.1 s for 37 detections with screenshots) |
| 14 | Final integration & evaluation | **Done** — see docs/EVALUATION.md (179 tests pass, 3 documented xfail) |

---

## Phase 1 — Project foundation · Verified (2026-11-06)

### What was built and why
The shared base every later phase builds on, so the five detectors stay independent
but produce identical output that the pipeline, database, dashboard and reports can
consume without per-detector code.

| Component | File | Purpose |
|-----------|------|---------|
| Detection schema | `backend/src/gameqa/core/schemas.py` | `Detection`, `BoundingBox`, `DefectCategory`, sub-types per FR-3, `Severity`, `Evidence`, `VideoInfo`, `DetectionSet`, `Frame`. Validates time/frame ordering, subtype ∈ category, normalised boxes |
| Detector interface | `core/detector.py` | Streaming `start → process(frame) → finish` contract, typed params (unknown keys rejected), `FULL` vs `SAMPLED` frame-rate declaration (FR-2), name registry for the pipeline |
| Persistence helper | `core/events.py` | `EventAccumulator`: FR-3 "must persist across consecutive frames"; min frames, min duration, gap tolerance, peak tracking |
| Errors | `core/errors.py` | `GameQAError` hierarchy |
| Device selection | `core/device.py` | cuda → mps → cpu; lazy torch import |
| Configuration | `config.py`, `config/default.yaml` | Typed settings; YAML + env (`GAMEQA_…`) + `.env`; absolute path resolution; per-detector persistence overrides; invalid values / unknown keys fail loudly |
| Logging | `logging_setup.py` | Console or JSON; rotating JSON log file; `job_context()` tags every line with the job id |
| Evaluation harness | `evaluation/ground_truth.py`, `evaluation/metrics.py` | Label file format with `reviewed_categories`; temporal-IoU + peak-tolerance one-to-one matching; per-category TP/FP/FN, precision, recall, F1, FP per minute; micro-average across videos; Markdown table |
| Environment check | `doctor.py` | Real checks: encodes an H.264 clip with ffmpeg and decodes it with OpenCV, verifies storage, disk, RAM, libx264, phase packages |
| CLI | `cli.py` | `gameqa doctor`, `gameqa config`, `gameqa evaluate` |
| Docs | `README.md`, `docs/ROADMAP.md`, `evaluation/README.md`, `evaluation/label_template.json` | |

Other files: `backend/pyproject.toml`, `.gitignore`, `.env.example`, tests in `backend/tests/`.

### Tests performed (actual results)
Environment: Apple M1, 8 GB RAM, macOS (Darwin 25.5), Python 3.13.12, OpenCV 4.14.0,
NumPy 2.5.4, ffmpeg 9.0.1.

| Test | Result |
|------|--------|
| `pytest` — 52 tests (schema validation, persistence logic, metrics on hand-computed cases, config precedence and error handling, detector contract with a toy detector on synthetic frames, JSON logging with job id, CLI evaluate end-to-end, OpenCV H.264 decode) | **52 passed, 0 failed** (0.36 s) |
| `gameqa doctor` on the project machine | 23 checks: 0 failed, 1 warning (8 GB RAM < 16 GB recommended); exit 0 |
| `gameqa doctor` with ffmpeg removed from PATH | ffmpeg, ffprobe, opencv-decode reported FAIL; exit code 1 ✔ |
| `GAMEQA_VIDEO__ANALYSIS_FPS=30 gameqa doctor` | warns "outside FR-2's 10–15 FPS" ✔ |
| `gameqa config --config /nonexistent.yaml` | clear error, exit 2 ✔ |
| CLI run from a different working directory | paths still resolve to `FYP/data` ✔ |

Hand-computed metric case (in `tests/test_metrics.py`): 3 GT events, 3 predictions →
TP 2 (one by IoU 0.6, one zero-length by peak rule), FP 1, FN 1 → P = R = F1 = 0.667,
FP/min = 0.5 — the harness reproduces these exactly. A greedy-matching case where a
naive first-come assignment would give 1 TP correctly gives 2 TP.

No gameplay footage was used in this phase: nothing in Phase 1 processes video
content beyond the synthetic ffmpeg test clip used to verify the decoder.

### Known issues / limitations
- **Hardware:** development machine has no CUDA GPU and 8 GB RAM (SRS: CUDA GPU, 16 GB).
  Code is device-agnostic; throughput numbers will be reported as M1 figures.
- `README.md` is referenced by `pyproject.toml`; it now exists (the first editable install
  printed a harmless "README not found" warning before it was written).
- `gameqa evaluate` matches prediction files to labels by `video_id`; there is no
  checksum check that the label refers to the same video file yet (added in Phase 2
  when video probing exists).
- Detector config `params` are free-form until each detector defines its params model.
- The project folder was not a git repository; `git init` was run, nothing committed.

### How Phase 1 connects to Phase 2
Phase 2 implements the video engine that produces `VideoInfo` and the `Frame` objects
defined here (full-rate and sampled streams, `Frame.is_sampled`), using
`video.allowed_extensions`, `video.max_upload_mb`, `video.analysis_fps` and
`video.normalized_height` from the configuration.

### Next step
Phase 2 — Video processing engine (started 2026-11-06).

---

## Phase 2 — Video processing engine · Verified (2026-11-07)

### Real-footage result (completion gate)
Footage: `v1_unity_clipping_tutorial` (see `evaluation/videos/sources.md`) — 1920×1080,
60 FPS constant frame rate, H.264, 199.25 s, 11 955 frames, with audio.
`evaluation/results/phase2_real_validation.md`:

| Check | Result |
|---|---|
| Frames decoded vs container | 11 955 / 11 955 |
| Decoder vs container timestamp mismatches | 0 |
| Timestamps strictly increasing | yes |
| Irregular intervals / VFR | 0 / no (all intervals 16.67 ms) |
| Truncation suspected | no |
| Sampled stream | 2 391 frames, 12.0 FPS |
| Random-access reads (5 random frames) bit-identical to full decode | 5 / 5 |
| Throughput, pipeline mode (`gameqa bench`) | **8.9× real time** (199 s of video in 22.3 s), peak 171 MB |
| Validation script wall time | 20.7 s |

An earlier run of the validation script took 552 s; per-stage timing showed the code
needs ~24 s (decode 23 s, five seeks 0.14–0.25 s each) and a re-run took 20.7 s. The
slow run coincided with high machine load (15-min load average ≈ 6); it was not
reproducible and no code change was needed.

Not covered by real footage (covered by synthetic tests only): VFR recordings,
.mkv/.avi containers, 30 FPS sources, ≥ 5-minute 1080p file (199 s used; memory is flat
in length, so longer files are not expected to behave differently).

### What was built
| Component | File | Purpose |
|-----------|------|---------|
| Upload validation | `video/validation.py` | FR-1: extension (.mp4/.avi/.mkv only; message names accepted formats), size ≤ 2 GB, empty files, content sniffing (magic bytes) so renamed non-video files and extension/content mismatches are rejected before decoding |
| Probe | `video/probe.py` | ffprobe metadata → `VideoInfo` (resolution after rotation, nominal + average FPS, codec, pixel format, bit depth, HDR flag, audio, size, fast fingerprint). Reads every video packet timestamp (no pixel decoding) → sorted presentation timestamps, interval statistics, **VFR detection**, start-offset removal, **truncation detection** against the container's declared frame count / duration |
| Frame stream | `video/stream.py` | Streaming OpenCV decode; decoder PTS timestamps cross-checked against ffprobe on every frame; original frame index; **time-based** 10–15 FPS sampling (`is_sampled`) that stays correct on VFR footage and on millisecond-rounded Matroska timestamps; lazy normalisation to 720p BGR uint8 (aspect kept); time-window reads; `read_frame_at()` for exact single frames at original resolution (screenshots in Phase 9) |
| `Frame` (core) | `core/schemas.py` | Now lazy: `image` is normalised on first access, `raw` keeps the original-resolution frame |
| CLI | `cli.py` | `gameqa probe`, `gameqa extract` (frames + index.json, e.g. for CVAT labelling), `gameqa bench` |
| Validation harness | `scripts/validate_video_engine.py` | Runs all Phase 2 gate checks on real files and writes a Markdown report |
| Tests | `tests/videos.py`, `tests/conftest.py`, `tests/test_video.py` | Synthetic videos whose frames encode their own index as a 10-bit stripe pattern, so every decoded picture can be checked against its claimed index and timestamp |

Config added: `video.upscale` (default true). `VideoInfo` gained Phase 2 fields
(all optional, backward compatible).

### Design decisions found by experiment
- OpenCV's `CAP_PROP_POS_MSEC` *is* the true presentation timestamp (max deviation from
  ffprobe 0.3 µs, including across a 0.5 s VFR gap) → decoder timestamps are used,
  ffprobe timestamps are the cross-check. `CAP_PROP_FPS` reports the *average* rate on
  VFR files (25 instead of 30), so it is not used.
- OpenCV correctly converts limited- and full-range YUV and 10-bit video to 8-bit BGR
  (measured black/white levels 0/253–255). HDR (PQ/HLG) is **not** tone-mapped → flagged.
- The pip OpenCV build has no hardware decoding on macOS (`CAP_PROP_HW_ACCELERATION` = 0).
- Resizing, not decoding, dominated cost (13.5 s vs 3.6 s per minute of 1080p60) →
  normalisation made lazy.

### Tests performed (actual results)
`pytest`: **95 passed, 0 failed** (52 Phase 1 + 43 Phase 2), 8.7 s.

Phase 2 tests cover: accepted formats (mp4/mkv/avi); rejection of .mov, text renamed
to .mp4, mkv renamed to .mp4, empty file, over-size file; probe of CFR 30/60, MKV,
AVI (MPEG-4), VFR with a 533 ms gap, a 2.5 s start offset, 10-bit HDR, audio; every
frame decoded in order with the correct picture and timestamp (verified per frame);
sampling exactly `ceil(2.5k)` for 30→12 FPS and every 5th frame for 60 FPS (after
fixing a bug, see below); time-based sampling across a VFR gap; 720p normalisation
(down from 1080p, up from 240p, opt-out); time windows; exact single-frame reads;
truncated MP4/MKV/AVI; audio-only and index-less MP4 rejected as corrupt.

**Validation harness on synthetic files** (`evaluation/results/phase2_synthetic_validation.md`):
all 6 complete files pass (frame count = container count, 0 timestamp mismatches,
strictly increasing timestamps, 5/5 random seeks return the bit-identical frame,
sampled rate 11.8–12.0 FPS; 9.9 for the VFR file because nothing is sampled inside its
0.53 s gap); all 3 truncated files flagged; .mov and fake .mp4 rejected.

**Throughput** (Apple M1, synthetic 1080p60 H.264 12 Mb/s, 60 s, 3600 frames):
| Mode | Wall time | Real-time factor | Peak memory |
|------|-----------|------------------|-------------|
| decode all + normalise sampled frames (pipeline mode) | 7.2 s | **8.4×** | 197 MB |
| decode all + normalise every frame (worst case) | 15.2 s | 3.9× | 195 MB |
Memory does not grow with length: 189 MB (2 s) → 193 MB (20 s) → 196 MB (60 s).
SRS 5.3.1 (≥ real time for 1080p 30/60) is met **on synthetic footage**; real
gameplay compresses differently and must be measured.

### Bugs found and fixed during testing
1. **Missed sampling frames in MKV** — Matroska stores millisecond timestamps, so
   60 FPS frame 5 sits at 0.083 s, just before the 0.0833 s grid point; it was
   skipped (sampled 0, 6, 10, 15, 21 …). Fix: a frame within 40 % of a frame interval
   before a grid point is taken as the nearest frame.
2. **Truncation went undetected for MKV/AVI** — ffprobe only lists packets that exist,
   so decoded-vs-listed counts matched. Fix: compare with the container's declared
   frame count / duration.
3. Validation script crashed when a random seek landed in the damaged part of a file;
   now counted as a failed seek.

### Known issues / limitations
- **Not yet validated on real gameplay footage** (blocking).
- HDR footage is converted without tone mapping (warning emitted).
- `.mov` is rejected because FR-1 lists only .mp4/.avi/.mkv (macOS screen recordings
  and some capture tools produce .mov; adding it is a one-line config change if the
  team agrees to extend FR-1).
- Truncated files may also be reported as VFR (their last packets are irregular).
- Constant-frame-rate recordings hide game frame drops as duplicated frames: Phase 2
  reports timing correctly, but CFR drop detection is Phase 3's job (duplicate-frame analysis).
- A time-window read anchors its sampling grid at the window start, so it can differ
  by one frame from the grid of a full read (windows are for evidence, not analysis).
- Throughput numbers are from the M1 dev machine, not the SRS CUDA target.

### Reproduce
```bash
cd backend
.venv/bin/python -m pytest -q
.venv/bin/gameqa probe ../evaluation/videos/<file>
.venv/bin/gameqa bench ../evaluation/videos/<file>
.venv/bin/python scripts/validate_video_engine.py -o ../evaluation/results/phase2_real_validation.md
```

### To unblock (real-footage gate)
Put gameplay recordings in `evaluation/videos/` — ideally mp4 + mkv (+ avi if
available), 30 and 60 FPS, at least one variable-frame-rate recording, and one 1080p
clip of ≥ 5 minutes — then run the validation script above. Phase 2 becomes Verified
when every real file passes (or each failure is explained and fixed).

### Connection to Phase 3
The FPS / frozen-frame detector consumes every frame (`FrameRate.FULL`) with exact
timestamps, plus `VideoInfo.is_vfr` and `VideoInfo.timing` to choose between the
VFR-interval method and the CFR duplicate-frame method.

---

## Phase 3 — FPS-drop & frozen-frame detector · Verified (2026-11-07)

**Scope of the claim:** measured on *injected* defects in real gameplay and in a
generated scene, plus a false-positive review of the real video. No real recording with
known game frame drops was available, so real-world recall is **not** established.

### Method (`backend/src/gameqa/detectors/fps.py`, registry name `fps_drop`)
Full-rate detector. Each frame → 160×90 grey thumbnail → mean absolute difference (MAD)
to the previous frame. One "new picture" timeline is built for both recording types:
- CFR: a frame with MAD < `duplicate_mad` (0.25) repeats the previous picture;
- VFR: an interval > 1.5× the median interval means frames are missing.
A repeat/gap counts as a **missed render** only if (1) the frames immediately before and
after it are moving (MAD ≥ `motion_mad` 1.0, "abrupt edges") and (2) the 3 nearest
changing frames on each side, within 0.25 s, have median MAD ≥ 1.0 ("sustained motion").
- `frozen_frame`: one picture held ≥ 250 ms under those conditions.
- `fps_drop`: 1 s sliding windows (0.25 s step) over *moving* stretches only; effective FPS
  = new pictures / s; event when < 0.75 × target (target auto = 60 for ≥ 50 FPS recordings,
  else 30) in ≥ 2 consecutive windows. Drops explained by a freeze are reported once.
- `summary`: estimated rendered FPS (median / p10), measurable fraction, target.

Each rule came from a measured failure:
| Rule | Evidence that required it |
|---|---|
| Ignore static stretches | Real video: 91 % of editor-segment frame pairs identical |
| Sustained motion (3 frames) | First real run: 8 "freezes" in the editor = UI redraws in pairs (6.55, 6.54, hold) |
| `duplicate_mad` 0.05 → 0.25 | Tuning set: re-encoded repeats have MAD 0.02–0.14 → 2 misses |
| Abrupt edges | After raising the threshold: player stopping (MAD 5.7 → 3.9 → 0.33 → hold) became a false freeze (8 FPs) |

### Results
Evaluation script: `backend/scripts/eval_phase3_fps.py`; report `evaluation/results/phase3/report.md`.
Labels: `evaluation/ground_truth_synthetic/phase3/` (all `synthetic: true`).

**Held-out (random placements, CRF 23, generated after tuning, seeds 2–5, 8 videos):**
| TP | FP | FN | Precision | Recall | F1 | FP/min |
|---|---|---|---|---|---|---|
| 45 | 0 | 1 | **1.000** | **0.978** | **0.989** | 0.0 |
The miss: a freeze ending at 17.84 s just before the player stops (18 s) — with no motion
after it, a hold is indistinguishable from standing still (by design).

Earlier rounds, reported for transparency: seed-1 held-out set used before the abrupt-edge
rule: P 0.812, R 1.000 (3 FP); after: seed 1 9/9, 0 FP. Tuning set (6 videos incl. 2 clean
controls, CFR + VFR, both bases): 20/20, 0 FP.

**Real footage (unlabelled, v1, 199 s):** 1 detection — `frozen_frame` 18.37–19.42 s (conf
0.64). Inspection: faint motion (MAD ≈ 1.1), 1 s still, then a *video-editing transition*
at 19.42 s, which the detector read as motion resuming → **false positive** (0.3 FP/min).
No events in the 19 s of gameplay; estimated rendered FPS median 57, p10 49 (of 60).
Measurable fraction only 9 % (the editor segment is static). These thresholds were partly
calibrated on this video, so it is not an independent test.

Throughput: 517–1 037 frames/s (≈ 9–17× real time at 60 FPS) including decode.

Unit tests: `tests/test_fps_detector.py` (12 tests: smooth motion, holds above/below
threshold, decimation to 30/20/15 FPS, 50 FPS not reported, player stop, static scene,
UI-style updates, VFR gap, target selection). Suite total 107 passed.

### Known limitations
- Real-world recall unmeasured (no real footage with known drops); MAE against profiler
  logs (proposal §8.3) is not possible — no profiler access (SRS §3).
- Freezes at the start/end of motion, or in static scenes, are undetectable by design.
- Edited footage: cuts/transitions after a still moment can look like a freeze (1 real FP).
- The recording rate caps measurement (60 FPS recording → drops below 60 only).
- Games that hold frames on purpose (hit-stop, pause screens with motion) will be reported.

---

## Phase 4 — Texture pop-in detector · Verified with major limitations (2026-11-07)

### Method (`detectors/texture.py`, `detectors/motion.py`; registry `texture_pop_in`, v1.1)
Full-rate. 480×270 grey; previous frame warped onto current (phase correlation first,
ORB+RANSAC similarity fallback). SSIM map (scikit-image) → per-cell dissimilarity on a
16×9 grid → cells > median + 6·MAD and > 0.12 are candidates (frames with median > 0.25
skipped as cuts / fast motion). Neighbouring clusters joined; changed area traced at
pixel level. **Classification at 720p**: low-pass (σ 2) difference ≤ 14 grey levels and
detail RMS change ≥ 2× (either direction), sharper side ≥ 6 → `texture_pop_in`. Must stay
quiet for 0.15 s. `unrendered_texture`: independent path — newly appearing magenta area
(≥ 0.4 % of frame, ≥ 40 % fill, hue std ≤ 4, gaps closed), persisting 0.15 s.
`exclude_regions` masks HUD/UI. Positive definition requires the sharp state to have
detail RMS ≥ 6 grey levels at 720p (pop-in of flat surfaces is not visible).

The SRS's convolutional-autoencoder alternative was **not built**: it needs a corpus of
clean footage per game for training, which does not exist in this project.

### How the design got here (each step measured on the tuning set, seed 0)
| Version | Change | Tuning recall / precision |
|---|---|---|
| 1.0 | 12 FPS, 320×180, cell-box classification | 0.08 / 0.33 |
| | 640×360 SSIM, classification at 720p | 0.23 / 0.75 |
| | pixel-level region refinement (cell boxes mixed in untouched texture: ratio 1.3 vs true 9.5) | 0.36 / 1.00 |
| 1.1 | full rate + phase correlation (12 FPS parallax hid pop-ins in real gameplay) | 0.36 → with magenta path |
| | magenta must be flat (hue std); natural magenta in the fractal gave 49 FPs | — |
| | visibility rule aligned with detector's detail measure | 0.59 / 0.89 |
| | finest band σ 1 tried | 0.44 / 0.75 → **reverted** |

### Results
**Held-out** (seeds 1–3, CRF 23, random placement, 9 videos; `evaluation/results/phase4/report_heldout.md`):
| TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|
| 45 | 9 | 19 | **0.833** | **0.703** | **0.763** |
Per base: real-gameplay base 16/16 found (FPs mostly the editor-toolbar locations that also
fire on the clean video); photo pan 18/24, 0 FP; Mandelbrot zoom 11/24, 0 FP (a continuously
zooming high-contrast fractal changes detail everywhere — weak case).

**Real footage** (v1, 199 s, unlabelled): 9 detections after merging, **all false positives**
on inspection — Unity Editor panels expanding/collapsing, asset grid appearing, gizmo lines,
and 2 on the editor toolbar above the game view. No real pop-in exists in this video, so
real recall is unknown. Real FP rate ≈ 2.7/min on UI-heavy footage.

Throughput: ~75–107 frames/s on M1 (≈ 1.3–1.8× real time at 60 FPS) — the slowest detector so far.
Unit tests: `tests/test_texture_detector.py` (7). Suite: all passing.

### Known limitations
- **UI/HUD changes are a major false-positive source**: text appearing on a flat panel has the
  same signature (same colour layout, more detail) as a sharpening texture. Mitigation:
  `exclude_regions` per game; capture the game window only.
- Strong parallax (near and far geometry moving differently) and very fast camera motion
  defeat the global alignment → misses.
- No real pop-in footage available → real-world recall unmeasured.
- LOD mesh swaps are not separated from texture swaps.

---

## Phase 5 — Animation glitch detector · Verified (2026-11-07)

### Method (`detectors/animation.py`, registry `animation_glitch`)
Full rate, 320×180 grey. Farneback dense optical flow between consecutive frames;
camera motion = median flow over **textured** pixels (on flat surfaces flow reads 0
whatever the camera does). Per 20×20 cell, over the last 8 frames:
- `flicker`: mean-brightness change (after camera compensation) flips sign with
  |change| ≥ 20 in ≥ 4 of 7 frame pairs. Has priority over jitter.
- `jitter`: residual cell flow (or the global camera vector) reverses direction with
  magnitude ≥ 1.5 px in ≥ 5 of 7 pairs.
- `unnatural_transition`: compensated frame change ≥ max(12, 5× recent median) **and**
  ≥ 3× both neighbouring frames (isolated one-frame jump). `missing_keyframe` is not
  separable in video and is reported under this subtype.
Events need ≥ 3 frames (flicker/jitter); gaps ≤ 0.25 s merged; jitter at the border of a
flicker suppressed. `exclude_regions` masks HUD/UI.

### How the design got here (tuning set, seed 0, 3 bases + clean controls)
| Change | Evidence | Tuning P / R |
|---|---|---|
| v1: phase-correlation compensation | real-gameplay clean video: 14 FPs | 0.33 / 0.82 |
| ignore intervals for video-edit cuts | 4.367 s is a tutorial cut (verified by frame inspection) | — |
| textured-median motion, jitter ≥ 1.5 px / 5 alternations | flat-surface flow ≈ 0; flow noise ~0.5 px | 0.54 / 0.82 |
| isolated-spike rule (≥ 3× both neighbours) | 7 remaining "teleports" were fast camera flicks that ramp (9 → 47 → 22) | 0.77 / 0.77 |
| flicker priority, amplitude 20 | flow is fooled by brightness flips (flicker labelled jitter) | 0.82 / 0.82 |
| merge duplicates | jitter at flicker borders; split events | **1.00 / 0.82** |

### Results
**Held-out** (seeds 1–3, CRF 23, 9 videos; `evaluation/results/phase5/report_heldout.md`):
| TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|
| 47 | 3 | 5 | **0.940** | **0.904** | **0.922** |
FPs: 3 short (≈ 0.03 s) jitter events on the real-gameplay base = fast camera pitch/yaw
reversals. FNs: 3 jitter (2 on the Mandelbrot zoom), 2 teleports.

**Real footage** (v1, unlabelled): gameplay segment 0–19 s → 1 edit cut (4.35 s,
indistinguishable from a teleport by definition) + 1 FP jitter (16.37 s, camera pitch
reversal over 3 frames, inspected). Editor segment → 25 `unnatural_transition` at window
switches / panels / the editing transition: real one-frame discontinuities, but UI, not
game defects (out-of-domain content). No real animation glitch exists in the video, so
real recall is unknown.

Throughput ≈ 100–130 frames/s (≈ 1.7–2× real time at 60 FPS). Unit tests:
`tests/test_animation_detector.py` (7).

### Known limitations
- Intended effects (screen shake, strobe, hit-flash), scripted camera cuts and video-edit
  cuts are reported (indistinguishable from defects without engine knowledge).
- Fast camera reversals can produce very short jitter events.
- A single character's pose snap is only seen if it changes a large enough screen area.
- Flat-shaded scenes give weak motion estimates (mitigated by textured-pixel median).

---

## Phase 6 — NPC anomaly detector · Blocked (needs footage with characters)

**Why Blocked:** the only available footage contains no characters, so NPC-anomaly
precision/recall cannot be measured. The detector is implemented, its rules are
unit-tested, and the model pipeline is verified on a real photograph — that is all that
can honestly be claimed.

### Method (`detectors/npc.py`, `detectors/models.py`; registry `npc_anomaly`)
Sampled stream (12 FPS). YOLOv8n (COCO weights, Apple MPS) → `person` boxes (conf ≥ 0.4,
height ≥ 12 % of frame) → IoU tracker → MediaPipe **PoseLandmarker** (Tasks API; the legacy
`mp.solutions.pose` no longer exists in MediaPipe 1.x) on each padded crop. YOLO results are
cached on the frame so the clipping detector reuses them. Camera motion (phase
correlation) is accumulated to separate character motion from camera motion.
| Subtype | Rule | Status |
|---|---|---|
| `t_pose` | both elbows ≥ 150°, upper arms 70–110° from torso, wrist span ≥ 2.2 × shoulder width, ≥ 1 s | implemented |
| `frozen_npc` | box-relative keypoint std ≤ 0.012 over 2 s while the box moves ≥ 0.5 box-heights *in the world* (camera motion removed) — sliding without animation | implemented |
| `ragdoll` | mean limb jump ≥ 0.35 box-heights per analysed frame for ≥ 0.25 s | implemented (heuristic) |
| `floating` | — | **not implemented**: no ground plane or depth in a single 2-D view; any rule would be a guess |
First-person **viewmodel filter**: tracks whose box touches the bottom screen edge in ≥ 80 %
of observations and stays screen-fixed are ignored (real footage: all 48 YOLO "person" hits
were the player's gloved hand, conf 0.42–0.49).

### Tests performed
- `tests/test_npc_detector.py` (12): T-pose accepted; arms down / up / bent / one arm /
  invisible wrist rejected; frozen-while-sliding detected; camera-pan-only and animated walk
  not frozen; ragdoll jump detected, small motion not; viewmodel filter; **YOLOv8 + MediaPipe
  on a real photo** (skimage "astronaut"): person conf > 0.5, pose found, nose above shoulders,
  not a T-pose.
- Real footage v1 (no characters): 0 NPC detections (correct). YOLO produced 48 false "person"
  detections on the first-person hand (2 % of analysed frames); 4 of 7 hand tracks recognised
  as viewmodel; remaining 3 were too short to classify and produced no events.
- Throughput ≈ 100–136 frames/s of video (YOLO 28 ms per analysed frame on MPS when warm;
  first call ≈ 7.5 s model load).

### Setup notes
`ultralytics` and `mediapipe` each pull a different OpenCV wheel (`opencv-python`,
`opencv-contrib-python`) which overwrite each other (cv2 became 5.0). They were replaced by a
single `opencv-contrib-python-headless` 4.x (`pip check` reports the replaced names as
missing — expected). Weights in `data/models/`: `yolov8n.pt` (Ultralytics GitHub release),
`pose_landmarker_full.task` (Google storage). MediaPipe prints a harmless error from its own
destructor at interpreter exit.

### To unblock
Footage with humanoid NPCs: normal gameplay (for false-positive rate) and clips with known
T-poses / sliding NPCs / ragdoll failures, labelled with `evaluation/label_template.json`
(category `npc_anomaly`, bbox recommended). Then run `gameqa evaluate`.

---

## Phase 7 — Collision & clipping detector · Failed validation (2026-11-07)

**Outcome in one line:** clipping is the one category with real positive examples, and the
detector built for it does **not** detect them reliably. It is shipped switched off
(experimental) rather than producing chance-level noise; the reasons are documented below.

### Why the SRS method (bounding-box overlap with static geometry) was not used
COCO YOLO has no wall/floor/terrain classes (no geometry box to overlap), and a 2-D overlap
is identical for "behind a wall" and "inside a wall". Two observable alternatives were built
(`detectors/clipping.py`, registry `collision_clipping`, v1.2):
1. `character_geometry` — **first-person viewmodel clipping** (`viewmodel_clipping`, default
   **off**): learn which pixels stay still while the camera moves (two-hypothesis test per
   textured pixel: "stayed still" fits, "moved with the camera" does not; camera motion =
   textured-pixel median of Farneback flow); viewmodel = largest learned component hanging
   from the bottom of the view (thin static lines removed, holes filled); clipping = a
   contiguous hidden group of interior learned pixels at the far end (≥ 0.7 of the viewmodel's
   extent from its screen anchor) while the near part stays ≥ 85 % visible; ±2 px sway
   tolerance; relearn when the viewmodel is lost for 0.5 s.
2. `character_character` — two YOLO `person` boxes with IoU ≥ 0.5 for ≥ 1 s (default on;
   viewmodel boxes touching the bottom edge excluded). Logic unit-tested with stubbed
   detections; **not validated** (no footage with characters).

### Real ground truth
`evaluation/ground_truth/v1_unity_clipping_tutorial.json`: 10 `character_geometry` events in
v1 where the rifle's muzzle / front-sight post is hidden inside a crate wall (labelled by
frame inspection at 12 FPS; boundaries ±0.1 s; **needs confirmation by a team member**).
Split for honest evaluation: tuning = clips 1–2 (0–7.6 s, 3 events), held-out = clip 3
(7.6–19.2 s, 6 events; one event at the cut boundary falls in neither).
Files: `evaluation/results/phase7/gt_{tuning,heldout}.json`, `*_pred.json`, `*_eval/`.

### What was tried (tuning clip unless stated)
| Version / change | Finding |
|---|---|
| v1.0 "tip = farthest 12 %" | 0/10: tip far larger than the vanishing post; clipped look became the reference; edit cut kept old weapon model |
| v1.1 far-end hidden component, 480×270, sway tolerance, relearn on loss | learned the **Unity Editor toolbar** as the "weapon" (static, textured, touches the sides) |
| bottom-anchored viewmodel; thin lines removed | tuning 2/3 events, 0 FP; **held-out 3/6, 1 FP (event P 0.75, R 0.50)** |
| **frame-level check** (is the detector on when the sight is hidden?) | tuning P 0.37 / R 0.54 vs 0.15 for "always on"; **held-out P 0.43 / R 0.87 vs 0.39 for "always on" → essentially chance**. The event score came from long detections overlapping short events: it fires "near a wall", not "tip inside the wall" |
| v1.2 two-hypothesis learning (smooth moving background had been learned as static) + interior-only visibility | clean synthetic sequence still gives spurious detections and an obvious synthetic occlusion is missed |

Root cause on the real video: the post is ~2 px wide at 480×270 and differs from the brown
wall by ~20 grey levels — at the size of the sway tolerance and match threshold; the
measurable signal is below the method's resolution. Stopped here rather than fitting more
parameters to a single 19 s video.

An evaluation-tool bug was found and fixed on the way: a prediction touching an ignore
interval was dropped entirely; now it must lie ≥ 50 % inside (test added). Phase 5 held-out
was re-run with the fix: unchanged (P 0.940, R 0.904).

### Tests
`tests/test_clipping_detector.py`: default-off check and person-overlap rule pass; the three
viewmodel mechanism tests are marked **xfail** with the reason (kept visible, not deleted).
Suite: 136 passed, 3 xfailed.

### What would be needed
(a) More clipping footage (several games, third-person included) to train a learned
"clipping" classifier (e.g. fine-tuned YOLOv8 class) instead of hand rules; (b) for
first-person weapons, a per-game viewmodel template supplied once by the tester would remove
the learning problem; (c) engine-side data (depth) — out of scope by the SRS.

---

## Phase 8 — Unified detection pipeline · Verified (2026-11-07)
`pipeline/runner.py`, `gameqa detect`. One decode pass; FULL-rate detectors get every frame,
SAMPLED detectors the 12 FPS grid; a detector raising in `process` or `finish` is disabled,
its error recorded, the others continue and the run is `completed_with_warnings` (NFR 5.1);
progress callback (monotonic, ends at 1.0). Severity and evidence run after the detectors.
Tests: `tests/test_pipeline.py` (5): routing 120/48 frames, crash at frame 30 isolated with
other results kept, crash in `finish` isolated, progress, detectors by name.

**All five detectors on the real 199 s 1080p60 video (M1, 8 GB):** status completed, no
errors, 351 s wall = **0.57× real time** (34 frames/s). SRS 5.3.2 provisional target
(15-min video in ≤ 45 min = 0.33×) is met on this machine. Time per detector: texture 130 s,
animation 107 s, NPC 72 s (YOLO + MediaPipe on the hand false positives), clipping 17 s,
FPS 12 s. Output: 37 detections (27 animation — 25 at Unity Editor discontinuities, 9 texture
— all UI, 1 freeze at the editing transition) — i.e. on this non-gameplay-heavy video the
detections are false positives, as reported per detector in Phases 3–5.
Files: `evaluation/results/phase8/`.

## Phase 9 — Evidence & severity · Verified (2026-11-07)
- `evidence.py`: screenshot at the peak frame at original resolution (plain + outlined with
  severity colour and label), 5–10 s clip centred and clamped to the video, ffmpeg H.264/AAC
  `+faststart`; 3 clips in parallel; per-detection failures become warnings.
- `severity.py` + `severity:` config: recurrence groups (same subtype, overlapping box or both
  full-frame); category gives the SRS band (clipping High; FPS drop/freeze Medium → High when
  severe: freeze ≥ 1 s, effective FPS < 50 % of target, or ≥ 3 s; NPC Medium; unrendered
  texture Medium; pop-in / animation Low) and large area (≥ 25 %), long (≥ 2 s) or recurring
  (≥ 3×) raises one band. The reason string is stored.
- Tests `tests/test_severity_evidence.py` (22): every rule; recurrence grouping; clip windows
  at start/end/long/short videos; **screenshot is exactly the reported frame** (decoded frame
  index) at original size, clip H.264 yuv420p, faststart, correct length, starts at the stated
  time — also on the MKV with a 2.5 s start offset; pipeline attaches both.
- Limitation: thresholds encode the SRS definitions but were **not calibrated against human
  severity ratings** (none exist). Whole-frame events group together, so many editor cuts
  in one video raise each other to Medium ("recurs 26×").

## Phase 10 — Backend & database · Verified (2026-11-07)
FastAPI (`api/app.py`, `api/routes.py`, `api/reports.py`), SQLAlchemy 2 models
(`api/models.py`: users, projects, project_members, videos, jobs, detections, audit_log;
cascading FKs), DB-backed queue + `worker/runner.py` (oldest queued job, `FOR UPDATE SKIP
LOCKED` on PostgreSQL, crash recovery, attempts limit, per-job option overrides). Uploads
stream to disk (no full file in memory), extension → size → content checks, max 5 queued
(429). CLI: `gameqa serve | worker | create-user`.
- Tests `tests/test_api.py` (16) pass on **SQLite and on PostgreSQL 18.3**
  (`GAMEQA_TEST_DATABASE_URL`).
- **Live run** (HTTPS :8443, PostgreSQL :5433, separate worker process, real 199 s video, all
  detectors): upload of 22.7 MB queued in **0.3 s** (SRS ≤ 5 s); job completed in 412 s
  with evidence; list of 37 detections **7 ms** (SRS ≤ 2 s).
- Not done: DB backups (SRS 5.1: daily) are an operations task — documented in the README
  (`pg_dump`), not automated; Alembic migrations not used (`create_all`).

## Phase 11 — Authentication & security · Verified (2026-11-07)
bcrypt (cost 12) + minimum 8 characters; HS256 JWT; **12 h inactivity enforced server-side**
(`last_activity`); roles tester/developer/qa_lead/admin; project isolation (non-members get
404, not 403); evidence never in the web root — served only via **10-minute HMAC-signed
URLs** bound to file + user (no session token in URLs), membership re-checked, path traversal
blocked, HTTP Range supported; audit log of login, upload, view, export, delete, user and
membership changes; deleting a job removes its evidence and (if unused) its video;
parameterised queries (SQLAlchemy); app refuses to start without a ≥ 32-character secret
(`.env`, git-ignored). HTTPS demo: `backend/scripts/make_dev_cert.sh` (self-signed);
verified **TLS 1.1 refused, TLS 1.2+ accepted**.
Tests cover wrong password, tampered token, inactivity expiry, password length, role
denials, isolation of projects/jobs/detections/reports, tampered/unsigned/traversal links.
Limitations: self-signed certificate (browser warning); no rate limiting on login.

## Phase 13 — Reporting · Verified (2026-11-07)
`reports.py` (JSON: meta, summary by category × severity, detection records with evidence
references; PDF via ReportLab: run details, summary table + bar chart, each detection with
outlined screenshot, severity + reason, times/frames, confidence, detector, clip path).
Both accept the same category/severity filters as the list. Live: JSON 0.02 s, PDF 1.1 s
(37 detections, 1.9 MB) — SRS: ≤ 5 s / ≤ 30 s for 100 detections. Exports are audited.

## Phase 12 — Frontend dashboard · Verified (2026-11-07)
`frontend/` — React 18 + TypeScript + Vite, no router/chart libraries (163 KB JS, 52 KB
gzipped); built files served by FastAPI from the same origin. Screens follow SRS §8:
login; projects (build, videos, detections, severity summary, recent activity, create
project / add member for QA leads); upload & queue (numbered 3-step upload with drag-and-drop,
client-side format check, upload progress, analysis settings: target FPS, sampling rate,
detectors; live queue with progress bars, re-run); review (category and severity filter chips,
combinable; list with time / category / duration / severity; evidence panel with outlined
screenshot, playable clip, severity reason, description, time, frames, detector, confidence);
report (totals, stacked bars per category, preview, one-click JSON / PDF export honouring the
filters). Severity is always colour + text. Evidence uses the signed URLs (no token in URLs).

Checked in the built-in browser against the live PostgreSQL-backed server with the real job
(37 detections): sign-in, projects page data, HIGH filter → the 1.1 s freeze, outlined
screenshot (1920 px) and **clip loaded and playable (8 s, readyState 4)** — 1 click from the
list (SRS ≤ 2), reason text shown, report and upload screens render with live data.
Contrast computed for every text/background pair: minimum **6.05:1 light / 7.71:1 dark**
(SRS ≥ 4.5:1). Type-check (`tsc` strict) and build pass.
Not done: the SRS usability test with people outside the group (record steps and
hesitations) — must be run by the team; no automated frontend tests (manual check only).
The browser pane did not trust the self-signed certificate, so the UI check used a second
local HTTP instance of the same app; HTTPS itself was verified with curl (TLS 1.2+).

## Phase 14 — Final integration & evaluation · Done (2026-11-07)
Full suite: **179 passed, 3 xfailed** (documented viewmodel-clipping failures); API suite also
passes on PostgreSQL 18. `gameqa doctor`: 0 failures, 2 warnings (8 GB RAM, no CUDA).
Consolidated results and requirement-by-requirement measurements: `docs/EVALUATION.md`.
Reproducible install: `backend/scripts/install.sh`; run instructions in `README.md`.

### Open items for the team
1. Confirm the 10 hand-labelled clipping events (`evaluation/ground_truth/v1_unity_clipping_tutorial.json`).
2. Provide real footage with characters (Phase 6) and with real frame drops / pop-in to
   measure real-world accuracy; label with `evaluation/label_template.json`.
3. Run the SRS 5.2 usability study with people outside the group.
4. Replace the self-signed certificate for any shared demo; set a real `GAMEQA_API__SECRET_KEY`.
5. Optional: Alembic migrations, scheduled backups, login rate limiting.

### Post-release fixes (2026-11-07, afternoon)
- **Incident:** running the API tests against PostgreSQL with the *real* `gameqa` database
  wiped it (the test fixture drops all tables per test) — the demo accounts, project and job
  were lost, so sign-in with `data/demo-credentials.txt` failed. Fix: the tests now refuse any
  database whose name does not end in `_test` (verified: refused on `gameqa`, 16 passed on
  `gameqa_test`). Demo accounts recreated with the same passwords; orphaned files of the lost
  job removed; the video re-analysed — identical result (37 detections: 1 High, 32 Medium, 4 Low).
- **Recurrence visible in the dashboard:** "Seen" column (`once` / `N×`), a *Recurrence* line
  ("Seen N times in this video (this is #k)") and **Show all N** to list only that issue's
  occurrences. Checked in the browser on the real job (26× editor-cut transitions; freeze once).
- `docs/USER_GUIDE.md`: step-by-step guide (start, sign in, upload, queue, review, recurrence,
  export, stop, troubleshooting).

---

# Prototype track (FPS analysis service with CLI + local GUI)

Requested 2026-11-07 for the supervisor demo: a simple FPS-analysis prototype usable from the
terminal (`python main.py analyze --video ...`) and a no-login local web page
(`python main.py --gui`), with Word (.docx) reports. Built on the existing, validated video
engine and FPS detector; the full system (login dashboard, other detectors) is untouched.

| Prototype phase | Status |
|---|---|
| P1 Foundation | **Done** |
| P2 FPS analysis engine | **Verified** (synthetic held-out; real video reviewed) |
| P3 CLI | **Verified** (real video + error cases; Word report checked visually) |
| P4 Local web GUI | **Verified** (real video in the browser; same results as CLI) |
| P5 Documentation (.docx) | **Done** (generated from real runs; checked by read-back + page-1 render) |
| P6 Testing & demo | **Verified** (18-case test set on CLI + GUI; 1 bug fixed; demo guide rehearsed) |

## P1 — Foundation · Done (2026-11-07)
`python-docx` 1.2.0 installed (+ matplotlib declared); `fps_service` section in
`config/default.yaml` (target FPS 60, drop ratio 0.75, freeze 250 ms, stutter ≥ 3 missed/s,
output folder `outputs/`, GUI 127.0.0.1:8765); `outputs/` git-ignored.

## P2 — FPS analysis engine · Verified (2026-11-07)
`backend/src/gameqa/fps_service/` — `analysis.py` (`analyze_video()`: the single engine for CLI
and GUI), `charts.py` (3 PNG charts), `store.py` (analysis.json, timeline.csv, windows.json,
charts). `detectors/fps.py` now also exposes its per-frame timeline (detection logic unchanged:
its 12 tests still pass). `video/probe.py`: OpenCV-only metadata fallback when ffprobe is absent.
New: **stutter** = ≥ 3 isolated missed frames in a 1 s window while effective FPS ≥ drop
threshold, ≥ 2 consecutive windows, not overlapping a freeze/drop. Statistics: average FPS from
timestamps, frame-interval stats, effective FPS (mean/median/min/p5), frame-time percentiles and
"1 % low" FPS = 1 / p99 frame time, measurable fraction.

**Synthetic evaluation** (`backend/scripts/eval_prototype_fps.py`; clean generated bases —
the real gameplay already stutters so it cannot be a stutter base; thresholds fixed before data):
| Set | Stutter | Freeze | FPS drop |
|---|---|---|---|
| Tuning (seed 0, + 2 clean controls) | 5/5, 0 FP | 2/2, 0 FP | 2/2, 0 FP |
| **Held-out (seeds 1–3, CRF 23)** | **11/11, 0 FP** | **8/9, 0 FP** | **7/7, 0 FP** |
Missed freeze: its first repeated frame differed by 0.68 after CRF 23 compression (> 0.25
repeat threshold), so the hold appeared to start after a "slowing" frame and the abrupt-edge
rule rejected it. Not tuned on the held-out set; recorded as a limitation.

**Real video** (v1, 199 s 1080p60 CFR): 26 s (7.6× real time). Average FPS 60.0 (timestamps
perfectly regular: CFR); measurable 9 % (only the 19 s of gameplay moves); effective FPS
mean 53.9 / median 57 / p5 27.4; frame times p50 16.67 ms, p99 33.3 ms → 1 % low 30 FPS;
130 missed frames while moving; events: 4 stutter periods covering most of the gameplay
(up to 5–9 missed frames/s, 51–55 FPS) and 1 freeze at 18.37 s. Review: the stutter matches
the isolated exact repeats seen during smooth motion in Phase 3 (real uneven pacing in the
recording — whether caused by the game, the recorder or the tutorial's editing cannot be told
from the video); the freeze is the known false positive before the editing transition.

Tests: `tests/test_fps_service.py` (12): missing / unsupported / text-as-mp4 / damaged files,
clean CFR statistics, VFR gap = freeze, stutter vs drop separation, configurable thresholds,
OpenCV-only fallback, saved files (JSON, CSV 76 rows, 3 PNG charts), safe output names, too-short
video. Full suite: **191 passed, 3 xfailed**.

Limitations: true game FPS not recoverable; recording rate caps measurement; still stretches
unmeasurable; edits/intentional pauses look like freezes; heavy compression can hide the first
frame of a freeze (1/9 held-out); only one real video available (needs more real footage).

## P3 — Command-line interface · Verified (2026-11-07)
`main.py` (project root): `python main.py analyze --video PATH [--target-fps N] [--drop-ratio R]
[--freeze-ms MS] [--stutter-min-missed K] [--output DIR] [--no-report] [--max-events N] [--quiet]`.
Calls the shared engine (`gameqa.fps_service`), shows a one-line progress bar in a terminal
(plain lines when redirected), prints video / frame-rate / events / verdict, writes the output
folder (`outputs/<date-time>_<video>/`: analysis.json, timeline.csv, windows.json,
charts/*.png, **FPS_ANALYSIS_REPORT.docx**). Exit codes: 0 ok, 2 invalid input, 3 wrong Python
environment (prints how to activate `backend/.venv`). `--gui` is accepted and reports that the
GUI arrives in P4 (now implemented, see P4).
`fps_service/report_docx.py` (python-docx): title, 9 sections — summary (verdict + key numbers),
video metadata, settings, frame presentation timing (+ chart), effective FPS and frame times
(+ 2 charts), colour-coded events table, method (equations), limitations (+ per-video
warnings), processing — explicit table borders and shaded label column so it renders the same
in Word, Pages and macOS Quick Look; page numbers in the footer.

Tests run:
- Real video (199 s): exit 0, 26 s; 4 stutters + 1 freeze, verdict and report path printed;
  re-run gives identical results.
- Errors: missing file, `.mov`, text renamed `.mp4`, `--drop-ratio 1.5`, `--target-fps 0` →
  one-line message, exit 2; missing `--video` → usage error; system Python without packages →
  activation instructions, exit 3.
- Terminal progress bar (real TTY via `script`), `--target-fps 30`, `--output`, `--no-report`.
- Report: rendered with Quick Look (page 1) — first version showed **no table borders** (viewer
  ignores Word table styles) → explicit borders + shaded key column added and re-checked;
  later pages verified by reading the file back: events table with colour fills, 3 charts at
  17 cm, method + limitation bullets. (LibreOffice is not installed — the `soffice` link is
  broken — so a full-document PDF render was not done.)
- `tests/test_main_cli.py` (8): report contents, thresholds from the command line, five invalid
  inputs (exit 2 + message), running exactly as `python main.py analyze ...`. Suite: **199 passed,
  3 xfailed**.

Limitations: same analysis limits as P2; the report is in English only; only one real video.

## P4 — Local web GUI · Verified (2026-11-07)
`python main.py --gui [--port N] [--host H] [--no-browser]` starts a local web app on
**127.0.0.1:8765** and opens the default browser. **No login, no accounts, no database.**
`backend/src/gameqa/webgui/app.py` (FastAPI): `GET /` page, `GET /api/config`,
`POST /api/analyze` (upload streamed to disk; extension check → 415, bad setting → 422, size
limit → 413), `GET /api/jobs/{id}` (status + progress + result), chart PNGs, Word report and
JSON downloads. One analysis at a time on a background thread; jobs kept in memory; files in
`outputs/<date-time>_<video>/` (+ `input/` with the uploaded video). A video that turns out
not to be a video fails with the engine's message and its folder is deleted. If the port is
taken, it says so and suggests `--port N+1` (exit 2). Listening beyond localhost prints a
warning (no login).
`webgui/static/` (`index.html`, `style.css`, `app.js`; no build step, no external scripts):
upload card (drag-and-drop or click, .mp4/.mkv/.avi, target 60/30/120/144 FPS, advanced
thresholds), progress bar (upload % then analysis frame counter), results (verdict, Word report
+ JSON downloads, 6 key numbers, effective-FPS chart, events table with timestamps and colour
tags, frame-interval and repeated-frame charts, video metadata, limitations, saved folder),
failure card; `#job=<id>` link reopens a result; light and dark mode; phone width.

Tests run:
- Real video uploaded to the running GUI: progress shown live (e.g. "32 % · analysing frame
  3,960 of ~11,955"); results **identical to the CLI**: 1 freeze, 0 drops, 4 stutters, median
  57, 1 % low 30, lowest 5, 9 % measurable, 130 missed frames; 23.8 s analysis; 3 charts load;
  Word report downloads (148 KB, `FPS_ANALYSIS_REPORT_<video>.docx`); JSON downloads.
- In the page: `notes.txt` → "not supported" message, button stays disabled; corrupt
  `broken_recording.mp4` → "Analysis failed: … is not a video file …", no folder left behind.
- Second `python main.py --gui` while running → port-in-use message, exit 2.
- Bugs found and fixed in browser testing: (1) changing only the `#job=` link did not switch
  the page to that job → now follows link changes; (2) on a 375 px phone screen the long video
  file name pushed the page to 472 px wide → names wrap, the events table scrolls inside its
  card. Re-checked on phone and desktop width, light and dark.
- `tests/test_webgui.py` (8): page/config without login, full upload→results flow, **GUI and
  CLI give identical results**, unsupported format rejected without leftovers, fake video fails
  and is cleaned up, invalid setting 422 / unknown job 404, browser opened at
  http://127.0.0.1:port (and not with `--no-browser`), port-in-use message. Suite: **207 passed,
  3 xfailed**.

Limitations: one analysis at a time; results are kept in memory, so after restarting the GUI
old `#job=` links say "not found" (the files stay in `outputs/`); uploaded videos are kept in
`outputs/.../input/` (delete old folders by hand); no login, so it must stay on 127.0.0.1;
analysis limits as P2.

## P5 — Documentation (.docx) · Done (2026-11-07)
**`docs/PROJECT_DOCUMENTATION.docx`** (≈ 1.7 MB): title page (university, group, supervisor), status
legend (Implemented and Tested / In Development / Proposed for Future Phases), contents, the
**20 required sections**, Appendix A (output files) and B (source files) — 47 tables, 14 figures,
20 numbered equations. **`docs/FPS_ANALYSIS_REPORT.docx`**: the per-video report of a real CLI
run on the real gameplay video (copied unchanged from `outputs/20261107-223236_…/`).

Generated, not hand-written, so it can be rebuilt as the project develops:
- `backend/scripts/capture_gui_screenshots.py` — drives headless Chrome over the DevTools
  protocol through a **real upload of the real video** (sets the page's file input, clicks
  Analyze, waits for the real analysis) and saves 8 PNGs (`docs/screenshots/gui_*.png`):
  start page, file chosen, progress, results, events, charts + metadata, unsupported file,
  failed analysis.
- `backend/scripts/build_project_docs.py --run outputs/<run>` — reads `analysis.json` and the
  charts of that run, the synthetic tuning / held-out tables
  (`evaluation/results/prototype_fps/report_seeds_*.md`), the pytest log
  (`docs/screenshots/pytest_full.txt`, refuses to build if tests failed), the captured CLI output
  (`docs/screenshots/cli_*.txt`), installed package versions and the machine; draws the
  architecture and pipeline diagrams (matplotlib); renders page 1 of the report with Quick Look.
  Results of the earlier detectors (texture, animation, NPC, clipping) are quoted from this file
  and say so.

Small fixes made while capturing the CLI output: errors are now printed after the banner when
output is redirected (stdout flushed first); `--gui` without FastAPI now says how to install it
(the old message still said "not available yet (Phase 4)").

Checks: document read back with python-docx — all 20 section headings, 23 table / 14 figure
captions, no empty or "None" values; one wrong cross-reference found ("Figures 3–6" → now
computed: 2–5); diagrams and all screenshots inspected; page 1 rendered with Quick Look.
Not done: a full page-by-page render (LibreOffice not installed; Quick Look renders only page 1;
Microsoft Word was not scripted to avoid opening it on the user's screen) → open it in Word to
review pagination. Suite at build time: **207 passed, 3 xfailed**.

Limitations: the per-video report sample is from the only real video; screenshots are
macOS/Chrome light mode; Windows setup instructions are untested.

## P6 — Prototype testing and demonstration · Verified (2026-11-07)
`backend/scripts/phase6_test.py` builds a test set and runs every case through the **real CLI**
(`python main.py analyze`, subprocess) **and the running GUI** (same upload endpoint as the
page), compares the two, and writes `evaluation/results/phase6/{results.json,report.md}`.
Only one real gameplay recording exists, so the videos are **derived from it** (labelled as
such): 20 s gameplay clip (.mp4 and .mkv), 720p AVI (MPEG-4 Part 2), 30 FPS (target 30), VFR
(repeats removed with mpdecimate), static editor segment, file cut to half its bytes, 2-frame
file, non-ASCII/space file name, and two copies with a defect injected at a known time; plus 6
invalid inputs (missing path, .txt, .mov, text renamed .mp4, 0-byte .mp4, folder named .mp4).

Results (final run): **CLI and GUI identical on all 10 analysable videos**; injected freeze
found at 10.00–10.80 s (injected 10.0–10.8), injected 20 FPS drop found at 3.50–6.75 s
(injected 4.0–6.5); MP4 / MKV / non-ASCII name give the same result as the original; static
segment: "Not measurable"; damaged, 2-frame and all invalid inputs: one-line reason, exit 2,
GUI 415 or failed job, no leftover files.

**Bug found and fixed (VFR):** the VFR copy reported an FPS drop at 8.5–9.75 s (26 FPS) that
the original did not: a 0.68 s moment where the player stood still (41 repeated frames in the
original, which the CFR analysis correctly treats as not measurable) became one timestamp gap,
and windows counted every gap as missing pictures without the motion test. Also, all hidden
frames were credited to the frame after the gap, so windows covering the gap missed them.
Fix (`detectors/fps.py`): hidden frames are placed at their own times inside the gap and
treated exactly like repeated CFR frames (missed only if the abrupt-edge + sustained-motion test
passes, otherwise they lower the window's moving share); still gaps are no frame times
(`analysis.py`). Not a threshold change. Regression test
`test_player_stopping_is_not_a_drop_in_cfr_or_vfr` (CFR + VFR). Re-runs: prototype tuning and
held-out reports **identical**; Phase 3 report identical except the summary line of
`p3_v1game_vfr` (median 54 → 53.5, measurable 91.5 → 93 %; same 4 detections, all TP). VFR copy
now: 1 freeze / 0 drops / 4 stutters, median 57 — same as the original.
Also: damaged-file message now names the file and says "damaged or incomplete" instead of
printing the full internal path.

**Recorded, not tuned:** the AVI re-encode does not report the 18.37 s freeze — the first frame
of the hold differs by 0.33 (> 0.25 repeat threshold), the same compression limitation as the
missed held-out freeze (P2). (In the original that freeze is the known editing-transition FP.)

Demo: `docs/DEMO_GUIDE.docx` (`backend/scripts/build_demo_guide.py`, numbers read from
results.json): checklist, 6 timed steps (intro, CLI, GUI, known-defect proof, errors,
limitations), likely questions, troubleshooting. Step 4 rehearsed through the real page
(headless Chrome): freeze shown at 00:10.000–00:10.800. `PROJECT_DOCUMENTATION.docx` rebuilt:
new §17.6 Phase 6 table, VFR rule in §8.2 / Eq. 9, roadmap P1–P6 done.
Suite: **209 passed, 3 xfailed**.

Limitations: all test videos derive from one recording of one game; no FPS-counter or profiler
ground truth; tested on macOS only.

