"""FastAPI app factory for the satdeploy dashboard.

The module-level ``app`` is constructed from env vars when this module is
imported as ``satdeploy.dashboard.app:app`` (the uvicorn entrypoint).
Tests call :func:`create_app` directly with explicit parameters to avoid
env-var setup.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from satdeploy.history import History


def _tile_state(record) -> str:
    """Classify a DeploymentRecord into the tile's colour bucket."""
    if not record:
        return "unknown"
    if record.action == "rollback":
        return "rolled-back"
    if not record.success:
        return "failed"
    return "deployed"


def create_app(
    db_path: Path,
    secret: str,
    config_path: Optional[Path] = None,
) -> FastAPI:
    app = FastAPI(title="satdeploy dashboard", docs_url=None, redoc_url=None)

    tpl_dir = Path(__file__).parent / "templates"
    static_dir = Path(__file__).parent / "static"
    templates = Jinja2Templates(directory=str(tpl_dir))
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.state.db_path = db_path
    app.state.secret = secret
    app.state.config_path = config_path
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        history = History(db_path)
        fleet = history.get_fleet_status()
        tiles = []
        for module, apps in fleet.items():
            for app_name, record in sorted(apps.items()):
                tiles.append({
                    "module": module,
                    "app": app_name,
                    "state": _tile_state(record),
                    "record": record,
                })
        events = history.get_all_history(limit=20)
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={"tiles": tiles, "events": events},
        )

    @app.get("/api/ticker", response_class=HTMLResponse)
    def ticker(request: Request):
        history = History(db_path)
        events = history.get_all_history(limit=20)
        return templates.TemplateResponse(
            request=request,
            name="_ticker.html",
            context={"events": events},
        )

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


def _from_env() -> FastAPI:
    db = os.environ.get("SATDEPLOY_DASHBOARD_DB")
    secret = os.environ.get("SATDEPLOY_DASHBOARD_SECRET")
    if not db or not secret:
        raise RuntimeError(
            "SATDEPLOY_DASHBOARD_DB and SATDEPLOY_DASHBOARD_SECRET must be set. "
            "Use `satdeploy dashboard` rather than running uvicorn directly."
        )
    config_path = os.environ.get("SATDEPLOY_DASHBOARD_CONFIG")
    return create_app(
        Path(db),
        secret,
        config_path=Path(config_path) if config_path else None,
    )


if os.environ.get("SATDEPLOY_DASHBOARD_DB"):
    app = _from_env()
else:
    app = None  # populated lazily by uvicorn or by tests via create_app()
