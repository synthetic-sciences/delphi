"""Reconcile source visibility contracts on deployed databases.

Revision ID: 013_visibility_contracts
Revises: 012_user_research_credentials
Create Date: 2026-07-26

Revision 008 originally gave every source type a ``public`` server default.
Papers are private by default in the application model, so databases already
stamped past revision 008 need a new migration to receive the corrected
contract. The migration also repairs paper rows where the old public default
conflicts with ``is_public = false`` and idempotently restores all visibility
columns, constraints, defaults, and indexes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "013_visibility_contracts"
down_revision: str | None = "012_user_research_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _reconcile_visibility(table: str, default: str) -> None:
    op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS visibility VARCHAR(16)")
    op.execute(
        f"UPDATE {table} SET visibility = CASE WHEN is_public THEN 'public' "
        "ELSE 'private' END WHERE visibility IS NULL"
    )
    op.execute(f"ALTER TABLE {table} ALTER COLUMN visibility SET DEFAULT '{default}'")
    op.execute(f"ALTER TABLE {table} ALTER COLUMN visibility SET NOT NULL")
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_visibility ON {table}(visibility)")


def upgrade() -> None:
    _reconcile_visibility("repositories", "public")
    _reconcile_visibility("papers", "private")
    op.execute(
        "UPDATE papers SET visibility = 'private' "
        "WHERE visibility = 'public' AND is_public IS NOT TRUE"
    )
    _reconcile_visibility("documentation_sources", "public")
    _reconcile_visibility("datasets", "public")


def downgrade() -> None:
    # Revision 008 used public as the server default for every source type.
    op.execute("ALTER TABLE papers ALTER COLUMN visibility SET DEFAULT 'public'")
