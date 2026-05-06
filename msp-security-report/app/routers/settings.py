"""MSP branding / settings page."""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.dependencies import (
    get_db,
    get_settings,
    template_context,
    templates,
    upload_dir,
)
from app.models import RecommendationOverride
from app.services.questions import SECTIONS


router = APIRouter(prefix="/settings", tags=["settings"])


_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
# SVG is intentionally excluded: even on an internal tool, an attacker-controlled
# SVG served from /static/uploads/ can carry inline <script> and execute in any
# admin's browser. Stick to raster image formats which the browser cannot treat
# as active content.
_ALLOWED_LOGO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
# Hard cap on logo uploads to keep the PDF cover responsive and prevent abuse.
_MAX_LOGO_BYTES = 5 * 1024 * 1024

# Curated list of professional Google Fonts for the PDF report. Users can also
# enter a custom family name; the report template will request the font from
# Google Fonts at render time and gracefully fall back to DejaVu / Liberation
# if the network is unavailable.
REPORT_FONT_PRESETS: list[str] = [
    "Poppins",
    "Inter",
    "Montserrat",
    "Roboto",
    "Open Sans",
    "Lato",
    "Source Sans 3",
    "Work Sans",
    "Nunito",
    "DejaVu Sans",
    "Liberation Sans",
]
_FONT_FAMILY_RE = re.compile(r"^[A-Za-z0-9 _\-]{1,120}$")


@router.get("", response_class=HTMLResponse)
def show_settings(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    settings = get_settings(db)
    ctx = template_context(
        request,
        db,
        settings=settings,
        errors=[],
        saved=False,
        font_presets=REPORT_FONT_PRESETS,
    )
    return templates.TemplateResponse("settings.html", ctx)


@router.post("")
async def save_settings(
    request: Request,
    db: Session = Depends(get_db),
    company_name: str = Form(...),
    primary_color: str = Form(...),
    contact_email: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    report_footer_text: Optional[str] = Form(None),
    report_font_family: Optional[str] = Form(None),
    report_font_custom: Optional[str] = Form(None),
    archive_after_years: int = Form(5),
    logo: Optional[UploadFile] = File(None),
    remove_logo: Optional[str] = Form(None),
):
    settings = get_settings(db)
    errors: list[str] = []

    company_name = (company_name or "").strip()
    if not company_name:
        errors.append("Company name is required.")

    primary_color = (primary_color or "").strip() or "#1f3a5f"
    if not _HEX_COLOR_RE.match(primary_color):
        errors.append("Primary color must be a hex value, e.g. #1f3a5f.")

    # If a custom font name was supplied, prefer it over the dropdown choice.
    chosen_font = (report_font_custom or "").strip() or (report_font_family or "").strip()
    if not chosen_font:
        chosen_font = "Poppins"
    if not _FONT_FAMILY_RE.match(chosen_font):
        errors.append(
            "Report font must contain only letters, numbers, spaces, hyphens, "
            "or underscores."
        )

    if errors:
        ctx = template_context(
            request,
            db,
            settings=settings,
            errors=errors,
            saved=False,
            font_presets=REPORT_FONT_PRESETS,
        )
        return templates.TemplateResponse(
            "settings.html", ctx, status_code=400
        )

    # Clamp the archive threshold to a sane range. 0 means "archive everything
    # older than this year" (effectively a single-year view) and we cap the
    # upper end so the form can't be used to disable archiving entirely.
    archive_clamped = max(0, min(int(archive_after_years or 0), 100))

    settings.company_name = company_name
    settings.primary_color = primary_color
    settings.contact_email = (contact_email or "").strip() or None
    settings.contact_phone = (contact_phone or "").strip() or None
    settings.report_footer_text = (report_footer_text or "").strip() or None
    settings.report_font_family = chosen_font
    settings.archive_after_years = archive_clamped

    # Handle logo upload.
    if logo is not None and logo.filename:
        ext = Path(logo.filename).suffix.lower()
        if ext not in _ALLOWED_LOGO_EXT:
            errors.append(
                "Logo must be PNG, JPG, JPEG, WEBP, or GIF."
            )
        else:
            payload = await logo.read()
            if len(payload) > _MAX_LOGO_BYTES:
                errors.append(
                    f"Logo file is too large (limit "
                    f"{_MAX_LOGO_BYTES // (1024 * 1024)} MiB)."
                )
            elif payload:
                # Write the new file FIRST and only then delete the old one,
                # so a failed write doesn't leave the MSP without a logo.
                new_name = f"logo_{uuid.uuid4().hex[:10]}{ext}"
                target = upload_dir() / new_name
                try:
                    with target.open("wb") as fh:
                        fh.write(payload)
                except OSError as exc:
                    errors.append(f"Could not save uploaded logo: {exc}")
                else:
                    previous = settings.logo_filename
                    settings.logo_filename = new_name
                    if previous:
                        old = upload_dir() / previous
                        try:
                            if old.exists():
                                old.unlink()
                        except OSError:
                            pass

    # Optionally remove the existing logo.
    if remove_logo == "1" and settings.logo_filename:
        old = upload_dir() / settings.logo_filename
        if old.exists():
            try:
                old.unlink()
            except OSError:
                pass
        settings.logo_filename = None

    if errors:
        ctx = template_context(
            request,
            db,
            settings=settings,
            errors=errors,
            saved=False,
            font_presets=REPORT_FONT_PRESETS,
        )
        return templates.TemplateResponse(
            "settings.html", ctx, status_code=400
        )

    db.commit()
    return RedirectResponse(url="/settings?saved=1", status_code=303)


# ----------------------------------------------------------------------------
# Recommendation overrides
# ----------------------------------------------------------------------------

# Hard cap on a single override to prevent obviously abusive payloads.
_MAX_RECOMMENDATION_CHARS = 2000


@router.get("/recommendations", response_class=HTMLResponse)
def show_recommendation_overrides(
    request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    """List every catalog question alongside its (default | overridden) text."""
    existing = {
        row.question_key: row.text
        for row in db.query(RecommendationOverride).all()
    }
    ctx = template_context(
        request,
        db,
        sections=SECTIONS,
        overrides=existing,
        saved=bool(request.query_params.get("saved")),
    )
    return templates.TemplateResponse("settings_recommendations.html", ctx)


@router.post("/recommendations")
async def save_recommendation_overrides(
    request: Request, db: Session = Depends(get_db)
):
    """Upsert / clear overrides in a single batch.

    Empty textareas mean "use the catalog default" and any existing override
    row for that question is deleted. Non-empty values are stored verbatim
    (after stripping) and replace any prior override.
    """
    form = await request.form()
    existing = {
        row.question_key: row
        for row in db.query(RecommendationOverride).all()
    }
    seen_keys: set[str] = set()

    for section in SECTIONS:
        for q in section["questions"]:
            key = q["key"]
            seen_keys.add(key)
            raw = form.get(f"override_{key}")
            if raw is None:
                continue
            text = str(raw).strip()
            if len(text) > _MAX_RECOMMENDATION_CHARS:
                text = text[:_MAX_RECOMMENDATION_CHARS]
            row = existing.get(key)
            if not text:
                if row is not None:
                    db.delete(row)
                continue
            if row is None:
                db.add(RecommendationOverride(question_key=key, text=text))
            else:
                row.text = text

    # Anything in the DB whose question is no longer in the catalog is also
    # cleaned up here so the override list never accumulates dead rows.
    for key, row in existing.items():
        if key not in seen_keys:
            db.delete(row)

    db.commit()
    return RedirectResponse(url="/settings/recommendations?saved=1", status_code=303)
