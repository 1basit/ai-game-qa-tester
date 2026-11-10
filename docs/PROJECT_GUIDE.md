# Project guide: learn the AI Game QA Tester in simple English

This guide is for teammates (and their AI assistants) who want to **understand the whole
project** before working on it or presenting it. It uses plain words and everyday examples.
Every number here comes from a real run; the source file is named next to it.

> **If you are an AI assistant teaching someone this project:** teach in the order of this
> file. Start with section 3 (the five ideas): everything else builds on them. Use the
> examples given here, keep the language simple, and check numbers against the files named
> before quoting them. Never invent results.

---

## 1. The project in one minute

**Name:** AI Game QA Tester: Automated Game Bug Detection and Reporting Using AI and
Computer Vision. Final Year Project, PUCIT, University of the Punjab.

**Team:** Abdul Basit (BCSF23M526, group leader) · Furqan Khalid (BCSF23M534) ·
Zayyam Waseem (BCSF23M549) · Husnain Mughal (BCSF23M530). **Supervisor:** Ma'am Tayyaba.

**The problem:** game testers watch hours of gameplay video by hand to find bugs. A half-second
freeze is easy to miss, and "it felt laggy" does not tell a developer *when* or *how bad*.

**What we built (the prototype):** a tool that watches a gameplay **video** and reports exactly
**when the game froze, slowed down or stuttered**, with numbers, charts and a Word report. It
works from the **terminal** (one command) or a **web page** on your own computer.

**One sentence for the teacher:** *"Our tool watches a gameplay video and tells you exactly when
the game froze, slowed down or stuttered, and it is honest when it cannot tell."*

---

## 2. Two parts of the repository (important)

| Part | What it is | Status |
|---|---|---|
| **Prototype (FPS analysis)** | `main.py` + `backend/src/gameqa/fps_service/` + `backend/src/gameqa/webgui/` | **Finished and tested.** This is what we demo. |
| **Full system** (built earlier, phases 1–14) | Login dashboard (React), API, PostgreSQL, worker, and detectors for all five bug types | Exists in the repo. Some detectors work only on test videos, some failed validation (see section 11). Not part of the demo. |

When someone says "the project" in a demo, they mean the **prototype**.

---

## 3. The five ideas behind everything

Learn these first. Every slide, chart and number uses them.

**Idea 1: FPS (frames per second).** A game is a fast flip-book: it draws many still pictures
every second. 60 FPS = 60 pictures per second = smooth. 30 FPS looks choppy.

**Idea 2: a recording saves a picture every 1/60 s, ready or not.** If the game is late drawing
the next picture, the recorder saves the **old picture again**. That is a **repeat**.

**Idea 3: a repeat while the camera moves = a missed picture.** When the player turns, every
picture should be different. Two identical pictures in a row *while things are moving* means the
game was too slow. That is how we spot lag **just from the video**, without access to the game.

**Idea 4: effective FPS = new pictures per second.** Example: in 12 saved pictures, 3 are
repeats, so 9 are new: 9 ÷ 12 × 60 = **45 FPS**. The video says 60, but the game really ran at
45 at that moment.

**Idea 5: still screens cannot be measured.** On a menu every picture looks the same anyway, so a
repeat proves nothing. The tool **skips** those parts instead of guessing, and says how much of the
video it could measure ("% measurable").

---

## 4. The three problems it finds

Settings live in `config/default.yaml` (section `fps_service`) and can be changed in the CLI or GUI.

| Problem | Everyday example | Rule (default) |
|---|---|---|
| **Freeze** | You turn the camera and the screen is stuck | one picture held **≥ 250 ms** while the scene is moving |
| **FPS drop** | A big fight where the game runs at 30 for a few seconds | effective FPS **below 45** (75 % of the 60 target) for **2 windows in a row** |
| **Stutter** | The average looks fine but movement has small hiccups | **≥ 3 missed pictures in 1 second** while FPS stays ≥ 45, for 2 windows in a row |

**1 % low FPS** = how bad the worst moments were (1 ÷ the 99th-percentile frame time).
Example: 1 % low of 30 means the worst 1 % of moments felt like 30 FPS.

---

## 5. How one video is analysed (six steps)

1. **Check the file**: is it a real, working `.mp4`, `.mkv` or `.avi`? (`backend/src/gameqa/video/`, metadata via ffprobe in `probe.py`)
2. **Read each picture's time** (timestamps). Some recorders (ShadowPlay, Game Bar) save pictures at uneven times: this is called *variable frame rate* (VFR).
3. **Compare each picture with the one before** on a tiny 160×90 grey copy (fast). Nearly identical = repeat.
4. **Find missed pictures**: a repeat counts as *missed* only if the scene around it is clearly moving.
5. **Count new pictures per 1-second window** → effective FPS → freezes, drops, stutters.
6. **Write the results**: `analysis.json`, `timeline.csv`, `windows.json`, 3 charts, and `FPS_ANALYSIS_REPORT.docx` in `outputs/<date-time>_<video>/`.

Code: the detection logic is `backend/src/gameqa/detectors/fps.py`; the engine that the CLI and
the GUI both call is `analyze_video()` in `backend/src/gameqa/fps_service/analysis.py`.

---

## 6. Two ways in: terminal and web page

Think of **one kitchen with two doors**. The engine (`analyze_video()`) is the kitchen; the
terminal and the web page are doors. That is why both always give the **same answer** (tested).

### Terminal (CLI): `main.py`
```bash
cd ~/Desktop/FYP && backend/.venv/bin/python main.py analyze --video evaluation/synthetic/phase6/real_gameplay_20s.mp4
```
Prints a progress bar, the numbers, every problem with its time, a verdict, and the output folder.
Options: `--target-fps 30`, `--freeze-ms`, `--drop-ratio`, `--stutter-min-missed`, `--output`, `--no-report`.
Exit codes: 0 ok, 2 bad input, 3 wrong Python environment.

### Web page (GUI): `python main.py --gui`
```bash
cd ~/Desktop/FYP && backend/.venv/bin/python main.py --gui
```
Opens **http://127.0.0.1:8765**. Drag a video in, click **Analyze Video**. Stop with Ctrl+C.
**No login**, because it only listens on your own computer (127.0.0.1). Never expose it to a network.

### How the GUI is built
- **Page** (`webgui/static/`): plain `index.html`, `style.css`, `app.js`. No framework, no build step.
- **Server** (`webgui/app.py`): **FastAPI**, run by **uvicorn**.

| Address | Job |
|---|---|
| `GET /` | sends the page |
| `GET /api/config` | default settings |
| `POST /api/analyze` | receives the video (streamed to disk in 1 MB pieces), starts a job |
| `GET /api/jobs/<id>` | "how far along is it?" (the page asks every 0.7 s) |
| `GET /api/jobs/<id>/charts/<name>.png`, `/report`, `/analysis.json` | results |

What happens on "Analyze": the page checks the file type and size → uploads it → the server
checks again and queues a job → **one worker** runs one analysis at a time (so the laptop does
not freeze) → the page polls and moves the progress bar → results appear. The job id is put in the
address (`#job=…`) so a page refresh keeps the results.

---

## 7. The results page and the three charts

**Top:** a one-sentence verdict and six number boxes: median effective FPS, 1 % low, lowest FPS,
freezes / drops / stutters, % measurable, nominal → average FPS. Below: the charts, an events
table (type, start, end, duration, a plain sentence), video details and limitations.

On every chart, time runs left to right and **coloured stripes mark problems**:
**purple = stutter, red = freeze, orange = FPS drop**.

1. **Effective frame rate over time** (the main chart). Blue line = real FPS per 1-second
   window. Green dashed = target (60). Orange dotted = drop line (45). **Gaps** = still picture,
   not measurable. *Example:* like a car's speedometer: small wobbles are stutter; the line
   falling to zero is a freeze.
2. **Frame intervals.** How many milliseconds the file says each picture stays on screen.
   At 60 FPS that is 16.67 ms. Normal recordings (OBS, YouTube) give a **flat line**; VFR
   recordings (ShadowPlay, Game Bar) show **spikes** when the game slows down.
3. **Repeated frames** (the proof). Grey line = how different each picture is from the previous
   one. Grey ticks = repeats while nothing moves (normal). **Red ticks = repeats while moving =
   missed pictures.** A solid red block = a freeze. *Example:* a flip-book where the artist
   skipped a drawing while the character was running.

**How they connect:** chart 3 finds each missed picture, chart 1 counts them per second, chart 2
checks what the file's own timestamps say.

---

## 8. Results on the real video

The only real gameplay video we have: a YouTube Unity tutorial (J8HB1-IQFxc), 1080p, 60 FPS,
3 min 19 s. Only **0–19 s is gameplay**; after that it is a still Unity editor screen.
(Source: `evaluation/videos/sources.md`; numbers: `DEVELOPMENT_PROGRESS.md` P2 and a re-run on 2026-11-10.)

| Number | Meaning |
|---|---|
| **57** | median effective FPS: nearly smooth |
| **30** | 1 % low FPS: the worst moments felt choppy |
| **4** | stutter periods |
| **1** | freeze at 18.37 s, but it is the **video maker's pause before an edit cut**, not a game bug |
| **9 %** | measurable, because only the gameplay part moves |
| **~25 s** | time to analyse the whole 199 s video (about 8× faster than real time) |

Lesson: the tool shows exact times, but a person should still watch each reported moment.

---

## 9. How we tested it (and why the results are honest)

**Hide bugs on purpose, then see if the tool finds them**, like a teacher hiding mistakes in an
essay. We generated videos and inserted freezes, drops and stutters at **known times**.

- **Practice videos (tuning, seed 0):** used to choose the rules (250 ms, 45 FPS, 3 missed/s).
- **Exam videos (held-out, seeds 1–3):** made **after** the rules were fixed. We never changed a rule
  after seeing them; that would be like seeing the exam questions first.

**Exam results** (`evaluation/results/prototype_fps/`):

| | Stutter | Freeze | FPS drop |
|---|---|---|---|
| Found | 11 / 11 | 8 / 9 | 7 / 7 |
| False alarms | 0 | 0 | 0 |

**26 of 27 hidden bugs found, zero false alarms.**
- **Precision 1.00**: every time it said "bug", it was right.
- **Recall 0.89 for freezes**: it found 8 of 9. The missed one: video compression changed the
  first frozen picture slightly, so it did not look like an exact repeat.

**Proof on the real video:** we froze it on purpose from 10.0 to 10.8 s → the tool reported
**10.00–10.80 s**. We slowed it to 20 FPS from 4.0 to 6.5 s → found **3.50–6.75 s** (slightly wider
because it measures in 1-second windows).

**18-case test set** (`evaluation/results/phase6/`): 12 videos made from the real one (MP4, MKV,
720p AVI, 30 FPS, VFR, still screen, damaged file, 2-frame file, strange file name, injected freeze,
injected drop, original) + 6 invalid inputs (missing file, .txt, .mov, text renamed .mp4, empty
file, folder). It never crashed, and the CLI and GUI gave **identical** results on all 10 videos it
could analyse.

**A bug we found in our own tool:** VFR recorders skip saving pictures when nothing changes. The
tool first counted those as "missed" even when the player stood still, so it reported a slowdown
that never happened. Fix: a skipped picture only counts if the camera was moving. A regression test
now guards it.

**Automatic tests:** 209 pass (+ 3 "expected failures" for the experimental clipping detector).

---

## 10. Limitations (say these yourself)

- **We measure the video, not the game.** A 144 FPS game recorded at 60 FPS can never show above 60.
- **Still screens** (menus, standing still) cannot be measured.
- **Video edits** and intentional pauses can look like freezes.
- **Only one real video** so far; the rules were chosen on computer-made videos.
- **Heavy compression** can hide a very short freeze.
- No FPS-counter or profiler ground truth yet; tested on macOS only.

---

## 11. The bigger system (beyond the prototype)

The SRS asks for five bug types. The earlier full system (`DEVELOPMENT_PROGRESS.md` phases 1–14)
has detectors for all five, built from **pretrained** models and rules (we have **not trained**
any model ourselves yet):

| Bug type | Method | Status |
|---|---|---|
| Performance (freeze / drop / stutter) | repeated-frame analysis | **Verified** (this prototype) |
| Texture pop-in (blurry wall turns sharp) | SSIM, camera-motion compensated | Verified with major limitations (synthetic F1 0.76; UI false alarms on real video) |
| Animation glitch (arm jumps) | Farneback optical flow | Verified on synthetic (F1 0.92); false alarms at edits |
| NPC problems (T-pose, frozen, floating) | YOLOv8 (COCO) + MediaPipe Pose | Blocked: no footage with characters to test on |
| Clipping (gun through wall) | box overlap / experimental | Failed validation; experimental and off |

In the presentation these four are shown as **"In development"**.

---

## 12. Next steps and the data plan for the AI part

**Next:** test the FPS tool on more real videos, especially with an **on-screen FPS counter**
(MSI Afterburner / RTSS) so we can compare our number with the game's own; recordings from
ShadowPlay and Xbox Game Bar; heavy scenes that really slow down.

**Later: AI for visual bugs.** Needs labelled data. Which parts need training:

| Bug type | Training needed? |
|---|---|
| FPS | No (counting only). Needs only test videos. |
| Texture pop-in | Maybe: an autoencoder learns from **clean** videos only, no labels |
| Animation glitch | No (rules). Needs test videos. |
| NPC problems | A little: boxes around game characters so YOLO learns game people |
| Clipping | **Yes, the most**: a new YOLOv8 class "clipping" |

**Two kinds of labels:**
- **Time label** (videos), format in `evaluation/label_template.json`:
  `{"category": "npc", "subtype": "t_pose", "start_s": 12.4, "end_s": 15.0}`
- **Box label** (pictures, for YOLO): a rectangle around the bug, one text line per box,
  e.g. `0 0.62 0.48 0.10 0.15` = class 0, centre at 62 % across / 48 % down, 10 % wide, 15 % tall.
  Cut frames with `gameqa extract VIDEO -o DIR`, draw boxes in **CVAT** (free).

**Where data comes from:**
1. **Our Unity "bug lab"** (main source): a small Unity scene where scripts cause bugs on purpose
   (push the gun into a wall, force a T-pose, swap a low-quality texture). The script writes the label
   itself, so labels are exact. Report these honestly as *made* bugs.
2. **Our own recordings** (OBS / ShadowPlay / Game Bar): lots of normal play + bugs we cause.
3. **Public footage** (GlitchBench, YouTube glitch videos): only where the licence allows.

**Rules:** include **normal pictures** too (gun near a wall but not through it), or the AI will give
false alarms. **Split by video, not by picture**: a whole video goes to training *or* testing, never
both (same idea as practice vs exam videos). Write a one-page labelling rule sheet; a second person
re-checks about 1 in 10 labels. Rough size: a few hundred labelled pictures for a first try;
Ultralytics suggests about 1,500 per class for good results.

**Honest status:** this dataset does not exist yet. It is the biggest risk in `docs/ROADMAP.md`.

---

## 13. The presentation

The slide deck lives on claude.ai (private to Abdul Basit; ask him to share it). 28 slides:
cover · team · agenda · problem · five bug types · what the prototype does · how we measure
smoothness (the 12-picture example) · six steps · three problems · architecture · tools · CLI demo ·
GUI · GUI results · Word report · the test video · results · "the tool says when it cannot tell" ·
how we tested · exam results · proof · 18 test files · bug we fixed · limitations · next steps ·
data plan · one sentence · thank you.

**If you only memorise one thing:** the 12-picture example (3 repeats → 9 new → 45 FPS).

---

## 14. Likely teacher questions

- **Is this the game's real FPS?** No. It is new pictures per second *in the video* while the camera moves. The video's own rate (60) is the maximum we can see.
- **How do you know it is correct?** Hidden bugs at known times: 26 of 27 found, 0 false alarms, on exam videos made after the rules were fixed. Plus the real video frozen at 10 s → found 10.00–10.80 s.
- **Why only 9 % measured?** On a still screen a repeat is normal, so we skip it instead of guessing.
- **Which files?** .mp4, .mkv, .avi; 30 or 60 FPS; constant or variable frame rate.
- **Why no login on the web page?** It only runs on your own computer (127.0.0.1).
- **Did you train an AI model?** Not yet. The FPS check does not need one. The data plan is in section 12.
- **Is the freeze at 18.37 s a bug?** No, it is the video maker's pause before an edit. That is why a person should check each reported moment.

---

## 15. Glossary

| Word | Meaning |
|---|---|
| Frame | one still picture of the video |
| FPS | frames (pictures) per second |
| Effective FPS | new (non-repeated) pictures per second while moving |
| Repeat / duplicate | a picture identical to the one before |
| Missed frame | a repeat while the scene is moving: the game was too slow |
| CFR / VFR | constant / variable frame rate (pictures at even / uneven times) |
| 1 % low | FPS of the worst 1 % of moments |
| Precision | of all alarms, how many were real |
| Recall | of all real bugs, how many were found |
| Held-out / exam videos | test videos never used to choose the rules |
| Seed | a number that decides where bugs are hidden in a generated video |
| YOLOv8 | an AI model that draws boxes around objects in a picture |
| MediaPipe Pose | finds body joints (shoulders, elbows…) of a person |
| SSIM | a score of how similar two pictures look |
| Optical flow | how each part of the picture moved between two frames |
| CVAT | free website for drawing labels on pictures |

---

## 16. Where to read more

| File | What is in it |
|---|---|
| `README.md` | setup and commands for the full system |
| `docs/USER_GUIDE.md` | step-by-step guide for the full system (dashboard) |
| `docs/PROJECT_DOCUMENTATION.docx` | the full prototype documentation (generated from real runs) |
| `docs/DEMO_GUIDE.docx` | the demo script for the supervisor |
| `docs/EVALUATION.md` | all evaluation results |
| `docs/ROADMAP.md` | requirements, risks, the dataset strategy |
| `DEVELOPMENT_PROGRESS.md` | what was done in each phase, with real numbers |
| `evaluation/README.md` | how to label videos |
