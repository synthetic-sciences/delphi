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


def upgrade() -> None:
    # 1. pg_trgm: trigram similarity for fuzzy identifier matching.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 2. GIN trigram index on code_chunks.content. Speeds up LIKE '%token%'
    #    queries from O(N) seq scan to O(log N) index lookup. Used by the
    #    BM25/keyword candidate stage in the hybrid retrieval pipeline.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_code_chunks_content_trgm
        ON code_chunks
        USING gin (content gin_trgm_ops)
        """
    )

    # 3. GIN trigram index on symbols.name and qualified_name for exact /
    #    fuzzy symbol lookup.
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

    # 4. GIN trigram index on repository_files.file_path so exact-path /
    #    glob-style queries can hit the index instead of seq-scanning every
    #    file in a 30k-file repo.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_repository_files_path_trgm
        ON repository_files
        USING gin (file_path gin_trgm_ops)
        """
    )

    # 5. tsvector generated column on code_chunks for BM25-style ranking.
    #    Postgres' ts_rank_cd is close enough to BM25 in practice and avoids
    #    pulling in a new dependency. The column is GENERATED so it stays in
    #    sync with content automatically.
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

    # 6. Same for paper_chunks — paper search currently uses pure vector,
    #    we add tsvector so we can blend BM25 into paper search too.
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

    # 7. Symbol-name index on code_chunks.symbol_names (stored as JSON-encoded
    #    text). LIKE '%"SymbolName"%' is fine for the volumes we deal with;
    #    GIN trgm on the text column makes it fast enough.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_code_chunks_symbol_names_trgm
        ON code_chunks
        USING gin (symbol_names gin_trgm_ops)
        WHERE symbol_names IS NOT NULL
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
