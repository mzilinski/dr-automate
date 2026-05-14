"""initial schema: users, user_profiles, dienstreisen, abrechnungen, account_requests

Revision ID: 001_init
Revises:
Create Date: 2026-05-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "001_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("remote_user", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("tour_dismissed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("remote_user", name="uq_users_remote_user"),
    )
    op.create_index("ix_users_remote_user", "users", ["remote_user"])

    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("vorname", sa.String(length=100), nullable=True),
        sa.Column("nachname", sa.String(length=100), nullable=True),
        sa.Column("abteilung", sa.String(length=100), nullable=True),
        sa.Column("telefon", sa.String(length=50), nullable=True),
        sa.Column("adresse_privat", sa.String(length=2048), nullable=True),
        sa.Column("iban", sa.String(length=512), nullable=True),
        sa.Column("bic", sa.String(length=512), nullable=True),
        sa.Column("mitreisender_name_default", sa.String(length=200), nullable=True),
        sa.Column("rkr_default", sa.String(length=20), nullable=True),
        sa.Column("abrechnende_dienststelle", sa.String(length=200), nullable=True),
        sa.Column("bahncards", sa.String(length=4096), nullable=True),
        sa.Column("ai_provider_default", sa.String(length=50), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    dienstreise_status = sa.Enum(
        "entwurf", "eingereicht", "genehmigt", "abgerechnet", "verworfen", name="dienstreise_status"
    )
    abrechnung_status = sa.Enum("entwurf", "eingereicht", "abgeschlossen", name="abrechnung_status")

    op.create_table(
        "dienstreisen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("titel", sa.String(length=200), nullable=False),
        sa.Column("zielort", sa.String(length=300), nullable=True),
        sa.Column("status", dienstreise_status, nullable=False, server_default="entwurf"),
        sa.Column("antrag_json", sa.String(length=65536), nullable=True),
        sa.Column("antrag_pdf_path", sa.String(length=512), nullable=True),
        sa.Column("genehmigung_datum", sa.Date(), nullable=True),
        sa.Column("genehmigung_aktenzeichen", sa.String(length=100), nullable=True),
        sa.Column("start_datum", sa.Date(), nullable=True),
        sa.Column("ende_datum", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_dienstreisen_user_id", "dienstreisen", ["user_id"])
    op.create_index("ix_dienstreisen_status", "dienstreisen", ["status"])
    op.create_index("ix_dienstreisen_start_datum", "dienstreisen", ["start_datum"])
    op.create_index("idx_dienstreisen_user_status", "dienstreisen", ["user_id", "status"])

    op.create_table(
        "abrechnungen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "dienstreise_id",
            sa.Integer(),
            sa.ForeignKey("dienstreisen.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", abrechnung_status, nullable=False, server_default="entwurf"),
        sa.Column("abrechnung_json", sa.String(length=65536), nullable=True),
        sa.Column("abrechnung_pdf_path", sa.String(length=512), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_abrechnungen_dienstreise_id", "abrechnungen", ["dienstreise_id"])

    op.create_table(
        "account_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("begruendung", sa.Text(), nullable=True),
        sa.Column("remote_addr", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("fulfilled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_account_requests_email", "account_requests", ["email"])


def downgrade() -> None:
    op.drop_index("ix_account_requests_email", "account_requests")
    op.drop_table("account_requests")
    op.drop_index("ix_abrechnungen_dienstreise_id", "abrechnungen")
    op.drop_table("abrechnungen")
    op.drop_index("idx_dienstreisen_user_status", "dienstreisen")
    op.drop_index("ix_dienstreisen_start_datum", "dienstreisen")
    op.drop_index("ix_dienstreisen_status", "dienstreisen")
    op.drop_index("ix_dienstreisen_user_id", "dienstreisen")
    op.drop_table("dienstreisen")
    op.drop_table("user_profiles")
    op.drop_index("ix_users_remote_user", "users")
    op.drop_table("users")
    sa.Enum(name="dienstreise_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="abrechnung_status").drop(op.get_bind(), checkfirst=True)
