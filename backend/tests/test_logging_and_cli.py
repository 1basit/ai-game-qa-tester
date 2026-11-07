import json
import shutil

import pytest

from gameqa.cli import main
from gameqa.core import DefectCategory, Detection, DetectionSet
from gameqa.doctor import check_opencv_decode
from gameqa.logging_setup import configure_logging, get_logger, job_context


def test_json_log_file_carries_job_id(tmp_path):
    log_file = tmp_path / "gameqa.log"
    configure_logging("INFO", json_format=False, log_file=log_file)
    log = get_logger("pipeline")
    with job_context("job-42"):
        log.info("frame batch done", extra={"frames": 120})
    log.info("outside job")
    lines = [json.loads(l) for l in log_file.read_text().splitlines()]
    assert lines[0]["job_id"] == "job-42" and lines[0]["extra"] == {"frames": 120}
    assert "job_id" not in lines[1]
    configure_logging("INFO")  # detach the file handler


def test_cli_config_json(capsys):
    assert main(["config", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["video"]["analysis_fps"] == 12


def test_cli_evaluate_end_to_end(tmp_path, capsys):
    gt = {
        "video_id": "clip1", "duration_s": 60, "reviewed_categories": ["fps_drop"],
        "events": [{"category": "fps_drop", "start_s": 10, "end_s": 12}],
    }
    (tmp_path / "gt").mkdir()
    (tmp_path / "gt" / "clip1.json").write_text(json.dumps(gt))
    pred = DetectionSet(
        video_id="clip1",
        detections=[
            Detection(category=DefectCategory.FPS_DROP, subtype="fps_drop", detector="x",
                      detector_version="0", start_time_s=10.2, end_time_s=11.8, peak_time_s=11,
                      start_frame=612, end_frame=708, peak_frame=660, confidence=0.7)
        ],
    )
    (tmp_path / "pred.json").write_text(pred.model_dump_json())
    rc = main(["evaluate", "-p", str(tmp_path / "pred.json"), "-g", str(tmp_path / "gt"),
               "-o", str(tmp_path / "out")])
    assert rc == 0
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["fps_drop"]["tp"] == 1 and summary["fps_drop"]["precision"] == 1.0
    assert "| fps_drop | 1 | 1 | 0 | 0 |" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_opencv_can_decode_h264():
    r = check_opencv_decode()
    assert r.status == "ok", r.detail
