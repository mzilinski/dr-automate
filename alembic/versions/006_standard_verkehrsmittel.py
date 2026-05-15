"""standard_verkehrsmittel im profil

Revision ID: 006_standard_verkehrsmittel
Revises: 005_anordnende
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "006_standard_verkehrsmittel"
down_revision: str | None = "005_anordnende"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_profiles") as batch:
        batch.add_column(sa.Column("standard_verkehrsmittel", sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_profiles") as batch:
        batch.drop_column("standard_verkehrsmittel")
