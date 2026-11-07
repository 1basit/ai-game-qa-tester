"""Analysis worker: takes queued jobs from the database one at a time (SRS 5.3.1:
one job processing, up to five queued) and runs the detection pipeline.

The queue is the ``jobs`` table: no extra broker (Redis/Celery) is needed for this load,
and jobs survive restarts. On start-up, jobs left ``processing`` by a crashed worker are
put back in the queue (or marked failed after ``max_job_attempts``).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from gameqa.api.models import DetectionRow, Job, JobStatus
from gameqa.config import Settings
from gameqa.logging_setup import get_logger, job_context
from gameqa.pipeline import run_pipeline

log = get_logger("worker")


class Worker:
    def __init__(self, settings: Settings, session_factory: sessionmaker):
        self.settings = settings
        self.Session = session_factory

    def recover(self) -> int:
        """Re-queue jobs interrupted by a crash."""
        n = 0
        with self.Session() as db:
            for job in db.scalars(select(Job).where(Job.status == JobStatus.processing)):
                n += 1
                if job.attempts >= self.settings.api.max_job_attempts:
                    job.status, job.error = JobStatus.failed, "worker stopped during processing too many times"
                    job.finished_at = datetime.now(timezone.utc)
                else:
                    job.status, job.message, job.progress = JobStatus.queued, "re-queued after worker restart", 0.0
            db.commit()
        return n

    def _claim(self) -> str | None:
        with self.Session() as db:
            q = select(Job.id).where(Job.status == JobStatus.queued).order_by(Job.created_at).limit(1)
            if db.bind.dialect.name == "postgresql":
                q = q.with_for_update(skip_locked=True)
            job_id = db.scalar(q)
            if job_id is None:
                return None
            claimed = db.execute(update(Job).where(Job.id == job_id, Job.status == JobStatus.queued).values(
                status=JobStatus.processing, started_at=datetime.now(timezone.utc), progress=0.0,
                message="starting", attempts=Job.attempts + 1)).rowcount
            db.commit()
            return job_id if claimed else None

    def process_one(self) -> str | None:
        """Run the oldest queued job. Returns its id, or None if the queue is empty."""
        job_id = self._claim()
        if job_id is None:
            return None
        with job_context(job_id), self.Session() as db:
            job = db.get(Job, job_id)
            video = job.video
            path = self.settings.paths.uploads_dir / video.stored_path
            settings = self._job_settings(job.options or {})
            last = [0.0]

            def progress(frac: float, msg: str) -> None:
                now = time.monotonic()
                if now - last[0] < 1.0 and frac < 1.0:
                    return
                last[0] = now
                with self.Session() as s2:
                    s2.execute(update(Job).where(Job.id == job_id).values(progress=float(frac), message=msg))
                    s2.commit()

            try:
                res = run_pipeline(path, settings, detector_names=(job.options or {}).get("detectors") or None,
                                   video_id=video.id, progress=progress,
                                   evidence_dir=self.settings.paths.evidence_dir, evidence_subdir=job.id)
            except Exception as exc:  # noqa: BLE001 - recorded on the job
                log.exception("job failed")
                job.status, job.error, job.message = JobStatus.failed, f"{type(exc).__name__}: {exc}", "failed"
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
                return job_id
            for d in res.detection_set.detections:
                db.add(DetectionRow(
                    id=d.id, job_id=job_id, category=d.category.value, subtype=d.subtype, detector=d.detector,
                    detector_version=d.detector_version, start_time_s=d.start_time_s, end_time_s=d.end_time_s,
                    peak_time_s=d.peak_time_s, start_frame=d.start_frame, end_frame=d.end_frame,
                    peak_frame=d.peak_frame, confidence=d.confidence,
                    severity=d.severity.value if d.severity else None, severity_reason=d.severity_reason,
                    occurrence_group=d.occurrence_group, data=d.model_dump(mode="json")))
            job.status = JobStatus.completed_with_warnings if res.warnings else JobStatus.completed
            job.warnings, job.run_info = res.warnings, res.as_dict()
            job.progress, job.message = 1.0, f"{len(res.detection_set.detections)} detections"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            log.info("job finished: %s, %d detections", job.status.value, len(res.detection_set.detections))
            return job_id

    def _job_settings(self, options: dict) -> Settings:
        s = self.settings.model_copy(deep=True)
        if options.get("analysis_fps"):
            s.video = s.video.model_copy(update={"analysis_fps": float(options["analysis_fps"])})
        if options.get("target_fps") and "fps_drop" in s.detectors:
            cfg = s.detectors["fps_drop"]
            s.detectors["fps_drop"] = cfg.model_copy(update={"params": {**cfg.params,
                                                                        "target_fps": float(options["target_fps"])}})
        return s

    def run_forever(self) -> None:
        n = self.recover()
        if n:
            log.warning("recovered %d interrupted job(s)", n)
        log.info("worker started; polling every %.1fs", self.settings.api.worker_poll_s)
        while True:
            if self.process_one() is None:
                time.sleep(self.settings.api.worker_poll_s)
