"""add immutable context sessions, revisions, and handoffs

Revision ID: 018_context_sessions
Revises: 017_connector_sync
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "018_context_sessions"
down_revision: str | None = "017_connector_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS context_sessions (
            session_id VARCHAR(36) PRIMARY KEY
                DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) NOT NULL,
            name VARCHAR(255) NOT NULL,
            objective TEXT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'completed', 'archived')),
            sharing_policy VARCHAR(16) NOT NULL DEFAULT 'private'
                CHECK (sharing_policy IN ('private', 'shared')),
            expires_at TIMESTAMPTZ,
            parent_session_id VARCHAR(36)
                REFERENCES context_sessions(session_id) ON DELETE SET NULL,
            parent_revision_id VARCHAR(36),
            handoff_note TEXT,
            current_revision_id VARCHAR(36),
            current_revision INTEGER NOT NULL DEFAULT 0
                CHECK (current_revision >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (user_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_context_sessions_user
        ON context_sessions (user_id, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_context_sessions_parent
        ON context_sessions (parent_session_id)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS context_revisions (
            revision_id VARCHAR(36) PRIMARY KEY
                DEFAULT gen_random_uuid()::text,
            session_id VARCHAR(36) NOT NULL
                REFERENCES context_sessions(session_id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL
                CHECK (revision_number >= 1),
            parent_revision_id VARCHAR(36),
            token_budget INTEGER NOT NULL
                CHECK (token_budget BETWEEN 1 AND 200000),
            tokens_used INTEGER NOT NULL
                CHECK (
                    tokens_used >= 0
                    AND tokens_used <= token_budget
                ),
            state JSONB NOT NULL,
            pinned_snapshots JSONB NOT NULL,
            context_manifest JSONB NOT NULL,
            content_hash VARCHAR(64) NOT NULL
                CHECK (length(content_hash) = 64),
            summary_model VARCHAR(200),
            summary_version VARCHAR(200),
            created_by VARCHAR(36) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (session_id, revision_number)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_context_revisions_session
        ON context_revisions (session_id, revision_number DESC)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_context_sessions_parent_revision'
            ) THEN
                ALTER TABLE context_sessions
                    ADD CONSTRAINT fk_context_sessions_parent_revision
                    FOREIGN KEY (parent_revision_id)
                    REFERENCES context_revisions(revision_id)
                    ON DELETE SET NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_context_sessions_current_revision'
            ) THEN
                ALTER TABLE context_sessions
                    ADD CONSTRAINT fk_context_sessions_current_revision
                    FOREIGN KEY (current_revision_id)
                    REFERENCES context_revisions(revision_id)
                    ON DELETE SET NULL;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_context_revision_update()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'context revisions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_context_revisions_immutable
        ON context_revisions
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_context_revisions_immutable
        BEFORE UPDATE ON context_revisions
        FOR EACH ROW EXECUTE FUNCTION prevent_context_revision_update()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE context_sessions
            DROP CONSTRAINT IF EXISTS fk_context_sessions_current_revision
        """
    )
    op.execute(
        """
        ALTER TABLE context_sessions
            DROP CONSTRAINT IF EXISTS fk_context_sessions_parent_revision
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_context_revisions_immutable
        ON context_revisions
        """
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_context_revision_update()")
    op.execute("DROP TABLE IF EXISTS context_revisions")
    op.execute("DROP TABLE IF EXISTS context_sessions")
