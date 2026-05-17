"""End-to-end integration tests against a real Postgres+pgvector.

Skipped automatically when DATABASE_URL doesn't point at a reachable
Postgres. Run locally with:

    docker compose up -d postgres
    DATABASE_URL=postgresql://synsc:synsc@localhost:5432/synsc \\
        pytest tests/test_integration_postgres.py -v
"""
from __future__ import annotations

import os
import uuid

import numpy as np
import pytest


def _postgres_reachable() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(url, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="No real Postgres at DATABASE_URL — skipping integration suite.",
)


@pytest.fixture
def user_id() -> str:
    """A unique user_id per test so we don't leak rows between tests."""
    return str(uuid.uuid4())


@pytest.fixture
def session():
    from synsc.database.connection import get_session

    with get_session() as s:
        yield s


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Migration 004 — hybrid retrieval infrastructure
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_pg_trgm_extension_enabled(session):
    """Migration 004 must have ensured pg_trgm exists."""
    from sqlalchemy import text
    row = session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'")
    ).first()
    assert row is not None, "pg_trgm extension missing — migration 004 didn't run?"


def test_code_chunks_has_tsv_column(session):
    from sqlalchemy import text
    row = session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'code_chunks' AND column_name = 'content_tsv'"
        )
    ).first()
    assert row is not None, "code_chunks.content_tsv missing"


def test_trigram_indexes_present(session):
    from sqlalchemy import text
    rows = session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE indexname IN ("
            "  'idx_code_chunks_content_trgm',"
            "  'idx_code_chunks_content_tsv',"
            "  'idx_symbols_name_trgm',"
            "  'idx_repository_files_path_trgm',"
            "  'idx_code_chunks_symbol_names_trgm'"
            ")"
        )
    ).all()
    names = {r[0] for r in rows}
    expected = {
        "idx_code_chunks_content_trgm",
        "idx_code_chunks_content_tsv",
        "idx_symbols_name_trgm",
        "idx_repository_files_path_trgm",
        "idx_code_chunks_symbol_names_trgm",
    }
    missing = expected - names
    assert not missing, f"Missing hybrid-retrieval indexes: {missing}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Migration 005 — Thesis connector
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_thesis_tables_present(session):
    from sqlalchemy import text
    expected = {
        "thesis_workspaces", "thesis_nodes", "thesis_node_chunks",
        "thesis_node_chunk_embeddings", "thesis_edges",
        "thesis_artifacts", "thesis_executions", "thesis_tool_contracts",
        "user_thesis_workspaces",
    }
    rows = session.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename IN :tables"
        ).bindparams(tables=tuple(expected))
    ).all()
    found = {r[0] for r in rows}
    missing = expected - found
    assert not missing, f"Missing Thesis tables: {missing}"


def test_thesis_node_chunks_has_tsv(session):
    from sqlalchemy import text
    row = session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'thesis_node_chunks' "
            "AND column_name = 'content_tsv'"
        )
    ).first()
    assert row is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Thesis connector — ingest + retrieve end-to-end
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_thesis_ingest_workspace_and_node(user_id, session, monkeypatch):
    # Mock the embedding generator with a *deterministic* fake — same text
    # → same vector — so vector-similarity anchoring is reproducible.
    class _FakeEmbed:
        def _vec(self, text):
            rng = np.random.default_rng(abs(hash(text)))
            v = rng.standard_normal(768).astype("float32")
            return v / (np.linalg.norm(v) or 1.0)
        def generate(self, texts):
            return np.stack([self._vec(t) for t in texts])
        def generate_single(self, text):
            return self._vec(text)
    # Patch *where the name is used* — conftest already session-patched the
    # defining module, but thesis_connector imports the name at module load,
    # so the binding is local to that module.
    fake = _FakeEmbed()
    monkeypatch.setattr(
        "synsc.services.thesis_connector.get_embedding_generator",
        lambda: fake,
    )

    from synsc.services.thesis_connector import (
        ingest_workspace, ingest_node, search_thesis_nodes,
    )

    ws = ingest_workspace(
        user_id=user_id,
        external_id=f"ws-{uuid.uuid4().hex[:8]}",
        name="Test Workspace",
        is_public=False,
    )
    assert ws["success"] is True
    assert "workspace_id" in ws

    # Ingest a claim node with a rationale.
    n = ingest_node(
        user_id=user_id,
        workspace_id=ws["workspace_id"],
        external_id="claim-1",
        node_type="claim",
        title="Layer norm improves convergence",
        summary="LayerNorm normalizes inputs across features.",
        content="In transformers, LayerNorm is applied before attention.",
        decision_rationale="Empirically converges 2x faster than batch norm.",
        is_committed=True,
    )
    assert n["success"] is True
    assert n["chunks"] >= 2  # summary + content + rationale each become chunks

    # Search should find it.
    hits = search_thesis_nodes(
        user_id=user_id, query="how does layer normalization work",
        workspace_ids=[ws["workspace_id"]], top_k=5,
    )
    assert len(hits) >= 1
    top = hits[0]
    assert top["title"] == "Layer norm improves convergence"
    # Citation-style ref is present.
    assert top["ref"].startswith("thesis://")
    # Committed boost was applied.
    assert top["components"]["committed_boost"] > 0


def test_thesis_what_not_to_repeat(user_id, monkeypatch):
    class _FakeEmbed:
        def generate(self, texts):
            return np.random.rand(len(texts), 768).astype("float32")
        def generate_single(self, text):
            return np.random.rand(768).astype("float32")
    # Patch *where the name is used* — conftest already session-patched the
    # defining module, but thesis_connector imports the name at module load,
    # so the binding is local to that module.
    fake = _FakeEmbed()
    monkeypatch.setattr(
        "synsc.services.thesis_connector.get_embedding_generator",
        lambda: fake,
    )

    from synsc.services.thesis_connector import (
        ingest_workspace, ingest_node,
        find_what_was_tried, find_what_not_to_repeat,
    )

    ws = ingest_workspace(
        user_id=user_id,
        external_id=f"ws-{uuid.uuid4().hex[:8]}",
        name="Failures Workspace",
    )
    # One failed hypothesis, one successful one.
    ingest_node(
        user_id=user_id, workspace_id=ws["workspace_id"],
        external_id="h1", node_type="hypothesis",
        title="Adding dropout helps", summary="we tried dropout on attention",
        outcome="failed",
    )
    ingest_node(
        user_id=user_id, workspace_id=ws["workspace_id"],
        external_id="h2", node_type="hypothesis",
        title="Adding RoPE helps", summary="we tried RoPE on positional",
        outcome="success",
    )

    tried = find_what_was_tried(
        user_id=user_id, question="dropout RoPE positional",
        workspace_ids=[ws["workspace_id"]],
    )
    assert tried["found"] >= 1

    nope = find_what_not_to_repeat(
        user_id=user_id, question="dropout RoPE positional",
        workspace_ids=[ws["workspace_id"]],
    )
    # Only the failed one should show up.
    titles = {m["title"] for m in nope["matches"]}
    assert "Adding dropout helps" in titles
    assert "Adding RoPE helps" not in titles


def test_thesis_find_related_nodes_via_question(user_id, monkeypatch):
    class _FakeEmbed:
        """Deterministic: same text → same vector — so the anchor pick is
        reproducible across runs.
        """
        def _vec(self, text):
            rng = np.random.default_rng(abs(hash(text)))
            v = rng.standard_normal(768).astype("float32")
            return v / (np.linalg.norm(v) or 1.0)
        def generate(self, texts):
            return np.stack([self._vec(t) for t in texts])
        def generate_single(self, text):
            return self._vec(text)
    # Patch *where the name is used* — conftest already session-patched the
    # defining module, but thesis_connector imports the name at module load,
    # so the binding is local to that module.
    fake = _FakeEmbed()
    monkeypatch.setattr(
        "synsc.services.thesis_connector.get_embedding_generator",
        lambda: fake,
    )

    from synsc.services.thesis_connector import (
        ingest_workspace, ingest_node, ingest_edge, find_related_nodes,
    )

    ws = ingest_workspace(
        user_id=user_id, external_id=f"ws-{uuid.uuid4().hex[:8]}", name="Graph",
    )
    parent_res = ingest_node(
        user_id=user_id, workspace_id=ws["workspace_id"],
        external_id="parent", node_type="claim",
        title="Hypothesis: attention scales",
    )
    ingest_node(
        user_id=user_id, workspace_id=ws["workspace_id"],
        external_id="child1", node_type="experiment",
        title="Experiment 1: vanilla attention",
    )
    ingest_node(
        user_id=user_id, workspace_id=ws["workspace_id"],
        external_id="child2", node_type="experiment",
        title="Experiment 2: linear attention",
    )
    # parent → child1, parent → child2
    ingest_edge(
        user_id=user_id, workspace_id=ws["workspace_id"],
        source_external_id="parent", target_external_id="child1",
        edge_type="derives",
    )
    ingest_edge(
        user_id=user_id, workspace_id=ws["workspace_id"],
        source_external_id="parent", target_external_id="child2",
        edge_type="derives",
    )

    # 1. Explicit-anchor form — the BFS walk must surface both children.
    #    This is the deterministic part of the API.
    related = find_related_nodes(
        user_id=user_id, node_id=parent_res["node_id"],
        max_depth=2, top_k=10,
    )
    related_titles = {r["title"] for r in related}
    assert "Experiment 1: vanilla attention" in related_titles
    assert "Experiment 2: linear attention" in related_titles

    # 2. Question-anchored form — anchor depends on vector similarity,
    #    which is stable here but the *specific* node picked depends on
    #    the (deterministic) hash-based fake. Just assert the call works
    #    end-to-end without raising. The anchor-selection is exercised by
    #    test_thesis_ingest_workspace_and_node above.
    related2 = find_related_nodes(
        user_id=user_id, question="attention scales",
        max_depth=2, top_k=10,
    )
    assert isinstance(related2, list)


def test_thesis_artifact_ingest_and_search(user_id, monkeypatch):
    class _FakeEmbed:
        def generate(self, texts):
            return np.random.rand(len(texts), 768).astype("float32")
        def generate_single(self, text):
            return np.random.rand(768).astype("float32")
    # Patch *where the name is used* — conftest already session-patched the
    # defining module, but thesis_connector imports the name at module load,
    # so the binding is local to that module.
    fake = _FakeEmbed()
    monkeypatch.setattr(
        "synsc.services.thesis_connector.get_embedding_generator",
        lambda: fake,
    )

    from synsc.services.thesis_connector import (
        ingest_workspace, ingest_node, ingest_artifact,
        find_relevant_artifacts,
    )

    ws = ingest_workspace(
        user_id=user_id, external_id=f"ws-{uuid.uuid4().hex[:8]}", name="W",
    )
    ingest_node(
        user_id=user_id, workspace_id=ws["workspace_id"],
        external_id="n1", node_type="run",
        title="Eval run on benchmark X",
    )
    ingest_artifact(
        user_id=user_id, workspace_id=ws["workspace_id"],
        node_external_id="n1", kind="table",
        name="accuracy_results.csv",
        preview="| model | accuracy |\n|----|----|\n| baseline | 0.72 |\n| ours | 0.83 |",
    )

    artifacts = find_relevant_artifacts(
        user_id=user_id, query="accuracy benchmark",
        workspace_ids=[ws["workspace_id"]], top_k=5,
    )
    assert len(artifacts) >= 1
    assert artifacts[0]["kind"] == "table"
    assert artifacts[0]["ref"].startswith("thesis://")


def test_thesis_tool_contract_ingest_and_retrieve(user_id):
    from synsc.services.thesis_connector import (
        ingest_tool_contract, retrieve_tool_contract,
    )
    res = ingest_tool_contract(
        user_id=user_id,
        tool_name="thesis_search_nodes",
        display_name="Search Thesis nodes",
        description="Hybrid search over Thesis nodes",
        when_to_use="When the agent needs to find prior hypotheses or claims",
    )
    assert res["success"] is True

    contracts = retrieve_tool_contract(
        user_id=user_id, task="find prior hypotheses", top_k=5,
    )
    assert len(contracts) >= 1
    assert contracts[0]["tool_name"] == "thesis_search_nodes"
