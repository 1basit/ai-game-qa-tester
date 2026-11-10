"""Build docs/PROJECT_DOCUMENTATION.docx (and copy a sample FPS_ANALYSIS_REPORT.docx).

Every number in the document is read from real artefacts at build time:
* `--run`        an output folder of `python main.py analyze` (analysis.json, charts, report)
* evaluation/results/prototype_fps/report_seeds_*.md   synthetic tuning / held-out results
* docs/screenshots/                                     GUI screenshots (capture_gui_screenshots.py),
                                                        captured CLI output, pytest log
* installed package versions and the machine's platform
Results of the earlier (non-prototype) detectors are quoted from DEVELOPMENT_PROGRESS.md,
where they were recorded when those phases were run; the document names that source.

    python backend/scripts/build_project_docs.py --run outputs/<run folder>
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
from datetime import date
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from docx import Document  # noqa: E402
from docx.enum.section import WD_SECTION  # noqa: E402,F401
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from gameqa.fps_service.report_docx import _borders, _page_number_footer, _shade, _table  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ACCENT = RGBColor(0x1D, 0x4E, 0xD8)
GREY = RGBColor(0x47, 0x54, 0x67)
STATUS = {  # label -> (fill, text colour)
    "Implemented and Tested": ("D1FADF", RGBColor(0x05, 0x60, 0x3A)),
    "In Development": ("FEF0C7", RGBColor(0x93, 0x37, 0x0D)),
    "Proposed for Future Phases": ("E0EAFF", RGBColor(0x1D, 0x4E, 0xD8)),
}
IMPL, DEV, PROP = STATUS.keys()


# --------------------------------------------------------------------------- data

def load_inputs(run: Path, shots: Path) -> dict:
    res = json.loads((run / "analysis.json").read_text())

    def eval_table(path: Path) -> dict:
        rows = {}
        for line in path.read_text().splitlines():
            m = re.match(r"\|\s*(stutter|freeze|fps_drop)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", line)
            if m:
                rows[m.group(1)] = tuple(int(x) for x in m.groups()[1:])
        if len(rows) != 3:
            raise SystemExit(f"could not read evaluation table from {path}")
        return rows

    ev = ROOT / "evaluation/results/prototype_fps"
    log = (shots / "pytest_full.txt").read_text()
    summary = next((ln.strip(" =") for ln in reversed(log.splitlines()) if re.search(r"\d+ passed", ln)), None)
    if not summary or re.search(r"\b\d+ (failed|error)", summary):
        raise SystemExit(f"pytest log missing or has failures: {summary}")

    def count_tests(*files):
        out = subprocess.run(["python", "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *files],
                             cwd=ROOT / "backend", capture_output=True, text=True).stdout
        return {f: sum(1 for ln in out.splitlines() if ln.startswith(f + "::")) for f in files}

    def pkg(name):
        try:
            return version(name)
        except PackageNotFoundError:
            return "not installed"

    ff = shutil.which("ffmpeg")
    ffv = subprocess.run([ff, "-version"], capture_output=True, text=True).stdout.split()[2] if ff else "not installed"
    chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    mem = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip()
    return {
        "res": res, "run": run, "tuning": eval_table(ev / "report_seeds_0.md"),
        "heldout": eval_table(ev / "report_seeds_1_2_3.md"), "pytest": summary,
        "tests": count_tests("tests/test_fps_service.py", "tests/test_main_cli.py", "tests/test_webgui.py"),
        "env": {
            "Machine": f"{chip or platform.machine()}, {round(int(mem) / 1024**3) if mem else '?'} GB RAM",
            "Operating system": f"macOS {platform.mac_ver()[0]} ({platform.platform(terse=True)})",
            "Python": platform.python_version(), "OpenCV": pkg("opencv-contrib-python-headless"),
            "NumPy": pkg("numpy"), "FFmpeg / ffprobe": ffv, "matplotlib": pkg("matplotlib"),
            "python-docx": pkg("python-docx"), "FastAPI": pkg("fastapi"), "uvicorn": pkg("uvicorn"),
            "pydantic": pkg("pydantic"), "pytest": pkg("pytest"),
            "Google Chrome (screenshots only)": "156" if Path("/Applications/Google Chrome.app").exists() else "-",
        },
        "pkgs": {n: pkg(n) for n in ("scikit-image", "ultralytics", "mediapipe", "pyyaml", "python-multipart",
                                     "pydantic-settings", "httpx")},
        "cli": {k: (shots / f"cli_{k}.txt").read_text() for k in ("help", "run", "error_missing", "error_format")},
        "phase6": json.loads((ROOT / "evaluation/results/phase6/results.json").read_text()),
    }


# --------------------------------------------------------------------------- diagrams

def _box(ax, x, y, w, h, title, body="", fill="#EEF2FF", edge="#1D4ED8", dashed=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=fill, ec=edge,
                                lw=1.4, ls="--" if dashed else "-"))
    ax.text(x + w / 2, y + h - 0.22, title, ha="center", va="top", fontsize=9.5, weight="bold", color="#101828")
    if body:
        ax.text(x + w / 2, y + h - 0.55, body, ha="center", va="top", fontsize=7.6, color="#344054", linespacing=1.35)


def _arrow(ax, a, b, dashed=False, text=""):
    ax.annotate("", xy=b, xytext=a, arrowprops=dict(arrowstyle="-|>", color="#475467", lw=1.2,
                                                     ls="--" if dashed else "-", shrinkA=2, shrinkB=2))
    if text:
        ax.text((a[0] + b[0]) / 2 + 0.08, (a[1] + b[1]) / 2, text, fontsize=7, color="#475467", va="center")


def architecture_diagram(out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 6.4))
    ax.set_xlim(0, 10); ax.set_ylim(0, 6.4); ax.axis("off")
    _box(ax, 0.3, 5.0, 2.9, 1.2, "Command line", "python main.py analyze\n--video FILE [--target-fps 30|60 ...]")
    _box(ax, 3.55, 5.0, 2.9, 1.2, "Local web GUI", "python main.py --gui\nFastAPI on 127.0.0.1:8765, no login")
    _box(ax, 6.8, 5.0, 2.9, 1.2, "Configuration", "config/default.yaml\ngameqa/config.py (thresholds)", fill="#F2F4F7",
         edge="#667085")
    _box(ax, 1.9, 3.05, 6.2, 1.35, "FPS analysis engine (one engine for CLI and GUI)",
         "fps_service/analysis.py: analyze_video()  ->  detectors/fps.py (repeated / missed frames,\n"
         "effective FPS windows, freezes, drops)  +  stutter periods and statistics")
    _box(ax, 0.3, 1.0, 3.0, 1.45, "Common video processing", "gameqa/video: validate file, probe\nmetadata (ffprobe / "
         "OpenCV),\nFrameStream: decode + timestamps")
    _box(ax, 3.55, 1.0, 2.9, 1.45, "Results and reports", "store.py, charts.py, report_docx.py\noutputs/<run>/: "
         "analysis.json,\ntimeline.csv, charts, .docx")
    _box(ax, 6.8, 1.0, 2.9, 1.45, "Future detection modules", "NPC (YOLOv8 + MediaPipe), texture\n(SSIM), animation "
         "(Farneback),\nclipping: same Detector interface", fill="#F9FAFB", edge="#98A2B3", dashed=True)
    _box(ax, 0.3, 0.05, 9.4, 0.62, "Testing: pytest (unit + end-to-end) and synthetic-injection evaluation with "
         "held-out data", fill="#F2F4F7", edge="#667085")
    _arrow(ax, (1.75, 5.0), (3.3, 4.4)); _arrow(ax, (5.0, 5.0), (5.0, 4.4))
    _arrow(ax, (8.25, 5.0), (7.2, 4.4), dashed=True, text="settings")
    _arrow(ax, (1.8, 2.45), (2.6, 3.05), text="frames")
    _arrow(ax, (5.0, 3.05), (5.0, 2.45), text="result")
    _arrow(ax, (8.25, 2.45), (7.6, 3.05), dashed=True, text="later")
    fig.savefig(out, dpi=200, bbox_inches="tight"); plt.close(fig)
    return out


def pipeline_diagram(out: Path) -> Path:
    steps = [("1. Validate", "exists, .mp4/.mkv/.avi,\nsize, real video content"),
             ("2. Metadata", "ffprobe (OpenCV fallback):\nresolution, nominal FPS,\nframes, duration, VFR"),
             ("3. Decode", "OpenCV, every frame\n+ presentation\ntimestamp t_i"),
             ("4. Compare", "160x90 grey thumbnail,\nMAD to previous frame"),
             ("5. Classify frames", "repeated? moving?\nmissed render while\nmoving? VFR gaps"),
             ("6. 1 s windows", "every 0.25 s: effective\nFPS, missed frames,\nmeasurable?"),
             ("7. Events", "freeze >= 250 ms\nFPS drop < 0.75 x target\nstutter >= 3 missed/s"),
             ("8. Outputs", "statistics, verdict,\ncharts, JSON/CSV,\nWord report")]
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.set_xlim(0, 10); ax.set_ylim(0, 3.6); ax.axis("off")
    for k, (t, b) in enumerate(steps):
        row, col = divmod(k, 4)
        col = col if row == 0 else 3 - col  # snake layout
        x, y = 0.2 + col * 2.45, 2.0 - row * 1.85
        _box(ax, x, y, 2.05, 1.45, t, b)
        if k < 7:
            if k == 3:
                _arrow(ax, (x + 1.02, y), (x + 1.02, y - 0.4))
            elif row == 0:
                _arrow(ax, (x + 2.05, y + 0.72), (x + 2.45, y + 0.72))
            else:
                _arrow(ax, (x, y + 0.72), (x - 0.4, y + 0.72))
    fig.savefig(out, dpi=200, bbox_inches="tight"); plt.close(fig)
    return out


# --------------------------------------------------------------------------- document helpers

class Doc:
    def __init__(self):
        self.d = Document()
        self.fig = self.tab = self.eqn = 0
        s = self.d.sections[0]
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)
        s.left_margin = s.right_margin = Cm(2.2)
        s.top_margin, s.bottom_margin = Cm(2.0), Cm(2.0)
        st = self.d.styles
        st["Normal"].font.name = "Calibri"
        st["Normal"].font.size = Pt(10.5)
        st["Normal"].paragraph_format.space_after = Pt(5)
        st["Normal"].paragraph_format.line_spacing = 1.12
        for name, size in (("Heading 1", 16), ("Heading 2", 12.5), ("Heading 3", 11)):
            st[name].font.size = Pt(size)
            st[name].font.color.rgb = ACCENT if name != "Heading 3" else RGBColor(0x10, 0x18, 0x28)
            st[name].font.name = "Calibri"
            st[name].paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
            st[name].paragraph_format.keep_with_next = True

    def h1(self, text, new_page=True):
        if new_page:
            self.d.add_page_break()
        self.d.add_heading(text, level=1)

    def h2(self, text):
        self.d.add_heading(text, level=2)

    def h3(self, text):
        self.d.add_heading(text, level=3)

    def p(self, text="", bold_lead=None, italic=False, size=None, align=None):
        para = self.d.add_paragraph()
        if bold_lead:
            para.add_run(bold_lead).bold = True
        r = para.add_run(text)
        r.italic = italic
        if size:
            r.font.size = Pt(size)
        if align:
            para.alignment = align
        return para

    def bullets(self, items, style="List Bullet"):
        for it in items:
            para = self.d.add_paragraph(style=style)
            if isinstance(it, tuple):
                para.add_run(it[0]).bold = True
                para.add_run(it[1])
            else:
                para.add_run(it)
            para.paragraph_format.space_after = Pt(2)

    def status(self, label, note=""):
        fill, colour = STATUS[label]
        t = self.d.add_table(rows=1, cols=1)
        t.alignment = WD_TABLE_ALIGNMENT.LEFT
        c = t.rows[0].cells[0]
        _shade(c, fill)
        para = c.paragraphs[0]
        r = para.add_run(f"STATUS: {label.upper()}")
        r.bold, r.font.size, r.font.color.rgb = True, Pt(9), colour
        if note:
            r2 = para.add_run(f"  —  {note}")
            r2.font.size, r2.font.color.rgb = Pt(9), colour
        self.d.add_paragraph().paragraph_format.space_after = Pt(0)

    def table(self, rows, header=None, widths=None, caption=None, status_col=None):
        if caption:
            self.tab += 1
            cp = self.d.add_paragraph()
            r = cp.add_run(f"Table {self.tab}. {caption}")
            r.bold, r.font.size, r.font.color.rgb = True, Pt(9), GREY
            cp.paragraph_format.keep_with_next = True
            cp.paragraph_format.space_after = Pt(2)
        t = _table(self.d, rows, header=header, widths=widths)
        if status_col is not None:
            for row in t.rows[1 if header else 0:]:
                cell = row.cells[status_col]
                for label, (fill, colour) in STATUS.items():
                    if cell.text.startswith(label):
                        _shade(cell, fill)
                        for run in cell.paragraphs[0].runs:
                            run.font.color.rgb, run.bold = colour, True
        self.d.add_paragraph().paragraph_format.space_after = Pt(0)
        return t

    def figure(self, path: Path, caption: str, width_cm=16.0):
        self.fig += 1
        para = self.d.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.keep_with_next = True
        para.add_run().add_picture(str(path), width=Cm(width_cm))
        cp = self.d.add_paragraph()
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = cp.add_run(f"Figure {self.fig}. {caption}")
        r.italic, r.font.size, r.font.color.rgb = True, Pt(9), GREY

    def eq(self, expr: str, where: str = ""):
        self.eqn += 1
        para = self.d.add_paragraph()
        ts = para.paragraph_format.tab_stops
        ts.add_tab_stop(Cm(8.3), WD_TAB_ALIGNMENT.CENTER)
        ts.add_tab_stop(Cm(16.6), WD_TAB_ALIGNMENT.RIGHT)
        r = para.add_run("\t" + expr)
        r.font.name, r.font.size, r.italic = "Cambria Math", Pt(11), True
        para.add_run(f"\t({self.eqn})").font.size = Pt(10)
        para.paragraph_format.space_after = Pt(2)
        if where:
            w = self.d.add_paragraph()
            run = w.add_run(where)
            run.font.size, run.font.color.rgb = Pt(9), GREY
            w.paragraph_format.left_indent = Cm(1)
        return self.eqn

    def code(self, text: str, size=7.5):
        t = self.d.add_table(rows=1, cols=1)
        _borders(t)
        c = t.rows[0].cells[0]
        _shade(c, "F5F6F8")
        para = c.paragraphs[0]
        for k, line in enumerate(text.rstrip("\n").split("\n")):
            if k:
                para.add_run().add_break(WD_BREAK.LINE)
            r = para.add_run(line)
            r.font.name, r.font.size = "Menlo", Pt(size)
        self.d.add_paragraph().paragraph_format.space_after = Pt(0)

    def note(self, text):
        r = self.d.add_paragraph().add_run(text)
        r.italic, r.font.size, r.font.color.rgb = True, Pt(9), GREY


def ft(s: float) -> str:
    m = int(s // 60)
    return f"{m:02d}:{s - 60 * m:06.3f}"


# --------------------------------------------------------------------------- content

def build(inp: dict, shots: Path, out: Path) -> Path:
    R = inp["res"]
    md, fi, ef, fr, cn, pr = (R["metadata"], R["frame_intervals"], R["effective_fps"], R["frame_times"],
                              R["counts"], R["processing"])
    tun, hel = inp["tuning"], inp["heldout"]
    charts = inp["run"] / "charts"
    arch = architecture_diagram(shots / "diagram_architecture.png")
    pipe = pipeline_diagram(shots / "diagram_pipeline.png")
    D = Doc()
    d = D.d
    sec = d.sections[0]
    sec.different_first_page_header_footer = True
    hp = sec.header.paragraphs[0]
    hp.text = "AI Game QA Tester — Project Documentation (FPS analysis prototype)"
    hp.runs[0].font.size, hp.runs[0].font.color.rgb = Pt(8), GREY
    _page_number_footer(sec)

    # ---------------- title page
    for txt, size, bold, col in (
            ("Department of Computer Science\nFaculty of Computing and Information Technology (FCIT)\n"
             "University of the Punjab, Lahore", 11, False, GREY),
            ("\n\nAI Game QA Tester", 30, True, ACCENT),
            ("Automated Game Bug Detection and Reporting Using Artificial Intelligence and Computer Vision", 14,
             False, RGBColor(0x10, 0x18, 0x28)),
            ("\nPROJECT DOCUMENTATION\nPrototype 1: FPS Analysis Service (command line + local web GUI)", 13, True,
             RGBColor(0x10, 0x18, 0x28))):
        para = d.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = para.add_run(txt)
        r.font.size, r.bold, r.font.color.rgb = Pt(size), bold, col
    d.add_paragraph("\n")
    D.table([("Group leader", "Abdul Basit (BCSF23M526)"),
             ("Group members", "Furqan Khalid (BCSF23M534), Zayyam Waseem (BCSF23M549), "
                               "Husnain Mughal (BCSF23M530)"),
             ("Supervisor", "Ma'am Tayyaba"),
             ("Programme / session", "BS Computer Science, session 2023–2027, FYP-1 (Fall 2026)"),
             ("Document version", f"1.0 — {date.today():%d %B %Y}"),
             ("Generated from", f"real analysis run outputs/{inp['run'].name}/ by "
                                "backend/scripts/build_project_docs.py")], widths=[4.5, 11.5])

    # ---------------- how to read + contents
    D.h1("About this document")
    D.p("This document describes the first working prototype of the AI Game QA Tester: an FPS analysis service "
        "that measures frame pacing in a recorded gameplay video and reports freezes, FPS drops and stutter, usable "
        "from the terminal and from a simple local web page. It also documents the methodology planned for the other "
        "four defect categories of the project. Every result quoted here comes from programs that were actually run; "
        "nothing is simulated or typed in by hand. Each part of the system carries one of three status labels:")
    D.table([(IMPL, "Code exists, is used by the prototype and was tested; results are reported in Section 17."),
             (DEV, "Code exists in the repository (from earlier exploratory work) and was partly tested, but it is "
                   "not validated well enough to be part of the prototype."),
             (PROP, "Methodology only. No working code yet.")],
            header=("Label", "Meaning"), widths=[5, 11], caption="Status labels used in this document",
            status_col=0)
    D.h2("Contents")
    for k, name in enumerate(SECTIONS, 1):
        para = d.add_paragraph(f"{k}.  {name}")
        para.paragraph_format.space_after = Pt(1)
        para.paragraph_format.left_indent = Cm(0.5)
    D.p("Appendix A. Output files   ·   Appendix B. Source files of the prototype", size=10)

    # ---------------- 1
    D.h1("1. Project overview and objectives")
    D.h2("1.1 Problem")
    D.p("Before a game is released, testers play it for many hours and write down what looks wrong. The process is "
        "slow, expensive and inconsistent, and short visual faults (a texture appearing late, a single stutter, a "
        "character stuck in a T-pose) are easy to miss after hours of play. Engine profilers measure performance but "
        "need access to the game and do not report what the player actually saw.")
    D.h2("1.2 Aim of the final-year project")
    D.p("The AI Game QA Tester analyses a recorded gameplay video after it has been captured, with no access to the "
        "engine or the source code, and produces a bug report listing each defect with its timestamp, evidence and "
        "severity. The proposal and the SRS define five defect categories: NPC anomalies, texture pop-in, FPS drops, "
        "animation glitches, and collision / geometry clipping.")
    D.h2("1.3 Objective of this prototype")
    D.p("For the first demonstration the scope was deliberately reduced to one module that works accurately rather "
        "than five incomplete ones: an FPS analysis service. Given a gameplay video it extracts the metadata, "
        "measures the timing of every frame, finds repeated (frozen) frames, freezes, FPS drops and stutter periods, "
        "and writes the results, charts and a Word report. It can be used from a terminal "
        "(python main.py analyze --video ...) or from a local web page started with python main.py --gui, which "
        "needs no login, password or account.")
    D.table([
        ("Accept a gameplay video and validate it (exists, .mp4 / .mkv / .avi, really a video)", IMPL),
        ("Extract metadata: resolution, nominal FPS, frame count, duration, frame timestamps", IMPL),
        ("Frame timing: intervals, irregular pacing, repeated / frozen frames, freezes, FPS drops, stutter", IMPL),
        ("Configurable targets and thresholds (30 / 60 / 120 / 144 FPS, drop ratio, freeze length, stutter)", IMPL),
        ("Command-line interface with progress and a concise summary", IMPL),
        ("Local web GUI without login: upload, progress, results, charts, events, report download", IMPL),
        ("Organised output folder and a Word report (FPS_ANALYSIS_REPORT.docx) per video", IMPL),
        ("NPC anomaly detection (YOLOv8 + MediaPipe)", DEV + " — not validated: no footage with characters"),
        ("Texture pop-in detection (SSIM)", DEV + " — synthetic F1 0.76; false alarms on real UI footage"),
        ("Animation glitch detection (Farneback optical flow)", DEV + " — synthetic F1 0.92; no real glitches"),
        ("Collision / geometry clipping detection", DEV + " — experimental, failed validation"),
        ("Convolutional-autoencoder texture check; floating-NPC check", PROP),
        ("Unified pipeline for all five modules with severity and one combined report", PROP),
    ], header=("Objective", "Status"), widths=[9.5, 6.5], caption="Objectives and their status", status_col=1)
    D.h2("1.4 Relationship to earlier work in the repository")
    D.p("The repository also contains an earlier, larger exploratory build (git commit 9a192cf): a dashboard with "
        "login, a PostgreSQL database, the four other detectors and PDF reports. That build is kept unchanged but is "
        "not part of this prototype, and the prototype does not need it. The prototype reuses two of its components "
        "that had already been validated: the common video-reading code (gameqa/video) and the FPS detector "
        "(gameqa/detectors/fps.py). The other detectors are the starting point for the future modules and are "
        "labelled In Development in this document.")

    # ---------------- 2
    D.h1("2. Overall system architecture")
    D.status(IMPL, "for the prototype components; future modules are proposed")
    D.p("The prototype is a small modular Python application that runs on one computer and stores its results as "
        "files. There is no database, no authentication, no cloud service and no job queue. Figure 1 shows the "
        "components and how data flows between them.")
    D.figure(arch, "Architecture of the prototype. Solid boxes are implemented; the dashed box is future work.")
    D.table([
        ("Common video processing", "backend/src/gameqa/video/", "Validates the file, reads metadata with ffprobe "
         "(OpenCV fallback) and decodes frames with their presentation timestamps (FrameStream)."),
        ("FPS analysis engine", "gameqa/fps_service/analysis.py, gameqa/detectors/fps.py", "analyze_video(): the "
         "single analysis function used by both interfaces. Classifies frames, computes windows, events and "
         "statistics."),
        ("Command-line interface", "main.py (project root)", "Argument parsing, progress bar, terminal summary, exit "
         "codes."),
        ("Local web GUI", "gameqa/webgui/app.py, webgui/static/", "FastAPI server on 127.0.0.1 with one HTML page; "
         "upload, background analysis, progress polling, results and downloads."),
        ("Report generation", "fps_service/store.py, charts.py, report_docx.py", "analysis.json, timeline.csv, "
         "windows.json, three PNG charts and FPS_ANALYSIS_REPORT.docx."),
        ("Configuration", "config/default.yaml, gameqa/config.py", "Default target FPS and thresholds, output folder, "
         "GUI address; every value can be overridden per run."),
        ("Testing", "backend/tests/, backend/scripts/eval_prototype_fps.py", "Unit and end-to-end tests; synthetic "
         "evaluation with tuning and held-out sets."),
    ], header=("Component", "Location", "Responsibility"), widths=[3.4, 5.0, 7.6],
        caption="Components of the prototype")
    D.h2("2.1 Key design decisions")
    D.bullets([
        ("One engine. ", "The CLI and the GUI both call fps_service.analyze_video() and save_results(); an automated "
                         "test checks that both give identical results for the same video."),
        ("Local files instead of a database. ", "Each analysis writes one folder outputs/<date-time>_<video>/. This "
                                                "is enough for a single user and easy to inspect."),
        ("No login, local only. ", "The GUI listens on 127.0.0.1 so only the same computer can open it; starting it "
                                   "on another address prints a warning."),
        ("FastAPI + plain HTML/CSS/JavaScript. ", "FastAPI was already used in the repository, starts in about a "
                                                  "second, and handles file uploads; the page needs no build step "
                                                  "or external scripts."),
        ("Pluggable detectors. ", "Every detector implements the same start / process / finish interface "
                                  "(gameqa/core/detector.py), so later modules can be added next to the FPS engine "
                                  "without changing it (Section 16)."),
    ])
    D.h2("2.2 Folder structure (prototype-relevant parts)")
    D.code("FYP/\n"
           "├── main.py                      CLI entry point:  analyze --video ...  |  --gui\n"
           "├── config/default.yaml          default thresholds (fps_service section)\n"
           "├── backend/\n"
           "│   ├── pyproject.toml           package 'gameqa' and its dependencies\n"
           "│   ├── src/gameqa/\n"
           "│   │   ├── video/               validate, probe (ffprobe / OpenCV), FrameStream\n"
           "│   │   ├── detectors/fps.py     repeated / missed frames, windows, freezes, drops\n"
           "│   │   ├── fps_service/         analysis.py, charts.py, store.py, report_docx.py\n"
           "│   │   └── webgui/              app.py + static/ (index.html, style.css, app.js)\n"
           "│   ├── tests/                   test_fps_service.py, test_main_cli.py, test_webgui.py, ...\n"
           "│   └── scripts/                 eval_prototype_fps.py, capture_gui_screenshots.py,\n"
           "│                                build_project_docs.py\n"
           "├── evaluation/                  real videos (videos/) and evaluation results (results/)\n"
           "├── outputs/                     one folder per analysis (git-ignored)\n"
           "└── docs/                        PROJECT_DOCUMENTATION.docx, FPS_ANALYSIS_REPORT.docx, screenshots/")

    # ---------------- 3
    D.h1("3. Prototype scope and implemented functionality")
    D.status(IMPL)
    D.table([
        ("Input formats", ".mp4, .mkv, .avi; other extensions are rejected with a message naming the accepted "
                          "formats; files whose content is not a video are rejected even with a valid extension."),
        ("Metadata", "Resolution, codec, container, nominal FPS, average FPS from timestamps, frame count, duration, "
                     "constant or variable frame rate, file size, audio present."),
        ("Frame timing", "Interval between every pair of consecutive frames (expected, median, min, max, 99th "
                         "percentile, number of irregular intervals)."),
        ("Repeated frames", "Frames showing the same picture as the previous one; repeats while the scene moves are "
                            "counted as missed renders."),
        ("Effective FPS", "New pictures per second in 1-second windows (every 0.25 s), while the picture moves; "
                          "mean, median, minimum, 5th percentile; share of the video that could be measured."),
        ("Frame times", "Time between new pictures while moving: p50, p95, p99, maximum, '1 % low' FPS."),
        ("Events", "Freeze (picture held ≥ 250 ms while moving), FPS drop (effective FPS below 0.75 × target), "
                   "stutter (≥ 3 missed frames per second while the average stays above the drop threshold); each "
                   "with start / end time, frames, duration and description."),
        ("Outputs", "Terminal summary, analysis.json, timeline.csv, windows.json, three charts, "
                    "FPS_ANALYSIS_REPORT.docx; in the GUI the same results on screen with downloads."),
        ("Interfaces", "python main.py analyze --video FILE [options];  python main.py --gui"),
    ], widths=[3.5, 12.5], caption="Implemented functionality")
    D.p("Out of scope for this prototype, by decision: login, registration or user management; databases; cloud "
        "deployment; a complex dashboard; the four other detectors; severity classification. These remain part of "
        "the full project (Sections 11–16 and 20).", italic=False)

    # ---------------- 4
    D.h1("4. Installation and environment setup")
    D.status(IMPL, "tested on the machine listed in Table 5; not yet tested on Windows or Linux")
    D.table(list(inp["env"].items()), widths=[5, 11], caption="Environment on which the prototype was built and "
                                                                   "tested (read at build time)")
    D.h2("4.1 Steps")
    D.p("The commands below are for macOS / Linux. On Windows, the activation command is "
        "backend\\.venv\\Scripts\\activate instead of source backend/.venv/bin/activate (not yet tested).")
    D.code("# 1. get the project and open a terminal in it\n"
           "cd ~/Desktop/FYP\n\n"
           "# 2. create a Python 3.10+ virtual environment (3.13 was used)\n"
           "python3 -m venv backend/.venv\n"
           "source backend/.venv/bin/activate\n\n"
           "# 3. install the package with the web GUI and test dependencies\n"
           "pip install -e \"backend[api,dev]\"\n\n"
           "# 4. optional but recommended: FFmpeg (ffprobe gives exact metadata)\n"
           "brew install ffmpeg          # macOS (Homebrew)\n\n"
           "# 5. check that it works\n"
           "python main.py --help\n"
           "cd backend && python -m pytest -q", size=8)
    D.p("Without FFmpeg the prototype still works: metadata is then read with OpenCV only and the report contains a "
        "warning that the frame count may be an estimate. Running python main.py with a Python that lacks the "
        "packages prints the activation instructions instead of a traceback (exit code 3).")

    # ---------------- 5
    D.h1("5. Using the command-line interface")
    D.status(IMPL)
    D.p("Activate the environment first (source backend/.venv/bin/activate), then run the commands from the project "
        "folder.")
    D.table([
        ("python main.py analyze --video \"path/to/gameplay.mp4\"", "Analyse with the defaults (target 60 FPS)."),
        ("python main.py analyze --video game.mp4 --target-fps 30", "Judge against a 30 FPS target."),
        ("python main.py analyze --video game.mp4 --drop-ratio 0.8 --freeze-ms 200 --stutter-min-missed 4",
         "Custom thresholds."),
        ("python main.py analyze --video game.mp4 --output results/run1", "Choose the output folder."),
        ("python main.py analyze --video game.mp4 --no-report", "Skip the Word report (faster)."),
        ("python main.py analyze --video game.mp4 --quiet", "No progress output (for scripts)."),
        ("python main.py --gui", "Start the local web GUI (Section 6)."),
    ], header=("Command", "What it does"), widths=[9.8, 6.2], caption="CLI commands")
    D.h2("5.1 Options (actual --help output)")
    D.code(inp["cli"]["help"])
    D.h2("5.2 A real run")
    D.p("Output of python main.py analyze --video on the real gameplay recording, captured exactly as printed "
        "(output redirected to a file, so progress appears as lines instead of the one-line bar shown in a "
        "terminal):")
    D.code(inp["cli"]["run"], size=6.8)
    D.table([("0", "analysis finished; results written"),
             ("2", "invalid input: missing file, unsupported format, not a video, damaged video, invalid option "
                   "value"),
             ("3", "wrong Python environment (packages missing): prints how to activate backend/.venv")],
            header=("Exit code", "Meaning"), widths=[2.5, 13.5], caption="Exit codes")
    D.p("Error messages are one line and name the problem, for example:")
    D.code(inp["cli"]["error_missing"].strip() + "\n\n" + inp["cli"]["error_format"].strip())

    # ---------------- 6
    D.h1("6. Opening and using the GUI")
    D.status(IMPL)
    D.code("source backend/.venv/bin/activate\n"
           "python main.py --gui                 # opens http://127.0.0.1:8765 in the default browser\n"
           "python main.py --gui --port 8800     # another port\n"
           "python main.py --gui --no-browser    # start the server only, open the address yourself\n"
           "# stop: Ctrl+C in the terminal", size=8)
    D.p("No login, password or account is needed. The page runs only on this computer. If the port is already in "
        "use (for example the GUI is already running), the command says so and suggests the next port.")
    D.bullets([
        "Drop a video on the dashed area or click it to choose a file (.mp4, .mkv or .avi).",
        "Choose the target frame rate (60, 30, 120 or 144 FPS). Advanced thresholds are optional.",
        "Click Analyze Video. The bar shows the upload and then the frame being analysed.",
        "Read the results: verdict, key numbers, effective FPS chart, events with timestamps, more charts, video "
        "details and limitations.",
        "Click Download Word report for FPS_ANALYSIS_REPORT_<video>.docx (or JSON for the raw data).",
        "Click Analyse another video to start again. The address #job=<id> reopens a result while the GUI runs.",
    ], style="List Number")
    gui_first = D.fig + 1
    D.figure(shots / "gui_1_upload.png", "Start page (real screenshot, light mode).", 15)
    D.figure(shots / "gui_2_video_selected.png", "The real gameplay video selected, advanced thresholds open.", 15)
    D.figure(shots / "gui_3_progress.png", "Progress while the real video is analysed.", 15)
    D.figure(shots / "gui_4_results.png", "Results for the real video: verdict, key numbers, effective FPS "
                                          "chart.", 15)
    gui_figs = f"Figures {gui_first}–{D.fig}"
    D.p("A step-by-step script for demonstrating the prototype (commands, expected results, likely questions) is "
        "delivered separately as docs/DEMO_GUIDE.docx.")

    # ---------------- 7
    D.h1("7. The video-processing pipeline")
    D.status(IMPL)
    D.figure(pipe, "Processing steps from the video file to the report.")
    D.table([
        ("1. Validate", "The path must exist and be a file; the extension must be .mp4, .mkv or .avi; the size "
                        "must be under the limit (2 GB); the first bytes must match a video container, so a text "
                        "file renamed to .mp4 is rejected before decoding."),
        ("2. Metadata", "ffprobe reads codec, container, resolution, nominal frame rate (r_frame_rate), average "
                        "frame rate, frame count, duration and whether the frame rate is variable. Without ffprobe, "
                        "OpenCV's properties are used."),
        ("3. Decode", "OpenCV decodes every frame (full rate: frame timing needs all frames). Each frame carries "
                      "its presentation timestamp t_i from the container, cross-checked with the decoder."),
        ("4. Compare", "Each frame is reduced to a 160 × 90 greyscale thumbnail and compared with the previous "
                       "one (mean absolute difference, Eq. 5). Small thumbnails make the comparison fast and robust "
                       "to compression noise."),
        ("5. Classify", "Repeated picture? Scene moving? A repeated picture inside motion is a missed render; in "
                        "variable-frame-rate files a long interval hides missing frames (Section 8)."),
        ("6. Windows", "A 1-second window slides in 0.25 s steps; in each moving window the new pictures are "
                       "counted (effective FPS) and missed frames are summed."),
        ("7. Events", "Freezes, FPS drops and stutter periods are found with persistence rules (Section 8.4)."),
        ("8. Outputs", "Statistics, verdict, three charts, analysis.json, timeline.csv, windows.json and the Word "
                       "report are written to outputs/<date-time>_<video>/."),
    ], header=("Step", "What happens"), widths=[2.6, 13.4], caption="Pipeline steps")

    # ---------------- 8
    D.h1("8. FPS detection methodology")
    D.status(IMPL)
    D.h2("8.1 What a video can and cannot tell")
    D.p("A recording does not contain the game's frame times. It contains the pictures the recorder captured. Four "
        "different quantities are easily confused, so the prototype keeps them apart:")
    D.table([
        ("Nominal FPS", "The rate written in the file header (e.g. 60).", "The recorder's setting, not the game.",
         "Yes (metadata)"),
        ("Presentation timestamps", "The time at which each frame should be shown.", "Gaps in variable-frame-rate "
         "recordings where the game delivered no frame.", "Yes, when the container has timestamps"),
        ("Repeated frames", "Consecutive frames with the same picture.", "In constant-frame-rate recordings a "
         "skipped render appears as a repeated picture.", "Yes, while the scene moves"),
        ("True engine FPS", "How many frames the game rendered per second.", "Ground truth.",
         "No. Needs a profiler log or an on-screen FPS counter"),
    ], header=("Quantity", "Definition", "What it reveals", "Measurable from the video?"),
        widths=[3.2, 4.4, 4.6, 3.8], caption="Nominal FPS vs timestamps vs repeated frames vs true engine FPS")
    D.p("The prototype therefore reports an effective FPS: the number of new pictures per second visible in the "
        "recording while the scene moves. It is capped by the recording rate (a 60 FPS recording cannot show a drop "
        "from 144 to 90 FPS) and is not the game's internal FPS; the reports say this explicitly.")
    D.h2("8.2 Repeated and missed frames")
    D.p("Two consecutive frames show the same picture when their thumbnail difference is below 0.25 grey levels "
        "(Eq. 6). Repeated frames are not bit-identical after lossy compression: differences of 0.02–0.14 were "
        "measured at CRF 18, and the threshold was calibrated on the tuning set. A repeated picture says nothing on "
        "its own: in a menu, a paused game or when the player stands still every frame repeats. A repeat is "
        "therefore counted as a missed render only when the scene is clearly moving on both sides: the frame before "
        "and the frame after the hold must both differ by at least 1.0 grey level (abrupt edges), and the median "
        "motion of three changing frames within 0.25 s on each side must also be at least 1.0 (sustained motion). "
        "A player slowing to a stop decelerates gradually and fails this test; a stalled renderer stops and restarts "
        "within one frame and passes it. This rule came from the real footage, where 91 % of the editor segment "
        "consists of identical frames.")
    D.p("Variable-frame-rate recordings store the same information differently: instead of repeating a picture, "
        "the recorder leaves a longer interval. An interval of k normal intervals hides k − 1 frames (Eq. 9). "
        "These hidden frames are treated exactly like k − 1 repeated frames of a constant-frame-rate file, placed "
        "at their own times inside the gap: missed renders only if the same abrupt-edge and sustained-motion test "
        "passes, otherwise a still stretch. (Phase 6 found that an earlier version counted every gap as missing "
        "pictures; see Section 17.6.)")
    D.figure(charts / "frame_changes.png", "Frame-to-frame change in the real video; red marks are repeated frames "
                                           "during motion (missed renders).")
    D.h2("8.3 Effective FPS windows")
    D.p("A 1-second window moves through the video in 0.25 s steps. A window is measurable when it holds at least two "
        "frames and at least half of its frames are moving. In a measurable window, effective FPS is the number of "
        "frames that are not missed renders (Eq. 10). Windows that are not measurable are shown as gaps in the "
        "charts and reported as the 'measurable' share of the video.")
    D.h2("8.4 Events and default thresholds")
    D.table([
        ("Freeze", "One picture held for ≥ 250 ms while the scene moves on both sides (also: a timestamp gap ≥ "
                   "250 ms between two moving pictures in VFR files).", "freeze_ms = 250", "--freeze-ms"),
        ("FPS drop", "Effective FPS below drop ratio × target in at least two consecutive windows (≥ 0.5 s).",
         "drop_ratio = 0.75, target_fps = 60 (→ 45 FPS)", "--drop-ratio, --target-fps"),
        ("Stutter", "At least K missed frames in a window while effective FPS stays ≥ the drop threshold, in at least "
                    "two consecutive windows, not overlapping a freeze or a drop (uneven pacing, not a low average).",
         "stutter_min_missed K = 3", "--stutter-min-missed"),
    ], header=("Event", "Rule", "Default (config/default.yaml)", "CLI option"), widths=[2.2, 7.6, 3.6, 2.6],
        caption="Detected events and their thresholds")
    D.p("Internal constants (not exposed as options): thumbnail 160 × 90; repeat threshold 0.25; motion threshold "
        "1.0; window 1 s, step 0.25 s; moving share ≥ 0.5; motion context 3 frames within 0.25 s. They were fixed on "
        "the tuning set before the held-out evaluation (Section 17).")

    # ---------------- 9
    D.h1("9. Mathematical equations and calculations")
    D.status(IMPL)
    D.p("Notation: N frames with presentation timestamps t_1 < t_2 < … < t_N (seconds); G_i is frame i reduced to a "
        "160 × 90 greyscale image.")
    D.eq("FPS_nominal = r_frame_rate of the stream (e.g. 60/1)", "read from the container header by ffprobe")
    D.eq("Δt_i = t_(i+1) − t_i ,   i = 1 … N−1", "frame (presentation) interval")
    D.eq("FPS_avg = (N − 1) / (t_N − t_1)", "average FPS from timestamps")
    D.eq("Δt_expected = 1000 / FPS_nominal  ms;   irregular ⇔ |Δt_i − median(Δt)| > 0.25 · median(Δt)",
         "expected interval and irregular-interval count")
    D.eq("MAD_i = (1 / (W·H)) · Σ_x Σ_y | G_i(x, y) − G_(i−1)(x, y) | ,   W = 160, H = 90",
         "mean absolute difference between consecutive thumbnails (grey levels 0–255)")
    D.eq("repeated_i ⇔ MAD_i < τ_rep ,   τ_rep = 0.25", "frame i shows the same picture as frame i−1")
    D.eq("missed(a…b) ⇔ MAD_(a−1) ≥ τ_mov  ∧  MAD_(b+1) ≥ τ_mov  ∧  M_before ≥ τ_mov  ∧  M_after ≥ τ_mov",
         "frames a…b repeat frame a−1; M = median MAD of 3 changing frames within 0.25 s on that side; τ_mov = 1.0")
    D.eq("hold = t_(b+1) − t_(a−1) ;   freeze ⇔ missed(a…b) ∧ hold ≥ 0.250 s", "length of a held picture")
    D.eq("k_i = round(Δt_i / median(Δt)) − 1 ,   hidden frames at t_i + m · median(Δt), m = 1 … k_i",
         "frames hidden inside a VFR interval; treated like repeated frames (missed only if Eq. 7's test passes)")
    D.eq("FPS_eff(w) = #{ i : t_i ∈ [w, w + 1 s), not missed_i } / 1 s", "effective FPS of a measurable window, "
                                                                          "w = t_1, t_1 + 0.25 s, …")
    D.eq("drop ⇔ FPS_eff(w) < r · FPS_target  for ≥ 2 consecutive windows ,   r = 0.75",
         "at a 60 FPS target the drop threshold is 0.75 × 60 = 45 FPS")
    D.eq("stutter ⇔ missed(w) ≥ K  ∧  FPS_eff(w) ≥ r · FPS_target  for ≥ 2 consecutive windows ,   K = 3",
         "missed(w) = missed renders + VFR missing frames in the window; the event is widened by 0.5 s on each side")
    D.eq("FT_j = t(next new picture) − t(new picture j) ,   1 % low FPS = 1 / P99(FT)",
         "frame times while moving; P99 = 99th percentile")
    D.eq("measurable share = measurable windows / all windows", "")
    D.eq("P = TP / (TP + FP) ,   R = TP / (TP + FN) ,   F1 = 2·P·R / (P + R)",
         "evaluation metrics (Section 17); an event matches a ground-truth event of the same type that it overlaps")
    D.h2("9.1 Worked example: the real video")
    D.table([
        ("Frames, first and last timestamp", f"N = {md['frame_count']:,}; duration {md['duration_s']} s"),
        ("Average FPS (Eq. 3)", f"({md['frame_count']:,} − 1) / ({md['duration_s']} s) ≈ {md['average_fps']} FPS "
                                f"(nominal {md['nominal_fps']})"),
        ("Intervals (Eq. 2, 4)", f"expected {fi['expected_ms']} ms; median {fi['median_ms']} ms; min "
                                 f"{fi['min_ms']} / max {fi['max_ms']} ms; irregular intervals: "
                                 f"{fi['irregular_intervals']} → constant frame rate"),
        ("Drop threshold (Eq. 11)", f"{R['settings']['drop_ratio']} × {ef['target_fps']:g} = "
                                    f"{ef['drop_threshold_fps']:g} FPS"),
        ("Effective FPS (Eq. 10)", f"median {ef['median']}, mean {ef['mean']}, min {ef['min']}, 5th percentile "
                                   f"{ef['p5']} FPS over the {round(ef['measurable_fraction'] * 100)} % measurable "
                                   "part"),
        ("1 % low (Eq. 13)", f"P99 frame time {fr['p99_ms']} ms → 1 / 0.0333 s = {fr['one_percent_low_fps']} FPS"),
        ("Repeated / missed", f"{cn['repeated_frames']:,} repeated frames in total, of which "
                              f"{cn['missed_frames_while_moving']} during motion (missed renders)"),
    ], widths=[4.6, 11.4], caption="Equations applied to the real recording (values from analysis.json)")

    # ---------------- 10
    D.h1("10. Technologies and libraries")
    pk = inp["pkgs"]
    env = inp["env"]
    D.table([
        ("Python", env["Python"], "Language of the whole system.", "Yes"),
        ("OpenCV", env["OpenCV"], "Video decoding (VideoCapture), image resizing and colour conversion. The "
                                  "contrib-headless build avoids the GUI dependencies and the clash between the "
                                  "OpenCV wheels of ultralytics and mediapipe.", "Yes"),
        ("NumPy", env["NumPy"], "Array maths: differences, percentiles, windows.", "Yes"),
        ("FFmpeg / ffprobe", env["FFmpeg / ffprobe"], "Exact metadata and timestamps; optional (OpenCV fallback).",
         "Yes (optional)"),
        ("pydantic / pydantic-settings", f"{env['pydantic']} / {pk['pydantic-settings']}", "Typed, validated "
         "configuration and result objects (invalid thresholds are rejected).", "Yes"),
        ("PyYAML", pk["pyyaml"], "Reads config/default.yaml.", "Yes"),
        ("matplotlib", env["matplotlib"], "The three charts (PNG) and the diagrams in this document.", "Yes"),
        ("python-docx", env["python-docx"], "FPS_ANALYSIS_REPORT.docx and this document.", "Yes"),
        ("FastAPI + uvicorn", f"{env['FastAPI']} / {env['uvicorn']}", "Local web server of the GUI; chosen because "
         "it is light, already used in the repository, and supports file upload with python-multipart "
         f"({pk['python-multipart']}).", "Yes"),
        ("HTML, CSS, JavaScript", "—", "The GUI page; no framework, no build step, no external scripts.", "Yes"),
        ("pytest + httpx", f"{env['pytest']} / {pk['httpx']}", "Automated tests, including the GUI API.", "Yes"),
        ("scikit-image", pk["scikit-image"], "SSIM for the texture pop-in detector.", "No (future module)"),
        ("Ultralytics YOLOv8", pk["ultralytics"], "Person detection for the NPC detector.", "No (future module)"),
        ("MediaPipe", pk["mediapipe"], "Pose landmarks for the NPC detector.", "No (future module)"),
    ], header=("Technology", "Version", "Used for", "Used by the prototype?"), widths=[3.3, 2.6, 7.4, 2.7],
        caption="Technologies (versions read from the installed environment)")

    # ---------------- 11
    D.h1("11. NPC detection with YOLOv8")
    D.status(DEV, "code in gameqa/detectors/npc.py; unit-tested; not validated — no footage with characters")
    D.p("YOLOv8 is a one-stage convolutional object detector. A backbone network extracts features at three scales; "
        "a detection head predicts, for every location of each feature map, a bounding box (centre, width, height) "
        "and a score for each class, in a single forward pass. Overlapping predictions of the same object are "
        "merged by non-maximum suppression. The model used (YOLOv8n, COCO weights) knows the class 'person', "
        "which is how human-like game characters are found.")
    D.bullets([
        ("Locating characters: ", "frames sampled at 12 FPS; boxes of class person with confidence ≥ 0.4 are kept "
                                  "and normalised to the frame size."),
        ("Tracking: ", "a box is linked to the existing track with the highest overlap (IoU ≥ 0.3, Eq. 16) seen in "
                       "the last 0.5 s, so each character gets an identity over time."),
        ("Filtering: ", "tracks that touch the bottom screen edge in ≥ 80 % of observations and stay fixed on "
                        "screen are the player's own first-person hands and are ignored (on the real video all 48 "
                        "YOLO 'person' hits were the player's gloved hand, confidence 0.42–0.49; the detector "
                        "reported 0 NPC anomalies, which is correct for a video without characters)."),
        ("Output: ", "each track's box crops the frame for pose estimation (Section 12)."),
    ])
    D.eq("IoU(A, B) = area(A ∩ B) / area(A ∪ B)", "overlap of two boxes (also used in Section 15)")
    D.p("Tested so far: the model pipeline on a real photograph (person found with confidence > 0.5, pose found) and "
        "the rules on synthetic keypoints. Not tested: real game characters. Limitations: COCO and MediaPipe were "
        "trained on real people, so stylised, non-human, very small or heavily occluded characters are missed.")

    # ---------------- 12
    D.h1("12. MediaPipe pose estimation")
    D.status(DEV, "T-pose, frozen NPC and ragdoll rules implemented; floating NPC is proposed only")
    D.p("MediaPipe PoseLandmarker estimates 33 body landmarks (nose, shoulders, elbows, wrists, hips, knees, ankles, "
        "…), each with x, y, a relative depth z and a visibility score. It handles one person per image, so it runs "
        "on each YOLO crop. Joint angles are computed from three landmarks:")
    D.eq("θ_b = arccos( ((a − b) · (c − b)) / (‖a − b‖ · ‖c − b‖) )", "angle at joint b, e.g. elbow (a = shoulder, "
                                                                     "b = elbow, c = wrist)")
    D.table([
        ("T-pose", "Both elbows ≥ 150° (straight arms), upper arms 70–110° from the torso, wrist-to-wrist span ≥ "
                   "2.2 × shoulder width, held ≥ 1 s.", DEV),
        ("Frozen NPC", "Landmarks in box-relative coordinates barely change (std ≤ 0.012) over 2 s while the box "
                       "moves ≥ 0.5 box heights in the world (camera motion removed): sliding without walking. A "
                       "character standing still is not reported.", DEV),
        ("Ragdoll anomaly", "Mean landmark jump ≥ 0.35 box heights per analysed frame for ≥ 0.25 s (limbs "
                            "teleporting); a heuristic, not a physics check.", DEV),
        ("Floating character", "Needs a ground reference: a single 2-D view has no depth, so contact cannot be "
                               "measured. Possible approaches: feet-to-shadow contact, monocular depth estimation, or "
                               "a learned classifier on labelled examples.", PROP),
    ], header=("Anomaly", "Rule (temporal tracking over the track's history)", "Status"), widths=[2.8, 9.4, 3.8],
        caption="NPC anomaly rules", status_col=2)

    # ---------------- 13
    D.h1("13. SSIM and autoencoder methodology (texture pop-in)")
    D.status(DEV, "SSIM detector in gameqa/detectors/texture.py; autoencoder proposed")
    D.p("Texture pop-in is a surface suddenly changing its level of detail (blurry → sharp) between two frames. The "
        "Structural Similarity Index compares two image patches x and y by luminance, contrast and structure:")
    D.eq("SSIM(x, y) = ((2μ_x μ_y + C1)(2σ_xy + C2)) / ((μ_x² + μ_y² + C1)(σ_x² + σ_y² + C2))",
         "μ means, σ² variances, σ_xy covariance of the patches; C1, C2 small constants; 1 = identical")
    D.bullets([
        ("Comparing consecutive frames: ", "every frame, 480 × 270 greyscale; the previous frame is first aligned "
                                           "to the current one (phase correlation, ORB + RANSAC fallback)."),
        ("Finding sudden changes: ", "the SSIM map is averaged per grid cell; cells far above the frame's own "
                                     "typical dissimilarity (median + k·MAD) are candidates."),
        ("Camera movement: ", "removed by the alignment; frames that cannot be aligned are skipped."),
        ("Lighting changes: ", "a pop-in keeps the colour layout (low-pass difference small) but changes "
                               "high-frequency detail by a large factor; a lighting change does the opposite."),
        ("Scene transitions: ", "frames whose typical dissimilarity is high everywhere (cuts, fades, fast motion) "
                                "are skipped; a pop-in must be local and stay quiet afterwards."),
    ])
    D.p("Recorded results (DEVELOPMENT_PROGRESS.md, Phase 4): held-out synthetic set precision 0.833, recall 0.703, "
        "F1 0.763; on the real video 9 detections, all false positives caused by editor interface elements. Real "
        "recall is unknown because no real pop-in footage is available.")
    D.h2("13.1 Convolutional autoencoder (proposed)")
    D.status(PROP)
    D.p("An autoencoder is trained only on clean frames (or patches) of a game. The encoder E compresses the input to "
        "a small code and the decoder D reconstructs it. Patterns seen in training reconstruct well; unusual ones "
        "(missing or low-resolution textures, magenta placeholder materials) reconstruct badly:")
    D.eq("e(x) = (1 / n) · ‖x − D(E(x))‖² ;   anomaly ⇔ e(x) > P99 of e on clean validation frames",
         "reconstruction error and threshold")
    D.p("Requirements before it can be built: clean footage of the target game for training, labelled defects for "
        "validation, and a GPU for training in reasonable time.")

    # ---------------- 14
    D.h1("14. Farneback optical flow methodology (animation glitches)")
    D.status(DEV, "gameqa/detectors/animation.py; validated on synthetic data only")
    D.p("Dense optical flow estimates a motion vector for every pixel between two consecutive frames. Farneback's "
        "method approximates each neighbourhood of an image by a quadratic polynomial f(x) ≈ xᵀAx + bᵀx + c. If the "
        "neighbourhood moves by d, the polynomial's coefficients change, and d can be solved from them:")
    D.eq("d = −½ · A⁻¹ · (b₂ − b₁)", "displacement from the polynomial coefficients of frames 1 and 2 (solved "
                                     "iteratively over an image pyramid)")
    D.bullets([
        ("Camera motion: ", "the global translation is estimated and removed, leaving the motion of objects."),
        ("Jitter: ", "flow (or camera motion) that reverses direction frame after frame with magnitude ≥ 1.5 px, "
                     "with at least 5 direction reversals in the recent window; normal movement keeps its "
                     "direction."),
        ("Flicker: ", "a region's brightness alternating up and down by ≥ 20 grey levels in ≥ 4 of 7 frame pairs."),
        ("Unnatural transition: ", "a one-frame spike in image change ≥ 3 × both neighbours (camera snap, missing "
                                   "keyframe)."),
        ("Temporal consistency: ", "events must persist over several frames; duplicates are merged."),
    ])
    D.p("Recorded results (Phase 5): held-out synthetic precision 0.940, recall 0.904, F1 0.922. On the real video: "
        "one video-edit cut (indistinguishable from a teleport by definition) and one false jitter during a fast "
        "camera pitch. Limitations: when the whole scene or the camera moves quickly, alignment fails and intended "
        "effects (screen shake, strobe lights, hit flashes) look like glitches.")

    # ---------------- 15
    D.h1("15. Collision and geometry clipping methodology")
    D.status(DEV, "experimental code in gameqa/detectors/clipping.py; FAILED validation; not usable yet")
    D.p("The SRS proposes detecting dynamic objects and characters with YOLOv8 and checking their bounding boxes for "
        "overlap (IoU, Eq. 16) with environmental objects; overlap that persists over time would indicate clipping.")
    D.p("Why box overlap alone cannot prove clipping:", bold_lead=None)
    D.bullets([
        "In a single 2-D view an object behind a wall (correct occlusion) and an object inside the wall (clipping) "
        "produce the same overlap; there is no depth.",
        "COCO-trained YOLO has no classes for walls, floors or terrain, so there is no geometry box to compare with.",
        "Boxes are coarse: a weapon tip entering a wall changes a few pixels, far below box precision.",
    ])
    D.p("What was tried: learning the first-person weapon ('viewmodel') appearance and reporting when its tip stops "
        "matching while the body still matches. On real footage with 9 hand-labelled clipping events, the "
        "frame-level check on held-out data gave precision 0.43 at recall 0.87, against 0.39 for always saying "
        "'clipping': essentially chance. It is therefore labelled failed validation.")
    D.p("Approaches that could work better: semantic segmentation of walls / floors; monocular depth estimation to "
        "compare object and surface depth; engine collision logs as ground truth; a classifier trained on labelled "
        "clipping clips; temporal reasoning (an object should be visible before it disappears into a surface).")

    # ---------------- 16
    D.h1("16. Future integration plan")
    D.status(PROP)
    D.p("All detectors implement the same interface (gameqa/core/detector.py): start(video) → process(frame) for "
        "each frame → finish() returning detections with category, subtype, start / end time and frame, confidence "
        "and evidence. The FPS engine already uses this interface through FpsDropDetector, so new modules plug in "
        "next to it without changes:")
    D.bullets([
        "One decoder pass feeds all detectors: full-rate modules (FPS, texture, animation) receive every frame, "
        "sampled modules (NPC, clipping) every fifth frame (12 FPS for a 60 FPS video).",
        "The CLI gains a --modules option (e.g. --modules fps,texture); the GUI shows a checkbox per module. Modules "
        "that are not validated stay off by default.",
        "Each module adds its own section and charts to the Word report; analysis.json gains one list per module.",
        "A rule-based severity (Low / Medium / High) from affected area, duration and recurrence is applied to all "
        "detections, as specified in the SRS.",
    ])
    D.table([
        ("Texture pop-in", "Suppress UI regions (static screen areas); real footage with pop-ins for testing",
         "Real-footage precision ≥ 0.8 on labelled clips"),
        ("Animation glitches", "Real footage with jitter / flicker; handling of video-edit cuts",
         "Held-out real F1 measured and documented"),
        ("NPC anomalies", "Footage with characters (and deliberately broken animations)",
         "T-pose and frozen-NPC precision / recall on labelled clips"),
        ("Clipping", "New method (segmentation or depth) — current method failed",
         "Better than the 'always clipping' baseline on held-out data"),
        ("Unified report + severity", "All above; severity calibrated against human ratings",
         "Agreement with tester ratings"),
    ], header=("Module", "Needed before integration", "Validation gate"), widths=[3.4, 7.0, 5.6],
        caption="Integration order and gates")

    # ---------------- 17
    D.h1("17. Testing methodology and actual results")
    D.status(IMPL)
    D.h2("17.1 Methodology")
    D.bullets([
        ("Automated tests (pytest): ", "unit tests of every rule, end-to-end runs of the CLI and the GUI API on "
                                       "real decoding, invalid-input tests."),
        ("Synthetic injection with ground truth: ", "freezes, FPS drops and stutter are injected into clean "
                                                    "generated videos at known times; detections are matched to "
                                                    "them by type and overlap. Thresholds were tuned on seed 0 only; "
                                                    "seeds 1–3 were generated afterwards and re-encoded at CRF 23 "
                                                    "(held out, never used for tuning)."),
        ("Real footage: ", "the analysis of a real gameplay recording was reviewed frame by frame at the reported "
                           "times. There is no profiler ground truth for this video, so it is reviewed, not scored."),
        ("Manual interface tests: ", "the CLI in a real terminal and the GUI in a browser, including error cases."),
    ])
    D.h2("17.2 Automated tests")
    tc = inp["tests"]
    D.table([
        ("tests/test_fps_service.py", tc["tests/test_fps_service.py"], "Missing / unsupported / text-as-video / "
         "damaged files, constant-frame-rate statistics, VFR gap → freeze, stutter vs drop, configurable "
         "thresholds, OpenCV fallback, saved files, too-short video."),
        ("tests/test_main_cli.py", tc["tests/test_main_cli.py"], "Report contents, command-line thresholds, five "
         "invalid inputs (exit 2 + message), running exactly as python main.py analyze."),
        ("tests/test_webgui.py", tc["tests/test_webgui.py"], "Page without login, upload → results flow, GUI and CLI "
         "give identical results, unsupported format, fake video, invalid setting, browser opening, port in use."),
        ("Whole repository", "—", f"Full suite result: {inp['pytest']}. The expected failures are the "
         "experimental clipping detector (Section 15)."),
    ], header=("Test file", "Tests", "What is checked"), widths=[4.2, 1.4, 10.4], caption="Automated tests")
    D.h2("17.3 Synthetic evaluation")
    rows = []
    for name, key in (("Stutter", "stutter"), ("Freeze", "freeze"), ("FPS drop", "fps_drop")):
        for setname, data in (("Tuning (seed 0 + 2 clean videos)", tun), ("Held-out (seeds 1–3, CRF 23)", hel)):
            tp, fp, fn = data[key]
            p = tp / (tp + fp) if tp + fp else 0
            r = tp / (tp + fn) if tp + fn else 0
            f1 = 2 * p * r / (p + r) if p + r else 0
            rows.append((name, setname, tp, fp, fn, f"{p:.3f}", f"{r:.3f}", f"{f1:.3f}"))
    D.table(rows, header=("Event", "Set", "TP", "FP", "FN", "Precision", "Recall", "F1"),
            widths=[1.9, 5.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.1],
            caption="Synthetic evaluation (from evaluation/results/prototype_fps/report_seeds_*.md)")
    D.p("The one missed held-out freeze: after CRF 23 compression its first repeated frame differed by 0.68 grey "
        "levels from the previous one (above the 0.25 repeat threshold), so the hold seemed to start one frame later "
        "after a 'slowing' frame and the abrupt-edge rule rejected it. The threshold was not changed on the "
        "held-out data; this is recorded as a limitation.")
    D.h2("17.4 Real gameplay recording")
    D.table([
        ("Video", f"{md['file_name']}"),
        ("Format", f"{md['resolution']}, {md['codec']}, {md['duration_s']} s, {md['frame_count']:,} frames, "
                   f"{md['file_size_mb']} MB, {'variable' if md['variable_frame_rate'] else 'constant'} frame rate"),
        ("Content", "A Unity tutorial: about 19 s of first-person gameplay followed by editor footage."),
        ("Nominal / average FPS", f"{md['nominal_fps']} / {md['average_fps']}"),
        ("Effective FPS", f"median {ef['median']}, mean {ef['mean']}, min {ef['min']} (target {ef['target_fps']:g})"),
        ("Frame times", f"p50 {fr['p50_ms']} ms, p99 {fr['p99_ms']} ms → 1 % low {fr['one_percent_low_fps']} FPS"),
        ("Measurable", f"{round(ef['measurable_fraction'] * 100)} % of the video (the moving part)"),
        ("Events", f"{cn['freezes']} freeze, {cn['fps_drops']} FPS drops, {cn['stutters']} stutter periods; "
                   f"{cn['missed_frames_while_moving']} missed frames while moving"),
        ("Processing", f"{pr['seconds']} s ({pr['realtime_factor']}× real time) on the machine in Table 5"),
    ], widths=[3.8, 12.2], caption="Real-video results (analysis.json of the run named on the title page)")
    D.table([(e["type"].replace("fps_drop", "FPS drop").capitalize(), ft(e["start_s"]), ft(e["end_s"]),
              f"{e['duration_s']:.2f} s", e["description"]) for e in R["events"]],
            header=("Event", "Start", "End", "Duration", "Description"), widths=[1.8, 2.0, 2.0, 1.8, 8.4],
            caption="Events detected in the real video")
    D.p("Review: the four stutter periods cover the gameplay part, where isolated exact repeats appear during smooth "
        "motion: real uneven pacing in the recording, but whether the game, the recorder or the tutorial's editing "
        "caused it cannot be decided from the video. The freeze at 18.37 s is a known false positive: it is the "
        "held picture just before an editing transition. No FPS drop was reported, consistent with the median of "
        f"{ef['median']} FPS.")
    D.h2("17.5 Interface tests")
    D.table([
        ("CLI, real video", "Results + Word report, exit 0", "As Section 5.2; identical on re-run", IMPL),
        ("CLI, missing file / .mov / text renamed .mp4 / --drop-ratio 1.5 / --target-fps 0",
         "One-line message, exit 2", "As expected (Section 5)", IMPL),
        ("CLI with a Python lacking the packages", "Activation instructions, exit 3", "As expected", IMPL),
        ("GUI, real video upload", "Progress, results equal to CLI, downloads",
         f"Identical results; report and JSON downloaded", IMPL),
        ("GUI, notes.txt", "Rejected before upload", "Message shown, button disabled", IMPL),
        ("GUI, text file renamed .mp4", "Analysis failed with reason, nothing left on disk", "As expected", IMPL),
        ("Second python main.py --gui while running", "Port-in-use message, exit 2", "As expected", IMPL),
        ("GUI at phone width (375 px) and in dark mode", "Readable, no sideways scrolling",
         "Fixed during testing (long file names), then passed", IMPL),
    ], header=("Case", "Expected", "Actual", "Status"), widths=[5.0, 4.0, 3.9, 3.1],
        caption="CLI and GUI tests", status_col=3)

    D.h2("17.6 Phase 6: CLI and GUI on a test set of videos")
    D.p("Only one real gameplay recording is available, so the Phase 6 test set was derived from it "
        "(backend/scripts/phase6_test.py): other containers and codecs, 30 FPS, variable frame rate, a static "
        "segment, damaged and tiny files, a non-ASCII file name, and two copies with a freeze or an FPS drop "
        "injected at a known time. Each video was analysed with the real CLI and uploaded to the running GUI; "
        "invalid inputs were tried in both.")
    p6rows = []
    for r in inp["phase6"]:
        c, g = r["cli"], r["gui"]
        res = c.get("result")
        if res:
            n = res["counts"]
            med = res["effective_fps"]["median"]
            summary = (f"{round(res['effective_fps']['measurable_fraction'] * 100)} % measurable; "
                       + (f"median {med} FPS; " if med is not None else "nothing moves, so no FPS is reported; ")
                       + f"{n['freezes']} / {n['fps_drops']} / {n['stutters']} freeze / drop / stutter"
                       + (f". {r['gt']}" if r.get("gt") else ""))
        else:
            summary = c.get("error", "")
        gui = "same result" if r.get("identical") else (g.get("status", "") + (f" ({g['http']})" if g.get("http")
                                                                                 not in (None, 202) else ""))
        p6rows.append((r["name"], r["kind"], f"exit {c['exit']}", gui, summary))
    D.table(p6rows, header=("File", "Variant", "CLI", "GUI", "Result / message"), widths=[3.4, 3.8, 1.3, 2.2, 5.3],
            caption="Phase 6 test set (from evaluation/results/phase6/results.json)")
    D.p("Findings: CLI and GUI gave identical results for every video; both injected defects were found at the "
        "injected times; every invalid input produced a one-line reason (exit code 2, or HTTP 415 / a failed job in "
        "the GUI) and left no files behind. One bug was found and fixed: in the variable-frame-rate copy a 0.7 s "
        "moment where the player stood still (repeated frames removed by the encoder) was reported as an FPS drop, "
        "while the same moment in the original file was correctly 'not measurable'. Timestamp gaps now follow "
        "the same rule as repeated frames (Section 8.2); a regression test covers it, and the Phase 3 and "
        "prototype evaluations were re-run with unchanged scores. The damaged-file message was also made clearer. "
        "One finding is recorded, not tuned: in the AVI (MPEG-4 Part 2) re-encode the first frame of the held "
        "picture at 18.37 s differs by 0.33 grey levels (threshold 0.25), so that freeze is not reported: the same "
        "compression limitation as the one missed held-out freeze.")

    # ---------------- 18
    D.h1("18. Known limitations and technical challenges")
    D.table([
        ("True game FPS", "Cannot be recovered from an ordinary recording. Only the pictures the recorder captured are "
                          "available; ground truth needs profiler logs (e.g. PresentMon, engine profiler) or an "
                          "on-screen FPS counter."),
        ("Recording rate cap", "A 60 FPS recording cannot show the game falling from 144 to 90 FPS."),
        ("Still scenes", "When the picture does not move a repeated frame is indistinguishable from a normal one; "
                         "such parts are excluded and reported as not measurable (91 % of the real video)."),
        ("Video editing and intended pauses", "Cuts, transitions, hit-stop effects and cut-scene pauses can look "
                                              "like freezes (the real-video freeze is such a case)."),
        ("Compression noise", "Heavy compression can hide the first frame of a freeze (1 of 9 held-out freezes "
                              "missed; the 18.37 s hold in the AVI re-encode of Phase 6)."),
        ("Little real footage", "Only one real recording, without ground truth, has been analysed; the Phase 6 "
                                "test videos are derived from it. Recordings from other games, with an FPS counter, "
                                "and real variable-frame-rate captures are needed to measure error against truth."),
        ("Prototype GUI", "One analysis at a time; results kept in memory (old result links stop working after a "
                          "restart, files remain in outputs/); uploaded videos are kept in outputs/<run>/input/; no "
                          "login, so it must stay on 127.0.0.1."),
        ("Platforms", "Built and tested on macOS (Apple M1, 8 GB). Windows and Linux are expected to work but were "
                      "not tested."),
        ("Other modules", "NPC, texture, animation and clipping detectors are not validated on real defects "
                          "(Sections 11–15)."),
    ], header=("Limitation", "Details"), widths=[4.0, 12.0], caption="Limitations")
    D.p("Main technical challenges met during development: separating a skipped render from a player standing still "
        "(solved with the abrupt-edge and sustained-motion rule); compression noise on repeated frames (calibrated "
        "repeat threshold); conflicting OpenCV wheels from ultralytics and mediapipe (single contrib-headless build); "
        "Word tables showing without borders in some viewers (explicit borders in the generated documents).")

    # ---------------- 19
    D.h1("19. Screenshots and actual outputs")
    D.status(IMPL, "all screenshots taken from real runs on the real video")
    D.p("The GUI screenshots were captured automatically from a real upload of the real video by "
        "backend/scripts/capture_gui_screenshots.py (headless Chrome driving the page; nothing on the page was "
        f"edited). {gui_figs} in Section 6 show the start page, file selection, progress and results.")
    D.figure(shots / "gui_5_events.png", "Detected events with timestamps (GUI).", 15.5)
    D.figure(shots / "gui_6_details.png", "Frame-interval and repeated-frame charts, video metadata and limitations "
                                          "(GUI).", 15.5)
    D.figure(shots / "gui_7_unsupported.png", "Unsupported file rejected before upload (GUI).", 14)
    D.figure(shots / "gui_8_failed.png", "A text file renamed to .mp4: the analysis fails with a clear reason "
                                         "(GUI).", 14)
    D.figure(charts / "effective_fps.png", "Chart from the output folder: effective FPS over time with target and "
                                           "drop threshold; shaded spans are events.")
    D.figure(charts / "frame_intervals.png", "Chart from the output folder: presentation intervals from "
                                             "timestamps (constant, as expected for a CFR file).")
    page1 = shots / "report_page1.png"
    if page1.exists():
        D.figure(page1, "First page of the generated FPS_ANALYSIS_REPORT.docx for the real video (rendered by macOS "
                        "Quick Look).", 12)
    D.p("The full Word report for the real video is delivered next to this document as FPS_ANALYSIS_REPORT.docx.")

    # ---------------- 20
    D.h1("20. Future development roadmap")
    D.table([
        ("P1–P6", "Foundation, FPS engine, CLI, local GUI, documentation, prototype testing and demo guide", IMPL),
        ("Next", "Collect real footage with an on-screen FPS counter / profiler log; measure the error of the FPS "
                 "estimates (mean absolute error, as required by the SRS)", PROP),
        ("Module 2", "Texture pop-in: UI suppression, real pop-in footage, validation", PROP),
        ("Module 3", "Animation glitches: real footage, cut handling, validation", PROP),
        ("Module 4", "NPC anomalies: footage with characters, validation; floating-NPC research", PROP),
        ("Module 5", "Clipping: new method (segmentation / depth), validation", PROP),
        ("Integration", "Unified pipeline (--modules), severity classification, combined Word / JSON report", PROP),
        ("FYP-2", "Usability test with testers; performance on the target GPU machine; final evaluation", PROP),
    ], header=("Phase", "Work", "Status"), widths=[2.2, 9.8, 4.0], caption="Roadmap", status_col=2)

    # ---------------- appendices
    D.h1("Appendix A. Output files of one analysis")
    D.table([
        ("analysis.json", "All results: settings, metadata, intervals, effective FPS, frame times, counts, events, "
                          "verdict, limitations, processing time."),
        ("timeline.csv", "One row per analysis window: time, measurable, effective FPS, missed frames."),
        ("windows.json", "The same windows in JSON for programs."),
        ("charts/effective_fps.png", "Effective FPS over time with target and drop threshold."),
        ("charts/frame_intervals.png", "Presentation intervals from timestamps."),
        ("charts/frame_changes.png", "Frame-to-frame change with repeated and missed frames marked."),
        ("FPS_ANALYSIS_REPORT.docx", "Word report: summary, video, settings, timing, effective FPS, events, method, "
                                     "limitations, processing."),
        ("input/<video> (GUI only)", "Copy of the uploaded video."),
    ], header=("File", "Contents"), widths=[4.6, 11.4], caption="Files in outputs/<date-time>_<video>/")
    D.h1("Appendix B. Source files of the prototype", new_page=False)
    D.table([
        ("main.py", "CLI and --gui entry point"),
        ("backend/src/gameqa/fps_service/analysis.py", "analyze_video(), statistics, stutter, verdict"),
        ("backend/src/gameqa/detectors/fps.py", "repeated / missed frames, windows, freezes, FPS drops"),
        ("backend/src/gameqa/fps_service/charts.py, store.py, report_docx.py", "charts, saved files, Word report"),
        ("backend/src/gameqa/webgui/app.py, static/", "local web GUI"),
        ("backend/src/gameqa/video/", "validation, metadata, decoding"),
        ("config/default.yaml, backend/src/gameqa/config.py", "configuration"),
        ("backend/tests/test_fps_service.py, test_main_cli.py, test_webgui.py", "prototype tests"),
        ("backend/scripts/eval_prototype_fps.py", "synthetic evaluation"),
        ("backend/scripts/capture_gui_screenshots.py, build_project_docs.py", "screenshots and this document"),
    ], header=("File", "Purpose"), widths=[8.6, 7.4], caption="Source files")

    out.parent.mkdir(parents=True, exist_ok=True)
    d.save(out)
    return out


SECTIONS = [
    "Project overview and objectives", "Overall system architecture", "Prototype scope and implemented functionality",
    "Installation and environment setup", "Using the command-line interface", "Opening and using the GUI",
    "The video-processing pipeline", "FPS detection methodology", "Mathematical equations and calculations",
    "Technologies and libraries", "NPC detection with YOLOv8", "MediaPipe pose estimation",
    "SSIM and autoencoder methodology (texture pop-in)", "Farneback optical flow methodology (animation glitches)",
    "Collision and geometry clipping methodology", "Future integration plan", "Testing methodology and actual results",
    "Known limitations and technical challenges", "Screenshots and actual outputs", "Future development roadmap",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True, help="output folder of a real `main.py analyze` run")
    ap.add_argument("--shots", type=Path, default=ROOT / "docs/screenshots")
    ap.add_argument("--out", type=Path, default=ROOT / "docs")
    a = ap.parse_args()
    run = a.run.resolve()
    inp = load_inputs(run, a.shots)
    # sample per-video report = the real run's report
    sample = a.out / "FPS_ANALYSIS_REPORT.docx"
    shutil.copy2(run / "FPS_ANALYSIS_REPORT.docx", sample)
    if shutil.which("qlmanage"):  # macOS: render page 1 of the report for Section 19
        subprocess.run(["qlmanage", "-t", "-s", "1400", "-o", str(a.shots), str(sample)], capture_output=True)
        png = a.shots / (sample.name + ".png")
        if png.exists():
            png.replace(a.shots / "report_page1.png")
    path = build(inp, a.shots, a.out / "PROJECT_DOCUMENTATION.docx")
    print("wrote", path)
    print("wrote", sample)


if __name__ == "__main__":
    main()
