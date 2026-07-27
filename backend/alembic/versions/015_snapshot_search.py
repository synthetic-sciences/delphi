"""index immutable snapshot content for exact-version retrieval

Revision ID: 015_snapshot_search
Revises: 014_source_snapshots
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "015_snapshot_search"
down_revision: str | None = "014_source_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_snapshot_items_content_fts
        ON source_snapshot_items
        USING GIN (to_tsvector('simple', content))
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS idx_source_snapshot_items_content_fts"
    )
