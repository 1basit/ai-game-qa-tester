# AGENTS.md: context for AI assistants

This file gives any AI coding assistant (Claude Code, Cursor, Copilot, ChatGPT, Gemini…) the
context needed to understand, explain and safely work on this repository. `CLAUDE.md` imports it.

## What this project is

**AI Game QA Tester: Automated Game Bug Detection and Reporting Using AI and Computer Vision.**
Final Year Project, PUCIT, University of the Punjab.
Team: Abdul Basit (BCSF23M526, group leader), Furqan Khalid (BCSF23M534), Zayyam Waseem
(BCSF23M549), Husnain Mughal (BCSF23M530). Supervisor: Ma'am Tayyaba.

The finished, demo-ready part is the **FPS-analysis prototype**: it reads a gameplay video and
reports **freezes, FPS drops and stutter** with exact times, statistics, 3 charts and a Word
report, from the terminal or a local no-login web page. It works only from the video (no game
access): a picture repeated *while the scene is moving* means the game missed a frame.

## Teaching someone this project

If a user asks you to explain or teach the project, **use `docs/PROJECT_GUIDE.md`**. It is
written in simple English with examples, in the right teaching order (start with its section 3,
"the five ideas"). Explain in plain words, use its examples, and quote only numbers that appear
in the repository's result files. Do not invent results.

## Quick start (macOS / Linux)

Requirements: Python 3.13 (3.10+), ffmpeg with libx264, Google Chrome (only for screenshot scripts).

```bash
backend/scripts/install.sh       # creates backend/.venv, installs packages + model weights, runs `gameqa doctor`
```

The script uses `python3.13`; with another version run `PYTHON=python3.12 backend/scripts/install.sh`.

The demo video is **not in git** (third-party, licence). Get YouTube video `J8HB1-IQFxc`
("How to fix Weapons/Hands Clipping Into Walls in Unity URP/SRP", 1080p60) and save it as
`evaluation/videos/YTDown.com_YouTube_Media_J8HB1-IQFxc_How-to-fix-Weapons-Hands-Clipping-Into-Walls-in-Unity-URP-SRP_001_1080p.mp4`
(details: `evaluation/videos/sources.md`). The 20 s demo clip is cut from it:

```bash
mkdir -p evaluation/synthetic/phase6 && ffmpeg -i evaluation/videos/YTDown.com_YouTube_Media_J8HB1-IQFxc_How-to-fix-Weapons-Hands-Clipping-Into-Walls-in-Unity-URP-SRP_001_1080p.mp4 -t 20 -c copy -an evaluation/synthetic/phase6/real_gameplay_20s.mp4
```

Run:

```bash
backend/.venv/bin/python main.py analyze --video evaluation/synthetic/phase6/real_gameplay_20s.mp4   # CLI
backend/.venv/bin/python main.py --gui                                                              # GUI on http://127.0.0.1:8765
backend/.venv/bin/python -m pytest backend                                                          # 209 passed, 3 xfailed
```

CLI options: `--target-fps`, `--drop-ratio`, `--freeze-ms`, `--stutter-min-missed`, `--output`,
`--no-report`, `--quiet`. Results go to `outputs/<date-time>_<video>/` (git-ignored).
A harmless `RuntimeError: cannot schedule new futures after shutdown` may print after pytest finishes.

## Repository map

```
main.py                         prototype entry point: `analyze --video ...` | `--gui`
config/default.yaml             every threshold (section fps_service: target 60, drop_ratio 0.75, freeze_ms 250, stutter_min_missed 3)
backend/src/gameqa/
  fps_service/                  PROTOTYPE engine: analysis.py (analyze_video, used by CLI and GUI), charts.py, report_docx.py, store.py
  webgui/                       PROTOTYPE local GUI: app.py (FastAPI) + static/ (index.html, app.js, style.css; no build step)
  detectors/fps.py              repeated/missed-frame detection (shared with the full system)
  video/                        validation, ffprobe metadata (probe.py), decoding
  detectors/ (others)           texture pop-in, animation glitch, NPC, clipping (full system, see status below)
  api/ worker/ pipeline/ ...    full system: FastAPI + PostgreSQL + worker + React dashboard (frontend/)
backend/tests/                  pytest suite (synthetic videos generated on the fly)
backend/scripts/                install, evaluation and doc-building scripts
docs/                           PROJECT_GUIDE.md (start here), ROADMAP.md, EVALUATION.md, USER_GUIDE.md, *.docx, screenshots/
evaluation/                     labels (ground_truth*/), results/, label_template.json; videos/ is git-ignored
DEVELOPMENT_PROGRESS.md         per-phase log with real numbers (prototype track P1–P6 at the end)
```

## Status

- **Prototype P1–P6: done and verified.** Exam (held-out) results: stutter 11/11, freeze 8/9,
  drop 7/7, **0 false alarms** (`evaluation/results/prototype_fps/`). CLI and GUI identical on
  all 10 analysable cases of the 18-case test set (`evaluation/results/phase6/`).
- **Full system (phases 1–14):** exists; texture pop-in and animation detectors verified only with
  limitations, NPC detector blocked (no footage), clipping failed validation. See `DEVELOPMENT_PROGRESS.md`.
- **No AI model has been trained by the team yet.** Detectors use pretrained YOLOv8n (COCO) and
  MediaPipe, or rules. The labelled dataset does not exist yet (biggest risk, `docs/ROADMAP.md` §5).
- Only one real gameplay video has been used so far.

## Rules for working on this repo

1. **No fake results.** Every number in docs, slides or reports must come from a real run. If
   something was not tested, say so.
2. **Evaluation protocol:** thresholds are chosen on *tuning* data (seed 0) and reported on
   *held-out* data (seeds 1–3) generated after the thresholds were fixed. Never tune on held-out
   data; disclose any tuning. Synthetic results are always reported separately from real-footage
   results. For future AI training: split train/validation/test **by video**, never by frame.
3. **The prototype GUI has no login, so it must stay bound to 127.0.0.1.**
4. **Never commit secrets or data:** `.env`, `data/` (credentials, uploads, model weights),
   videos and `outputs/` are git-ignored; keep it that way.
5. **Tests must not touch a real database.** API tests use a temporary SQLite file by default;
   never point `GAMEQA_TEST_DATABASE_URL` at a real `gameqa` database.
6. Main documentation for the supervisor is **Word (.docx)**, rebuilt from real runs:
   `backend/.venv/bin/python backend/scripts/capture_gui_screenshots.py --video <video> --url http://127.0.0.1:8765`
   (GUI running), then, with `backend/.venv` activated, `python backend/scripts/build_project_docs.py --run outputs/<run>`.
7. Change detection thresholds only through `config/default.yaml`, and re-run the evaluation scripts after any change to `detectors/fps.py`.
