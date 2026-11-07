"""REST API (FR-1, FR-5 retrieval, FR-6 data, SRS 5.4)."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from collections import Counter
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gameqa.api.models import (AuditLog, DetectionRow, Job, JobStatus, Project, ProjectMember, Role, User, Video)
from gameqa.api.security import (audit, check_project_access, create_token, current_user, get_db, hash_password,
                                 require_role, sign_file, verify_file_signature, verify_password)
from gameqa.core.errors import GameQAError, UnsupportedFormatError
from gameqa.core.schemas import DefectCategory, Severity
from gameqa.video import probe_video, validate_file, validate_filename

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]


# ======================================================================= schemas
# Plain format check: the email-validator package rejects reserved/internal domains
# (e.g. *.test, *.local) that studios use for internal accounts.
EmailStr = Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)]


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: Role
    is_active: bool


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""
    role: Role = Role.tester


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = None


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    game_build: str = ""


class MemberIn(BaseModel):
    email: EmailStr


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role, is_active=u.is_active)


def _job_out(j: Job) -> dict:
    v = j.video
    return {
        "id": j.id, "project_id": j.project_id, "video_id": j.video_id,
        "video_filename": v.original_filename if v else None,
        "video_duration_s": (v.info or {}).get("duration_s") if v else None,
        "status": j.status.value, "progress": round(j.progress, 3), "message": j.message,
        "options": j.options, "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
        "attempts": j.attempts, "error": j.error, "warnings": j.warnings,
        "detection_count": len(j.detections),
    }


def _check_password(request: Request, pw: str) -> None:
    n = request.app.state.settings.api.min_password_length
    if len(pw) < n:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"password must be at least {n} characters")


# ======================================================================= auth & users
@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: DB):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        audit(db, None, "login_failed", "user", "", email=body.email.lower())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    from datetime import datetime, timezone

    user.last_activity = datetime.now(timezone.utc)
    db.commit()
    audit(db, user, "login", "user", user.id)
    cfg = request.app.state.settings.api
    return {"access_token": create_token(user, cfg.secret_key, cfg.token_lifetime_days), "token_type": "bearer",
            "user": _user_out(user)}


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser):
    return _user_out(user)


@router.get("/users", response_model=list[UserOut])
def list_users(db: DB, _: User = Depends(require_role(Role.admin))):
    return [_user_out(u) for u in db.scalars(select(User).order_by(User.email))]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, db: DB, admin: User = Depends(require_role(Role.admin))):
    _check_password(request, body.password)
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    u = User(email=body.email.lower(), full_name=body.full_name, password_hash=hash_password(body.password),
             role=body.role)
    db.add(u)
    db.commit()
    audit(db, admin, "create_user", "user", u.id, email=u.email, role=u.role.value)
    return _user_out(u)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, request: Request, db: DB,
                admin: User = Depends(require_role(Role.admin))):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "user not found")
    if body.role is not None:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.password:
        _check_password(request, body.password)
        u.password_hash = hash_password(body.password)
    db.commit()
    audit(db, admin, "update_user", "user", u.id, **body.model_dump(exclude={"password"}, exclude_none=True))
    return _user_out(u)


# ======================================================================= projects
def _project_out(db: Session, p: Project) -> dict:
    jobs = db.scalars(select(Job).where(Job.project_id == p.id)).all()
    open_det = db.scalar(select(func.count(DetectionRow.id)).join(Job).where(Job.project_id == p.id)) or 0
    sev = Counter(db.scalars(select(DetectionRow.severity).join(Job).where(Job.project_id == p.id)).all())
    last = max((j.finished_at for j in jobs if j.finished_at), default=None)
    return {"id": p.id, "name": p.name, "game_build": p.game_build, "created_at": p.created_at,
            "videos": db.scalar(select(func.count(Video.id)).where(Video.project_id == p.id)) or 0,
            "jobs": len(jobs), "detections": open_det, "by_severity": dict(sev), "last_analysis": last}


@router.get("/projects")
def list_projects(db: DB, user: CurrentUser):
    q = select(Project).order_by(Project.created_at.desc())
    if user.role is not Role.admin:
        q = q.join(ProjectMember).where(ProjectMember.user_id == user.id)
    return [_project_out(db, p) for p in db.scalars(q)]


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, db: DB, user: User = Depends(require_role(Role.qa_lead))):
    p = Project(name=body.name, game_build=body.game_build, created_by=user.id)
    db.add(p)
    db.flush()
    db.add(ProjectMember(project_id=p.id, user_id=user.id))
    db.commit()
    audit(db, user, "create_project", "project", p.id, name=p.name)
    return _project_out(db, p)


@router.get("/projects/{project_id}")
def get_project(project_id: str, db: DB, user: CurrentUser):
    return _project_out(db, check_project_access(db, user, project_id))


@router.get("/projects/{project_id}/members", response_model=list[UserOut])
def list_members(project_id: str, db: DB, user: CurrentUser):
    check_project_access(db, user, project_id)
    users = db.scalars(select(User).join(ProjectMember).where(ProjectMember.project_id == project_id))
    return [_user_out(u) for u in users]


@router.post("/projects/{project_id}/members", status_code=201)
def add_member(project_id: str, body: MemberIn, db: DB, user: User = Depends(require_role(Role.qa_lead))):
    check_project_access(db, user, project_id)
    target = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if target is None:
        raise HTTPException(404, "user not found")
    if not db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                 ProjectMember.user_id == target.id)):
        db.add(ProjectMember(project_id=project_id, user_id=target.id))
        db.commit()
    audit(db, user, "add_member", "project", project_id, member=target.email)
    return {"ok": True}


# ======================================================================= upload & jobs (FR-1)
@router.post("/projects/{project_id}/videos", status_code=201)
async def upload_video(project_id: str, request: Request, db: DB, user: CurrentUser,
                       file: UploadFile = File(...),
                       detectors: str = Form(""), analysis_fps: float | None = Form(None),
                       target_fps: float | None = Form(None)):
    settings = request.app.state.settings
    check_project_access(db, user, project_id)
    try:  # cheapest check first: no job, nothing stored for a wrong format (FR-1)
        ext = validate_filename(file.filename or "", settings.video.allowed_extensions)
    except UnsupportedFormatError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    waiting = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.queued)) or 0
    if waiting >= settings.api.max_queued_jobs:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"the analysis queue is full ({waiting} jobs waiting); try again later")
    names = [d.strip() for d in detectors.split(",") if d.strip()]
    unknown = set(names) - set(settings.detectors)
    if unknown:
        raise HTTPException(422, f"unknown detectors: {sorted(unknown)}")
    if analysis_fps is not None and not 1 <= analysis_fps <= 60:
        raise HTTPException(422, "analysis_fps must be 1-60")

    uploads = settings.paths.uploads_dir
    uploads.mkdir(parents=True, exist_ok=True)
    limit = settings.video.max_upload_mb * 1024 * 1024
    vid = uuid.uuid4().hex
    final = uploads / f"{vid}{ext}"
    size = 0
    with tempfile.NamedTemporaryFile(dir=uploads, suffix=ext, delete=False) as tmp:  # stream, never in memory
        tmp_path = Path(tmp.name)
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                                    f"file exceeds the {settings.video.max_upload_mb} MB limit")
            tmp.write(chunk)
    try:
        tmp_path.rename(final)
        validate_file(final, settings.video.allowed_extensions, settings.video.max_upload_mb)
        info = probe_video(final).info
    except GameQAError as exc:
        final.unlink(missing_ok=True)
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    video = Video(id=vid, project_id=project_id, original_filename=Path(file.filename or final.name).name,
                  stored_path=final.name, size_bytes=size, info=info.model_dump(mode="json"), uploaded_by=user.id)
    options = {"detectors": names or settings.enabled_detectors(), "analysis_fps": analysis_fps,
               "target_fps": target_fps}
    job = Job(project_id=project_id, video_id=vid, options=options, created_by=user.id, message="queued")
    db.add_all([video, job])
    db.commit()
    db.refresh(job)
    audit(db, user, "upload", "job", job.id, filename=video.original_filename, size=size)
    return _job_out(job)


def _get_job(db: Session, user: User, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    check_project_access(db, user, job.project_id)
    return job


@router.get("/jobs")
def list_jobs(db: DB, user: CurrentUser, project_id: str | None = None, limit: int = Query(50, le=500)):
    q = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if project_id:
        check_project_access(db, user, project_id)
        q = q.where(Job.project_id == project_id)
    elif user.role is not Role.admin:
        q = q.join(ProjectMember, ProjectMember.project_id == Job.project_id).where(ProjectMember.user_id == user.id)
    return [_job_out(j) for j in db.scalars(q)]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: DB, user: CurrentUser):
    return _job_out(_get_job(db, user, job_id))


@router.post("/jobs/{job_id}/rerun", status_code=201)
def rerun_job(job_id: str, request: Request, db: DB, user: CurrentUser):
    """NFR 5.1: a failed (or finished) job can be re-run without uploading the video again."""
    old = _get_job(db, user, job_id)
    if old.status in (JobStatus.queued, JobStatus.processing):
        raise HTTPException(409, "job is still queued or running")
    waiting = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.queued)) or 0
    if waiting >= request.app.state.settings.api.max_queued_jobs:
        raise HTTPException(429, "the analysis queue is full")
    job = Job(project_id=old.project_id, video_id=old.video_id, options=old.options, created_by=user.id,
              message="queued (re-run)")
    db.add(job)
    db.commit()
    db.refresh(job)
    audit(db, user, "rerun", "job", job.id, previous=old.id)
    return _job_out(job)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, request: Request, db: DB, user: CurrentUser):
    """SRS 5.4: deleting a job removes its records, screenshots, clips and — when no other
    job uses it — the uploaded video."""
    job = _get_job(db, user, job_id)
    if job.status is JobStatus.processing:
        raise HTTPException(409, "job is running; wait until it finishes")
    settings = request.app.state.settings
    shutil.rmtree(settings.paths.evidence_dir / job.id, ignore_errors=True)
    video = job.video
    others = db.scalar(select(func.count(Job.id)).where(Job.video_id == job.video_id, Job.id != job.id)) or 0
    db.delete(job)
    removed_video = False
    if others == 0 and video is not None:
        (settings.paths.uploads_dir / video.stored_path).unlink(missing_ok=True)
        db.delete(video)
        removed_video = True
    db.commit()
    audit(db, user, "delete", "job", job_id, removed_video=removed_video)
    return {"ok": True, "removed_video": removed_video}


# ======================================================================= detections (FR-6 data)
def _media(request: Request, user: User, rel: str | None) -> str | None:
    if not rel:
        return None
    return f"/api/files/{rel}?{sign_file(request.app.state.settings.api.secret_key, rel, user.id)}"


def _det_out(request: Request, user: User, row: DetectionRow) -> dict:
    d = dict(row.data)
    ev = d.get("evidence") or {}
    d["media"] = {"screenshot": _media(request, user, ev.get("screenshot_path")),
                  "screenshot_marked": _media(request, user, (d.get("metrics") or {}).get("screenshot_marked")),
                  "clip": _media(request, user, ev.get("clip_path"))}
    return d


def _split(v: str | None) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()] if v else []


@router.get("/jobs/{job_id}/detections")
def list_detections(job_id: str, request: Request, db: DB, user: CurrentUser,
                    category: str | None = None, severity: str | None = None, subtype: str | None = None):
    """Filter by category and/or severity, individually or combined; comma = OR within a field."""
    job = _get_job(db, user, job_id)
    q = select(DetectionRow).where(DetectionRow.job_id == job.id).order_by(DetectionRow.start_time_s)
    cats, sevs, subs = _split(category), _split(severity), _split(subtype)
    try:
        [DefectCategory(c) for c in cats]
        [Severity(s) for s in sevs]
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if cats:
        q = q.where(DetectionRow.category.in_(cats))
    if sevs:
        q = q.where(DetectionRow.severity.in_(sevs))
    if subs:
        q = q.where(DetectionRow.subtype.in_(subs))
    rows = db.scalars(q).all()
    audit(db, user, "view", "job", job.id, filters={"category": cats, "severity": sevs, "subtype": subs})
    return [_det_out(request, user, r) for r in rows]


@router.get("/detections/{detection_id}")
def get_detection(detection_id: str, request: Request, db: DB, user: CurrentUser):
    row = db.get(DetectionRow, detection_id)
    if row is None:
        raise HTTPException(404, "detection not found")
    _get_job(db, user, row.job_id)
    return _det_out(request, user, row)


@router.get("/files/{rel_path:path}")
def serve_file(rel_path: str, request: Request, db: DB, exp: int, uid: str, sig: str):
    """Evidence files, outside the web root, only via short-lived signed URLs issued to a
    project member (SRS 5.4). Supports HTTP Range for video seeking."""
    settings = request.app.state.settings
    if not verify_file_signature(settings.api.secret_key, rel_path, uid, exp, sig):
        raise HTTPException(403, "invalid or expired link")
    user = db.get(User, uid)
    if user is None or not user.is_active:
        raise HTTPException(403, "invalid link")
    job_id = rel_path.split("/", 1)[0]
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "not found")
    check_project_access(db, user, job.project_id)
    root = settings.paths.evidence_dir.resolve()
    path = (root / rel_path).resolve()
    if root not in path.parents or not path.is_file():  # no path traversal
        raise HTTPException(404, "not found")
    return FileResponse(path)


# ======================================================================= statistics & audit
@router.get("/stats")
def stats(db: DB, user: CurrentUser, project_id: str | None = None):
    """Per-project statistics for members; cross-project statistics for QA leads / admins."""
    q = select(DetectionRow.category, DetectionRow.severity).join(Job)
    if project_id:
        check_project_access(db, user, project_id)
        q = q.where(Job.project_id == project_id)
    elif user.role not in (Role.qa_lead, Role.admin):
        raise HTTPException(403, "cross-project statistics are available to QA leads")
    rows = db.execute(q).all()
    return {"total": len(rows), "by_category": dict(Counter(r[0] for r in rows)),
            "by_severity": dict(Counter(r[1] for r in rows))}


@router.get("/audit")
def audit_log(db: DB, _: User = Depends(require_role(Role.admin)), limit: int = Query(200, le=2000)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.ts.desc()).limit(limit))
    return [{"ts": r.ts, "user": r.user_email, "action": r.action, "target_type": r.target_type,
             "target_id": r.target_id, "details": r.details} for r in rows]


@router.get("/health")
def health():
    return {"ok": True}
