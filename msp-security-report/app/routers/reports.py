"""Report generation and download routes."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.dependencies import get_db, report_dir_path
from app.models import Assessment, AssessmentStatus, GeneratedReport
from app.services.report_generator import generate_report_pdf


router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/assessments/{assessment_id}/generate")
def generate(assessment_id: int, db: Session = Depends(get_db)):
    a = db.get(Assessment, assessment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Assessment not found")

    record = generate_report_pdf(db, a)

    # Mark assessment as complete on first successful PDF generation.
    if a.status != AssessmentStatus.complete:
        a.status = AssessmentStatus.complete
        a.completed_at = datetime.utcnow()
        db.commit()

    # Send the user back to the summary page rather than straight into the file
    # download. This guarantees they see the freshly generated report in the
    # report history list (and the client dashboard reflects it on next view),
    # while the summary template auto-triggers a download of the new report so
    # the convenience of the previous flow is preserved.
    return RedirectResponse(
        url=f"/assessments/{a.id}/summary?generated={record.id}",
        status_code=303,
    )


@router.get("/{report_id}/download")
def download(report_id: int, db: Session = Depends(get_db)):
    record = db.get(GeneratedReport, report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found")

    base = report_dir_path().resolve()
    path = (base / record.filename).resolve()
    # Guard against a corrupted DB row trying to escape the report directory.
    try:
        path.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report path.")

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Report file is missing on disk. Re-generate the report from the "
                "assessment summary page."
            ),
        )

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=record.filename,
    )
