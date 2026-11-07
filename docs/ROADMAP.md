# AI Game QA Tester — Development Roadmap

Source of truth: `AI_Game_QA_Tester_FYP_Proposal (2) (1).docx` (the proposal) and
`FYP1_SRS-BCS-F23M526.docx` (the SRS). Requirement IDs below (FR-1 … FR-6, NFR §5.x)
refer to the SRS.

---

## 1. Requirements digest

| ID | Requirement (condensed) | Phase(s) |
|----|-------------------------|----------|
| FR-1 | Upload .mp4/.avi/.mkv (others rejected with message, no job); async job queue; status queued / processing / complete / failed | 2 (validation), 10, 11 |
| FR-2 | OpenCV decode; normalise resolution + colour space; per-frame timestamps from metadata; keep full-rate frame intervals for FPS analysis; sub-sample to 10–15 FPS for other detectors | 2 |
| FR-3 | Five detectors in one pass: (a) NPC — T-pose, frozen, floating, ragdoll via YOLOv8 + MediaPipe; (b) texture pop-in via SSIM (+ autoencoder as proposed alternative); (c) FPS drops vs 30/60 target + frozen frames; (d) animation glitches — unnatural transitions, missing keyframes, flicker, jitter via Farneback flow; (e) collision/geometry clipping via bounding-box overlap. Detections must persist across consecutive frames | 3–8 |
| FR-4 | Start/end timestamps; high-res screenshot; 5–10 s clip; traceable to original footage | 9 |
| FR-5 | Low/Medium/High by affected area, duration, recurrence; High = collision or severe performance; persist to DB | 9, 10 |
| FR-6 | Dashboard list with category/timestamp/severity/screenshot/clip; filter by category and severity (combined); JSON export; PDF with screenshots + summary stats | 11, 12 |
| NFR 5.1 | One detector failing must not kill the job → "completed with warnings"; failed jobs re-runnable without re-upload; daily DB backup | 8, 10 |
| NFR 5.2 | Upload ≤ 3 steps; clip in ≤ 2 clicks; export = 1 action; contrast ≥ 4.5:1; severity = colour + text | 11 |
| NFR 5.3 | Preprocessing ≥ real time for 1080p30/60; upload ≤ 2 GB; queued within 5 s; 1 running + 5 queued; ~12 FPS analysis target (15-min video ≤ 45 min, provisional); list ≤ 2 s for 500 detections; filter ≤ 1 s; JSON ≤ 5 s; PDF (100 detections) ≤ 30 s | 2, 8, 10–12, 13 |
| NFR 5.4 | Email + password (≥ 8 chars, bcrypt); signed tokens, 12 h inactivity expiry; RBAC (tester / developer / QA lead / admin), per-project isolation; HTTPS TLS ≥ 1.2; files outside web root via authenticated endpoints; content-type + size checks; parameterised queries; audit log; cascading delete of video + evidence | 10, 11 |
| Validation (proposal §8.3) | Per-class precision / recall / F1; mAP@0.5 for spatial bugs; FPS MAE; throughput (FPS processed) | 1 (harness), 3–7, 13 |

## 2. Feasibility review — gaps, conflicts and unrealistic expectations

These are stated plainly so the final report does not over-claim.

1. **Hardware mismatch (blocking for the SRS performance targets, not for development).**
   The SRS assumes a CUDA GPU on Ubuntu/Windows. The development machine is an
   **Apple M1, 8 GB RAM, no CUDA**. All code will be device-agnostic
   (`cuda` → `mps` → `cpu` auto-selection). YOLOv8 can use Apple `mps`; MediaPipe runs on
   CPU. Throughput figures measured here will be reported as *M1 figures*, not as the
   SRS target hardware. 8 GB RAM means frames must be **streamed**, never held as a
   whole video in memory.

2. **FPS-drop detection from a recorded file — the documented method does not work as
   written.** The SRS says "compare frame presentation intervals against the 30/60 FPS
   target". Most capture tools (OBS, ShadowPlay, Game Bar) record at a **constant
   frame rate**: when the game drops frames the recorder *duplicates* the previous frame,
   so every presentation interval in the file is identical. Container timestamps only
   help for variable-frame-rate (VFR) recordings.
   *Realistic approach:* (a) use container PTS intervals when the file is VFR; (b) for
   CFR files, detect **duplicated / near-identical consecutive frames** and compute an
   *effective rendered FPS* per sliding window. Limitations: a static scene (paused menu,
   camera not moving) also produces identical frames → must be distinguished using
   HUD/UI-change cues and documented as a false-positive source; the recording rate caps
   what can be measured (a 60 FPS recording cannot show drops from 144 → 90).
   *Ground truth conflict:* the proposal measures MAE against "engine profiler logs",
   but the SRS explicitly says the system has no profiler access. Proposed alternative:
   ground truth from (i) footage recorded with an on-screen FPS counter (RTSS / in-game
   overlay) read manually, and (ii) controlled frame-drop injection into clean footage
   (exactly known ground truth, clearly labelled as synthetic).

3. **Collision / geometry clipping via bounding-box overlap — weakest requirement.**
   COCO-pretrained YOLOv8 has no classes for walls, floors, terrain or most props, so
   there is no "static geometry" box to overlap with. Even with boxes, 2-D box overlap is
   identical for "character behind a wall" (correct occlusion) and "character inside a
   wall" (clipping) — depth is not observable from a single rendered view.
   *Realistic approach (to be evaluated in Phase 7):* (a) character–character and
   character–prop interpenetration using person/object boxes + pose keypoints
   (feasible with COCO classes); (b) a **fine-tuned YOLOv8 "clipping" appearance class**
   trained on labelled frames (needs a labelled dataset — e.g. GlitchBench-style images
   + self-recorded clips annotated in CVAT); (c) report static-geometry clipping only as
   *low-confidence candidates*. This detector will be documented as the least reliable.

4. **NPC anomalies.** YOLO "person" + MediaPipe Pose are trained on **real humans**.
   They work on realistic humanoid characters and degrade on stylised, non-human, small
   or heavily armoured characters. MediaPipe Pose is single-person, so it must run on
   YOLO crops. Per sub-type:
   - *T-pose*: feasible (arm abduction angle ≈ 90°, elbows straight, held over time).
   - *Frozen NPC*: feasible but ambiguous — an idle NPC standing still is normal. Will be
     defined as "keypoints static while the character is in a non-idle context / scene
     is moving" and tuned for precision.
   - *Floating*: no ground plane or depth from 2-D video. Only a weak heuristic is
     possible (feet keypoints vs. shadow / support region, sustained vertical offset).
     Expect low recall; will be reported honestly.
   - *Ragdoll failure*: approximated as anatomically impossible keypoint configurations
     and extreme keypoint velocity. Heuristic, not a physics check.
   - Note: the MediaPipe 1.x Python package no longer ships the legacy
     `mp.solutions.pose` API; the **Tasks API (`PoseLandmarker`)** will be used.

5. **Texture pop-in vs. normal scene change.** Frame-to-frame SSIM drops for camera cuts,
   fast pans, explosions, UI overlays and lighting changes. A raw SSIM threshold will
   produce many false positives. *Approach:* estimate global camera motion (feature
   homography), warp the previous frame onto the current one, compute **region-wise**
   SSIM, and flag local, sharp, persistent changes that do not match global motion;
   suppress shot cuts. The **convolutional autoencoder** is listed in the SRS as a
   "proposed alternative": it needs a training set of clean footage per game and will be
   evaluated only if SSIM results are insufficient — not silently skipped, but built
   only if justified by measurements.

6. **Animation glitches at 10–15 FPS.** Flicker and single-frame jitter can be invisible
   after sub-sampling (aliasing). The frame stream will therefore offer short
   **full-rate windows** around candidate events. Optical-flow outliers are dominated by
   camera motion, so global motion will be compensated first (shared with pop-in).
   "Missing keyframes" is not directly observable in video; it will be approximated as
   a sudden discontinuity in local motion (teleport / pop between poses).

7. **No labelled dataset exists yet.** The proposal cites a ~20 GB / 500+ clip custom
   dataset that does not yet exist. This is the **largest project risk**: every detector
   needs real footage with and without its defect, labelled with start/end times. A
   dataset track runs alongside the detector phases (see §5). Where real defect footage
   for a sub-type cannot be found, the limitation will be reported rather than
   replaced by synthetic numbers.

8. **Severity rules partly conflict.** FR-5 says severity comes from area / duration /
   recurrence, but also says "High = a collision problem or severe performance issue",
   i.e. category influences severity. Implementation: a category-aware rule table
   (category gives the ceiling/floor, measurements place the detection within it), with
   the reason string stored for every decision. "Affects gameplay" cannot be observed
   from pixels, so Low/Medium is a proxy and will be described as such.

9. **Evidence clips.** OpenCV's `VideoWriter` on macOS/Linux typically produces MPEG-4
   Part 2 (`mp4v`) which browsers do not play. Clips will be cut with **ffmpeg (H.264,
   `+faststart`)** so they play in the dashboard's HTML5 `<video>` element. Screenshots
   use OpenCV.

10. **mAP@0.5** requires bounding-box ground truth for NPC and clipping detections (CVAT
    annotation), not just time intervals. Planned for Phase 13 on a small annotated
    subset; time-interval P/R/F1 is the primary metric for all five detectors.

11. **"Five detectors run in parallel" (proposal).** On an 8 GB M1, running five models
    concurrently would exhaust memory. The pipeline will make **one decoding pass** and
    feed each frame to all enabled detectors sequentially (meets FR-3's "single pass"
    requirement without the memory cost of parallel processes).

12. **Out of scope (kept out):** real-time analysis, engine plugins, source-code access,
    audio/network/localisation bugs, automatic fixing, mobile UI (SRS §3, §6.4).

13. **SRS placeholders still open:** exact GPU model, minimum RAM, JIRA/Trello URL, and
    incomplete citations [7]–[9]. These do not block development but must be filled in
    the final documents.

## 3. Technology decisions

| Concern | Choice | Reason |
|---------|--------|--------|
| Language | Python 3.13 (meets "3.10+") | Newest version for which OpenCV, Ultralytics, MediaPipe and PyTorch all ship macOS-arm64 wheels |
| Video I/O | OpenCV 4.x (`opencv-python-headless`) + ffprobe/ffmpeg | OpenCV for decoding/processing as documented; ffprobe for reliable metadata (VFR detection, rotation, codec); ffmpeg for browser-playable clips. Pinned `<5` to match the documented "OpenCV 4.x" |
| SSIM | `scikit-image` (`structural_similarity`) | Reference implementation, region-wise maps |
| Optical flow | OpenCV `calcOpticalFlowFarneback` | As documented |
| Detection / pose | Ultralytics YOLOv8 (COCO) + MediaPipe Tasks `PoseLandmarker` | As documented |
| Backend | **FastAPI** | Native async, request validation via Pydantic (shared with the detection schema), automatic OpenAPI docs for the frontend team |
| Database | **PostgreSQL** + SQLAlchemy 2 + Alembic | Data is relational (users ↔ projects ↔ jobs ↔ detections); RBAC and per-project isolation map to foreign keys; `ON DELETE CASCADE` supports the SRS deletion rule; parameterised queries by default |
| Job queue | DB-backed queue + one worker process | SRS load is 1 running + 5 queued. Avoids adding Redis/Celery; jobs survive restarts; re-run = re-queue |
| Frontend | React (Vite) + TypeScript | As documented; Vite is the current standard React tooling |
| PDF | ReportLab | Pure Python, no system libraries (WeasyPrint needs Pango/Cairo) |
| Config | YAML defaults + environment overrides (`GAMEQA_…`) via `pydantic-settings` | One typed config object used by CLI, worker and API |
| Testing | pytest; per-detector evaluation harness with temporal-IoU matching | Same metric code for all five detectors |

## 4. Phases

The order was adjusted from the original brief in one place: the detectors are ordered
by **dependency and risk**, not by the order in the proposal. FPS/frozen-frame comes
first (most deterministic, establishes the evaluation workflow), texture pop-in
introduces global-motion compensation that animation detection reuses, and NPC
detection introduces YOLO/MediaPipe tracking that clipping detection reuses. All five
categories remain in scope. Security, which the SRS specifies in detail but the brief
did not list, is given its own phase.

| # | Phase | Objective & deliverables | Depends on | Success criteria (completion gate) | Complexity |
|---|-------|--------------------------|-----------|-----------------------------------|-----------|
| 1 | **Project foundation** | Repo layout, Python package, typed config (YAML + env), logging, the shared `Detection` schema, streaming `Detector` interface, temporal persistence helper (FR-3 persistence rule), evaluation harness (temporal-IoU P/R/F1), `gameqa doctor` env check, test suite, progress tracking | — | `pytest` green; `gameqa doctor` reports real environment; schema round-trips JSON; metrics verified on hand-computed cases | M |
| 2 | **Video processing engine** | Format/size/content validation (FR-1), ffprobe metadata (fps, VFR/CFR, duration, resolution, codec, rotation), streaming OpenCV decoder, per-frame timestamps (PTS), normalisation (resolution + colour space), dual stream: full-rate timing + 10–15 FPS sampled frames, full-rate windows on demand, `gameqa probe` / `gameqa extract` CLI | 1 | Real gameplay clips (mp4/mkv/avi, 30/60 FPS, CFR+VFR) decode with correct frame counts and timestamps; ≥ real-time on 1080p; bounded memory; corrupt/unsupported files rejected cleanly | M |
| 3 | **FPS-drop & frozen-frame detector** | Effective-FPS estimation (VFR intervals + CFR duplicate-frame analysis), frozen-frame (screen freeze) events, target 30/60 FPS, static-scene suppression | 2 | P/R/F1 on labelled real + injected-drop footage; MAE of effective FPS vs ground truth; documented false-positive cases | M |
| 4 | **Texture pop-in detector** | Global motion compensation (ORB + homography), region-wise SSIM, shot-cut suppression, persistence; autoencoder evaluated only if SSIM metrics are insufficient | 2 | P/R/F1 on footage with real pop-in and clean footage; FP analysis by cause | L |
| 5 | **Animation glitch detector** | Farneback flow with camera-motion compensation; flicker (luminance oscillation), jitter (direction reversals), teleport/discontinuity; full-rate windows | 2, 4 (motion comp.) | P/R/F1 per sub-type where footage exists | L |
| 6 | **NPC anomaly detector** | YOLOv8 person detection + simple tracking, MediaPipe PoseLandmarker on crops, T-pose / frozen / floating / ragdoll rules, persistence | 2 | P/R/F1 per sub-type; YOLO person recall on game characters measured; sub-types without footage reported as untested | XL |
| 7 | **Collision & clipping detector** | Character–character / character–object interpenetration from boxes + keypoints; evaluate fine-tuned YOLO "clipping" class if a labelled set is available; documented limits for static geometry | 6 | P/R/F1 on labelled clips; explicit statement of what cannot be detected | XL (research risk) |
| 8 | **Unified detection pipeline** | One decode pass feeding all enabled detectors; per-detector fault isolation (→ "completed with warnings"); progress callbacks; throughput measurement | 3–7 | Full-length real video processed end-to-end; detector crash injected → job completes with warning; FPS throughput reported | M |
| 9 | **Evidence & severity** | Screenshots (with region outline), 5–10 s H.264 clips via ffmpeg, recurrence grouping, category-aware severity rules with stored reasons | 8 | Every detection has a playable clip and screenshot traceable to source frames; severity rules unit-tested and spot-checked | M |
| 10 | **Backend & database** | FastAPI, PostgreSQL schema + migrations, upload (≤ 2 GB, streamed to disk), DB-backed queue + worker, job status, re-run, deletion with file cleanup, error handling | 9 | API tests; upload → queued ≤ 5 s; worker survives restarts; re-run without re-upload | L |
| 11 | **Authentication & security** | Users/projects, bcrypt, JWT with 12 h inactivity expiry, RBAC (tester / developer / QA lead / admin), per-project isolation, authenticated file serving, audit log, HTTPS for the demo setup | 10 | Security tests: cross-project access denied, expired tokens rejected, audit entries written | M |
| 12 | **Frontend dashboard** | React: login, projects, upload with settings, job queue/progress, detection list with combined filters, evidence panel (screenshot + clip), summary view | 10, 11 | Usability targets from NFR 5.2 checked; list of 500 detections ≤ 2 s; filter ≤ 1 s | L |
| 13 | **Reporting** | JSON export (FR-6 fields + evidence refs), ReportLab PDF with screenshots and per-category/severity statistics | 9, 10 | JSON ≤ 5 s; 100-detection PDF ≤ 30 s; schema validated | M |
| 14 | **Final integration & evaluation** | End-to-end tests, benchmark on the full labelled set, per-class P/R/F1, mAP@0.5 subset, FPS MAE, throughput, usability test, bug fixing, final docs | all | Evaluation report with real numbers and documented limitations | L |

### Dependency graph

```
1 ─► 2 ─┬─► 3 ──────────────┐
        ├─► 4 ─► 5 ─────────┤
        └─► 6 ─► 7 ─────────┴─► 8 ─► 9 ─► 10 ─┬─► 11 ─► 12 ─┐
                                              └──────► 13 ───┴─► 14
```

## 5. Dataset & testing strategy

- **Ground-truth format** (`evaluation/ground_truth/<video_id>.json`): video id, list of
  labelled events `{category, subtype, start_s, end_s, bbox?, notes}`, and the
  categories that were *reviewed* (so absence of a label in a reviewed category counts
  as a true negative region).
- **Matching:** a predicted event matches a ground-truth event of the same category if
  their temporal IoU ≥ 0.3 (configurable) or the prediction's peak falls inside the GT
  interval; greedy one-to-one matching. Unmatched predictions = FP; unmatched GT = FN.
- **Data sources (to be confirmed with the team):**
  1. Self-recorded footage from games the team owns (normal play + deliberately
     reproduced bugs, e.g. lowering texture streaming budget, frame-rate limiter for
     drops, known-buggy indie/early-access games).
  2. Public glitch footage (e.g. GlitchBench / VideoGlitchBench, YouTube compilations)
     — only where licences permit, downloaded with the team's agreement.
  3. Controlled synthetic injection (duplicated frames, inserted freezes, low-res texture
     patch swaps, flicker) — always reported separately from real-footage results.
- **Clean footage is as important as buggy footage**: false-positive rate on normal play
  is the main risk named in the proposal.
- Unit tests for every module; evaluation runs for every detector; end-to-end tests from
  Phase 8 onward.

## 6. Recommended folder structure

```
FYP/
├── docs/                      ROADMAP.md, architecture notes, the proposal & SRS
├── backend/
│   ├── pyproject.toml
│   ├── src/gameqa/
│   │   ├── config.py          typed settings (YAML + env)
│   │   ├── logging_setup.py
│   │   ├── cli.py             `gameqa` command
│   │   ├── core/              schemas, detector interface, persistence helper, errors
│   │   ├── video/             Phase 2: probe, decode, normalise, frame streams
│   │   ├── detectors/         Phases 3–7: fps/, texture/, animation/, npc/, clipping/
│   │   ├── pipeline/          Phase 8: single-pass runner
│   │   ├── evidence/          Phase 9: screenshots, clips
│   │   ├── severity/          Phase 9: rule engine
│   │   ├── evaluation/        Phase 1: ground truth + metrics
│   │   ├── db/                Phase 10: models, migrations
│   │   ├── api/               Phases 10–11: FastAPI routers, auth
│   │   ├── worker/            Phase 10: job runner
│   │   └── reports/           Phase 13: JSON + PDF
│   └── tests/
├── frontend/                  Phase 12: React + Vite
├── config/default.yaml        all thresholds and paths
├── evaluation/                ground_truth/, results/ (videos are git-ignored)
├── data/                      runtime storage: uploads/, evidence/, models/ (git-ignored)
├── DEVELOPMENT_PROGRESS.md
└── README.md
```
