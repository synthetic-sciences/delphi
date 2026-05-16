"""context_blobs

Revision ID: 006_context_blobs
Revises: 005_thesis_connector
Create Date: 2026-05-17

Adds a named-context store so the same agent identity can carry an indexed
source set + preferences across IDEs (Cursor / Claude Code / Windsurf).
Mirrors Nia's nia.context save/load.

A context is just (user_id, name, payload) where payload is a JSONB blob
holding source_ids, source_types, default topic, default tokens, and an
optional thesis_workspace_id.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "006_context_blobs"
down_revision: Union[str, None] = "005_thesis_connector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "context_blobs",
        sa.Column("context_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "name", name="unique_user_context_name"),
    )
    op.create_index(
        "idx_context_blobs_user", "context_blobs", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_context_blobs_user", table_name="context_blobs")
    op.drop_table("context_blobs")
