"""Run Alembic migrations safely, including legacy databases.

This is invoked from the Docker entrypoint. It handles three cases:

1. Brand-new database (no tables): run `alembic upgrade head` to build the
   schema from scratch using the migrations.
2. Database that already has the application tables but no `alembic_version`
   row (this happens when a previous container created the schema via
   `Base.metadata.create_all`): stamp it at revision `0001` then upgrade.
3. Database that is already on Alembic: simply upgrade to head.
"""
from __future__ import annotations

import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database import engine


def run() -> None:
    cfg = Config("alembic.ini")

    print(f"[migrations] DATABASE_URL={engine.url!s}")
    insp = inspect(engine)
    table_names = set(insp.get_table_names())
    print(f"[migrations] Existing tables: {sorted(table_names) or '(none)'}")

    has_alembic = "alembic_version" in table_names
    has_app_tables = "msp_settings" in table_names

    # If alembic_version exists but is empty, treat as untracked.
    current_version: str | None = None
    if has_alembic:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
            current_version = row[0] if row else None
    print(f"[migrations] Current Alembic version: {current_version or '(none)'}")

    needs_stamp = has_app_tables and current_version is None
    if needs_stamp:
        # Schema produced by Base.metadata.create_all (or a partially-applied
        # earlier migration). Mark it as already at revision 0001 so subsequent
        # migrations apply cleanly without re-creating the existing tables.
        print("[migrations] Legacy / untracked schema detected; stamping at revision 0001")
        command.stamp(cfg, "0001")

    print("[migrations] Upgrading to head")
    command.upgrade(cfg, "head")
    print("[migrations] Done")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:  # pragma: no cover - bootstrap helper
        print(f"[migrations] FAILED: {exc}", file=sys.stderr)
        raise
