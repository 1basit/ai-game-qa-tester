"""Prototype CLI (`python main.py analyze ...`) and the per-video Word report."""

import importlib.util
import json
import subprocess
import sys

import pytest
from docx import Document

from gameqa.config import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location("gameqa_main", PROJECT_ROOT / "main.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def test_analyze_writes_results_and_report(vids, tmp_path, capsys):
    out = tmp_path / "out"
    code = cli.main(["analyze", "--video", str(vids["vfr"]), "--target-fps", "30", "--output", str(out), "--quiet"])
    assert code == 0
    text = capsys.readouterr().out
    assert "FREEZE" in text and "RESULT  Detected 1 freeze(s)" in text and "FPS_ANALYSIS_REPORT.docx" in text
    data = json.loads((out / "analysis.json").read_text())
    assert data["settings"]["target_fps"] == 30 and data["counts"]["freezes"] == 1
    doc = Document(out / "FPS_ANALYSIS_REPORT.docx")
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert headings[:3] == ["1. Summary", "2. Video", "3. Analysis settings"] and "8. Limitations" in headings
    events = next(t for t in doc.tables if t.rows[0].cells[0].text == "Type")
    assert [r.cells[0].text for r in events.rows[1:]] == ["Freeze"]
    assert len(doc.inline_shapes) == 3


def test_thresholds_from_command_line(vids, tmp_path):
    out = tmp_path / "o"
    assert cli.main(["analyze", "--video", str(vids["vfr"]), "--freeze-ms", "800", "--target-fps", "30",
                     "--output", str(out), "--no-report", "--quiet"]) == 0
    data = json.loads((out / "analysis.json").read_text())
    assert data["settings"]["freeze_ms"] == 800 and data["counts"]["freezes"] == 0  # the 533 ms gap is below 800 ms
    assert not (out / "FPS_ANALYSIS_REPORT.docx").exists()


@pytest.mark.parametrize("args, message", [
    (["--video", "/no/such/file.mp4"], "does not exist"),
    (["--video", "{mov}"], "Accepted formats"),
    (["--video", "{text}"], "not a video file"),
    (["--video", "{cfr}", "--drop-ratio", "1.5"], "between 0 and 1"),
    (["--video", "{cfr}", "--target-fps", "-5"], "must be positive"),
])
def test_invalid_input_exit_code_2(vids, capsys, args, message):
    args = [a.format(mov=vids["mov"], text=vids["text_as_mp4"], cfr=vids["cfr30"]) for a in args]
    assert cli.main(["analyze", *args, "--quiet"]) == 2
    assert message in capsys.readouterr().err


def test_runs_as_a_script_from_the_project_folder(vids, tmp_path):
    """Exactly what the user types: `python main.py analyze --video ...`."""
    r = subprocess.run([sys.executable, "main.py", "analyze", "--video", str(vids["cfr30"]), "--target-fps", "30",
                        "--output", str(tmp_path / "s")], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "No freezes, drops or stutters detected" in r.stdout and (tmp_path / "s" / "FPS_ANALYSIS_REPORT.docx").exists()
