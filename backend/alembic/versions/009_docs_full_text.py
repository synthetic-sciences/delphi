"""docs_full_text

Revision ID: 009_docs_full_text
Revises: 008_source_visibility
Create Date: 2026-05-17

Adds a BM25-style full-text column to documentation_chunks. Code, paper,
and atlas-node chunks all got this in migration 004 / 005; docs were
vector-only, which underweights identifier-shaped queries like
``OAuth2PasswordBearer`` in conceptual doc retrieval.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_docs_full_text"
down_revision: Union[str, None] = "008_source_visibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE documentation_chunks
        ADD COLUMN IF NOT EXISTS content_tsv tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english',
                coalesce(heading, '') || ' ' || coalesce(content, '')
            )
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_documentation_chunks_content_tsv
        ON documentation_chunks
        USING gin (content_tsv)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_documentation_chunks_content_trgm
        ON documentation_chunks
        USING gin (content gin_trgm_ops)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS idx_documentation_chunks_content_trgm"
    )
    op.execute(
        "DROP INDEX IF EXISTS idx_documentation_chunks_content_tsv"
    )
    op.execute(
        "ALTER TABLE documentation_chunks DROP COLUMN IF EXISTS content_tsv"
    )
