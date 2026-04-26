"""docs_sources

Revision ID: 003_docs_sources
Revises: 002_research_jobs
Create Date: 2026-04-26

Adds the documentation source_type — sitemap-driven crawl + embed.
Mirrors upstream synsc-context migration 021 (b2a251d) without RLS
(Delphi enforces auth at the HTTP layer). Uses ``String(36)`` UUIDs to
match the rest of Delphi's schema, and the same 768-dim ``vector``
column as ``paper_chunk_embeddings`` so the shared sentence-transformers
embedder produces matching shapes.

Tables:
- documentation_sources
- documentation_chunks
- documentation_chunk_embeddings (with HNSW index on the vector column)
- user_documentation_sources
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_docs_sources"
down_revision: Union[str, None] = "002_research_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documentation_sources",
        sa.Column("docs_id", sa.String(length=36), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("sitemap_url", sa.Text(), nullable=True),
        sa.Column("indexed_by", sa.String(length=36), nullable=True),
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "pages_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "chunks_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "indexed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("url", name="uq_documentation_sources_url"),
    )
    op.create_index(
        "idx_docs_sources_indexed_by", "documentation_sources", ["indexed_by"]
    )

    op.create_table(
        "documentation_chunks",
        sa.Column("chunk_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "docs_id",
            sa.String(length=36),
            sa.ForeignKey("documentation_sources.docs_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_docs_chunks_docs", "documentation_chunks", ["docs_id"]
    )

    # Embeddings table — vector(768) column added via raw SQL since pgvector
    # isn't a first-class Alembic type. Matches paper_chunk_embeddings.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS documentation_chunk_embeddings (
            embedding_id VARCHAR(36) PRIMARY KEY,
            docs_id      VARCHAR(36) NOT NULL
                REFERENCES documentation_sources(docs_id) ON DELETE CASCADE,
            chunk_id     VARCHAR(36) NOT NULL
                REFERENCES documentation_chunks(chunk_id) ON DELETE CASCADE,
            embedding    vector(768) NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_docs_emb_hnsw
        ON documentation_chunk_embeddings
        USING hnsw (embedding vector_cosine_ops)
        """
    )
    op.create_index(
        "idx_docs_emb_chunk",
        "documentation_chunk_embeddings",
        ["chunk_id"],
    )

    op.create_table(
        "user_documentation_sources",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "docs_id",
            sa.String(length=36),
            sa.ForeignKey("documentation_sources.docs_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("user_id", "docs_id"),
    )


def downgrade() -> None:
    op.drop_table("user_documentation_sources")
    op.execute("DROP INDEX IF EXISTS idx_docs_emb_hnsw")
    op.drop_index(
        "idx_docs_emb_chunk", table_name="documentation_chunk_embeddings"
    )
    op.execute("DROP TABLE IF EXISTS documentation_chunk_embeddings")
    op.drop_index("idx_docs_chunks_docs", table_name="documentation_chunks")
    op.drop_table("documentation_chunks")
    op.drop_index(
        "idx_docs_sources_indexed_by", table_name="documentation_sources"
    )
    op.drop_table("documentation_sources")
