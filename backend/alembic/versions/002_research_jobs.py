"""research_jobs

Revision ID: 002_research_jobs
Revises: 001_initial
Create Date: 2026-04-26

Reserved for async / oracle-mode research jobs. P0 runs every mode
synchronously inside the request, so this table stays empty until a
future change moves oracle to background processing. Created now so the
schema is stable when that lands and so future migrations stay linear.

Mirrors upstream synsc-context migration 019 (e23d4d8). Differences vs.
upstream:

- No RLS / `auth.uid()` policy: Delphi enforces auth at the HTTP layer,
  not Postgres. The owner-only policy upstream uses Supabase's
  ``auth.uid()``, which is unavailable here.
- Uses ``String(36)`` for UUID columns to match the rest of Delphi's
  schema (rather than the native ``UUID`` type upstream uses with
  ``gen_random_uuid()``).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_research_jobs"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_jobs",
        sa.Column("job_id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("source_ids", sa.ARRAY(sa.Text()), nullable=True),
        sa.Column("source_types", sa.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("answer_markdown", sa.Text(), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column(
            "tokens_in", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "tokens_out", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "latency_ms", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mode IN ('quick', 'deep', 'oracle')", name="research_jobs_mode_check"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="research_jobs_status_check",
        ),
    )

    op.create_index(
        "idx_research_jobs_user",
        "research_jobs",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_research_jobs_status",
        "research_jobs",
        ["status"],
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("idx_research_jobs_status", table_name="research_jobs")
    op.drop_index("idx_research_jobs_user", table_name="research_jobs")
    op.drop_table("research_jobs")
