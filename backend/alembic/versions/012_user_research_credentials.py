"""encrypted per-user research provider credentials

Revision ID: 012_user_research_credentials
Revises: 011_durable_source_jobs
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "012_user_research_credentials"
down_revision: str | None = "011_durable_source_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_research_credentials (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(32) NOT NULL,
            encrypted_key TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_research_credentials_user_provider
                UNIQUE (user_id, provider),
            CONSTRAINT ck_user_research_credentials_provider
                CHECK (provider = 'gemini')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_research_credentials_user
        ON user_research_credentials (user_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_research_credentials")
