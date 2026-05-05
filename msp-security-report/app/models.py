"""SQLAlchemy ORM models for the MSP Security Posture Report application."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AssessmentStatus(str, enum.Enum):
    in_progress = "in_progress"
    complete = "complete"


class RiskRating(str, enum.Enum):
    critical = "Critical"
    high = "High"
    medium = "Medium"
    low = "Low"
    informational = "Informational"


class MSPSettings(Base):
    """Single-row table holding MSP branding for the report and UI."""

    __tablename__ = "msp_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Your MSP")
    logo_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    primary_color: Mapped[str] = mapped_column(String(16), nullable=False, default="#1f3a5f")
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    report_footer_text: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        default="Confidential - Prepared for the named client only.",
    )
    report_font_family: Mapped[str] = mapped_column(
        String(120), nullable=False, default="Poppins"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class Client(Base):
    """A managed customer of the MSP."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    industry: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    primary_contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    primary_contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    assessments: Mapped[List["Assessment"]] = relationship(
        "Assessment",
        back_populates="client",
        cascade="all, delete-orphan",
        order_by="Assessment.year.desc()",
    )


class Assessment(Base):
    """A single annual security posture assessment for a client."""

    __tablename__ = "assessments"
    __table_args__ = (UniqueConstraint("client_id", "year", name="uq_client_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AssessmentStatus] = mapped_column(
        Enum(AssessmentStatus, name="assessment_status"),
        default=AssessmentStatus.in_progress,
        nullable=False,
    )
    overall_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_rating: Mapped[Optional[RiskRating]] = mapped_column(
        Enum(RiskRating, name="risk_rating"), nullable=True
    )
    nessus_csv_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    nessus_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    client: Mapped[Client] = relationship("Client", back_populates="assessments")
    answers: Mapped[List["AssessmentAnswer"]] = relationship(
        "AssessmentAnswer",
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="AssessmentAnswer.id",
    )
    reports: Mapped[List["GeneratedReport"]] = relationship(
        "GeneratedReport",
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="GeneratedReport.generated_at.desc()",
    )


class AssessmentAnswer(Base):
    """Stores one answer to one question within an assessment."""

    __tablename__ = "assessment_answers"
    __table_args__ = (
        UniqueConstraint("assessment_id", "question_key", name="uq_assessment_question"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section: Mapped[str] = mapped_column(String(120), nullable=False)
    question_key: Mapped[str] = mapped_column(String(120), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Internal value (e.g. "yes", "partial", "no").
    answer_value: Mapped[str] = mapped_column(String(64), nullable=False)
    # Display label that was shown to the user (e.g. "Yes", "Partial", "No").
    answer_label: Mapped[str] = mapped_column(String(120), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    assessment: Mapped[Assessment] = relationship("Assessment", back_populates="answers")


class GeneratedReport(Base):
    """Tracks every PDF report that has been generated for an assessment."""

    __tablename__ = "generated_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    assessment: Mapped[Assessment] = relationship("Assessment", back_populates="reports")
