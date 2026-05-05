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

from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.dependencies import get_settings, template_context, templates
from app.models import Assessment, AssessmentStatus, Client, MSPSettings
from app.routers import assessments, clients, reports, settings


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
                )
            )
            session.commit()


def create_app() -> FastAPI:
    app = FastAPI(
        title="MSP Security Posture Report",
        description=(
            "Internal tool used by the MSP technical team to perform annual "
            "security posture assessments and produce branded PDF reports."
        ),
        version="1.0.0",
    )

    static_dir = _BASE / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(clients.router)
    app.include_router(assessments.router)
    app.include_router(reports.router)
    app.include_router(settings.router)

    @app.on_event("startup")
    def _startup() -> None:
        _bootstrap_db()

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

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
