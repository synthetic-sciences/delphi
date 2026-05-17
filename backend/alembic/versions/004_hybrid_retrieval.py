"""hybrid_retrieval

Revision ID: 004_hybrid_retrieval
Revises: 003_docs_sources
Create Date: 2026-05-10

Adds infrastructure for hybrid retrieval: vector + BM25/full-text + trigram +
exact symbol/path lookup. Pure-vector search loses too much precision on
identifier-heavy queries — agents looking for ``handleAuthCallback`` should
hit it on the first try, not get a list of semantically-similar middleware
functions.

Adds:
- ``pg_trgm`` extension (already enabled by some hosts; idempotent).
- GIN trigram indexes on ``code_chunks.content`` and ``symbols.name`` for
  fast LIKE / similarity() queries.
- ``code_chunks.content_tsv`` generated column + GIN index for BM25-style
  full-text matching.
- ``code_chunks.path_lookup`` index on ``file_id`` ordered by chunk_index
  to support quick context expansion (already exists via unique_file_chunk
  but we add a covering index on file_path through repository_files).

The columns and indexes are nullable / IF NOT EXISTS so the migration is
safe to re-run on partially-bootstrapped databases.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "004_hybrid_retrieval"
down_revision: Union[str, None] = "003_docs_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, name: str) -> bool:
    """Return True if the table exists in the public schema."""
    import sqlalchemy as sa
    return bool(
        bind.execute(
            sa.text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = 'public' AND table_name = :name"
                ")"
            ),
            {"name": name},
        ).scalar()
    )


def upgrade() -> None:
    # 1. pg_trgm: trigram similarity for fuzzy identifier matching.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Tables may not exist yet if the DB was created from SQLAlchemy models
    # only (no setup_local.sql). We skip the table-modifying steps in that
    # case — they'll get applied by the next migration or when the model
    # initialiser re-runs against the upgraded schema.
    bind = op.get_bind()

    if _table_exists(bind, "code_chunks"):
        # 2. GIN trigram index on code_chunks.content. Speeds up LIKE
        #    '%token%' queries from O(N) seq scan to O(log N) lookup.
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_code_chunks_content_trgm
            ON code_chunks
            USING gin (content gin_trgm_ops)
            """
        )
        # 5. tsvector generated column on code_chunks for BM25-style ranking.
        op.execute(
            """
            ALTER TABLE code_chunks
            ADD COLUMN IF NOT EXISTS content_tsv tsvector
            GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_code_chunks_content_tsv
            ON code_chunks
            USING gin (content_tsv)
            """
        )
        # 7. Symbol-name trigram index.
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_code_chunks_symbol_names_trgm
            ON code_chunks
            USING gin (symbol_names gin_trgm_ops)
            WHERE symbol_names IS NOT NULL
            """
        )

    if _table_exists(bind, "symbols"):
        # 3. GIN trigram indexes on symbols for exact/fuzzy symbol lookup.
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_symbols_name_trgm
            ON symbols
            USING gin (name gin_trgm_ops)
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_symbols_qualified_name_trgm
            ON symbols
            USING gin (qualified_name gin_trgm_ops)
            """
        )

    if _table_exists(bind, "repository_files"):
        # 4. GIN trigram index on file_path for exact-path / glob queries.
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_repository_files_path_trgm
            ON repository_files
            USING gin (file_path gin_trgm_ops)
            """
        )

    if _table_exists(bind, "paper_chunks"):
        # 6. Same tsvector trick for paper_chunks so BM25 lights up paper
        #    search too.
        op.execute(
            """
            ALTER TABLE paper_chunks
            ADD COLUMN IF NOT EXISTS content_tsv tsvector
            GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_paper_chunks_content_tsv
            ON paper_chunks
            USING gin (content_tsv)
            """
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_code_chunks_symbol_names_trgm")
    op.execute("DROP INDEX IF EXISTS idx_paper_chunks_content_tsv")
    op.execute("ALTER TABLE paper_chunks DROP COLUMN IF EXISTS content_tsv")
    op.execute("DROP INDEX IF EXISTS idx_code_chunks_content_tsv")
    op.execute("ALTER TABLE code_chunks DROP COLUMN IF EXISTS content_tsv")
    op.execute("DROP INDEX IF EXISTS idx_repository_files_path_trgm")
    op.execute("DROP INDEX IF EXISTS idx_symbols_qualified_name_trgm")
    op.execute("DROP INDEX IF EXISTS idx_symbols_name_trgm")
    op.execute("DROP INDEX IF EXISTS idx_code_chunks_content_trgm")
    # Don't drop pg_trgm — other migrations / extensions may use it.
