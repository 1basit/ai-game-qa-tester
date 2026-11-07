"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from gameqa.api.models import init_db, make_engine, make_sessionmaker
from gameqa.config import PROJECT_ROOT, Settings, get_settings
from gameqa.core.errors import ConfigError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if len(settings.api.secret_key) < 32:
        raise ConfigError("GAMEQA_API__SECRET_KEY must be set to a random string of at least 32 characters")
    engine = make_engine(settings.database.url)
    init_db(engine)
    settings.paths.ensure()
    app = FastAPI(title="AI Game QA Tester", version="0.1.0")
    app.state.settings = settings
    app.state.sessionmaker = make_sessionmaker(engine)
    app.add_middleware(CORSMiddleware, allow_origins=settings.api.cors_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])
    from gameqa.api.reports import router as reports_router
    from gameqa.api.routes import router

    app.include_router(router)
    app.include_router(reports_router)
    dist = PROJECT_ROOT / "frontend" / "dist"
    if dist.is_dir():  # built dashboard served from the same origin (production / demo)
        app.mount("/", StaticFiles(directory=Path(dist), html=True), name="dashboard")
    return app
