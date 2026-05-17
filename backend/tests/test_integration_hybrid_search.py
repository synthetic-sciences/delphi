"""End-to-end hybrid-retrieval + context-pack tests against real Postgres.

Indexes a small repo by directly inserting chunks/symbols/embeddings,
then exercises ``hybrid_retrieve``, ``search_code`` (agent quality_mode),
``build_context_pack``, and ``get_chunk_context``.

Skipped automatically when DATABASE_URL doesn't point at Postgres.
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
    return str(uuid.uuid4())


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Replace the embedding generator with a deterministic fake.

    Each chunk's text → a 768-dim vector that's just the hash of the
    text mapped onto floats. Same text → same vector → reproducible
    similarity scores.
    """
    class _Fake:
        model_name = "fake-768"
        batch_size = 64

        def _vec(self, text):
            h = abs(hash(text))
            rng = np.random.default_rng(h)
            v = rng.standard_normal(768).astype("float32")
            return v / np.linalg.norm(v)

        def generate(self, texts):
            return np.stack([self._vec(t) for t in texts])

        def generate_single(self, text):
            return self._vec(text)

    instance = _Fake()
    # Patch each call site separately — the binding is module-local for any
    # consumer that ``from synsc.embeddings.generator import …`` at import
    # time, so patching the definition module alone is too late.
    for target in (
        "synsc.embeddings.generator.get_embedding_generator",
        "synsc.services.search_service.get_embedding_generator",
        "synsc.services.thesis_connector.get_embedding_generator",
    ):
        try:
            monkeypatch.setattr(target, lambda inst=instance: inst)
        except AttributeError:
            pass  # Name not imported at that path — fine.
    return instance


@pytest.fixture
def seeded_repo(user_id, fake_embeddings):
    """Insert a tiny repo with three chunks containing distinct symbols.

    Returns (repo_id, file_id, chunk_ids dict by symbol name).
    """
    from sqlalchemy import text
    from synsc.database.connection import get_session

    repo_id = str(uuid.uuid4())
    file_id = str(uuid.uuid4())
    chunks = {
        "handleAuthCallback": (
            f"async def handleAuthCallback(req):\n    return await verify(req)",
            1, 2, "function",
        ),
        "verifyToken": (
            f"def verifyToken(t):\n    return jwt.decode(t)",
            10, 11, "function",
        ),
        "render_homepage": (
            f"def render_homepage():\n    return 'hello'",
            20, 21, "function",
        ),
    }
    chunk_ids: dict[str, str] = {}
    sym_ids: dict[str, str] = {}

    with get_session() as session:
        # Repo + file
        session.execute(
            text(
                "INSERT INTO repositories "
                "(repo_id, url, owner, name, branch, indexed_by, is_public, deep_indexed) "
                "VALUES (:rid, :url, 'test', 'integ', 'main', :uid, FALSE, TRUE)"
            ),
            {"rid": repo_id, "url": f"https://test/{repo_id}", "uid": user_id},
        )
        session.execute(
            text(
                "INSERT INTO repository_files "
                "(file_id, repo_id, file_path, file_name, language) "
                "VALUES (:fid, :rid, 'src/auth.py', 'auth.py', 'python')"
            ),
            {"fid": file_id, "rid": repo_id},
        )
        # User collection link
        session.execute(
            text(
                "INSERT INTO user_repositories (user_id, repo_id) "
                "VALUES (:uid, :rid)"
            ),
            {"uid": user_id, "rid": repo_id},
        )

        for idx, (name, (content, start, end, ktype)) in enumerate(chunks.items()):
            cid = str(uuid.uuid4())
            chunk_ids[name] = cid
            session.execute(
                text(
                    "INSERT INTO code_chunks "
                    "(chunk_id, repo_id, file_id, chunk_index, content, "
                    " start_line, end_line, language, symbol_names) "
                    "VALUES (:cid, :rid, :fid, :idx, :content, :s, :e, "
                    " 'python', :sn)"
                ),
                {
                    "cid": cid, "rid": repo_id, "fid": file_id, "idx": idx,
                    "content": content, "s": start, "e": end,
                    "sn": f'["{name}"]',
                },
            )
            # Embedding
            emb = fake_embeddings.generate_single(content)
            emb_str = "[" + ",".join(str(x) for x in emb.tolist()) + "]"
            session.execute(
                text(
                    "INSERT INTO chunk_embeddings "
                    "(embedding_id, chunk_id, repo_id, embedding) "
                    "VALUES (:eid, :cid, :rid, CAST(:emb AS vector))"
                ),
                {
                    "eid": str(uuid.uuid4()), "cid": cid,
                    "rid": repo_id, "emb": emb_str,
                },
            )
            # Symbol
            sid = str(uuid.uuid4())
            sym_ids[name] = sid
            session.execute(
                text(
                    "INSERT INTO symbols "
                    "(symbol_id, repo_id, file_id, name, qualified_name, "
                    " symbol_type, start_line, end_line, language) "
                    "VALUES (:sid, :rid, :fid, :name, :qn, :stype, :s, :e, 'python')"
                ),
                {
                    "sid": sid, "rid": repo_id, "fid": file_id,
                    "name": name, "qn": name, "stype": ktype,
                    "s": start, "e": end,
                },
            )
        session.commit()

    return repo_id, file_id, chunk_ids, sym_ids


def test_hybrid_search_finds_exact_symbol(user_id, seeded_repo, fake_embeddings):
    """Exact symbol match should outrank semantically-similar decoys."""
    from synsc.services.search_service import SearchService

    repo_id, _, chunk_ids, _ = seeded_repo
    svc = SearchService(user_id=user_id)
    res = svc.search_code(
        query="handleAuthCallback",
        repo_ids=[repo_id], top_k=5, user_id=user_id,
        quality_mode="agent",
    )
    assert res["success"] is True
    assert len(res["results"]) >= 1
    top = res["results"][0]
    # Symbol branch should fire on the exact identifier match.
    assert top["chunk_id"] == chunk_ids["handleAuthCallback"]
    assert top.get("candidate_sources") is not None
    # At minimum, vector + symbol contributed.
    assert "symbol" in top["candidate_sources"] or "bm25" in top["candidate_sources"]


def test_hybrid_meta_block_reports_branches(user_id, seeded_repo, fake_embeddings):
    """search_code with agent mode returns the per-branch source counts."""
    from synsc.services.search_service import SearchService

    repo_id, _, _, _ = seeded_repo
    svc = SearchService(user_id=user_id)
    res = svc.search_code(
        query="verifyToken", repo_ids=[repo_id], top_k=5,
        user_id=user_id, quality_mode="agent",
    )
    assert res["success"] is True
    assert res["quality_mode"] == "agent"
    assert res["hybrid"] is not None
    sources = res["hybrid"]["sources_hit"]
    # Vector branch always fires; the symbol branch should fire on the
    # exact symbol query.
    assert sources["vector"] >= 1
    assert sources["symbol"] >= 1


def test_get_context_returns_neighbors(user_id, seeded_repo, fake_embeddings):
    from synsc.services.context_pack import get_chunk_context

    _, _, chunk_ids, _ = seeded_repo
    chunk_id = chunk_ids["verifyToken"]  # chunk_index=1 → has neighbors
    res = get_chunk_context(
        chunk_id=chunk_id, user_id=user_id,
        radius=1, include_enclosing=False, include_same_class=False,
    )
    assert "error" not in res
    assert res["primary"]["chunk_id"] == chunk_id
    # chunk_index=1 has neighbors at 0 and 2.
    assert len(res["neighbors"]) == 2


def test_build_context_pack_returns_structured_payload(user_id, seeded_repo, fake_embeddings):
    from synsc.services.context_pack import build_context_pack

    repo_id, _, _, _ = seeded_repo
    pack = build_context_pack(
        query="how does handleAuthCallback work?",
        user_id=user_id, repo_ids=[repo_id],
        quality_mode="agent",
        token_budget=4000,
    )
    # Top-level shape
    assert "snippets" in pack
    assert "rationale" in pack
    assert "symbols" in pack
    assert pack["quality_mode"] == "agent"
    assert pack["token_budget"] == 4000
    # Should have found at least one primary snippet for the matching chunk.
    primaries = [s for s in pack["snippets"] if s["role"] == "primary"]
    assert len(primaries) >= 1
    # Rationale records the steps the planner took.
    assert "steps" in pack["rationale"]
    assert pack["rationale"]["steps"][0]["name"] == "primary_search"


def test_chunk_used_stamps_on_get_context(user_id, seeded_repo, fake_embeddings):
    """get_context should log a chunk_used event so we can measure
    returned-vs-used.
    """
    from sqlalchemy import text
    from synsc.database.connection import get_session
    from synsc.services.context_pack import get_chunk_context

    _, _, chunk_ids, _ = seeded_repo
    cid = chunk_ids["render_homepage"]
    get_chunk_context(chunk_id=cid, user_id=user_id, radius=0)

    # The auto-stamp wrote a row to activity_log.
    with get_session() as session:
        rows = session.execute(
            text(
                "SELECT * FROM activity_log "
                "WHERE user_id = :uid AND action = 'chunk_used' "
                "  AND resource_id = :cid"
            ),
            {"uid": user_id, "cid": cid},
        ).fetchall()
        assert len(rows) >= 1


def test_get_symbol_returns_source_body(user_id, seeded_repo, fake_embeddings):
    """get_symbol must now include the reconstructed source, not just metadata."""
    from synsc.services.symbol_service import SymbolService

    _, _, _, sym_ids = seeded_repo
    svc = SymbolService(user_id=user_id)
    res = svc.get_symbol(sym_ids["handleAuthCallback"], user_id=user_id)
    assert res["success"] is True
    assert res["source"] is not None
    assert "handleAuthCallback" in res["source"]
    # The reconstructed source comes from the overlapping code_chunks.
    assert len(res["source_chunks"]) >= 1


def test_failure_classifier_writes_to_activity_log(user_id):
    """classify_failure inserts a row into activity_log with the chosen code."""
    from sqlalchemy import text
    from synsc.database.connection import get_session
    from synsc.services.observability import classify_failure

    res = classify_failure(
        description="no result found for X",
        user_id=user_id, query="X",
    )
    assert res["code"] == "no_hits"
    with get_session() as session:
        rows = session.execute(
            text(
                "SELECT * FROM activity_log "
                "WHERE user_id = :uid AND action = 'failure_classification'"
            ),
            {"uid": user_id},
        ).fetchall()
        assert len(rows) >= 1
