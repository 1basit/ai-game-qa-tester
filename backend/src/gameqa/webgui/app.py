"""Local web GUI for the FPS analysis prototype (`python main.py --gui`).

* No login, no accounts, no database: it is meant to run on the user's own computer and
  listens on 127.0.0.1 only by default.
* Uses exactly the same engine as the CLI (`gameqa.fps_service.analyze_video` +
  `save_results`), so results, charts and the Word report are identical.
* One analysis at a time (a single background worker thread); jobs live in memory and
  their files in `outputs/<date-time>_<video>/` (the uploaded video is kept in `input/`).
"""

from __future__ import annotations

import shutil
import threading
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from gameqa.config import FpsServiceConfig, get_settings
from gameqa.core.errors import GameQAError, UnsupportedFormatError
from gameqa.fps_service import analyze_video, output_folder, save_results
from gameqa.video import validate_filename

STATIC = Path(__file__).parent / "static"
CHARTS = ("effective_fps", "frame_intervals", "frame_changes")


@dataclass
class Job:
    id: str
    video_name: str
    folder: Path
    status: str = "queued"  # queued | analysing | done | failed
    progress: float = 0.0
    message: str = "waiting"
    error: str | None = None
    result: dict | None = None
    files: dict = field(default_factory=dict)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI Game QA Tester — FPS analysis (local)", docs_url=None, redoc_url=None)
    jobs: dict[str, Job] = {}
    lock = threading.Lock()
    worker = ThreadPoolExecutor(max_workers=1)  # one analysis at a time

    def run(job: Job, video: Path, cfg: FpsServiceConfig) -> None:
        def progress(f: float, msg: str) -> None:
            job.progress, job.message = 0.95 * f, msg

        job.status = "analysing"
        try:
            result, timeline = analyze_video(video, cfg, progress=progress)
            job.message = "writing charts and Word report"
            job.files = save_results(result, timeline, job.folder)
            job.result = result.model_dump(mode="json")
            job.status, job.progress, job.message = "done", 1.0, "done"
        except GameQAError as exc:  # not a usable video: report it and remove the job folder
            job.status, job.error, job.message = "failed", str(exc), "failed"
            shutil.rmtree(job.folder, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001 - shown to the user instead of a silent hang
            job.status, job.error, job.message = "failed", f"unexpected error: {type(exc).__name__}: {exc}", "failed"

    def get(job_id: str) -> Job:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "analysis not found (the GUI was restarted?)")
        return job

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/config")
    def config():
        c = settings.fps_service
        return {"target_fps": c.target_fps, "drop_ratio": c.drop_ratio, "freeze_ms": c.freeze_ms,
                "stutter_min_missed": c.stutter_min_missed, "max_upload_mb": settings.video.max_upload_mb,
                "extensions": settings.video.allowed_extensions}

    @app.post("/api/analyze", status_code=202)
    async def analyze(file: UploadFile = File(...), target_fps: float = Form(60.0), drop_ratio: float = Form(0.75),
                      freeze_ms: float = Form(250.0), stutter_min_missed: int = Form(3)):
        try:
            validate_filename(file.filename or "", settings.video.allowed_extensions)
            cfg = FpsServiceConfig(**{**settings.fps_service.model_dump(), "target_fps": target_fps,
                                      "drop_ratio": drop_ratio, "freeze_ms": freeze_ms,
                                      "stutter_min_missed": stutter_min_missed})
        except UnsupportedFormatError as exc:
            raise HTTPException(415, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, f"invalid setting: {exc}") from None
        name = Path(file.filename or "video.mp4").name
        folder = output_folder(name, settings.fps_service)
        dest = folder / "input" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        limit, size = settings.video.max_upload_mb * 1024 * 1024, 0
        with open(dest, "wb") as out:  # stream to disk, never the whole file in memory
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    out.close()
                    shutil.rmtree(folder, ignore_errors=True)
                    raise HTTPException(413, f"file is larger than {settings.video.max_upload_mb} MB")
                out.write(chunk)
        job = Job(id=uuid.uuid4().hex[:12], video_name=name, folder=folder)
        with lock:
            jobs[job.id] = job
        worker.submit(run, job, dest, cfg)
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}")
    def status(job_id: str):
        j = get(job_id)
        return {"id": j.id, "video_name": j.video_name, "status": j.status, "progress": round(j.progress, 3),
                "message": j.message, "error": j.error, "result": j.result,
                "charts": {c: f"/api/jobs/{j.id}/charts/{c}.png" for c in CHARTS} if j.status == "done" else {},
                "report": f"/api/jobs/{j.id}/report" if "report_docx" in j.files else None,
                "folder": str(j.folder)}

    @app.get("/api/jobs/{job_id}/charts/{name}.png")
    def chart(job_id: str, name: str):
        j = get(job_id)
        if name not in CHARTS or f"chart_{name}" not in j.files:
            raise HTTPException(404, "chart not found")
        return FileResponse(j.files[f"chart_{name}"], media_type="image/png")

    @app.get("/api/jobs/{job_id}/report")
    def report(job_id: str):
        j = get(job_id)
        if "report_docx" not in j.files:
            raise HTTPException(404, "report not ready")
        stem = Path(j.video_name).stem
        return FileResponse(j.files["report_docx"], filename=f"FPS_ANALYSIS_REPORT_{stem}.docx",
                            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    @app.get("/api/jobs/{job_id}/analysis.json")
    def analysis_json(job_id: str):
        j = get(job_id)
        if "analysis_json" not in j.files:
            raise HTTPException(404, "not ready")
        return FileResponse(j.files["analysis_json"], filename=f"analysis_{Path(j.video_name).stem}.json")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.state.jobs = jobs
    return app


def _port_free(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host if host != "localhost" else "127.0.0.1", port))
        except OSError:
            return False
    return True


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> int:
    import uvicorn

    if not _port_free(host, port):
        print(f"  ERROR: port {port} is already in use (is the GUI already running? then just open "
              f"http://127.0.0.1:{port}). Or start on another port: python main.py --gui --port {port + 1}")
        return 2

    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '127.0.0.1') else host}:{port}"
    print(f"\nAI Game QA Tester — local FPS analysis GUI\n  open {url} in your browser (Ctrl+C to stop)\n")
    if host not in ("127.0.0.1", "localhost"):
        print("  warning: the GUI has no login; listening beyond this computer exposes it to your network.\n")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0
