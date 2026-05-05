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

    return RedirectResponse(url=f"/reports/{record.id}/download", status_code=303)


@router.get("/{report_id}/download")
def download(report_id: int, db: Session = Depends(get_db)):
    record = db.get(GeneratedReport, report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found")

    path = report_dir_path() / record.filename
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Report file is missing on disk. Re-generate the report from the "
                "assessment summary page."
            ),
        )

    download_name = record.filename
    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=download_name,
    )
