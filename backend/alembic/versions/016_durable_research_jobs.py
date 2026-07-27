"""make asynchronous research jobs durable and replayable

Revision ID: 016_durable_research_jobs
Revises: 015_snapshot_search
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "016_durable_research_jobs"
down_revision: str | None = "015_snapshot_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE research_jobs
            ADD COLUMN IF NOT EXISTS auto_index BOOLEAN NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS auto_indexed JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS usage JSONB NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN IF NOT EXISTS worker_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3,
            ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """
    )
    op.execute(
        """
        ALTER TABLE research_jobs
            DROP CONSTRAINT IF EXISTS research_jobs_status_check
        """
    )
    op.execute(
        """
        ALTER TABLE research_jobs
            ADD CONSTRAINT research_jobs_status_check
            CHECK (
                status IN (
                    'pending',
                    'running',
                    'cancelling',
                    'completed',
                    'failed',
                    'cancelled'
                )
            )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS research_events (
            event_id VARCHAR(36) PRIMARY KEY,
            job_id VARCHAR(36) NOT NULL
                REFERENCES research_jobs(job_id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_research_events_job_seq UNIQUE (job_id, seq)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS research_messages (
            message_id VARCHAR(36) PRIMARY KEY,
            job_id VARCHAR(36) NOT NULL
                REFERENCES research_jobs(job_id) ON DELETE CASCADE,
            role VARCHAR(16) NOT NULL
                CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            citations JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_jobs_claim
        ON research_jobs (status, created_at)
        WHERE status = 'pending'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_events_job_seq
        ON research_events (job_id, seq)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_messages_job_created
        ON research_messages (job_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_research_messages_job_created")
    op.execute("DROP INDEX IF EXISTS idx_research_events_job_seq")
    op.execute("DROP INDEX IF EXISTS idx_research_jobs_claim")
    op.execute("DROP TABLE IF EXISTS research_messages")
    op.execute("DROP TABLE IF EXISTS research_events")
    op.execute(
        """
        ALTER TABLE research_jobs
            DROP CONSTRAINT IF EXISTS research_jobs_status_check
        """
    )
    op.execute(
        """
        UPDATE research_jobs
        SET status = 'failed',
            error_message = COALESCE(
                error_message,
                'Research job cancelled before schema downgrade'
            ),
            completed_at = COALESCE(completed_at, NOW()),
            updated_at = NOW()
        WHERE status IN ('cancelling', 'cancelled')
        """
    )
    op.execute(
        """
        ALTER TABLE research_jobs
            ADD CONSTRAINT research_jobs_status_check
            CHECK (status IN ('pending', 'running', 'completed', 'failed'))
        """
    )
    op.execute(
        """
        ALTER TABLE research_jobs
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS started_at,
            DROP COLUMN IF EXISTS max_attempts,
            DROP COLUMN IF EXISTS attempt_count,
            DROP COLUMN IF EXISTS worker_id,
            DROP COLUMN IF EXISTS usage,
            DROP COLUMN IF EXISTS auto_indexed,
            DROP COLUMN IF EXISTS auto_index
        """
    )
