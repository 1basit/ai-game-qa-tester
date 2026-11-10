"""Typed configuration.

Precedence (highest first):
1. keyword overrides passed to ``load_settings()`` (used by tests and the CLI)
2. environment variables ``GAMEQA_<SECTION>__<FIELD>`` (e.g. ``GAMEQA_VIDEO__ANALYSIS_FPS=15``)
3. a ``.env`` file in the project root
4. the YAML file (``config/default.yaml``, or ``GAMEQA_CONFIG_FILE``)
5. defaults defined below

Relative paths are resolved against the project root so the CLI, worker and API all
agree on where data lives regardless of the current working directory.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from gameqa.core.errors import ConfigError
from gameqa.core.events import PersistenceRule
from gameqa.severity import SeverityConfig


def _find_project_root() -> Path:
    env = os.environ.get("GAMEQA_PROJECT_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    # backend/src/gameqa/config.py -> project root is three levels above "src"
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "default.yaml").is_file():
            return parent
    return Path.cwd().resolve()


PROJECT_ROOT = _find_project_root()
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config" / "default.yaml"


class PathsConfig(BaseModel):
    data_dir: Path = Path("data")
    uploads_dir: Path = Path("data/uploads")
    evidence_dir: Path = Path("data/evidence")
    models_dir: Path = Path("data/models")
    logs_dir: Path = Path("data/logs")
    evaluation_dir: Path = Path("evaluation")

    def resolved(self, root: Path) -> PathsConfig:
        return PathsConfig(
            **{k: (v if v.is_absolute() else (root / v)).resolve() for k, v in self}
        )

    def ensure(self) -> None:
        for _, p in self:
            Path(p).mkdir(parents=True, exist_ok=True)


class VideoConfig(BaseModel):
    allowed_extensions: list[str] = Field(default_factory=lambda: [".mp4", ".avi", ".mkv"])
    max_upload_mb: int = Field(default=2048, gt=0, description="SRS 5.3.1: uploads up to 2 GB")
    analysis_fps: float = Field(
        default=12.0, ge=1.0, le=60.0, description="Sampled stream rate; FR-2 specifies 10-15"
    )
    normalized_height: int = Field(
        default=720, ge=144, le=2160, description="Detector input height (aspect preserved)"
    )
    upscale: bool = Field(
        default=True,
        description="Also scale smaller footage up to normalized_height, so pixel-based "
        "thresholds mean the same thing for every video",
    )

    @field_validator("allowed_extensions")
    @classmethod
    def _lower_dot(cls, v: list[str]) -> list[str]:
        return [e.lower() if e.startswith(".") else f".{e.lower()}" for e in v]


class DetectorConfig(BaseModel):
    enabled: bool = True
    persistence: PersistenceRule | None = None  # None -> use the global rule
    params: dict[str, Any] = Field(default_factory=dict)


class EvidenceConfig(BaseModel):
    clip_duration_s: float = Field(default=8.0, ge=5.0, le=10.0, description="FR-4: 5-10 s")
    screenshot_format: Literal["png", "jpg"] = "png"


class EvaluationConfig(BaseModel):
    iou_threshold: float = Field(default=0.3, gt=0.0, le=1.0)
    peak_tolerance_s: float = Field(default=0.5, ge=0.0)
    match_subtype: bool = False


class FpsServiceConfig(BaseModel):
    """Prototype FPS analysis service (CLI `main.py analyze` and `main.py --gui`)."""

    target_fps: float = Field(default=60.0, gt=0, description="FPS the game is expected to hold (30 or 60)")
    drop_ratio: float = Field(default=0.75, gt=0, lt=1, description="drop if effective FPS < ratio x target")
    freeze_ms: float = Field(default=250.0, gt=0, description="picture held at least this long while moving = freeze")
    stutter_min_missed: int = Field(
        default=3, ge=1, description="missed frames within 1 s (isolated, above the drop threshold) = stutter")
    output_dir: Path = Path("outputs")
    gui_host: str = "127.0.0.1"
    gui_port: int = 8765


class DatabaseConfig(BaseModel):
    url: str = Field(
        default="postgresql+psycopg://gameqa@localhost:5433/gameqa",
        description="SQLAlchemy URL. Override with GAMEQA_DATABASE__URL (tests use SQLite)")


class ApiConfig(BaseModel):
    secret_key: str = Field(
        default="", description="JWT signing key. MUST be set via GAMEQA_API__SECRET_KEY (or .env) outside tests")
    token_lifetime_days: int = 7
    inactivity_hours: float = Field(default=12.0, description="SRS 5.4: sessions expire after 12 h of inactivity")
    min_password_length: int = 8
    max_queued_jobs: int = Field(default=5, description="SRS 5.3.1: one running job, up to five queued")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "https://localhost:5173"])
    worker_poll_s: float = 2.0
    max_job_attempts: int = 3


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    json_format: bool = False
    to_file: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GAMEQA_",
        env_nested_delimiter="__",
        env_file=str(PROJECT_ROOT / ".env"),
        extra="forbid",
    )

    device: Literal["auto", "cuda", "mps", "cpu"] = "auto"
    paths: PathsConfig = Field(default_factory=PathsConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    persistence: PersistenceRule = Field(default_factory=PersistenceRule)
    detectors: dict[str, DetectorConfig] = Field(default_factory=dict)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    severity: SeverityConfig = Field(default_factory=SeverityConfig)
    fps_service: FpsServiceConfig = Field(default_factory=FpsServiceConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Not a setting: where this configuration was loaded from.
    config_file: Path | None = Field(default=None, exclude=True)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings, dotenv_settings]
        yaml_file = settings_cls.model_config.get("yaml_file")
        if yaml_file:
            sources.append(YamlConfigSettingsSource(settings_cls))
        return tuple(sources)

    def persistence_for(self, detector: str) -> PersistenceRule:
        cfg = self.detectors.get(detector)
        return cfg.persistence if cfg and cfg.persistence else self.persistence

    def enabled_detectors(self) -> list[str]:
        return [name for name, cfg in self.detectors.items() if cfg.enabled]


def load_settings(config_file: str | Path | None = None, **overrides: Any) -> Settings:
    """Load settings from YAML + environment, with paths resolved to absolute."""
    path = Path(
        config_file or os.environ.get("GAMEQA_CONFIG_FILE") or DEFAULT_CONFIG_FILE
    ).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    if not path.is_file():
        raise ConfigError(f"configuration file not found: {path}")

    class _FileSettings(Settings):
        model_config = SettingsConfigDict(yaml_file=str(path))

    try:
        loaded = _FileSettings(**overrides)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration in {path}:\n{exc}") from exc

    loaded.paths = loaded.paths.resolved(PROJECT_ROOT)
    loaded.config_file = path
    return loaded


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (CLI, worker, API)."""
    return load_settings()
