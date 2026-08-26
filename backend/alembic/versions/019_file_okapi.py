"""persist file-level Okapi lexical statistics

Revision ID: 019_file_okapi
Revises: 018_context_sessions
Create Date: 2026-08-24
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "019_file_okapi"
down_revision: Union[str, None] = "018_context_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE repositories
          ADD COLUMN IF NOT EXISTS file_okapi_index_version VARCHAR(32),
          ADD COLUMN IF NOT EXISTS file_okapi_documents_count
            INTEGER NOT NULL DEFAULT 0;

        CREATE TABLE IF NOT EXISTS repository_file_lexical_documents (
          file_id UUID PRIMARY KEY
            REFERENCES repository_files(file_id) ON DELETE CASCADE,
          repo_id UUID NOT NULL
            REFERENCES repositories(repo_id) ON DELETE CASCADE,
          document_length INTEGER NOT NULL CHECK (document_length > 0),
          content_hash VARCHAR(64) NOT NULL,
          index_version VARCHAR(32) NOT NULL
        );

        CREATE TABLE IF NOT EXISTS repository_file_lexical_terms (
          file_id UUID NOT NULL
            REFERENCES repository_files(file_id) ON DELETE CASCADE,
          repo_id UUID NOT NULL
            REFERENCES repositories(repo_id) ON DELETE CASCADE,
          term VARCHAR(128) NOT NULL,
          term_frequency INTEGER NOT NULL CHECK (term_frequency > 0),
          PRIMARY KEY (file_id, term)
        );

        CREATE INDEX IF NOT EXISTS idx_file_lexical_terms_scope
        ON repository_file_lexical_terms (repo_id, term, file_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS repository_file_lexical_terms;
        DROP TABLE IF EXISTS repository_file_lexical_documents;
        ALTER TABLE repositories
          DROP COLUMN IF EXISTS file_okapi_documents_count,
          DROP COLUMN IF EXISTS file_okapi_index_version;
        """
    )
