"""Paperless-Anbindung: Profil-Token + Upload-Warteschlange

Revision ID: 009_paperless
Revises: 008_api_keys
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "009_paperless"
down_revision: str | None = "008_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_profiles") as batch:
        batch.add_column(sa.Column("paperless_api_token", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("paperless_auto", sa.Boolean(), server_default=sa.false(), nullable=False))

    op.create_table(
        "paperless_uploads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dienstreise_id", sa.Integer(), sa.ForeignKey("dienstreisen.id", ondelete="CASCADE"), nullable=False),
        sa.Column("art", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("versuche", sa.Integer(), nullable=False),
        sa.Column("naechster_versuch", sa.DateTime(timezone=True), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("dokument_id", sa.Integer(), nullable=True),
        sa.Column("meldung", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("dienstreise_id", "art", name="uq_paperless_uploads_reise_art"),
    )


def downgrade() -> None:
    op.drop_table("paperless_uploads")
    with op.batch_alter_table("user_profiles") as batch:
        batch.drop_column("paperless_auto")
        batch.drop_column("paperless_api_token")
