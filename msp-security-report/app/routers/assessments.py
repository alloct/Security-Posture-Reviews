"""Assessment workflow routes.

Handles:
  * Creating a new assessment for a client (with year)
  * The multi-step wizard - one section per page
  * Per-section answer saving
  * Optional Nessus CSV upload + preview
  * The summary page that shows the score before report generation
  * Close / reopen assessment lifecycle actions
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import (
    get_db,
    report_dir_path,
    template_context,
    templates,
    upload_dir,
)
from app.models import (
    Assessment,
    AssessmentAnswer,
    AssessmentStatus,
    Client,
)
from app.services.nessus_parser import (
    NessusParseError,
    parse_and_summarise,
)
from app.services.questions import SECTIONS, section_by_key
from app.services.scoring import (
    generate_executive_findings,
    generate_recommendations,
    score_assessment,
)


router = APIRouter(prefix="/assessments", tags=["assessments"])


# Hard cap on Nessus CSV uploads. The full file is read into memory for the
# pandas parser, so we refuse anything that would obviously be abusive on a
# small internal host. 50 MiB comfortably handles real-world enterprise scans.
_MAX_NESSUS_BYTES = 50 * 1024 * 1024

# Sanitiser for the user-supplied portion of the stored Nessus filename.
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitise_filename_component(value: str) -> str:
    """Reduce a user-supplied filename to a safe, filesystem-friendly slug."""
    base = Path(value or "").name
    cleaned = _FILENAME_UNSAFE.sub("_", base).strip("._") or "upload"
    return cleaned[:80]


def _delete_assessment_files(assessment: Assessment) -> None:
    """Best-effort removal of every file produced for this assessment."""
    if assessment.nessus_csv_filename:
        target = upload_dir() / assessment.nessus_csv_filename
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
    for record in list(assessment.reports):
        path = report_dir_path() / record.filename
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _get_assessment_or_404(db: Session, assessment_id: int) -> Assessment:
    a = db.get(Assessment, assessment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return a


def _section_index(section_key: str) -> int:
    for i, s in enumerate(SECTIONS):
        if s["key"] == section_key:
            return i
    raise HTTPException(status_code=404, detail="Unknown section")


def _existing_answers_map(assessment: Assessment, section_key: str) -> dict[str, str]:
    return {
        a.question_key: a.answer_value
        for a in assessment.answers
        if a.section == section_key
    }


# ----------------------------------------------------------------------------
# Create / start
# ----------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse)
def start_assessment_form(
    request: Request,
    db: Session = Depends(get_db),
    client_id: Optional[int] = None,
) -> HTMLResponse:
    clients = db.query(Client).order_by(Client.name).all()
    selected = db.get(Client, client_id) if client_id else None
    ctx = template_context(
        request,
        db,
        clients=clients,
        selected_client=selected,
        default_year=datetime.utcnow().year,
        errors=[],
    )
    return templates.TemplateResponse("assessment/start.html", ctx)


@router.post("/new")
def start_assessment(
    request: Request,
    db: Session = Depends(get_db),
    client_id: int = Form(...),
    year: int = Form(...),
):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    existing = db.scalar(
        select(Assessment).where(
            Assessment.client_id == client_id, Assessment.year == year
        )
    )
    if existing is not None:
        return RedirectResponse(
            url=f"/assessments/{existing.id}/sections/{SECTIONS[0]['key']}",
            status_code=303,
        )

    a = Assessment(
        client_id=client.id,
        year=year,
        status=AssessmentStatus.in_progress,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return RedirectResponse(
        url=f"/assessments/{a.id}/sections/{SECTIONS[0]['key']}", status_code=303
    )


# ----------------------------------------------------------------------------
# Wizard navigation
# ----------------------------------------------------------------------------

@router.get("/{assessment_id}", response_class=HTMLResponse)
def open_assessment(assessment_id: int, db: Session = Depends(get_db)):
    """Resume entry point - jumps to the first unanswered section, or summary."""
    a = _get_assessment_or_404(db, assessment_id)
    answered_sections = {ans.section for ans in a.answers}
    for section in SECTIONS:
        # If a section has any unanswered question, go there.
        section_q_keys = {q["key"] for q in section["questions"]}
        answered_keys = {
            ans.question_key for ans in a.answers if ans.section == section["key"]
        }
        if section_q_keys - answered_keys:
            return RedirectResponse(
                url=f"/assessments/{a.id}/sections/{section['key']}", status_code=303
            )
    # Everything answered -> summary
    return RedirectResponse(url=f"/assessments/{a.id}/summary", status_code=303)


@router.get("/{assessment_id}/sections/{section_key}", response_class=HTMLResponse)
def show_section(
    assessment_id: int,
    section_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    a = _get_assessment_or_404(db, assessment_id)
    section = section_by_key(section_key)
    if section is None:
        raise HTTPException(status_code=404, detail="Unknown section")

    idx = _section_index(section_key)
    answers_map = _existing_answers_map(a, section_key)
    prev_key = SECTIONS[idx - 1]["key"] if idx > 0 else None
    next_key = SECTIONS[idx + 1]["key"] if idx < len(SECTIONS) - 1 else None

    ctx = template_context(
        request,
        db,
        assessment=a,
        client=a.client,
        section=section,
        section_index=idx,
        section_total=len(SECTIONS),
        all_sections=SECTIONS,
        answers=answers_map,
        prev_section_key=prev_key,
        next_section_key=next_key,
    )
    return templates.TemplateResponse("assessment/section.html", ctx)


@router.post("/{assessment_id}/sections/{section_key}")
async def save_section(
    assessment_id: int,
    section_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    a = _get_assessment_or_404(db, assessment_id)
    section = section_by_key(section_key)
    if section is None:
        raise HTTPException(status_code=404, detail="Unknown section")

    form = await request.form()
    direction = (form.get("direction") or "next").strip()

    # Upsert each answer in this section.
    for question in section["questions"]:
        raw = form.get(f"q_{question['key']}")
        if raw is None:
            continue
        value = str(raw)
        # Resolve label from option list.
        label = next(
            (opt["label"] for opt in question["options"] if opt["value"] == value),
            value,
        )

        existing = next(
            (
                ans
                for ans in a.answers
                if ans.question_key == question["key"]
            ),
            None,
        )
        if existing is None:
            db.add(
                AssessmentAnswer(
                    assessment_id=a.id,
                    section=section_key,
                    question_key=question["key"],
                    question_text=question["text"],
                    answer_value=value,
                    answer_label=label,
                    weight=question["weight"],
                )
            )
        else:
            existing.answer_value = value
            existing.answer_label = label
            existing.weight = question["weight"]
            existing.section = section_key
            existing.question_text = question["text"]

    db.commit()

    # Determine next URL based on direction.
    idx = _section_index(section_key)
    if direction == "previous" and idx > 0:
        target = f"/assessments/{a.id}/sections/{SECTIONS[idx - 1]['key']}"
    elif idx < len(SECTIONS) - 1 and direction != "save":
        target = f"/assessments/{a.id}/sections/{SECTIONS[idx + 1]['key']}"
    elif direction == "save":
        target = f"/assessments/{a.id}/sections/{section_key}"
    else:
        target = f"/assessments/{a.id}/summary"

    return RedirectResponse(url=target, status_code=303)


# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------

@router.get("/{assessment_id}/summary", response_class=HTMLResponse)
def assessment_summary(
    assessment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    generated: int = 0,
):
    a = _get_assessment_or_404(db, assessment_id)
    result = score_assessment(a)
    recommendations = generate_recommendations(result)
    findings = generate_executive_findings(result, recommendations)

    # Persist latest score on the record so the dashboard reflects it.
    a.overall_score = round(result.percentage, 1)
    a.risk_rating = result.risk_rating
    db.commit()

    total_questions = sum(len(s["questions"]) for s in SECTIONS)
    answered = len(a.answers)

    # generated is the GeneratedReport.id we just created; 0 means this isn't
    # a post-generation visit. The template uses it to highlight the new row
    # and trigger the download.
    just_generated_id = generated or 0

    ctx = template_context(
        request,
        db,
        assessment=a,
        client=a.client,
        result=result,
        recommendations=recommendations,
        executive_findings=findings,
        total_questions=total_questions,
        answered_questions=answered,
        report_just_generated=just_generated_id,
    )
    return templates.TemplateResponse("assessment/summary.html", ctx)


# ----------------------------------------------------------------------------
# Nessus CSV upload
# ----------------------------------------------------------------------------

@router.post("/{assessment_id}/nessus")
async def upload_nessus(
    assessment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nessus_csv: UploadFile = File(...),
):
    a = _get_assessment_or_404(db, assessment_id)

    if not nessus_csv or not nessus_csv.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    if not nessus_csv.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv export from Nessus")

    # Stream-read with a hard size cap so a malicious or accidental huge
    # upload cannot OOM the server. UploadFile is backed by SpooledTemporaryFile.
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await nessus_csv.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_NESSUS_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Nessus CSV is too large (limit "
                    f"{_MAX_NESSUS_BYTES // (1024 * 1024)} MiB)."
                ),
            )
        chunks.append(chunk)
    payload = b"".join(chunks)

    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        _, summary = parse_and_summarise(payload)
    except NessusParseError as exc:
        # Re-render the summary page with an error.
        result = score_assessment(a)
        recommendations = generate_recommendations(result)
        findings = generate_executive_findings(result, recommendations)
        ctx = template_context(
            request,
            db,
            assessment=a,
            client=a.client,
            result=result,
            recommendations=recommendations,
            executive_findings=findings,
            total_questions=sum(len(s["questions"]) for s in SECTIONS),
            answered_questions=len(a.answers),
            nessus_error=str(exc),
        )
        return templates.TemplateResponse(
            "assessment/summary.html", ctx, status_code=400
        )

    # If a previous CSV was attached, remove it before overwriting so we don't
    # leak files on disk. The DB row is overwritten below.
    if a.nessus_csv_filename:
        old = upload_dir() / a.nessus_csv_filename
        try:
            if old.exists():
                old.unlink()
        except OSError:
            pass

    safe_user_part = _sanitise_filename_component(nessus_csv.filename)
    safe_name = f"nessus_{a.id}_{uuid.uuid4().hex[:8]}_{safe_user_part}"
    target = upload_dir() / safe_name
    with target.open("wb") as fh:
        fh.write(payload)

    a.nessus_csv_filename = safe_name
    a.nessus_summary = summary

    # Recompute score with deduction applied.
    result = score_assessment(a)
    a.overall_score = round(result.percentage, 1)
    a.risk_rating = result.risk_rating

    db.commit()
    return RedirectResponse(
        url=f"/assessments/{a.id}/summary", status_code=303
    )


@router.post("/{assessment_id}/nessus/clear")
def clear_nessus(assessment_id: int, db: Session = Depends(get_db)):
    a = _get_assessment_or_404(db, assessment_id)
    if a.nessus_csv_filename:
        target = upload_dir() / a.nessus_csv_filename
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
    a.nessus_csv_filename = None
    a.nessus_summary = None
    result = score_assessment(a)
    a.overall_score = round(result.percentage, 1)
    a.risk_rating = result.risk_rating
    db.commit()
    return RedirectResponse(
        url=f"/assessments/{a.id}/summary", status_code=303
    )


# ----------------------------------------------------------------------------
# Lifecycle actions: close / reopen
# ----------------------------------------------------------------------------

@router.post("/{assessment_id}/close")
def close_assessment(assessment_id: int, db: Session = Depends(get_db)):
    """Mark an assessment as complete without generating a report.

    Useful when a year's review has been written up out-of-band, or when the
    assessment is being parked rather than reported on.
    """
    a = _get_assessment_or_404(db, assessment_id)
    if a.status != AssessmentStatus.complete:
        a.status = AssessmentStatus.complete
        a.completed_at = datetime.utcnow()
        # Keep the latest score on the record so the dashboard reflects it.
        result = score_assessment(a)
        a.overall_score = round(result.percentage, 1)
        a.risk_rating = result.risk_rating
        db.commit()
    return RedirectResponse(
        url=f"/assessments/{a.id}/summary", status_code=303
    )


@router.post("/{assessment_id}/reopen")
def reopen_assessment(assessment_id: int, db: Session = Depends(get_db)):
    """Reopen a completed assessment so answers can be edited again."""
    a = _get_assessment_or_404(db, assessment_id)
    if a.status != AssessmentStatus.in_progress:
        a.status = AssessmentStatus.in_progress
        a.completed_at = None
        db.commit()
    return RedirectResponse(
        url=f"/assessments/{a.id}/summary", status_code=303
    )


@router.post("/{assessment_id}/delete")
def delete_assessment(assessment_id: int, db: Session = Depends(get_db)):
    a = _get_assessment_or_404(db, assessment_id)
    client_id = a.client_id

    # Best-effort cleanup of every file produced for this assessment, including
    # Nessus CSV and generated PDF reports. The DB rows themselves cascade.
    _delete_assessment_files(a)

    db.delete(a)
    db.commit()
    return RedirectResponse(url=f"/clients/{client_id}", status_code=303)
