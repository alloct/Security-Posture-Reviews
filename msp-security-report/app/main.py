"""FastAPI application entry point.

Run locally with::

    uvicorn app.main:app --reload

The application:
  * mounts a static file directory used by the dashboard CSS and uploaded logos
  * registers the four feature routers
  * provides a dashboard view at the root
  * runs lightweight startup steps to ensure the database schema and a default
    MSPSettings row are present
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.database import Base, engine, get_db
from app.dependencies import template_context, templates
from app.models import Assessment, AssessmentStatus, Client, MSPSettings
from app.routers import assessments, clients, reports, settings
from app.services.questions import SECTIONS
from app.services.scoring import score_assessment


_BASE = Path(__file__).resolve().parent


def _bootstrap_db() -> None:
    """Seed the default MSPSettings row if missing.

    Schema management is handled by Alembic via the Docker entrypoint
    (or `alembic upgrade head` for local development). We still call
    `metadata.create_all` here as a last-resort safety net for developers
    running uvicorn directly without applying migrations - this never runs
    against an existing schema in production because the entrypoint runs
    migrations first.
    """
    Base.metadata.create_all(bind=engine)
    from app.database import SessionLocal

    with SessionLocal() as session:
        if session.query(MSPSettings).first() is None:
            session.add(
                MSPSettings(
                    company_name="Your MSP",
                    primary_color="#1f3a5f",
                    report_footer_text="Confidential - Prepared for the named client only.",
                    report_font_family="Poppins",
                    archive_after_years=5,
                )
            )
            session.commit()


class NoStoreHTMLMiddleware(BaseHTTPMiddleware):
    """Set ``Cache-Control: no-store`` on dynamic HTML responses.

    Without this, browsers may serve a stale rendering of pages like the
    client detail (e.g. via the bfcache when the user clicks Back after a
    report download), which makes freshly generated reports appear missing.
    Static assets under ``/static`` are not affected.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            return response
        ctype = response.headers.get("content-type", "")
        if ctype.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _bootstrap_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="MSP Security Posture Report",
        description=(
            "Internal tool used by the MSP technical team to perform annual "
            "security posture assessments and produce branded PDF reports."
        ),
        version="1.0.0",
        lifespan=_lifespan,
    )

    app.add_middleware(NoStoreHTMLMiddleware)

    static_dir = _BASE / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(clients.router)
    app.include_router(assessments.router)
    app.include_router(reports.router)
    app.include_router(settings.router)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
        client_count = db.query(func.count(Client.id)).scalar() or 0
        in_progress = (
            db.query(func.count(Assessment.id))
            .filter(Assessment.status == AssessmentStatus.in_progress)
            .scalar()
            or 0
        )
        complete = (
            db.query(func.count(Assessment.id))
            .filter(Assessment.status == AssessmentStatus.complete)
            .scalar()
            or 0
        )
        recent_assessments = (
            db.query(Assessment)
            .order_by(desc(Assessment.created_at))
            .limit(8)
            .all()
        )
        recent_clients = (
            db.query(Client).order_by(desc(Client.created_at)).limit(8).all()
        )
        avg_score = (
            db.query(func.avg(Assessment.overall_score))
            .filter(Assessment.overall_score.isnot(None))
            .scalar()
        )

        ctx = template_context(
            request,
            db,
            client_count=client_count,
            in_progress=in_progress,
            complete=complete,
            recent_assessments=recent_assessments,
            recent_clients=recent_clients,
            avg_score=round(avg_score, 1) if avg_score is not None else None,
            now=datetime.utcnow(),
        )
        return templates.TemplateResponse("dashboard.html", ctx)

    @app.get("/portfolio", response_class=HTMLResponse)
    def portfolio_heatmap(
        request: Request, db: Session = Depends(get_db)
    ) -> HTMLResponse:
        """Per-client section heatmap of the most recent assessment scores.

        The grid lets a vCISO answer "where am I weakest across the book?"
        in one view. Cells are coloured by the same score bands the rest of
        the report uses, and clicking a cell opens that section directly.
        """
        clients = (
            db.query(Client)
            .options(selectinload(Client.assessments).selectinload(Assessment.answers))
            .order_by(Client.name)
            .all()
        )

        rows = []
        for client in clients:
            # Pick the most recent assessment that has any answers; otherwise
            # the latest, otherwise None. This keeps brand-new clients in the
            # grid as a single empty row instead of disappearing.
            latest = next(
                (a for a in client.assessments if a.answers),
                client.assessments[0] if client.assessments else None,
            )
            cells = []
            if latest is not None:
                result = score_assessment(latest)
                section_lookup = {s.key: s for s in result.sections}
                for sec in SECTIONS:
                    bucket = section_lookup.get(sec["key"])
                    if bucket is None or bucket.possible == 0:
                        cells.append({"key": sec["key"], "name": sec["name"], "state": "empty"})
                        continue
                    pct = bucket.percentage
                    if pct >= 85:
                        state = "good"
                    elif pct >= 70:
                        state = "warn"
                    elif pct >= 50:
                        state = "high"
                    else:
                        state = "critical"
                    cells.append(
                        {
                            "key": sec["key"],
                            "name": sec["name"],
                            "state": state,
                            "percentage": pct,
                            "answered": bucket.answered,
                            "total": bucket.total,
                        }
                    )
            else:
                cells = [
                    {"key": s["key"], "name": s["name"], "state": "empty"}
                    for s in SECTIONS
                ]
            rows.append(
                {
                    "client": client,
                    "latest": latest,
                    "cells": cells,
                }
            )

        ctx = template_context(
            request,
            db,
            sections=[{"key": s["key"], "name": s["name"]} for s in SECTIONS],
            rows=rows,
        )
        return templates.TemplateResponse("portfolio.html", ctx)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
