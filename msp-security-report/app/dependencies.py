"""Shared FastAPI dependencies."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MSPSettings


_BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BASE / "templates"))


def upload_dir() -> Path:
    raw = os.getenv("UPLOAD_DIR", str(_BASE / "static" / "uploads"))
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


def report_dir_path() -> Path:
    raw = os.getenv("REPORT_DIR", str(_BASE / "static" / "uploads" / "reports"))
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_settings(db: Session) -> MSPSettings:
    """Fetch the singleton MSP settings row, creating defaults if absent."""
    settings = db.query(MSPSettings).first()
    if settings is None:
        settings = MSPSettings(
            company_name="Your MSP",
            primary_color="#1f3a5f",
            report_footer_text="Confidential - Prepared for the named client only.",
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def template_context(request: Request, db: Session, **extra) -> dict:
    """Build a Jinja context dict that always includes MSP settings."""
    settings = get_settings(db)
    ctx = {
        "request": request,
        "msp": settings,
    }
    ctx.update(extra)
    return ctx


__all__ = [
    "templates",
    "upload_dir",
    "report_dir_path",
    "get_settings",
    "template_context",
    "get_db",
]
