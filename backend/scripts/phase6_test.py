"""Prototype Phase 6: end-to-end tests of the CLI and the GUI on a set of videos + invalid inputs.

Only ONE real gameplay recording is available (evaluation/videos, see sources.md). The video
test set is therefore built from it, and every variant is labelled as derived:
  container / codec / frame-rate / resolution variants, a variable-frame-rate version, a
  static editor-only segment, a truncated file, a 2-frame file, a path with spaces and
  non-ASCII characters, and two copies of the gameplay part with a freeze or an FPS drop
  injected at a KNOWN time (ground truth).
Each video is analysed with the real CLI (`python main.py analyze ...` in a subprocess) and
uploaded to the running GUI (`python main.py --gui`) through the same HTTP endpoint the page
uses; the two results must be identical.

    python main.py --gui --no-browser &          # GUI must be running
    python backend/scripts/phase6_test.py [--gui http://127.0.0.1:8765]

Writes evaluation/results/phase6/results.json and report.md.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from gameqa.evaluation.synthetic import Drop, Freeze, render

ROOT = Path(__file__).resolve().parents[2]
REAL = ROOT / "evaluation/videos/YTDown.com_YouTube_Media_J8HB1-IQFxc_How-to-fix-Weapons-Hands-Clipping-Into-Walls-in-Unity-URP-SRP_001_1080p.mp4"
VID = ROOT / "evaluation/synthetic/phase6"
RES = ROOT / "evaluation/results/phase6"
FF = ["ffmpeg", "-y", "-loglevel", "error"]

# injected ground truth (output time, seconds) — chosen inside the moving gameplay part (0–18 s)
FREEZE_GT = (10.0, 10.8)
DROP_GT = (4.0, 6.5)


def ff(*args):
    subprocess.run([*FF, *map(str, args)], check=True)


def build_videos() -> list[dict]:
    VID.mkdir(parents=True, exist_ok=True)
    clip = VID / "real_gameplay_20s.mp4"
    cases = [dict(name="real_full_1080p60.mp4", path=REAL, kind="real recording (original)", target=60)]

    def once(path: Path, make):
        if not path.exists():
            make(path)
        return path

    once(clip, lambda p: ff("-i", REAL, "-t", 20, "-c", "copy", "-an", p))
    cases.append(dict(name=clip.name, path=clip, kind="real, first 20 s (gameplay), stream copy", target=60))
    p = once(VID / "real_gameplay_20s.mkv", lambda p: ff("-i", clip, "-c", "copy", p))
    cases.append(dict(name=p.name, path=p, kind="real, MKV container (stream copy)", target=60))
    p = once(VID / "real_gameplay_720p.avi", lambda p: ff("-i", clip, "-vf", "scale=-2:720", "-c:v", "mpeg4",
                                                           "-q:v", 3, p))
    cases.append(dict(name=p.name, path=p, kind="real, AVI container, MPEG-4 Part 2, 720p", target=60))
    p = once(VID / "real_gameplay_30fps.mp4", lambda p: ff("-i", clip, "-vf", "fps=30", "-c:v", "libx264",
                                                            "-crf", 18, p))
    cases.append(dict(name=p.name, path=p, kind="real, resampled to 30 FPS (target 30)", target=30))
    p = once(VID / "real_gameplay_vfr.mp4", lambda p: ff("-i", clip, "-vf", "mpdecimate", "-fps_mode", "vfr",
                                                          "-c:v", "libx264", "-crf", 18, p))
    cases.append(dict(name=p.name, path=p, kind="real, repeated frames removed -> variable frame rate", target=60))
    p = once(VID / "real_editor_static_30s.mp4", lambda p: ff("-ss", 100, "-i", REAL, "-t", 30, "-c:v", "libx264",
                                                               "-crf", 18, "-an", p))
    cases.append(dict(name=p.name, path=p, kind="real, 30 s of the (mostly static) Unity editor", target=60))
    p = VID / "real_gameplay_truncated.mp4"
    if not p.exists():
        data = clip.read_bytes()
        p.write_bytes(data[: len(data) // 2])
    cases.append(dict(name=p.name, path=p, kind="real 20 s file cut to half its bytes (damaged)", target=60))
    p = once(VID / "tiny_2_frames.mp4", lambda p: ff("-i", clip, "-frames:v", 2, "-c:v", "libx264", p))
    cases.append(dict(name=p.name, path=p, kind="real, only 2 frames", target=60))
    p = VID / "gameplay clip ü (copy).mp4"
    if not p.exists():
        shutil.copy2(clip, p)
    cases.append(dict(name=p.name, path=p, kind="real 20 s, file name with spaces / non-ASCII", target=60))
    p = VID / "inject_freeze.mp4"
    if not p.exists():
        render(REAL, p, [Freeze(FREEZE_GT[0], FREEZE_GT[1] - FREEZE_GT[0])], 0.0, 18.0)
    cases.append(dict(name=p.name, path=p, kind=f"real gameplay 0–18 s, 720p, freeze injected {FREEZE_GT}",
                      target=60, gt=("freeze", *FREEZE_GT)))
    p = VID / "inject_drop.mp4"
    if not p.exists():
        render(REAL, p, [Drop(DROP_GT[0], DROP_GT[1] - DROP_GT[0], keep_every=3)], 0.0, 18.0)
    cases.append(dict(name=p.name, path=p, kind=f"real gameplay 0–18 s, 720p, 20 FPS drop injected {DROP_GT}",
                      target=60, gt=("fps_drop", *DROP_GT)))
    return cases


def invalid_inputs() -> list[dict]:
    bad = VID / "invalid"
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "notes.txt").write_text("not a video\n")
    (bad / "clip.mov").write_bytes(b"\x00" * 1000)
    (bad / "text_renamed.mp4").write_text("this is text\n" * 100)
    (bad / "empty.mp4").write_bytes(b"")
    (bad / "a_folder.mp4").mkdir(exist_ok=True)
    return [dict(name="does_not_exist.mp4", path=bad / "does_not_exist.mp4", kind="missing path"),
            dict(name="notes.txt", path=bad / "notes.txt", kind="unsupported extension .txt"),
            dict(name="clip.mov", path=bad / "clip.mov", kind="unsupported extension .mov"),
            dict(name="text_renamed.mp4", path=bad / "text_renamed.mp4", kind="text file renamed .mp4"),
            dict(name="empty.mp4", path=bad / "empty.mp4", kind="0-byte .mp4"),
            dict(name="a_folder.mp4", path=bad / "a_folder.mp4", kind="folder named .mp4")]


def run_cli(case: dict) -> dict:
    out = VID / "cli_out" / Path(case["name"]).stem
    shutil.rmtree(out, ignore_errors=True)
    t0 = time.time()
    cmd = [sys.executable, str(ROOT / "main.py"), "analyze", "--video", str(case["path"]),
           "--target-fps", str(case.get("target", 60)), "--output", str(out), "--quiet"]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    r = {"exit": p.returncode, "seconds": round(time.time() - t0, 1)}
    err = [ln.strip() for ln in p.stderr.splitlines() if "ERROR" in ln]
    if err:
        r["error"] = err[0].replace("ERROR: ", "")
    if p.returncode == 0:
        r["result"] = json.loads((out / "analysis.json").read_text())
        r["report_bytes"] = (out / "FPS_ANALYSIS_REPORT.docx").stat().st_size
    return r


def run_gui(case: dict, base: str) -> dict:
    t0 = time.time()
    with httpx.Client(base_url=base, timeout=600) as c:
        if not case["path"].is_file():
            return {"status": "not uploadable (not a file)"}
        with open(case["path"], "rb") as f:
            r = c.post("/api/analyze", files={"file": (case["name"], f)},
                       data={"target_fps": str(case.get("target", 60))})
        if r.status_code != 202:
            return {"http": r.status_code, "status": "rejected", "error": r.json().get("detail")}
        jid = r.json()["job_id"]
        while True:
            j = c.get(f"/api/jobs/{jid}").json()
            if j["status"] in ("done", "failed"):
                break
            time.sleep(0.5)
        out = {"http": 202, "status": j["status"], "seconds": round(time.time() - t0, 1), "error": j["error"]}
        if j["status"] == "done":
            out["result"] = j["result"]
            rep = c.get(j["report"])
            out["report"] = (rep.status_code, len(rep.content))
            out["charts_ok"] = all(c.get(u).status_code == 200 for u in j["charts"].values())
        return out


STABLE = ("metadata", "frame_intervals", "effective_fps", "frame_times", "counts", "events", "verdict")


def same(a: dict, b: dict) -> bool:
    def norm(r):
        r = {k: r[k] for k in STABLE}
        r["metadata"] = {k: v for k, v in r["metadata"].items() if k not in ("file_name",)}
        return json.dumps(r, sort_keys=True)
    return norm(a) == norm(b)


def gt_check(case: dict, res: dict) -> str:
    if "gt" not in case:
        return ""
    typ, a, b = case["gt"]
    hits = [e for e in res["events"] if e["type"] == typ and e["start_s"] <= b + 0.5 and e["end_s"] >= a - 0.5]
    return (f"FOUND {typ} {hits[0]['start_s']:.2f}–{hits[0]['end_s']:.2f} s (injected {a}–{b} s)" if hits
            else f"MISSED {typ} (injected {a}–{b} s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gui", default="http://127.0.0.1:8765")
    a = ap.parse_args()
    httpx.get(a.gui + "/api/config").raise_for_status()
    RES.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in build_videos() + invalid_inputs():
        print("·", case["name"], flush=True)
        cli = run_cli(case)
        gui = run_gui(case, a.gui)
        row = {"name": case["name"], "kind": case["kind"], "target": case.get("target"), "cli": cli, "gui": gui}
        if cli.get("result") and gui.get("result"):
            row["identical"] = same(cli["result"], gui["result"])
        if cli.get("result"):
            row["gt"] = gt_check(case, cli["result"])
        rows.append(row)
    (RES / "results.json").write_text(json.dumps(rows, indent=1, default=str))
    md = ["# Phase 6 — CLI and GUI on the test set", "",
          "All videos are derived from the ONE real recording (see backend/scripts/phase6_test.py).", "",
          "| Video | Variant | CLI exit / s | GUI | Same result | Measurable | Eff. FPS median / min | "
          "Freeze / drop / stutter | Ground truth / error |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c, g = r["cli"], r["gui"]
        res = c.get("result")
        if res:
            e, n = res["effective_fps"], res["counts"]
            cols = [f"{round(e['measurable_fraction'] * 100)} %", f"{e['median']} / {e['min']}",
                    f"{n['freezes']} / {n['fps_drops']} / {n['stutters']}", r.get("gt") or ""]
        else:
            cols = ["", "", "", c.get("error", "")]
        gui_s = g.get("status", "") + (f" {g['http']}" if g.get("http") not in (None, 202) else "")
        md.append(f"| {r['name']} | {r['kind']} | {c['exit']} / {c['seconds']} | {gui_s} | "
                  f"{'yes' if r.get('identical') else ('—' if 'identical' not in r else 'NO')} | " + " | ".join(cols)
                  + " |")
    (RES / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
