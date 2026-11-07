"""Backend: FR-1 upload/queue, worker, FR-5 persistence, FR-6 filters/exports, SRS 5.4 security.

Runs against a file-based SQLite database (same SQLAlchemy models as PostgreSQL)."""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from gameqa.api.app import create_app
from gameqa.api.models import AuditLog, Job, JobStatus, Role, User
from gameqa.api.security import hash_password
from gameqa.config import load_settings
from gameqa.worker import Worker

SECRET = "test-secret-" + "x" * 40
PW = "correct-horse-1"


@pytest.fixture
def env(tmp_path):
    """SQLite by default; set GAMEQA_TEST_DATABASE_URL to run the same tests on PostgreSQL."""
    import os

    from gameqa.api.models import Base, make_engine

    db_url = os.environ.get("GAMEQA_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    if not db_url.startswith("sqlite"):
        eng = make_engine(db_url)
        Base.metadata.drop_all(eng)  # fresh schema per test
        eng.dispose()
    s = load_settings()
    s.paths = s.paths.model_copy(update={"uploads_dir": tmp_path / "uploads", "evidence_dir": tmp_path / "evidence",
                                         "data_dir": tmp_path, "logs_dir": tmp_path / "logs"})
    s.database = s.database.model_copy(update={"url": db_url})
    s.api = s.api.model_copy(update={"secret_key": SECRET, "max_queued_jobs": 2})
    s.logging = s.logging.model_copy(update={"to_file": False})
    app = create_app(s)
    client = TestClient(app)
    Session = app.state.sessionmaker
    with Session() as db:
        for email, role in [("admin@qa.test", Role.admin), ("lead@qa.test", Role.qa_lead),
                            ("tester@qa.test", Role.tester), ("dev@qa.test", Role.developer)]:
            db.add(User(email=email, password_hash=hash_password(PW), role=role))
        db.commit()
    return {"client": client, "app": app, "settings": s, "Session": Session, "worker": Worker(s, Session)}


def login(c, email):
    r = c.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_project(c, lead_h, members=("tester@qa.test",)):
    p = c.post("/api/projects", json={"name": "Build 1.2", "game_build": "1.2.0"}, headers=lead_h).json()
    for m in members:
        assert c.post(f"/api/projects/{p['id']}/members", json={"email": m}, headers=lead_h).status_code == 201
    return p


def upload(c, h, pid, path, name=None, **form):
    with open(path, "rb") as f:
        return c.post(f"/api/projects/{pid}/videos", headers=h, files={"file": (name or path.name, f)},
                      data={k: str(v) for k, v in form.items()})


# ---------------------------------------------------------------- authentication (SRS 5.4)
def test_login_and_password_storage(env):
    c = env["client"]
    assert c.post("/api/auth/login", json={"email": "tester@qa.test", "password": "wrong-pass"}).status_code == 401
    h = login(c, "tester@qa.test")
    assert c.get("/api/auth/me", headers=h).json()["role"] == "tester"
    with env["Session"]() as db:
        u = db.query(User).filter_by(email="tester@qa.test").one()
        assert u.password_hash.startswith("$2") and PW not in u.password_hash  # bcrypt, salted


def test_token_required_and_tampering_rejected(env):
    c = env["client"]
    assert c.get("/api/projects").status_code == 401
    h = login(c, "tester@qa.test")
    bad = {"Authorization": h["Authorization"][:-3] + "abc"}
    assert c.get("/api/projects", headers=bad).status_code == 401


def test_session_expires_after_12h_inactivity(env):
    c = env["client"]
    h = login(c, "tester@qa.test")
    assert c.get("/api/auth/me", headers=h).status_code == 200
    with env["Session"]() as db:
        u = db.query(User).filter_by(email="tester@qa.test").one()
        u.last_activity = datetime.now(timezone.utc) - timedelta(hours=12, minutes=1)
        db.commit()
    r = c.get("/api/auth/me", headers=h)
    assert r.status_code == 401 and "inactivity" in r.json()["detail"]


def test_password_minimum_length(env):
    c = env["client"]
    admin = login(c, "admin@qa.test")
    r = c.post("/api/users", headers=admin, json={"email": "new@qa.test", "password": "short7!", "role": "tester"})
    assert r.status_code == 422
    r = c.post("/api/users", headers=admin, json={"email": "new@qa.test", "password": "long-enough", "role": "tester"})
    assert r.status_code == 201


# ---------------------------------------------------------------- roles & isolation
def test_role_permissions(env):
    c = env["client"]
    tester, lead = login(c, "tester@qa.test"), login(c, "lead@qa.test")
    assert c.post("/api/users", headers=tester, json={"email": "x@qa.test", "password": PW}).status_code == 403
    assert c.post("/api/projects", headers=tester, json={"name": "nope"}).status_code == 403
    assert c.post("/api/projects", headers=lead, json={"name": "ok"}).status_code == 201
    assert c.get("/api/audit", headers=lead).status_code == 403
    assert c.get("/api/stats", headers=tester).status_code == 403   # cross-project: QA lead only
    assert c.get("/api/stats", headers=lead).status_code == 200


def test_project_isolation(env, vids):
    c = env["client"]
    lead, tester, dev = login(c, "lead@qa.test"), login(c, "tester@qa.test"), login(c, "dev@qa.test")
    p = make_project(c, lead)                          # dev is NOT a member
    job = upload(c, tester, p["id"], vids["cfr30"]).json()
    assert c.get(f"/api/projects/{p['id']}", headers=dev).status_code == 404
    assert c.get(f"/api/jobs/{job['id']}", headers=dev).status_code == 404
    assert c.get(f"/api/jobs/{job['id']}/detections", headers=dev).status_code == 404
    assert c.get(f"/api/jobs/{job['id']}/report.json", headers=dev).status_code == 404
    assert [x["id"] for x in c.get("/api/projects", headers=dev).json()] == []
    assert len(c.get("/api/projects", headers=tester).json()) == 1


# ---------------------------------------------------------------- upload & queue (FR-1)
def test_upload_validation_creates_no_job(env, vids):
    c = env["client"]
    lead, tester = login(c, "lead@qa.test"), login(c, "tester@qa.test")
    p = make_project(c, lead)
    r = upload(c, tester, p["id"], vids["mov"])
    assert r.status_code == 415 and "Accepted formats: .avi, .mkv, .mp4" in r.json()["detail"]
    r = upload(c, tester, p["id"], vids["text_as_mp4"])
    assert r.status_code == 415
    assert c.get("/api/jobs", headers=tester).json() == []
    assert list(env["settings"].paths.uploads_dir.iterdir()) == []  # nothing left on disk


def test_queue_limit(env, vids):
    c = env["client"]
    lead, tester = login(c, "lead@qa.test"), login(c, "tester@qa.test")
    p = make_project(c, lead)
    t0 = time.perf_counter()
    first = upload(c, tester, p["id"], vids["cfr30"])
    assert first.status_code == 201 and first.json()["status"] == "queued"
    assert time.perf_counter() - t0 < 5  # SRS 5.3.1: in the queue within 5 s of the upload finishing
    assert upload(c, tester, p["id"], vids["cfr30"]).status_code == 201
    assert upload(c, tester, p["id"], vids["cfr30"]).status_code == 429  # max_queued_jobs = 2 in this test


# ---------------------------------------------------------------- worker, persistence, filters, files
def _run_job(env, vids, key="vfr", **form):
    c = env["client"]
    lead, tester = login(c, "lead@qa.test"), login(c, "tester@qa.test")
    p = make_project(c, lead)
    job = upload(c, tester, p["id"], vids[key], detectors="fps_drop,animation_glitch", **form).json()
    assert env["worker"].process_one() == job["id"]
    return c, tester, p, c.get(f"/api/jobs/{job['id']}", headers=tester).json()


def test_worker_processes_job_and_stores_detections(env, vids):
    c, tester, _, job = _run_job(env, vids)
    assert job["status"] == "completed" and job["progress"] == 1.0 and job["detection_count"] >= 1
    dets = c.get(f"/api/jobs/{job['id']}/detections", headers=tester).json()
    frozen = [d for d in dets if d["subtype"] == "frozen_frame"]
    assert frozen and frozen[0]["start_time_s"] == pytest.approx(29 / 30, abs=0.02)  # the 0.53 s VFR gap
    d = frozen[0]
    assert d["severity"] in {"medium", "high"} and d["severity_reason"]
    assert d["evidence"]["screenshot_path"].startswith(job["id"] + "/")


def test_filters_individual_and_combined(env, vids):
    c, tester, _, job = _run_job(env, vids)
    url = f"/api/jobs/{job['id']}/detections"
    every = c.get(url, headers=tester).json()
    fps = c.get(url, params={"category": "fps_drop"}, headers=tester).json()
    assert fps and all(d["category"] == "fps_drop" for d in fps)
    sev = every[0]["severity"]
    both = c.get(url, params={"category": "fps_drop", "severity": sev}, headers=tester).json()
    assert all(d["category"] == "fps_drop" and d["severity"] == sev for d in both)
    assert c.get(url, params={"category": "npc_anomaly"}, headers=tester).json() == []
    assert c.get(url, params={"severity": "catastrophic"}, headers=tester).status_code == 422


def test_signed_evidence_links(env, vids):
    c, tester, _, job = _run_job(env, vids)
    d = c.get(f"/api/jobs/{job['id']}/detections", headers=tester).json()[0]
    shot, clip = d["media"]["screenshot"], d["media"]["clip"]
    r = c.get(shot)
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/")
    r = c.get(clip, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100   # seeking works in the <video> element
    assert c.get(shot.replace("sig=", "sig=0")).status_code == 403          # tampered
    assert c.get(shot.split("?")[0]).status_code == 422                     # unsigned
    traversal = shot.replace(d["evidence"]["screenshot_path"], f"{job['id']}/../../test.db")
    assert c.get(traversal).status_code in (403, 404)


def test_rerun_failed_job_without_reupload(env, vids):
    c = env["client"]
    lead, tester = login(c, "lead@qa.test"), login(c, "tester@qa.test")
    p = make_project(c, lead)
    job = upload(c, tester, p["id"], vids["cfr30"], detectors="fps_drop").json()
    stored = env["settings"].paths.uploads_dir / next(env["settings"].paths.uploads_dir.iterdir()).name
    backup = stored.read_bytes()
    stored.write_bytes(b"\x00" * 100)                     # simulate a damaged file -> job fails
    env["worker"].process_one()
    failed = c.get(f"/api/jobs/{job['id']}", headers=tester).json()
    assert failed["status"] == "failed" and failed["error"]
    stored.write_bytes(backup)                            # (e.g. storage repaired) -> re-run
    new = c.post(f"/api/jobs/{job['id']}/rerun", headers=tester)
    assert new.status_code == 201 and new.json()["video_id"] == job["video_id"]
    env["worker"].process_one()
    assert c.get(f"/api/jobs/{new.json()['id']}", headers=tester).json()["status"] == "completed"


def test_worker_recovers_interrupted_jobs(env, vids):
    c = env["client"]
    lead, tester = login(c, "lead@qa.test"), login(c, "tester@qa.test")
    p = make_project(c, lead)
    job = upload(c, tester, p["id"], vids["cfr30"]).json()
    with env["Session"]() as db:
        j = db.get(Job, job["id"])
        j.status, j.attempts = JobStatus.processing, 1
        db.commit()
    assert env["worker"].recover() == 1
    assert c.get(f"/api/jobs/{job['id']}", headers=tester).json()["status"] == "queued"


def test_delete_removes_files_and_records(env, vids):
    c, tester, _, job = _run_job(env, vids)
    s = env["settings"]
    assert (s.paths.evidence_dir / job["id"]).is_dir() and any(s.paths.uploads_dir.iterdir())
    assert c.get(f"/api/jobs/{job['id']}/detections", headers=tester).status_code == 200  # audited "view"
    r = c.delete(f"/api/jobs/{job['id']}", headers=tester)
    assert r.status_code == 200 and r.json()["removed_video"]
    assert not (s.paths.evidence_dir / job["id"]).exists() and not any(s.paths.uploads_dir.iterdir())
    assert c.get(f"/api/jobs/{job['id']}", headers=tester).status_code == 404
    with env["Session"]() as db:
        actions = {a.action for a in db.query(AuditLog).all()}
    assert {"upload", "view", "delete", "login"} <= actions


# ---------------------------------------------------------------- reports (FR-6)
def test_json_and_pdf_reports(env, vids):
    c, tester, _, job = _run_job(env, vids)
    r = c.get(f"/api/jobs/{job['id']}/report.json", headers=tester)
    data = r.json()
    assert r.status_code == 200 and data["summary"]["total"] == job["detection_count"]
    assert data["detections"][0]["evidence"]["clip_path"] and "media" not in data["detections"][0]
    r = c.get(f"/api/jobs/{job['id']}/report.pdf", headers=tester)
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and r.content.count(b"/Type /Page") >= 2
    with env["Session"]() as db:
        actions = {a.action for a in db.query(AuditLog).all()}
    assert {"export_json", "export_pdf"} <= actions


def test_app_refuses_to_start_without_secret(tmp_path):
    from gameqa.core import ConfigError

    s = load_settings()
    s.api = s.api.model_copy(update={"secret_key": ""})
    s.database = s.database.model_copy(update={"url": f"sqlite:///{tmp_path / 'x.db'}"})
    with pytest.raises(ConfigError):
        create_app(s)


