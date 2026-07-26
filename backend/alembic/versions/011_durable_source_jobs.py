"""durable generic source indexing jobs

Revision ID: 011_durable_source_jobs
Revises: 010_symbol_references
Create Date: 2026-07-27

Persists the complete /v1/sources async payload and adds a bounded retry
lease so work abandoned by a crashed worker can be reclaimed safely.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "011_durable_source_jobs"
down_revision: str | None = "010_symbol_references"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE indexing_jobs ADD COLUMN IF NOT EXISTS source_url TEXT")
    op.execute("ALTER TABLE indexing_jobs ADD COLUMN IF NOT EXISTS display_name TEXT")
    op.execute("ALTER TABLE indexing_jobs ADD COLUMN IF NOT EXISTS options JSONB")
    op.execute("ALTER TABLE indexing_jobs ADD COLUMN IF NOT EXISTS result_source_id VARCHAR(36)")
    op.execute(
        "ALTER TABLE indexing_jobs "
        "ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE indexing_jobs ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3"
    )
    op.execute("UPDATE indexing_jobs SET attempt_count = 0 WHERE attempt_count IS NULL")
    op.execute("UPDATE indexing_jobs SET max_attempts = 3 WHERE max_attempts IS NULL")
    op.execute(
        "ALTER TABLE indexing_jobs "
        "ALTER COLUMN attempt_count SET DEFAULT 0, "
        "ALTER COLUMN attempt_count SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE indexing_jobs "
        "ALTER COLUMN max_attempts SET DEFAULT 3, "
        "ALTER COLUMN max_attempts SET NOT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE indexing_jobs DROP COLUMN IF EXISTS max_attempts")
    op.execute("ALTER TABLE indexing_jobs DROP COLUMN IF EXISTS attempt_count")
    op.execute("ALTER TABLE indexing_jobs DROP COLUMN IF EXISTS result_source_id")
    op.execute("ALTER TABLE indexing_jobs DROP COLUMN IF EXISTS options")
    op.execute("ALTER TABLE indexing_jobs DROP COLUMN IF EXISTS display_name")
    op.execute("ALTER TABLE indexing_jobs DROP COLUMN IF EXISTS source_url")
