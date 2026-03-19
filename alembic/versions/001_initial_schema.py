"""Initial schema baseline.

Revision ID: 001_initial
Revises: None
Create Date: 2026-03-19

Idempotent: stamps the alembic version on an existing database
without modifying any tables. This allows Alembic to manage all
future migrations on databases that were created by setup_local.sql.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if the database already has tables (created by setup_local.sql).
    # If so, skip — this migration just establishes the Alembic baseline.
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = 'public' AND table_name = 'repositories'"
            ")"
        )
    )
    already_exists = result.scalar()

    if already_exists:
        # Tables already created by setup_local.sql — nothing to do.
        return

    # If this is a truly fresh database (no setup_local.sql), create the
    # pgvector extension. Table creation is handled by SQLAlchemy models
    # via Base.metadata.create_all() or subsequent migrations.
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))


def downgrade() -> None:
    # The initial migration is a baseline — downgrade is intentionally a no-op.
    pass
