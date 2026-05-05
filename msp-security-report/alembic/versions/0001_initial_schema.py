"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "msp_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("company_name", sa.String(length=255), nullable=False, server_default="Your MSP"),
        sa.Column("logo_filename", sa.String(length=255), nullable=True),
        sa.Column("primary_color", sa.String(length=16), nullable=False, server_default="#1f3a5f"),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=64), nullable=True),
        sa.Column("report_footer_text", sa.String(length=512), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("primary_contact_name", sa.String(length=255), nullable=True),
        sa.Column("primary_contact_email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_clients_name", "clients", ["name"])

    assessment_status = sa.Enum("in_progress", "complete", name="assessment_status")
    risk_rating = sa.Enum(
        "Critical", "High", "Medium", "Low", "Informational", name="risk_rating"
    )

    op.create_table(
        "assessments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("status", assessment_status, nullable=False, server_default="in_progress"),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("risk_rating", risk_rating, nullable=True),
        sa.Column("nessus_csv_filename", sa.String(length=255), nullable=True),
        sa.Column("nessus_summary", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_id", "year", name="uq_client_year"),
    )
    op.create_index("ix_assessments_client_id", "assessments", ["client_id"])

    op.create_table(
        "assessment_answers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "assessment_id",
            sa.Integer(),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section", sa.String(length=120), nullable=False),
        sa.Column("question_key", sa.String(length=120), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_value", sa.String(length=64), nullable=False),
        sa.Column("answer_label", sa.String(length=120), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("assessment_id", "question_key", name="uq_assessment_question"),
    )
    op.create_index(
        "ix_assessment_answers_assessment_id", "assessment_answers", ["assessment_id"]
    )

    op.create_table(
        "generated_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "assessment_id",
            sa.Integer(),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_generated_reports_assessment_id", "generated_reports", ["assessment_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_generated_reports_assessment_id", table_name="generated_reports")
    op.drop_table("generated_reports")
    op.drop_index("ix_assessment_answers_assessment_id", table_name="assessment_answers")
    op.drop_table("assessment_answers")
    op.drop_index("ix_assessments_client_id", table_name="assessments")
    op.drop_table("assessments")
    op.drop_index("ix_clients_name", table_name="clients")
    op.drop_table("clients")
    op.drop_table("msp_settings")
    sa.Enum(name="risk_rating").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="assessment_status").drop(op.get_bind(), checkfirst=True)
