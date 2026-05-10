"""thesis_connector

Revision ID: 005_thesis_connector
Revises: 004_hybrid_retrieval
Create Date: 2026-05-10

Adds the Thesis source-type so Delphi can index Thesis nodes, artifacts,
executions, tool contracts, and graph edges. Thesis is the long-running
research workflow system upstream — agents working in Thesis need to know
"what has already been tried", "what artifacts exist", and "what tool
contracts apply to this task".

Tables:
- thesis_workspaces  : top-level project / repo of Thesis nodes.
- thesis_nodes       : nodes in the graph (claims, hypotheses, plans, etc.).
- thesis_node_chunks : chunked node summaries + content for embedding.
- thesis_node_chunk_embeddings : pgvector embeddings.
- thesis_edges       : parent/child + named edges between nodes.
- thesis_artifacts   : tables, plots, logs, diffs produced by node executions.
- thesis_executions  : run logs / outputs / status for a node.
- thesis_tool_contracts : per-tool docs (signature + when_to_use + examples).
- user_thesis_workspaces : access link.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "005_thesis_connector"
down_revision: Union[str, None] = "004_hybrid_retrieval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Workspaces — top-level grouping (Thesis project / experiment campaign).
    op.create_table(
        "thesis_workspaces",
        sa.Column("workspace_id", sa.String(length=36), primary_key=True),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("indexed_by", sa.String(length=36), nullable=True),
        sa.Column(
            "is_public", sa.Boolean(), nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("nodes_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifacts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tags", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "indexed_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("external_id", name="uq_thesis_workspaces_external"),
    )
    op.create_index(
        "idx_thesis_workspaces_indexed_by",
        "thesis_workspaces", ["indexed_by"],
    )

    # Nodes — claims/hypotheses/plans/decisions in the Thesis graph.
    op.create_table(
        "thesis_nodes",
        sa.Column("node_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(length=36),
            sa.ForeignKey("thesis_workspaces.workspace_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column(
            "node_type", sa.String(length=64), nullable=False,
            comment="claim/hypothesis/plan/decision/insight/run/etc.",
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("tags", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("decision_rationale", sa.Text(), nullable=True),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column("is_committed", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("workspace_id", "external_id",
                            name="uq_thesis_nodes_workspace_external"),
    )
    op.create_index("idx_thesis_nodes_workspace", "thesis_nodes", ["workspace_id"])
    op.create_index("idx_thesis_nodes_type", "thesis_nodes", ["node_type"])
    op.create_index("idx_thesis_nodes_status", "thesis_nodes", ["status"])
    op.create_index("idx_thesis_nodes_outcome", "thesis_nodes", ["outcome"])

    # Node chunks — chunked content for embedding-based retrieval.
    op.create_table(
        "thesis_node_chunks",
        sa.Column("chunk_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "node_id", sa.String(length=36),
            sa.ForeignKey("thesis_nodes.node_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id", sa.String(length=36),
            sa.ForeignKey("thesis_workspaces.workspace_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "chunk_kind", sa.String(length=24), nullable=False,
            comment="summary | content | rationale | outcome",
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_thesis_node_chunks_node", "thesis_node_chunks", ["node_id"]
    )
    # Full-text + trigram so hybrid retrieval works on the graph too.
    op.execute(
        """
        ALTER TABLE thesis_node_chunks
        ADD COLUMN content_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED
        """
    )
    op.execute(
        "CREATE INDEX idx_thesis_node_chunks_tsv "
        "ON thesis_node_chunks USING gin(content_tsv)"
    )
    op.execute(
        "CREATE INDEX idx_thesis_node_chunks_content_trgm "
        "ON thesis_node_chunks USING gin(content gin_trgm_ops)"
    )

    # Embeddings — vector(768) to match the global embedding dim.
    op.execute(
        """
        CREATE TABLE thesis_node_chunk_embeddings (
            embedding_id VARCHAR(36) PRIMARY KEY,
            workspace_id VARCHAR(36) NOT NULL
                REFERENCES thesis_workspaces(workspace_id) ON DELETE CASCADE,
            node_id VARCHAR(36) NOT NULL
                REFERENCES thesis_nodes(node_id) ON DELETE CASCADE,
            chunk_id VARCHAR(36) NOT NULL UNIQUE
                REFERENCES thesis_node_chunks(chunk_id) ON DELETE CASCADE,
            embedding vector(768) NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_thesis_node_emb_hnsw "
        "ON thesis_node_chunk_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # Edges — directed graph, with edge type ('parent','blocks','derives_from',etc.)
    op.create_table(
        "thesis_edges",
        sa.Column("edge_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(length=36),
            sa.ForeignKey("thesis_workspaces.workspace_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_node_id", sa.String(length=36),
            sa.ForeignKey("thesis_nodes.node_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_node_id", sa.String(length=36),
            sa.ForeignKey("thesis_nodes.node_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("edge_type", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "source_node_id", "target_node_id", "edge_type",
            name="uq_thesis_edges_triple",
        ),
    )
    op.create_index(
        "idx_thesis_edges_source", "thesis_edges", ["source_node_id", "edge_type"]
    )
    op.create_index(
        "idx_thesis_edges_target", "thesis_edges", ["target_node_id", "edge_type"]
    )

    # Artifacts — tables, plots, logs, diffs produced by node executions.
    op.create_table(
        "thesis_artifacts",
        sa.Column("artifact_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(length=36),
            sa.ForeignKey("thesis_workspaces.workspace_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "node_id", sa.String(length=36),
            sa.ForeignKey("thesis_nodes.node_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False,
                  comment="table | plot | log | diff | metric | model"),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("preview", sa.Text(), nullable=True),
        sa.Column("uri", sa.Text(), nullable=True),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_thesis_artifacts_workspace", "thesis_artifacts", ["workspace_id"]
    )
    op.create_index("idx_thesis_artifacts_node", "thesis_artifacts", ["node_id"])
    op.create_index("idx_thesis_artifacts_kind", "thesis_artifacts", ["kind"])
    op.execute(
        "CREATE INDEX idx_thesis_artifacts_preview_trgm "
        "ON thesis_artifacts USING gin(preview gin_trgm_ops) "
        "WHERE preview IS NOT NULL"
    )

    # Executions — run logs / status / outputs for a node.
    op.create_table(
        "thesis_executions",
        sa.Column("execution_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(length=36),
            sa.ForeignKey("thesis_workspaces.workspace_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "node_id", sa.String(length=36),
            sa.ForeignKey("thesis_nodes.node_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("tool", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("inputs", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_thesis_executions_node", "thesis_executions", ["node_id"]
    )
    op.create_index(
        "idx_thesis_executions_status", "thesis_executions", ["status"]
    )

    # Tool contracts — per-tool documentation (signature + when_to_use).
    op.create_table(
        "thesis_tool_contracts",
        sa.Column("contract_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(length=36),
            sa.ForeignKey("thesis_workspaces.workspace_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("when_to_use", sa.Text(), nullable=True),
        sa.Column("avoid_when", sa.Text(), nullable=True),
        sa.Column("signature", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("examples", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("tags", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "indexed_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_thesis_tool_contracts_tool",
        "thesis_tool_contracts", ["tool_name"],
    )
    op.execute(
        "CREATE INDEX idx_thesis_tool_when_trgm "
        "ON thesis_tool_contracts USING gin(when_to_use gin_trgm_ops) "
        "WHERE when_to_use IS NOT NULL"
    )

    # User access link.
    op.create_table(
        "user_thesis_workspaces",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "workspace_id", sa.String(length=36),
            sa.ForeignKey("thesis_workspaces.workspace_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("user_id", "workspace_id"),
    )


def downgrade() -> None:
    op.drop_table("user_thesis_workspaces")
    op.execute("DROP INDEX IF EXISTS idx_thesis_tool_when_trgm")
    op.drop_index(
        "idx_thesis_tool_contracts_tool", table_name="thesis_tool_contracts"
    )
    op.drop_table("thesis_tool_contracts")
    op.drop_index("idx_thesis_executions_status", table_name="thesis_executions")
    op.drop_index("idx_thesis_executions_node", table_name="thesis_executions")
    op.drop_table("thesis_executions")
    op.execute("DROP INDEX IF EXISTS idx_thesis_artifacts_preview_trgm")
    op.drop_index("idx_thesis_artifacts_kind", table_name="thesis_artifacts")
    op.drop_index("idx_thesis_artifacts_node", table_name="thesis_artifacts")
    op.drop_index(
        "idx_thesis_artifacts_workspace", table_name="thesis_artifacts"
    )
    op.drop_table("thesis_artifacts")
    op.drop_index("idx_thesis_edges_target", table_name="thesis_edges")
    op.drop_index("idx_thesis_edges_source", table_name="thesis_edges")
    op.drop_table("thesis_edges")
    op.execute("DROP INDEX IF EXISTS idx_thesis_node_emb_hnsw")
    op.execute("DROP TABLE IF EXISTS thesis_node_chunk_embeddings")
    op.execute("DROP INDEX IF EXISTS idx_thesis_node_chunks_content_trgm")
    op.execute("DROP INDEX IF EXISTS idx_thesis_node_chunks_tsv")
    op.execute("ALTER TABLE thesis_node_chunks DROP COLUMN IF EXISTS content_tsv")
    op.drop_index(
        "idx_thesis_node_chunks_node", table_name="thesis_node_chunks"
    )
    op.drop_table("thesis_node_chunks")
    op.drop_index("idx_thesis_nodes_outcome", table_name="thesis_nodes")
    op.drop_index("idx_thesis_nodes_status", table_name="thesis_nodes")
    op.drop_index("idx_thesis_nodes_type", table_name="thesis_nodes")
    op.drop_index("idx_thesis_nodes_workspace", table_name="thesis_nodes")
    op.drop_table("thesis_nodes")
    op.drop_index(
        "idx_thesis_workspaces_indexed_by", table_name="thesis_workspaces"
    )
    op.drop_table("thesis_workspaces")
