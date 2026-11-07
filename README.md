# AI Game QA Tester

Automated game bug detection and reporting from **recorded gameplay video**, using
computer vision (OpenCV, SSIM, Farneback optical flow, YOLOv8, MediaPipe).
Final Year Project, BS Computer Science, PUCIT — University of the Punjab.

Upload a recording → the system analyses it offline for five defect categories → every
finding gets a timestamp, a screenshot, a 5–10 s evidence clip and a Low/Medium/High
severity → review it in a web dashboard → export a JSON or PDF bug report. No game-engine
access, source code or profiler logs are needed or used.

**Read before relying on results:** detection quality differs a lot by category — see
[docs/EVALUATION.md](docs/EVALUATION.md). In short: FPS drop/freeze and animation glitches
work well on injected defects; texture pop-in is moderate and confuses UI changes with
pop-in; NPC anomalies are untested on game footage; viewmodel clipping failed validation
and is switched off.

- Plan and feasibility review: [docs/ROADMAP.md](docs/ROADMAP.md)
- Phase-by-phase status, tests and known issues: [DEVELOPMENT_PROGRESS.md](DEVELOPMENT_PROGRESS.md)
- Results summary: [docs/EVALUATION.md](docs/EVALUATION.md)
- Labelling and evaluation tools: [evaluation/README.md](evaluation/README.md)

## Architecture

```
React dashboard (frontend/) ──HTTPS──► FastAPI (gameqa.api) ──► PostgreSQL (users, projects, jobs, detections, audit)
                                          │ upload → job "queued"
                                          ▼
                              worker (gameqa.worker) ── one job at a time
                                          │
              video engine (gameqa.video) ─┤ one decode pass, full-rate + 12 FPS streams
                                          ▼
   detectors: fps_drop · texture_pop_in · animation_glitch · npc_anomaly · collision_clipping
                                          ▼
              severity rules (gameqa.severity) → evidence: screenshots + H.264 clips (gameqa.evidence)
                                          ▼
                          JSON / PDF reports (gameqa.reports)
```

## Setup (macOS / Linux)

Requirements: Python 3.10+ (3.13 used), ffmpeg with libx264, PostgreSQL 14+ (18 used),
Node.js 18+ (for building the dashboard).

```bash
backend/scripts/install.sh            # venv, packages, OpenCV fix, model weights, then `gameqa doctor`
(cd frontend && npm install && npm run build)
cp .env.example .env                  # then set GAMEQA_API__SECRET_KEY to a long random string
```

## Running the full system

```bash
# 1. database (a project-local instance; any PostgreSQL works via GAMEQA_DATABASE__URL)
/opt/homebrew/opt/postgresql@18/bin/initdb -D data/postgres -U gameqa --auth=trust --locale=C   # once
LC_ALL=en_US.UTF-8 /opt/homebrew/opt/postgresql@18/bin/pg_ctl -D data/postgres \
  -o "-p 5433 -k /tmp -c listen_addresses=localhost" -l data/logs/postgres.log start
/opt/homebrew/opt/postgresql@18/bin/createdb -h localhost -p 5433 -U gameqa gameqa                 # once

# 2. first admin account (password is prompted)
backend/.venv/bin/gameqa create-user --email admin@example.com --role admin

# 3. HTTPS certificate for the demo (self-signed) and the two processes
backend/scripts/make_dev_cert.sh
backend/.venv/bin/gameqa worker &
backend/.venv/bin/gameqa serve --port 8443 --ssl-cert data/tls/dev-cert.pem --ssl-key data/tls/dev-key.pem
```

Open `https://localhost:8443` (the built dashboard is served by the API; the browser warns
about the self-signed certificate until it is trusted). For frontend development:
`cd frontend && npm run dev` (Vite on :5173, proxies `/api` to :8443).

Stop: `pkill -f "gameqa (serve|worker)"` and
`/opt/homebrew/opt/postgresql@18/bin/pg_ctl -D data/postgres stop`.
Backups (SRS 5.1, daily): `pg_dump -h localhost -p 5433 -U gameqa gameqa > backup.sql`
plus a copy of `data/uploads` and `data/evidence`.

## Command line

```bash
backend/.venv/bin/gameqa doctor                    # environment check
backend/.venv/bin/gameqa probe VIDEO               # metadata, frame timing, VFR, truncation
backend/.venv/bin/gameqa detect VIDEO [--detectors fps_drop,...] [-o out.json] [--evidence DIR]
backend/.venv/bin/gameqa evaluate -p PRED.json -g evaluation/ground_truth -o OUT
backend/.venv/bin/gameqa extract VIDEO -o DIR      # frames for labelling
backend/.venv/bin/gameqa bench VIDEO               # throughput vs real time
backend/.venv/bin/gameqa serve | worker | create-user
backend/.venv/bin/python -m pytest backend         # 179 tests (+3 expected failures, see EVALUATION)
```

Configuration: `config/default.yaml` (every threshold and path); override any value with
`GAMEQA_<SECTION>__<FIELD>` environment variables or `.env`.

## Layout

```
backend/src/gameqa/   core · video · detectors · pipeline · severity · evidence · reports · api · worker · evaluation
backend/tests/        pytest suite (synthetic videos generated on the fly)
backend/scripts/      install, certificate, per-phase evaluation scripts
frontend/             React + Vite dashboard
config/               configuration
evaluation/           labels (real + synthetic) and results; videos are git-ignored
data/                 runtime storage (uploads, evidence, models, logs, database) — git-ignored
```
