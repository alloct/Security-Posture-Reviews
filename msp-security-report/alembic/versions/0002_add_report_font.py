"""Add report_font_family to msp_settings.

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-02 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("msp_settings") as batch:
        batch.add_column(
            sa.Column(
                "report_font_family",
                sa.String(length=120),
                nullable=False,
                server_default="Poppins",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("msp_settings") as batch:
        batch.drop_column("report_font_family")
