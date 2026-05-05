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


router = APIRouter(prefix="/settings", tags=["settings"])


_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_ALLOWED_LOGO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

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

    settings.company_name = company_name
    settings.primary_color = primary_color
    settings.contact_email = (contact_email or "").strip() or None
    settings.contact_phone = (contact_phone or "").strip() or None
    settings.report_footer_text = (report_footer_text or "").strip() or None
    settings.report_font_family = chosen_font

    # Handle logo upload.
    if logo is not None and logo.filename:
        ext = Path(logo.filename).suffix.lower()
        if ext not in _ALLOWED_LOGO_EXT:
            errors.append(
                "Logo must be PNG, JPG, JPEG, WEBP, GIF or SVG."
            )
        else:
            payload = await logo.read()
            if payload:
                # Remove the previous logo if any.
                if settings.logo_filename:
                    old = upload_dir() / settings.logo_filename
                    if old.exists():
                        try:
                            old.unlink()
                        except OSError:
                            pass
                new_name = f"logo_{uuid.uuid4().hex[:10]}{ext}"
                target = upload_dir() / new_name
                with target.open("wb") as fh:
                    fh.write(payload)
                settings.logo_filename = new_name

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
