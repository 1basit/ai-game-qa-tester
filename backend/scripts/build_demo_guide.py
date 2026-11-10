"""Build docs/DEMO_GUIDE.docx: a step-by-step demonstration script for the supervisor.

Expected results quoted in the guide are read from the Phase 6 test run
(evaluation/results/phase6/results.json), so they match what the demo will show.

    python backend/scripts/build_demo_guide.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from docx.shared import Pt

from gameqa.fps_service.report_docx import _page_number_footer
from build_project_docs import ACCENT, GREY, Doc, ft  # same styles as PROJECT_DOCUMENTATION.docx

ROOT = Path(__file__).resolve().parents[2]


def main():
    rows = {r["name"]: r for r in json.loads((ROOT / "evaluation/results/phase6/results.json").read_text())}
    real = rows["real_full_1080p60.mp4"]["cli"]["result"]
    inj = rows["inject_freeze.mp4"]["cli"]["result"]
    freeze = next(e for e in inj["events"] if e["type"] == "freeze" and 9.5 <= e["start_s"] <= 11)
    secs = rows["real_full_1080p60.mp4"]["cli"]["seconds"]
    e, c = real["effective_fps"], real["counts"]

    D = Doc()
    d = D.d
    _page_number_footer(d.sections[0])
    t = d.add_paragraph()
    r = t.add_run("AI Game QA Tester — Demonstration Guide")
    r.bold, r.font.size, r.font.color.rgb = True, Pt(20), ACCENT
    s = d.add_paragraph()
    r = s.add_run(f"FPS analysis prototype · about 10 minutes · {date.today():%d %B %Y}")
    r.font.size, r.font.color.rgb = Pt(10), GREY
    D.p("A script for showing the prototype to the supervisor: what to run, what to say, and what will appear. "
        "The expected values below come from the Phase 6 test run on this computer.")

    D.h2("Before the demo (5 minutes earlier)")
    D.bullets([
        "Open a terminal in the project folder:  cd ~/Desktop/FYP",
        "Activate the environment:  source backend/.venv/bin/activate",
        "Check it works:  python main.py --help   (shows the usage text)",
        "If a GUI is still running from before, stop it (Ctrl+C in its terminal) or use another port.",
        "Have these files ready: the real video in evaluation/videos/, evaluation/synthetic/phase6/"
        "inject_freeze.mp4 (known freeze), and any .txt file (to show the error message). The test videos are "
        "generated, not stored in git: if inject_freeze.mp4 is missing, start the GUI and run "
        "python backend/scripts/phase6_test.py once (about 3 minutes).",
        "Optional: run the tests once:  cd backend && python -m pytest -q  (takes about 75 s).",
    ], style="List Number")

    D.h2("Step 1 · Introduce (1 minute)")
    D.p("Say: the prototype analyses a recorded gameplay video and measures frame pacing: how regularly new pictures "
        "appear. It finds freezes, FPS drops and stutter, with timestamps, and writes a Word report. It works from "
        "the terminal and from a local web page with no login. Important: it measures the recording, not the "
        "game's internal FPS. That would need a profiler log.")

    D.h2(f"Step 2 · Command line on the real video (3 minutes)")
    D.code('python main.py analyze --video "evaluation/videos/YTDown.com_YouTube_Media_J8HB1-IQFxc_How-to-fix-'
           'Weapons-Hands-Clipping-Into-Walls-in-Unity-URP-SRP_001_1080p.mp4"', size=8)
    D.p(f"Takes about {round(secs)} s. Point out the progress bar, then the summary:")
    D.table([("Video", f"{real['metadata']['resolution']}, {real['metadata']['duration_s']} s, "
                       f"{real['metadata']['frame_count']:,} frames, nominal {real['metadata']['nominal_fps']} FPS"),
             ("Effective FPS", f"median {e['median']}, minimum {e['min']} (target {e['target_fps']:g})"),
             ("1 % low", f"{real['frame_times']['one_percent_low_fps']} FPS"),
             ("Measurable", f"{round(e['measurable_fraction'] * 100)} % (only the moving gameplay part)"),
             ("Events", f"{c['freezes']} freeze, {c['fps_drops']} drops, {c['stutters']} stutter periods"),
             ("Verdict", real["verdict"])], widths=[3.5, 12.5])
    D.p("Then open the output folder printed at the end (Finder: open outputs/) and open "
        "FPS_ANALYSIS_REPORT.docx. Show the summary, the charts and the events table.")
    D.p("Explain the two questions it raises: only 9 % is measurable because the rest of the video is the static "
        "Unity editor, where a repeated frame is normal; the freeze at "
        f"{ft(next(x for x in real['events'] if x['type'] == 'freeze')['start_s'])} is the held picture before an "
        "editing transition: a known false positive, shown honestly in the documentation.")

    D.h2("Step 3 · The same analysis in the browser (3 minutes)")
    D.code("python main.py --gui", size=8)
    D.bullets([
        "The browser opens http://127.0.0.1:8765 by itself. Point out: no login, runs only on this computer.",
        "Drag the real video onto the page (or click and choose it), keep 60 FPS, click Analyze Video.",
        "While it runs: the bar shows the frame being analysed.",
        "Results: same numbers as the terminal (the CLI and GUI use one engine; a test checks they are identical). "
        "Scroll through the chart, the events table with timestamps, and click Download Word report.",
    ])

    D.h2("Step 4 · Proof on a known defect (2 minutes)")
    D.p("Click Analyse another video and upload evaluation/synthetic/phase6/inject_freeze.mp4: the real gameplay with "
        "a 0.8-second freeze inserted at exactly 10.0 s (made by backend/scripts/phase6_test.py).")
    D.p(f"Expected: a Freeze event at {ft(freeze['start_s'])}–{ft(freeze['end_s'])} ({freeze['duration_s']:.2f} s). "
        "Say: on synthetic tests generated after the thresholds were fixed, the engine found 11/11 stutters, 8/9 "
        "freezes and 7/7 FPS drops with no false alarms.")
    D.figure(ROOT / "docs/screenshots/demo_inject_freeze_events.png",
             "What the page shows for inject_freeze.mp4 (rehearsed through the real page).", 15)

    D.h2("Step 5 · Error handling (30 seconds)")
    D.p("Click Analyse another video and choose a .txt file: the page refuses it and names the accepted formats. "
        "In the terminal:  python main.py analyze --video missing.mp4  prints a one-line error (exit code 2).")

    D.h2("Step 6 · Limitations and next steps (1 minute)")
    D.bullets([
        "True game FPS cannot be read from a recording; the next step is footage with an FPS counter or a profiler "
        "log to measure the error.",
        "Still scenes cannot be measured; video edits can look like freezes.",
        "The other four detectors (NPC, texture, animation, clipping) are documented and partly built; they will be "
        "added one at a time after validation (PROJECT_DOCUMENTATION.docx, Sections 11–16).",
    ])

    D.h2("Likely questions")
    D.table([
        ("Is this the game's real FPS?", "No. It is the rate of new pictures in the recording while the scene moves. "
                                         "The recording rate caps it (60 here)."),
        ("How do you know it is correct?", "Synthetic tests with defects injected at known times, tuned on one set "
                                           "and measured on a separate held-out set; plus the known-freeze video in "
                                           "Step 4. No profiler ground truth exists for the real video yet."),
        ("Why is so little of the video measurable?", "When nothing moves, a repeated frame looks exactly like a "
                                                      "normal one, so those parts are excluded instead of guessed."),
        ("Can it handle other formats?", ".mp4, .mkv and .avi, constant or variable frame rate, 30 or 60 FPS: all "
                                         "tested in Phase 6."),
        ("Why no login?", "It runs only on this computer (127.0.0.1); a login adds nothing for a local tool."),
    ], header=("Question", "Answer"), widths=[5.0, 11.0])

    D.h2("If something goes wrong")
    D.table([
        ("'port 8765 is already in use'", "A GUI is already running: open http://127.0.0.1:8765, or start with "
                                          "python main.py --gui --port 8766."),
        ("'Missing dependency (...)' (exit 3)", "The environment is not active: "
                                                          "source backend/.venv/bin/activate"),
        ("Browser does not open", "Open http://127.0.0.1:8765 by hand."),
        ("Report not opening", "It is in the output folder printed by the CLI / shown under the GUI results."),
    ], header=("Symptom", "Fix"), widths=[5.5, 10.5])

    out = ROOT / "docs/DEMO_GUIDE.docx"
    d.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
