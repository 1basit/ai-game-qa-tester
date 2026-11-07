"""Report export endpoints (FR-6, UC-RPT-01): JSON and PDF, filters optional."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from gameqa.api.models import Project
from gameqa.api.routes import DB, CurrentUser, _get_job, list_detections
from gameqa.api.security import audit
from gameqa.reports import build_json, build_pdf

router = APIRouter(prefix="/api")


def _meta(db, job) -> dict:
    project = db.get(Project, job.project_id)
    info = job.video.info or {}
    return {"project": project.name if project else "", "game_build": project.game_build if project else "",
            "video": job.video.original_filename, "duration_s": info.get("duration_s"), "job_id": job.id,
            "status": job.status.value, "finished_at": job.finished_at, "warnings": job.warnings or [],
            "options": job.options}


@router.get("/jobs/{job_id}/report.json")
def report_json(job_id: str, request: Request, db: DB, user: CurrentUser,
                category: str | None = None, severity: str | None = None):
    job = _get_job(db, user, job_id)
    dets = list_detections(job_id, request, db, user, category, severity, None)
    audit(db, user, "export_json", "job", job.id)
    data = build_json(_meta(db, job), dets)
    return JSONResponse(jsonable_encoder(data), headers={"Content-Disposition": f'attachment; filename="bug-report-{job.id}.json"'})


@router.get("/jobs/{job_id}/report.pdf")
def report_pdf(job_id: str, request: Request, db: DB, user: CurrentUser,
               category: str | None = None, severity: str | None = None):
    job = _get_job(db, user, job_id)
    dets = list_detections(job_id, request, db, user, category, severity, None)
    tmp = Path(tempfile.mkstemp(suffix=".pdf")[1])
    build_pdf(tmp, _meta(db, job), dets, request.app.state.settings.paths.evidence_dir)
    audit(db, user, "export_pdf", "job", job.id)
    return FileResponse(tmp, media_type="application/pdf", filename=f"bug-report-{job.id}.pdf",
                        background=BackgroundTask(tmp.unlink, missing_ok=True))
