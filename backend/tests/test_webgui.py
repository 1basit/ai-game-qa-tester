"""Local web GUI (`python main.py --gui`): upload -> analysis -> results / charts / report."""

import time

import pytest
from fastapi.testclient import TestClient

from gameqa.config import get_settings
from gameqa.webgui.app import create_app


@pytest.fixture
def client(tmp_path):
    s = get_settings()
    saved = s.fps_service
    s.fps_service = saved.model_copy(update={"output_dir": tmp_path / "outputs"})
    try:
        yield TestClient(create_app()), tmp_path / "outputs"
    finally:
        s.fps_service = saved


def upload(c, path, name=None, **form):
    with open(path, "rb") as f:
        return c.post("/api/analyze", files={"file": (name or path.name, f)}, data={k: str(v) for k, v in form.items()})


def wait(c, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.2)
    raise AssertionError("analysis did not finish")


def test_page_and_config_without_login(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200 and "Analyze Video" in r.text and "no login" in r.text.lower()
    assert c.get("/static/app.js").status_code == 200
    cfg = c.get("/api/config").json()
    assert cfg["target_fps"] == 60 and cfg["extensions"] == [".mp4", ".avi", ".mkv"]


def test_full_analysis_flow(client, vids):
    c, out = client
    r = upload(c, vids["vfr"], target_fps=30, drop_ratio=0.75, freeze_ms=250, stutter_min_missed=3)
    assert r.status_code == 202
    j = wait(c, r.json()["job_id"])
    assert j["status"] == "done" and j["progress"] == 1.0
    res = j["result"]
    assert res["settings"]["target_fps"] == 30 and [e["type"] for e in res["events"]] == ["freeze"]
    for url in j["charts"].values():
        png = c.get(url)
        assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    rep = c.get(j["report"])
    assert rep.status_code == 200 and rep.content[:2] == b"PK"  # .docx is a zip
    assert "FPS_ANALYSIS_REPORT_vfr.docx" in rep.headers["content-disposition"]
    assert c.get(f"/api/jobs/{j['id']}/analysis.json").json()["counts"]["freezes"] == 1
    folder = next(out.iterdir())
    assert (folder / "input" / "vfr.mp4").exists() and (folder / "FPS_ANALYSIS_REPORT.docx").exists()


def test_same_engine_as_cli(client, vids, tmp_path):
    """GUI and CLI must give identical results for the same video and settings."""
    import importlib.util
    import json

    from gameqa.config import PROJECT_ROOT

    spec = importlib.util.spec_from_file_location("gameqa_main", PROJECT_ROOT / "main.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.main(["analyze", "--video", str(vids["vfr"]), "--target-fps", "30", "--output", str(tmp_path / "cli"),
                     "--no-report", "--quiet"]) == 0
    cli_res = json.loads((tmp_path / "cli" / "analysis.json").read_text())
    c, _ = client
    gui_res = wait(c, upload(c, vids["vfr"], target_fps=30).json()["job_id"])["result"]
    for key in ("effective_fps", "frame_times", "counts", "frame_intervals"):
        assert gui_res[key] == cli_res[key], key
    assert [e["start_s"] for e in gui_res["events"]] == [e["start_s"] for e in cli_res["events"]]


def test_unsupported_format_rejected_before_upload_is_stored(client, vids):
    c, out = client
    r = upload(c, vids["mov"])
    assert r.status_code == 415 and "Accepted formats" in r.json()["detail"]
    assert not out.exists() or not any(out.iterdir())


def test_fake_video_fails_with_message_and_no_leftovers(client, vids):
    c, out = client
    j = wait(c, upload(c, vids["text_as_mp4"]).json()["job_id"])
    assert j["status"] == "failed" and "not a video file" in j["error"]
    assert not any(out.iterdir())


def test_invalid_setting_and_unknown_job(client, vids):
    c, _ = client
    assert upload(c, vids["cfr30"], drop_ratio=1.5).status_code == 422
    assert c.get("/api/jobs/doesnotexist").status_code == 404
    assert c.get("/api/jobs/doesnotexist/report").status_code == 404


def test_run_opens_browser_on_localhost(monkeypatch):
    """`python main.py --gui` serves on 127.0.0.1 and opens the default browser at that URL."""
    import uvicorn

    from gameqa.webgui import app as gui

    calls = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port, log_level: calls.update(host=host, port=port))
    monkeypatch.setattr(gui, "_port_free", lambda h, p: True)

    class NowTimer:  # run the delayed browser-open immediately
        def __init__(self, delay, fn):
            self.fn = fn

        def start(self):
            self.fn()

    monkeypatch.setattr(gui.threading, "Timer", NowTimer)
    monkeypatch.setattr(gui.webbrowser, "open", lambda url: calls.update(url=url))
    assert gui.run(port=8799) == 0
    assert calls == {"host": "127.0.0.1", "port": 8799, "url": "http://127.0.0.1:8799"}

    calls.clear()
    assert gui.run(port=8799, open_browser=False) == 0
    assert "url" not in calls


def test_run_reports_port_in_use(capsys):
    import socket

    from gameqa.webgui import app as gui

    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert gui.run(port=port, open_browser=False) == 2
    out = capsys.readouterr().out
    assert "already in use" in out and f"--port {port + 1}" in out
