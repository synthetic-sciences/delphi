"""End-to-end hybrid-retrieval + context-pack tests against real Postgres.

Indexes a small repo by directly inserting chunks/symbols/embeddings,
then exercises ``hybrid_retrieve``, ``search_code`` (agent quality_mode),
``build_context_pack``, and ``get_chunk_context``.

Skipped automatically when DATABASE_URL doesn't point at Postgres.
"""
from __future__ import annotations

import contextlib
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
        "synsc.services.atlas_connector.get_embedding_generator",
    ):
        with contextlib.suppress(AttributeError):
            monkeypatch.setattr(target, lambda inst=instance: inst)
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
            "async def handleAuthCallback(req):\n    return await verify(req)",
            1, 2, "function",
        ),
        "verifyToken": (
            "def verifyToken(t):\n    return jwt.decode(t)",
            10, 11, "function",
        ),
        "render_homepage": (
            "def render_homepage():\n    return 'hello'",
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


def test_qualified_symbol_outranks_same_leaf_name(user_id, seeded_repo):
    """A fully qualified API query must win over unrelated same-name symbols."""
    from sqlalchemy import text

    from synsc.database.connection import get_session
    from synsc.services.hybrid_retrieval import exact_symbol_search

    repo_id, _, _, _ = seeded_repo
    target_chunk_id = str(uuid.uuid4())
    rows = (
        {
            "file_id": str(uuid.uuid4()),
            "chunk_id": str(uuid.uuid4()),
            "symbol_id": str(uuid.uuid4()),
            "path": "src/other.py",
            "qualified_name": "other.Option",
            "start_line": 1,
        },
        {
            "file_id": str(uuid.uuid4()),
            "chunk_id": target_chunk_id,
            "symbol_id": str(uuid.uuid4()),
            "path": "src/click.py",
            "qualified_name": "click.Option",
            "start_line": 100,
        },
    )
    with get_session() as session:
        for index, row in enumerate(rows):
            session.execute(
                text(
                    "INSERT INTO repository_files "
                    "(file_id, repo_id, file_path, file_name, language) "
                    "VALUES (:file_id, :repo_id, :path, :path, 'python')"
                ),
                {**row, "repo_id": repo_id},
            )
            session.execute(
                text(
                    "INSERT INTO code_chunks "
                    "(chunk_id, repo_id, file_id, chunk_index, content, "
                    " start_line, end_line, language, symbol_names) "
                    "VALUES (:chunk_id, :repo_id, :file_id, :chunk_index, "
                    " :content, :start_line, :start_line, 'python', '[\"Option\"]')"
                ),
                {
                    **row,
                    "repo_id": repo_id,
                    "chunk_index": index + 10,
                    "content": f"class {row['qualified_name']}: pass",
                },
            )
            session.execute(
                text(
                    "INSERT INTO symbols "
                    "(symbol_id, repo_id, file_id, name, qualified_name, "
                    " symbol_type, start_line, end_line, language) "
                    "VALUES (:symbol_id, :repo_id, :file_id, 'Option', "
                    " :qualified_name, 'class', :start_line, :start_line, 'python')"
                ),
                {**row, "repo_id": repo_id},
            )
        session.commit()

    with get_session() as session:
        results = exact_symbol_search(
            session,
            "click.Option",
            user_id,
            repo_ids=[repo_id],
            top_k=1,
        )

    assert [result.chunk_id for result in results] == [target_chunk_id]


def test_trigram_search_recovers_a_misspelled_identifier(
    user_id,
    seeded_repo,
):
    """A one-character identifier typo should retrieve the intended chunk."""
    from synsc.database.connection import get_session
    from synsc.services.hybrid_retrieval import trigram_search

    repo_id, _, chunk_ids, _ = seeded_repo
    with get_session() as session:
        results = trigram_search(
            session,
            "SETUPTOOLS_SCM_PRETEND_VERSION handlAuthCallback",
            user_id,
            repo_ids=[repo_id],
            top_k=5,
        )

    assert results[0].chunk_id == chunk_ids["handleAuthCallback"]
    assert results[0].sources["trigram"] > 0.7


def test_agent_search_keeps_a_trigram_only_hit_amid_vector_decoys(
    user_id,
    seeded_repo,
    fake_embeddings,
):
    """A fuzzy-only recovery must survive fusion and final result selection."""
    from synsc.services.search_service import SearchService

    repo_id, _, chunk_ids, _ = seeded_repo
    vector_results = [
        {
            "chunk_id": str(uuid.uuid4()),
            "repo_id": repo_id,
            "file_id": str(uuid.uuid4()),
            "repo_name": "test/integ",
            "file_path": f"src/decoy_{index}.py",
            "content": f"def unrelated_{index}(): pass",
            "start_line": 1,
            "end_line": 1,
            "chunk_index": 0,
            "chunk_type": "function",
            "language": "python",
            "symbol_names": [f"unrelated_{index}"],
            "is_public": False,
            "similarity": 1.0 - index / 1000,
        }
        for index in range(50)
    ]

    class DecoyVectorStore:
        def search(self, **_kwargs):
            return vector_results

    svc = SearchService(user_id=user_id)
    svc._vector_store = DecoyVectorStore()
    result = svc.search_code(
        query="SETUPTOOLS_SCM_PRETEND_VERSION handlAuthCallback",
        repo_ids=[repo_id],
        top_k=20,
        user_id=user_id,
        quality_mode="agent",
    )

    target = next(
        (
            row
            for row in result["results"]
            if row["chunk_id"] == chunk_ids["handleAuthCallback"]
        ),
        None,
    )
    assert target is not None
    assert "trigram" in target["candidate_sources"]


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


def _insert_file_okapi_lexical_rows(
    session,
    *,
    repo_id: str,
    file_id: str,
    file_path: str,
    content: str,
    content_hash: str,
) -> None:
    import json

    from sqlalchemy import text

    from synsc.services.file_okapi import FILE_OKAPI_INDEX_VERSION, build_file_okapi_document

    document = build_file_okapi_document(file_path, content)
    session.execute(
        text(
            """
            INSERT INTO repository_file_lexical_documents (
                file_id, repo_id, document_length, content_hash,
                index_version, term_frequencies
            )
            VALUES (
                :file_id, :repo_id, :document_length, :content_hash,
                :index_version, CAST(:term_frequencies AS jsonb)
            )
            """
        ),
        {
            "file_id": file_id,
            "repo_id": repo_id,
            "document_length": document.document_length,
            "content_hash": content_hash,
            "index_version": FILE_OKAPI_INDEX_VERSION,
            "term_frequencies": json.dumps(document.term_frequencies),
        },
    )


@pytest.fixture
def file_okapi_repos(user_id):
    """Seed accessible and private repositories with lexical rows and chunks."""
    from sqlalchemy import text

    from synsc.database.connection import get_session
    from synsc.services.file_okapi import FILE_OKAPI_INDEX_VERSION

    accessible_repo_id = str(uuid.uuid4())
    private_repo_id = str(uuid.uuid4())
    strong_file_id = str(uuid.uuid4())
    weak_file_id = str(uuid.uuid4())
    private_file_id = str(uuid.uuid4())
    strong_chunk_early = str(uuid.uuid4())
    strong_chunk_best = str(uuid.uuid4())
    weak_chunk_id = str(uuid.uuid4())
    private_chunk_id = str(uuid.uuid4())

    strong_path = "src/HTTPServer.py"
    weak_path = "src/user_helpers.py"
    private_path = "src/HTTPServer_secret.py"
    strong_content = (
        "class HTTPServer:\n"
        "    def get_user(self, user_id):\n"
        "        return self.users[user_id]\n"
    )
    strong_chunk_early_content = "# configuration defaults\nTIMEOUT = 30\n"
    strong_chunk_best_content = (
        "The http server exposes get user handlers.\n"
        "Each get user request is routed by the server.\n"
    )
    weak_content = "def normalize_user(value):\n    return value.strip()\n"
    private_content = (
        "class HTTPServer:\n"
        "    def get_user(self, secret):\n"
        "        return secret\n"
    )

    with get_session() as session:
        for repo_id, owner, indexed_by, is_public in (
            (accessible_repo_id, "acme", user_id, False),
            (private_repo_id, "secret", str(uuid.uuid4()), False),
        ):
            session.execute(
                text(
                    """
                    INSERT INTO repositories (
                        repo_id, url, owner, name, branch, indexed_by,
                        is_public, deep_indexed,
                        file_okapi_index_version, file_okapi_documents_count
                    )
                    VALUES (
                        :repo_id, :url, :owner, :name, 'main', :indexed_by,
                        :is_public, TRUE, :index_version, :document_count
                    )
                    """
                ),
                {
                    "repo_id": repo_id,
                    "url": f"https://test/{repo_id}",
                    "owner": owner,
                    "name": "service",
                    "indexed_by": indexed_by,
                    "is_public": is_public,
                    "index_version": FILE_OKAPI_INDEX_VERSION,
                    "document_count": 2 if repo_id == accessible_repo_id else 1,
                },
            )

        session.execute(
            text(
                "INSERT INTO user_repositories (user_id, repo_id) "
                "VALUES (:user_id, :repo_id)"
            ),
            {"user_id": user_id, "repo_id": accessible_repo_id},
        )

        files = (
            (strong_file_id, accessible_repo_id, strong_path, strong_content, "hash-strong"),
            (weak_file_id, accessible_repo_id, weak_path, weak_content, "hash-weak"),
            (
                private_file_id,
                private_repo_id,
                private_path,
                private_content,
                "hash-private",
            ),
        )
        for file_id, repo_id, file_path, _content, _hash in files:
            session.execute(
                text(
                    """
                    INSERT INTO repository_files (
                        file_id, repo_id, file_path, file_name, language
                    )
                    VALUES (:file_id, :repo_id, :file_path, :file_name, 'python')
                    """
                ),
                {
                    "file_id": file_id,
                    "repo_id": repo_id,
                    "file_path": file_path,
                    "file_name": file_path.rsplit("/", 1)[-1],
                },
            )

        for file_id, repo_id, file_path, content, content_hash in files:
            _insert_file_okapi_lexical_rows(
                session,
                repo_id=repo_id,
                file_id=file_id,
                file_path=file_path,
                content=content,
                content_hash=content_hash,
            )

        chunks = (
            (
                strong_chunk_early,
                accessible_repo_id,
                strong_file_id,
                strong_chunk_early_content,
                1,
                1,
                0,
            ),
            (
                strong_chunk_best,
                accessible_repo_id,
                strong_file_id,
                strong_chunk_best_content,
                2,
                4,
                1,
            ),
            (
                weak_chunk_id,
                accessible_repo_id,
                weak_file_id,
                weak_content,
                1,
                2,
                0,
            ),
            (
                private_chunk_id,
                private_repo_id,
                private_file_id,
                private_content,
                1,
                3,
                0,
            ),
        )
        for (
            chunk_id,
            repo_id,
            file_id,
            content,
            start_line,
            end_line,
            chunk_index,
        ) in chunks:
            session.execute(
                text(
                    """
                    INSERT INTO code_chunks (
                        chunk_id, repo_id, file_id, chunk_index, content,
                        start_line, end_line, language, symbol_names
                    )
                    VALUES (
                        :chunk_id, :repo_id, :file_id, :chunk_index, :content,
                        :start_line, :end_line, 'python', :symbol_names
                    )
                    """
                ),
                {
                    "chunk_id": chunk_id,
                    "repo_id": repo_id,
                    "file_id": file_id,
                    "chunk_index": chunk_index,
                    "content": content,
                    "start_line": start_line,
                    "end_line": end_line,
                    "symbol_names": '["HTTPServer"]',
                },
            )
        session.commit()

    return {
        "accessible_repo_id": accessible_repo_id,
        "private_repo_id": private_repo_id,
        "strong_file_id": strong_file_id,
        "weak_file_id": weak_file_id,
        "private_file_id": private_file_id,
        "strong_chunk_early": strong_chunk_early,
        "strong_chunk_best": strong_chunk_best,
        "weak_chunk_id": weak_chunk_id,
        "private_chunk_id": private_chunk_id,
    }


def test_file_okapi_search_ranks_accessible_files_and_hides_private_repo(
    user_id,
    file_okapi_repos,
):
    from synsc.database.connection import get_session
    from synsc.services.hybrid_retrieval import file_okapi_search

    data = file_okapi_repos
    with get_session() as session:
        results = file_okapi_search(
            session,
            "HTTPServer get_user",
            user_id,
            repo_ids=[data["accessible_repo_id"], data["private_repo_id"]],
            top_k=10,
        )

    assert results == []

    with get_session() as session:
        scoped = file_okapi_search(
            session,
            "http server get user",
            user_id,
            repo_ids=[data["accessible_repo_id"]],
            top_k=10,
        )

    assert len(scoped) == 2
    assert len({candidate.file_id for candidate in scoped}) == 2
    assert scoped[0].file_id == data["strong_file_id"]
    assert scoped[0].chunk_id == data["strong_chunk_best"]
    assert scoped[0].chunk_id != data["strong_chunk_early"]
    assert scoped[0].sources["file_okapi"] > scoped[1].sources["file_okapi"]
    assert all(candidate.sources["file_okapi"] > 0 for candidate in scoped)
    assert data["private_file_id"] not in {candidate.file_id for candidate in scoped}


def test_file_okapi_search_applies_language_filter(user_id):
    """Only lexical documents whose files match the language filter contribute."""
    import json

    from sqlalchemy import text

    from synsc.database.connection import get_session
    from synsc.services.file_okapi import (
        FILE_OKAPI_INDEX_VERSION,
        bm25_term_score,
        build_file_okapi_document,
    )
    from synsc.services.hybrid_retrieval import file_okapi_search

    repo_id = str(uuid.uuid4())
    python_file_id = str(uuid.uuid4())
    rust_file_id = str(uuid.uuid4())
    python_chunk_id = str(uuid.uuid4())
    rust_chunk_id = str(uuid.uuid4())
    python_path = "src/user_service.py"
    rust_path = "src/user_service.rs"
    python_content = "class UserService:\n    user = UserService()\n"
    rust_content = "struct UserService;\nimpl UserService { fn user(&self) {} }\n"

    with get_session() as session:
        session.execute(
            text(
                """
                INSERT INTO repositories (
                    repo_id, url, owner, name, branch, indexed_by,
                    is_public, deep_indexed,
                    file_okapi_index_version, file_okapi_documents_count
                )
                VALUES (
                    :repo_id, :url, 'acme', 'service', 'main', :indexed_by,
                    FALSE, TRUE, :index_version, 2
                )
                """
            ),
            {
                "repo_id": repo_id,
                "url": f"https://test/{repo_id}",
                "indexed_by": user_id,
                "index_version": FILE_OKAPI_INDEX_VERSION,
            },
        )
        session.execute(
            text(
                "INSERT INTO user_repositories (user_id, repo_id) "
                "VALUES (:user_id, :repo_id)"
            ),
            {"user_id": user_id, "repo_id": repo_id},
        )
        for file_id, file_path, language in (
            (python_file_id, python_path, "python"),
            (rust_file_id, rust_path, "rust"),
        ):
            session.execute(
                text(
                    """
                    INSERT INTO repository_files (
                        file_id, repo_id, file_path, file_name, language
                    )
                    VALUES (:file_id, :repo_id, :file_path, :file_name, :language)
                    """
                ),
                {
                    "file_id": file_id,
                    "repo_id": repo_id,
                    "file_path": file_path,
                    "file_name": file_path.rsplit("/", 1)[-1],
                    "language": language,
                },
            )
        for file_id, file_path, content in (
            (python_file_id, python_path, python_content),
            (rust_file_id, rust_path, rust_content),
        ):
            document = build_file_okapi_document(file_path, content)
            session.execute(
                text(
                    """
                    INSERT INTO repository_file_lexical_documents (
                        file_id, repo_id, document_length, content_hash,
                        index_version, term_frequencies
                    )
                    VALUES (
                        :file_id, :repo_id, :document_length, :content_hash,
                        :index_version, CAST(:term_frequencies AS jsonb)
                    )
                    """
                ),
                {
                    "file_id": file_id,
                    "repo_id": repo_id,
                    "document_length": document.document_length,
                    "content_hash": f"hash-{file_id[:8]}",
                    "index_version": FILE_OKAPI_INDEX_VERSION,
                    "term_frequencies": json.dumps(document.term_frequencies),
                },
            )
        for chunk_id, file_id, content, chunk_index in (
            (python_chunk_id, python_file_id, python_content, 0),
            (rust_chunk_id, rust_file_id, rust_content, 0),
        ):
            session.execute(
                text(
                    """
                    INSERT INTO code_chunks (
                        chunk_id, repo_id, file_id, chunk_index, content,
                        start_line, end_line, language, symbol_names
                    )
                    VALUES (
                        :chunk_id, :repo_id, :file_id, :chunk_index, :content,
                        1, 2, 'python', '[]'
                    )
                    """
                ),
                {
                    "chunk_id": chunk_id,
                    "repo_id": repo_id,
                    "file_id": file_id,
                    "chunk_index": chunk_index,
                    "content": content,
                },
            )
        session.commit()

    with get_session() as session:
        results = file_okapi_search(
            session,
            "user service",
            user_id,
            repo_ids=[repo_id],
            language="python",
            top_k=10,
        )

    assert len(results) == 1
    assert results[0].file_id == python_file_id

    python_doc = build_file_okapi_document(python_path, python_content)
    expected_score = sum(
        bm25_term_score(
            term_frequency=python_doc.term_frequencies[term],
            document_length=python_doc.document_length,
            document_count=1,
            document_frequency=1,
            average_document_length=float(python_doc.document_length),
        )
        for term in ("user", "service")
    )
    assert results[0].sources["file_okapi"] == pytest.approx(expected_score)


def test_file_okapi_search_returns_empty_for_zero_term_overlap(user_id):
    from sqlalchemy import text

    from synsc.database.connection import get_session
    from synsc.services.file_okapi import FILE_OKAPI_INDEX_VERSION
    from synsc.services.hybrid_retrieval import file_okapi_search

    repo_id = str(uuid.uuid4())
    file_id = str(uuid.uuid4())

    with get_session() as session:
        session.execute(
            text(
                """
                INSERT INTO repositories (
                    repo_id, url, owner, name, branch, indexed_by,
                    is_public, deep_indexed,
                    file_okapi_index_version, file_okapi_documents_count
                )
                VALUES (
                    :repo_id, :url, 'acme', 'service', 'main', :indexed_by,
                    FALSE, TRUE, :index_version, 1
                )
                """
            ),
            {
                "repo_id": repo_id,
                "url": f"https://test/{repo_id}",
                "indexed_by": user_id,
                "index_version": FILE_OKAPI_INDEX_VERSION,
            },
        )
        session.execute(
            text(
                "INSERT INTO user_repositories (user_id, repo_id) "
                "VALUES (:user_id, :repo_id)"
            ),
            {"user_id": user_id, "repo_id": repo_id},
        )
        session.execute(
            text(
                """
                INSERT INTO repository_files (
                    file_id, repo_id, file_path, file_name, language
                )
                VALUES (:file_id, :repo_id, 'src/example.py', 'example.py', 'python')
                """
            ),
            {"file_id": file_id, "repo_id": repo_id},
        )
        _insert_file_okapi_lexical_rows(
            session,
            repo_id=repo_id,
            file_id=file_id,
            file_path="src/example.py",
            content="def alpha():\n    return 1\n",
            content_hash="hash-alpha",
        )
        session.commit()

    with get_session() as session:
        results = file_okapi_search(
            session,
            "zzzznonexistent",
            user_id,
            repo_ids=[repo_id],
            top_k=10,
        )

    assert results == []
