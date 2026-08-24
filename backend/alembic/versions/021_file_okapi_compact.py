"""compact file-level Okapi lexical storage to JSONB term maps

Revision ID: 021_file_okapi_compact
Revises: 020_symbol_parent_index
Create Date: 2026-08-24
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "021_file_okapi_compact"
down_revision: Union[str, None] = "020_symbol_parent_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE repository_file_lexical_documents
          ADD COLUMN IF NOT EXISTS term_frequencies JSONB;

        UPDATE repository_file_lexical_documents AS d
        SET term_frequencies = agg.term_frequencies
        FROM (
            SELECT file_id,
                   jsonb_object_agg(term, term_frequency ORDER BY term)
                       AS term_frequencies
            FROM repository_file_lexical_terms
            GROUP BY file_id
        ) AS agg
        WHERE d.file_id = agg.file_id;

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM repository_file_lexical_documents
                WHERE term_frequencies IS NULL
                   OR term_frequencies = '{}'::jsonb
            ) THEN
                RAISE EXCEPTION
                    'file okapi compact migration: document with null or empty term_frequencies';
            END IF;
        END $$;

        ALTER TABLE repository_file_lexical_documents
          ALTER COLUMN term_frequencies SET NOT NULL;

        ALTER TABLE repository_file_lexical_documents
          ADD CONSTRAINT ck_file_lexical_documents_nonempty_terms
          CHECK (
              jsonb_typeof(term_frequencies) = 'object'
              AND term_frequencies <> '{}'::jsonb
          );

        CREATE INDEX IF NOT EXISTS idx_file_lexical_term_keys
        ON repository_file_lexical_documents
        USING GIN (term_frequencies);

        DROP TABLE IF EXISTS repository_file_lexical_terms;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE repository_file_lexical_terms (
          file_id UUID NOT NULL
            REFERENCES repository_files(file_id) ON DELETE CASCADE,
          repo_id UUID NOT NULL
            REFERENCES repositories(repo_id) ON DELETE CASCADE,
          term VARCHAR(128) NOT NULL,
          term_frequency INTEGER NOT NULL CHECK (term_frequency > 0),
          PRIMARY KEY (file_id, term)
        );

        CREATE INDEX idx_file_lexical_terms_scope
        ON repository_file_lexical_terms (repo_id, term, file_id);

        INSERT INTO repository_file_lexical_terms
            (file_id, repo_id, term, term_frequency)
        SELECT d.file_id,
               d.repo_id,
               kv.key AS term,
               (kv.value)::text::integer AS term_frequency
        FROM repository_file_lexical_documents AS d,
             jsonb_each_text(d.term_frequencies) AS kv(key, value);

        DROP INDEX IF EXISTS idx_file_lexical_term_keys;

        ALTER TABLE repository_file_lexical_documents
          DROP CONSTRAINT IF EXISTS ck_file_lexical_documents_nonempty_terms;

        ALTER TABLE repository_file_lexical_documents
          DROP COLUMN IF EXISTS term_frequencies;
        """
    )
