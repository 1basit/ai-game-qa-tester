"""Database schema (SQLAlchemy 2, PostgreSQL in deployment; SQLite in tests).

Relational because the data is: users ↔ projects (membership = access control) ↔
videos ↔ jobs ↔ detections. ``ON DELETE CASCADE`` implements the SRS rule that deleting
a job removes its database records (files are removed by the API layer).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, create_engine, event)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    """SRS Table 1 user classes."""

    tester = "tester"
    developer = "developer"
    qa_lead = "qa_lead"
    admin = "admin"


class JobStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    completed_with_warnings = "completed_with_warnings"
    failed = "failed"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), default=Role.tester)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_activity: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    memberships: Mapped[list[ProjectMember]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    game_build: Mapped[str] = mapped_column(String(120), default="")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    members: Mapped[list[ProjectMember]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))  # relative to uploads_dir
    size_bytes: Mapped[int] = mapped_column(Integer)
    info: Mapped[dict] = mapped_column(JSON, default=dict)  # VideoInfo
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, native_enum=False), default=JobStatus.queued, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String(200), default="")
    options: Mapped[dict] = mapped_column(JSON, default=dict)  # detectors, analysis_fps, target_fps
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    run_info: Mapped[dict] = mapped_column(JSON, default=dict)
    video: Mapped[Video] = relationship()
    detections: Mapped[list[DetectionRow]] = relationship(back_populates="job", cascade="all, delete-orphan",
                                                          passive_deletes=True)


class DetectionRow(Base):
    __tablename__ = "detections"
    __table_args__ = (Index("ix_det_job_cat_sev", "job_id", "category", "severity"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    subtype: Mapped[str] = mapped_column(String(40))
    detector: Mapped[str] = mapped_column(String(60))
    detector_version: Mapped[str] = mapped_column(String(20))
    start_time_s: Mapped[float] = mapped_column(Float)
    end_time_s: Mapped[float] = mapped_column(Float)
    peak_time_s: Mapped[float] = mapped_column(Float)
    start_frame: Mapped[int] = mapped_column(Integer)
    end_frame: Mapped[int] = mapped_column(Integer)
    peak_frame: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    severity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    severity_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
    data: Mapped[dict] = mapped_column(JSON)  # full Detection JSON (bbox, metrics, evidence, description)
    job: Mapped[Job] = relationship(back_populates="detections")


class AuditLog(Base):
    """SRS 5.4: who uploaded, viewed, exported or deleted what, and when."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    user_email: Mapped[str] = mapped_column(String(254), default="")
    action: Mapped[str] = mapped_column(String(40))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------- engine / session
def make_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite needs this for ON DELETE CASCADE
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
