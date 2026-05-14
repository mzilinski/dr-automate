"""bezahlt_datum + bezahlt-status + profile.email override

Revision ID: 004_bezahlt_email
Revises: 003_auto_save_flag
Create Date: 2026-05-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004_bezahlt_email"
down_revision: str | None = "003_auto_save_flag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Email-Override in user_profiles
    with op.batch_alter_table("user_profiles") as batch:
        batch.add_column(sa.Column("email", sa.String(length=254), nullable=True))

    # 2) bezahlt_datum + neuer Enum-Wert "bezahlt" in dienstreisen.
    #    SQLAlchemy-Enum auf SQLite erzeugt eine CHECK-Constraint mit fixer
    #    Werte-Liste — batch_alter_table copy-and-recreates die Tabelle mit
    #    neuer Constraint.
    new_enum = sa.Enum(
        "entwurf", "eingereicht", "genehmigt", "abgerechnet", "bezahlt", "verworfen",
        name="dienstreise_status",
    )
    with op.batch_alter_table("dienstreisen") as batch:
        batch.add_column(sa.Column("bezahlt_datum", sa.Date(), nullable=True))
        batch.alter_column(
            "status",
            existing_type=sa.Enum(
                "entwurf", "eingereicht", "genehmigt", "abgerechnet", "verworfen",
                name="dienstreise_status",
            ),
            type_=new_enum,
            existing_nullable=False,
        )


def downgrade() -> None:
    old_enum = sa.Enum(
        "entwurf", "eingereicht", "genehmigt", "abgerechnet", "verworfen",
        name="dienstreise_status",
    )
    with op.batch_alter_table("dienstreisen") as batch:
        # Daten mit 'bezahlt' zurueck auf 'abgerechnet' setzen, bevor Constraint enger wird
        batch.execute("UPDATE dienstreisen SET status='abgerechnet' WHERE status='bezahlt'")
        batch.alter_column(
            "status",
            existing_type=sa.Enum(
                "entwurf", "eingereicht", "genehmigt", "abgerechnet", "bezahlt", "verworfen",
                name="dienstreise_status",
            ),
            type_=old_enum,
            existing_nullable=False,
        )
        batch.drop_column("bezahlt_datum")
    with op.batch_alter_table("user_profiles") as batch:
        batch.drop_column("email")
