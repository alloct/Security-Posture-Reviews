"""Feature pack: notes, executive summary override, archive setting,
recommendation overrides table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-06 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Per-answer evidence / context.
    with op.batch_alter_table("assessment_answers") as batch:
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))

    # 2) Per-assessment optional executive-summary narrative.
    with op.batch_alter_table("assessments") as batch:
        batch.add_column(
            sa.Column("executive_summary_override", sa.Text(), nullable=True)
        )

    # 3) Archive threshold (years) on MSP settings.
    with op.batch_alter_table("msp_settings") as batch:
        batch.add_column(
            sa.Column(
                "archive_after_years",
                sa.Integer(),
                nullable=False,
                server_default="5",
            )
        )

    # 4) Recommendation overrides table.
    op.create_table(
        "recommendation_overrides",
        sa.Column("question_key", sa.String(length=120), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("recommendation_overrides")

    with op.batch_alter_table("msp_settings") as batch:
        batch.drop_column("archive_after_years")

    with op.batch_alter_table("assessments") as batch:
        batch.drop_column("executive_summary_override")

    with op.batch_alter_table("assessment_answers") as batch:
        batch.drop_column("notes")
