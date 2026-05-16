"""amtsbezeichnung im profil

Revision ID: 007_amtsbezeichnung
Revises: 006_standard_verkehrsmittel
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "007_amtsbezeichnung"
down_revision: str | None = "006_standard_verkehrsmittel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_profiles") as batch:
        batch.add_column(sa.Column("amtsbezeichnung", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_profiles") as batch:
        batch.drop_column("amtsbezeichnung")
