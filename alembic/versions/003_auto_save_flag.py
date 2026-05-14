"""add auto_save_dienstreisen-Flag to user_profiles

Revision ID: 003_auto_save_flag
Revises: 002_deepseek_key
Create Date: 2026-05-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003_auto_save_flag"
down_revision: str | None = "002_deepseek_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_profiles") as batch:
        batch.add_column(
            sa.Column("auto_save_dienstreisen", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("user_profiles") as batch:
        batch.drop_column("auto_save_dienstreisen")
