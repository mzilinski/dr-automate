"""anordnende_dienststelle im profil

Revision ID: 005_anordnende
Revises: 004_bezahlt_email
Create Date: 2026-05-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005_anordnende"
down_revision: str | None = "004_bezahlt_email"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_profiles") as batch:
        batch.add_column(sa.Column("anordnende_dienststelle", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_profiles") as batch:
        batch.drop_column("anordnende_dienststelle")
