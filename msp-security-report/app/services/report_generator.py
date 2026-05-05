"""PDF report generation using WeasyPrint."""
from __future__ import annotations

import os
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session
from weasyprint import HTML

from app.models import Assessment, Client, GeneratedReport, MSPSettings
from app.services.scoring import (
    ScoringResult,
    generate_executive_findings,
    generate_recommendations,
    score_assessment,
)


# Locate the Jinja templates that ship with the application.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_DIR = _PROJECT_ROOT / "templates"


# Where the generated PDFs live. Configurable via env so the Docker volume can
# point to /app/app/static/uploads/reports.
def report_dir() -> Path:
    raw = os.getenv(
        "REPORT_DIR", str(_PROJECT_ROOT / "static" / "uploads" / "reports")
    )
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _logo_url(settings: MSPSettings) -> Optional[str]:
    """Return a file:// URL for the logo so WeasyPrint can render it."""
    if not settings.logo_filename:
        return None
    upload_dir_env = os.getenv(
        "UPLOAD_DIR", str(_PROJECT_ROOT / "static" / "uploads")
    )
    candidate = Path(upload_dir_env) / settings.logo_filename
    if candidate.exists():
        return candidate.as_uri()
    return None


# Fonts that ship with the Docker image and require no network fetch.
_OFFLINE_FONTS = {"DejaVu Sans", "Liberation Sans", "Helvetica", "Arial", "Times"}


def _google_fonts_url(family: str) -> Optional[str]:
    """Build a Google Fonts CSS2 URL for the requested family.

    Returns None for built-in/system fonts where no remote fetch is needed.
    """
    if not family:
        return None
    if family.strip() in _OFFLINE_FONTS:
        return None
    fam_param = urllib.parse.quote_plus(family.strip()) + ":wght@400;600;700"
    return f"https://fonts.googleapis.com/css2?family={fam_param}&display=swap"


def _font_stack(family: str) -> str:
    """Return a CSS font-family stack with the chosen family first and
    DejaVu / Liberation as offline fallbacks."""
    fam = (family or "Poppins").strip()
    return f'"{fam}", "Liberation Sans", "DejaVu Sans", Helvetica, Arial, sans-serif'


def _risk_palette(primary_color: str) -> dict:
    """Static palette used inside the PDF template - tuned for printability."""
    return {
        "primary": primary_color or "#1f3a5f",
        "primary_dark": "#0e1f33",
        "muted": "#6b7280",
        "panel_bg": "#f5f7fa",
        "panel_border": "#d8dde6",
        "table_header_bg": "#1f3a5f",
        "table_header_fg": "#ffffff",
        "row_alt_bg": "#f1f4f8",
        "critical": "#7a1313",
        "high": "#c2410c",
        "medium": "#b45309",
        "low": "#15803d",
        "informational": "#475569",
    }


def _build_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["round1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else x
    env.filters["pct"] = lambda x: f"{int(round(float(x)))}%" if x is not None else "n/a"
    return env


def render_report_html(
    assessment: Assessment, client: Client, settings: MSPSettings
) -> tuple[str, ScoringResult]:
    """Render the report template to an HTML string. Returns (html, result)."""
    result = score_assessment(assessment)
    recommendations = generate_recommendations(result)
    findings = generate_executive_findings(result, recommendations)

    env = _build_jinja_env()
    template = env.get_template("report/report_template.html")
    font_family = (settings.report_font_family or "Poppins").strip()
    html = template.render(
        assessment=assessment,
        client=client,
        settings=settings,
        result=result,
        recommendations=recommendations,
        executive_findings=findings,
        nessus_summary=assessment.nessus_summary,
        logo_url=_logo_url(settings),
        palette=_risk_palette(settings.primary_color),
        generated_at=datetime.utcnow(),
        font_family=font_family,
        font_stack=_font_stack(font_family),
        google_fonts_url=_google_fonts_url(font_family),
    )
    return html, result


def generate_report_pdf(
    db: Session,
    assessment: Assessment,
) -> GeneratedReport:
    """Render and persist a PDF report. Updates assessment scoring on the way."""
    client = assessment.client
    settings = db.query(MSPSettings).first()
    if settings is None:
        # Should never happen because main.py seeds defaults, but be safe.
        settings = MSPSettings(company_name="Your MSP", primary_color="#1f3a5f")

    html_str, result = render_report_html(assessment, client, settings)

    # Persist the latest score and rating on the assessment record.
    assessment.overall_score = round(result.percentage, 1)
    assessment.risk_rating = result.risk_rating

    safe_client = "".join(
        c if c.isalnum() or c in ("-", "_") else "_" for c in (client.name or "client")
    )
    filename = (
        f"{safe_client}_{assessment.year}_security_posture_"
        f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.pdf"
    )
    out_path = report_dir() / filename
    HTML(string=html_str, base_url=str(_PROJECT_ROOT)).write_pdf(target=str(out_path))

    record = GeneratedReport(assessment_id=assessment.id, filename=filename)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
