"""add durable incremental connector synchronization

Revision ID: 017_connector_sync
Revises: 016_durable_research_jobs
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "017_connector_sync"
down_revision: str | None = "016_durable_research_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE source_snapshots
            DROP CONSTRAINT IF EXISTS ck_source_snapshots_type
        """
    )
    op.execute(
        """
        ALTER TABLE source_snapshots
            ADD CONSTRAINT ck_source_snapshots_type CHECK (
                source_type IN ('repo', 'paper', 'dataset', 'docs', 'connector')
            )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS connector_sources (
            source_id VARCHAR(36) PRIMARY KEY
                DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL,
            indexed_by VARCHAR(36) NOT NULL,
            is_public BOOLEAN NOT NULL DEFAULT FALSE,
            provider VARCHAR(100) NOT NULL,
            display_name TEXT NOT NULL,
            external_ref TEXT NOT NULL,
            classification VARCHAR(16) NOT NULL DEFAULT 'private'
                CHECK (
                    classification IN (
                        'public', 'unlisted', 'private', 'local_sensitive'
                    )
                ),
            encrypted_config TEXT NOT NULL,
            encrypted_cursor TEXT,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            schedule_seconds INTEGER
                CHECK (
                    schedule_seconds IS NULL
                    OR schedule_seconds BETWEEN 60 AND 31536000
                ),
            next_sync_at TIMESTAMPTZ,
            last_synced_at TIMESTAMPTZ,
            last_snapshot_id VARCHAR(36),
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_connector_sources_owner_identity
                CHECK (user_id = indexed_by),
            CONSTRAINT ck_connector_sources_public_classification
                CHECK (is_public = (classification = 'public'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_connector_sources_user
        ON connector_sources (user_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_connector_sources_provider
        ON connector_sources (provider)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_connector_sources_due
        ON connector_sources (enabled, next_sync_at)
        WHERE enabled IS TRUE AND schedule_seconds IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_connector_sources (
            user_id VARCHAR(36) NOT NULL,
            source_id VARCHAR(36) NOT NULL
                REFERENCES connector_sources(source_id) ON DELETE CASCADE,
            added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, source_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_connector_sources_source
        ON user_connector_sources (source_id)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS connector_sync_jobs (
            job_id VARCHAR(36) PRIMARY KEY
                DEFAULT gen_random_uuid()::text,
            source_id VARCHAR(36) NOT NULL
                REFERENCES connector_sources(source_id) ON DELETE CASCADE,
            user_id VARCHAR(36) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (
                    status IN (
                        'pending', 'running', 'completed',
                        'failed', 'cancelled'
                    )
                ),
            priority INTEGER NOT NULL DEFAULT 0
                CHECK (priority BETWEEN -100 AND 100),
            worker_id VARCHAR(100),
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            lease_expires_at TIMESTAMPTZ,
            records_changed INTEGER NOT NULL DEFAULT 0,
            result_snapshot_id VARCHAR(36),
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_connector_sync_jobs_status
        ON connector_sync_jobs (status, priority DESC, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_connector_sync_jobs_source
        ON connector_sync_jobs (source_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_connector_sync_jobs_user
        ON connector_sync_jobs (user_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_connector_sync_jobs_active_source
        ON connector_sync_jobs (source_id)
        WHERE status IN ('pending', 'running')
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS connector_sync_jobs")
    op.execute("DELETE FROM source_snapshot_heads WHERE source_type = 'connector'")
    op.execute("DELETE FROM source_snapshots WHERE source_type = 'connector'")
    op.execute("DROP TABLE IF EXISTS user_connector_sources")
    op.execute("DROP TABLE IF EXISTS connector_sources")
    op.execute(
        """
        ALTER TABLE source_snapshots
            DROP CONSTRAINT IF EXISTS ck_source_snapshots_type
        """
    )
    op.execute(
        """
        ALTER TABLE source_snapshots
            ADD CONSTRAINT ck_source_snapshots_type CHECK (
                source_type IN ('repo', 'paper', 'dataset', 'docs')
            )
        """
    )
