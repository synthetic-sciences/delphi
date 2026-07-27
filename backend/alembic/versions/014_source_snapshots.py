"""append-only content-addressed source snapshots

Revision ID: 014_source_snapshots
Revises: 013_visibility_contracts
Create Date: 2026-07-27

Copies normalized source chunks and their existing vectors into versioned,
append-only storage. A separate head table identifies the current snapshot
without mutating previously published content.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "014_source_snapshots"
down_revision: str | None = "013_visibility_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    for table in ("papers", "datasets", "documentation_sources"):
        op.execute(
            f"""
            ALTER TABLE {table}
            ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(255)
            """
        )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS source_snapshots (
            snapshot_id VARCHAR(36) PRIMARY KEY
                DEFAULT gen_random_uuid()::text,
            source_id VARCHAR(36) NOT NULL,
            source_type VARCHAR(24) NOT NULL,
            version TEXT NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            external_ref TEXT NOT NULL,
            display_name TEXT NOT NULL,
            classification VARCHAR(16) NOT NULL,
            item_count INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            embedding_model VARCHAR(255) NOT NULL,
            embedding_fingerprint VARCHAR(64) NOT NULL,
            vector_count INTEGER NOT NULL DEFAULT 0,
            vectors_complete BOOLEAN NOT NULL DEFAULT FALSE,
            created_by VARCHAR(36),
            manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sealed_at TIMESTAMPTZ,
            CONSTRAINT ck_source_snapshots_type CHECK (
                source_type IN ('repo', 'paper', 'dataset', 'docs')
            ),
            CONSTRAINT ck_source_snapshots_classification CHECK (
                classification IN (
                    'public', 'unlisted', 'private', 'local_sensitive'
                )
            ),
            CONSTRAINT uq_source_snapshot_version_content UNIQUE (
                source_type, source_id, version, content_hash,
                embedding_model, embedding_fingerprint
            ),
            CONSTRAINT ck_source_snapshot_vector_count CHECK (
                vector_count >= 0 AND vector_count <= item_count
            ),
            CONSTRAINT ck_source_snapshot_vector_completeness CHECK (
                vectors_complete = (vector_count = item_count)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_snapshots_source
        ON source_snapshots(source_type, source_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_snapshots_created
        ON source_snapshots(created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_snapshots_created_by
        ON source_snapshots(created_by)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS source_snapshot_items (
            item_id VARCHAR(36) PRIMARY KEY
                DEFAULT gen_random_uuid()::text,
            snapshot_id VARCHAR(36) NOT NULL
                REFERENCES source_snapshots(snapshot_id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            origin_item_id VARCHAR(36) NOT NULL,
            locator TEXT NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_source_snapshot_item_ordinal
                UNIQUE (snapshot_id, ordinal)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_snapshot_items_snapshot
        ON source_snapshot_items(snapshot_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_snapshot_items_origin
        ON source_snapshot_items(origin_item_id)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS source_snapshot_item_embeddings (
            embedding_id VARCHAR(36) PRIMARY KEY
                DEFAULT gen_random_uuid()::text,
            snapshot_id VARCHAR(36) NOT NULL
                REFERENCES source_snapshots(snapshot_id) ON DELETE CASCADE,
            item_id VARCHAR(36) NOT NULL UNIQUE
                REFERENCES source_snapshot_items(item_id) ON DELETE CASCADE,
            embedding vector(768) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_snapshot_item_embeddings_snapshot
        ON source_snapshot_item_embeddings(snapshot_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_snapshot_item_embeddings_item
        ON source_snapshot_item_embeddings(item_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_snapshot_item_embeddings_vector
        ON source_snapshot_item_embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS source_snapshot_heads (
            source_type VARCHAR(24) NOT NULL,
            source_id VARCHAR(36) NOT NULL,
            snapshot_id VARCHAR(36) NOT NULL
                REFERENCES source_snapshots(snapshot_id) ON DELETE RESTRICT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (source_type, source_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_snapshot_heads_snapshot
        ON source_snapshot_heads(snapshot_id)
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_source_snapshot_update()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.sealed_at IS NULL
               AND NEW.sealed_at IS NOT NULL
               AND (to_jsonb(OLD) - 'sealed_at')
                   = (to_jsonb(NEW) - 'sealed_at') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'published source snapshots are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_sealed_snapshot_item_change()
        RETURNS TRIGGER AS $$
        DECLARE
            target_snapshot_id VARCHAR(36);
            previous_snapshot_id VARCHAR(36);
        BEGIN
            IF TG_OP = 'INSERT' THEN
                target_snapshot_id := NEW.snapshot_id;
            ELSIF TG_OP = 'DELETE' THEN
                IF pg_trigger_depth() > 1 THEN
                    RETURN OLD;
                END IF;
                target_snapshot_id := OLD.snapshot_id;
            ELSE
                target_snapshot_id := NEW.snapshot_id;
                previous_snapshot_id := OLD.snapshot_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM source_snapshots
                WHERE snapshot_id IN (
                    target_snapshot_id,
                    previous_snapshot_id
                )
                  AND sealed_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'sealed source snapshot contents are immutable';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_source_snapshots_immutable
        ON source_snapshots
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_snapshots_immutable
        BEFORE UPDATE ON source_snapshots
        FOR EACH ROW EXECUTE FUNCTION prevent_source_snapshot_update()
        """
    )
    for table in (
        "source_snapshot_items",
        "source_snapshot_item_embeddings",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}"
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION prevent_sealed_snapshot_item_change()
            """
        )


def downgrade() -> None:
    for table in (
        "source_snapshot_item_embeddings",
        "source_snapshot_items",
        "source_snapshots",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}"
        )
    op.execute("DROP TABLE IF EXISTS source_snapshot_heads")
    op.execute("DROP TABLE IF EXISTS source_snapshot_item_embeddings")
    op.execute("DROP TABLE IF EXISTS source_snapshot_items")
    op.execute("DROP TABLE IF EXISTS source_snapshots")
    op.execute(
        "DROP FUNCTION IF EXISTS prevent_sealed_snapshot_item_change()"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_source_snapshot_update()")
    for table in ("documentation_sources", "datasets", "papers"):
        op.execute(
            f"ALTER TABLE {table} DROP COLUMN IF EXISTS embedding_model"
        )
