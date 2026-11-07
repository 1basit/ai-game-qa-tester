"""Logging configuration.

* Human-readable console output by default, JSON lines optionally (for the worker).
* A ``job_id`` context variable is attached to every record, so log lines produced by
  the pipeline, the detectors and the API for one analysis job can be filtered
  together (needed for NFR 5.1 "log it, carry on").
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import logging.handlers
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("gameqa_job_id", default=None)

_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "job_id", "job"}


class _JobContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = _job_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if getattr(record, "job_id", None):
            payload["job_id"] = record.job_id
        extras = {k: v for k, v in vars(record).items() if k not in _STD_ATTRS}
        if extras:
            payload["extra"] = extras
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s%(job)s: %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        job = getattr(record, "job_id", None)
        record.job = f" [job={job}]" if job else ""
        return super().format(record)


def configure_logging(
    level: str = "INFO", json_format: bool = False, log_file: Path | None = None
) -> None:
    """Configure the ``gameqa`` logger tree. Safe to call more than once."""
    root = logging.getLogger("gameqa")
    root.setLevel(level)
    root.propagate = False
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()

    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter() if json_format else ConsoleFormatter())
    console.addFilter(_JobContextFilter())
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(JsonFormatter())  # files are always JSON lines: machine-readable
        fh.addFilter(_JobContextFilter())
        root.addHandler(fh)


def configure_from_settings(settings) -> None:  # type: ignore[no-untyped-def]
    log_file = settings.paths.logs_dir / "gameqa.log" if settings.logging.to_file else None
    configure_logging(settings.logging.level, settings.logging.json_format, log_file)


@contextlib.contextmanager
def job_context(job_id: str) -> Iterator[None]:
    """Attach ``job_id`` to every log record emitted inside this block."""
    token = _job_id.set(job_id)
    try:
        yield
    finally:
        _job_id.reset(token)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith("gameqa") else f"gameqa.{name}")
