"""Thesis connector — index Thesis workspaces, nodes, edges, artifacts,
executions, and tool contracts into Delphi for graph-aware retrieval.

Three reasons this exists:

1. **Agent context for long-running research**: Thesis is a graph-of-claims
   /hypotheses/decisions. An agent picking up a workflow needs "what's
   already been tried, what has been decided, what tool contracts apply".
   Pure-code retrieval misses all of that.

2. **Decision memory**: ``find_decisions(question)`` surfaces prior
   rationale — so the agent doesn't redo work or contradict an earlier
   committed decision.

3. **Artifact-aware ranking**: results from nodes that *produced* artifacts
   (tables, plots, logs) rank higher than nodes that only stated intent.

The connector is push-based: callers (Thesis itself, or a sync job) call
``ingest_workspace`` / ``ingest_node`` / ``ingest_edge`` / ``ingest_artifact``
to stream entities in. We embed node summaries / content / rationale as
chunks so they participate in the vector + BM25 + graph retrieval pipeline.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from synsc.database.connection import get_session
from synsc.embeddings.generator import get_embedding_generator

logger = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Ingestion API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def ingest_workspace(
    *,
    user_id: str,
    external_id: str,
    name: str,
    display_name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    is_public: bool = False,
) -> dict[str, Any]:
    """Create or update a Thesis workspace and link it to the user."""
    if not user_id:
        return {"success": False, "error": "auth_required"}
    with get_session() as session:
        row = session.execute(
            text(
                "SELECT workspace_id FROM thesis_workspaces "
                "WHERE external_id = :eid"
            ),
            {"eid": external_id},
        ).first()
        if row:
            workspace_id = str(row[0])
            session.execute(
                text(
                    "UPDATE thesis_workspaces SET name=:name, "
                    "display_name=:dn, description=:desc, tags=:tags, "
                    "is_public=:pub, updated_at=NOW() "
                    "WHERE workspace_id=:wid"
                ),
                {
                    "name": name, "dn": display_name, "desc": description,
                    "tags": json.dumps(tags) if tags else None,
                    "pub": is_public, "wid": workspace_id,
                },
            )
        else:
            workspace_id = _new_uuid()
            session.execute(
                text(
                    "INSERT INTO thesis_workspaces "
                    "(workspace_id, external_id, name, display_name, "
                    " description, indexed_by, is_public, tags) "
                    "VALUES (:wid, :eid, :name, :dn, :desc, :uid, :pub, :tags)"
                ),
                {
                    "wid": workspace_id, "eid": external_id, "name": name,
                    "dn": display_name, "desc": description,
                    "uid": user_id, "pub": is_public,
                    "tags": json.dumps(tags) if tags else None,
                },
            )
        # Link user.
        session.execute(
            text(
                "INSERT INTO user_thesis_workspaces (user_id, workspace_id) "
                "VALUES (:uid, :wid) ON CONFLICT DO NOTHING"
            ),
            {"uid": user_id, "wid": workspace_id},
        )
        session.commit()
    return {"success": True, "workspace_id": workspace_id}


def ingest_node(
    *,
    user_id: str,
    workspace_id: str,
    external_id: str,
    node_type: str,
    title: str | None = None,
    summary: str | None = None,
    content: str | None = None,
    status: str | None = None,
    outcome: str | None = None,
    tags: list[str] | None = None,
    decision_rationale: str | None = None,
    commit_sha: str | None = None,
    is_committed: bool = False,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Create or update a node, then re-chunk + re-embed its content."""
    if not user_id:
        return {"success": False, "error": "auth_required"}

    with get_session() as session:
        if not _user_can_write_workspace(session, user_id, workspace_id):
            return {"success": False, "error": "access_denied"}

        existing = session.execute(
            text(
                "SELECT node_id FROM thesis_nodes "
                "WHERE workspace_id = :wid AND external_id = :eid"
            ),
            {"wid": workspace_id, "eid": external_id},
        ).first()

        if existing:
            node_id = str(existing[0])
            session.execute(
                text(
                    "UPDATE thesis_nodes SET node_type=:nt, title=:title, "
                    "summary=:summary, content=:content, status=:status, "
                    "outcome=:outcome, tags=:tags, "
                    "decision_rationale=:rat, commit_sha=:sha, "
                    "is_committed=:committed, created_by=:cb, "
                    "updated_at=NOW() "
                    "WHERE node_id=:nid"
                ),
                {
                    "nt": node_type, "title": title, "summary": summary,
                    "content": content, "status": status, "outcome": outcome,
                    "tags": json.dumps(tags) if tags else None,
                    "rat": decision_rationale, "sha": commit_sha,
                    "committed": is_committed, "cb": created_by,
                    "nid": node_id,
                },
            )
            # Drop old chunks/embeddings before re-inserting.
            session.execute(
                text(
                    "DELETE FROM thesis_node_chunk_embeddings WHERE node_id=:nid"
                ),
                {"nid": node_id},
            )
            session.execute(
                text("DELETE FROM thesis_node_chunks WHERE node_id=:nid"),
                {"nid": node_id},
            )
        else:
            node_id = _new_uuid()
            session.execute(
                text(
                    "INSERT INTO thesis_nodes "
                    "(node_id, workspace_id, external_id, node_type, title, "
                    " summary, content, status, outcome, tags, "
                    " decision_rationale, commit_sha, is_committed, created_by) "
                    "VALUES (:nid, :wid, :eid, :nt, :title, :summary, "
                    " :content, :status, :outcome, :tags, :rat, :sha, "
                    " :committed, :cb)"
                ),
                {
                    "nid": node_id, "wid": workspace_id, "eid": external_id,
                    "nt": node_type, "title": title, "summary": summary,
                    "content": content, "status": status, "outcome": outcome,
                    "tags": json.dumps(tags) if tags else None,
                    "rat": decision_rationale, "sha": commit_sha,
                    "committed": is_committed, "cb": created_by,
                },
            )

        # Build chunks: one per section that has content.
        chunks: list[tuple[str, str]] = []  # (kind, content)
        if title:
            chunks.append(("summary", f"# {title}\n\n{summary or ''}".strip()))
        elif summary:
            chunks.append(("summary", summary))
        if content:
            chunks.append(("content", content))
        if decision_rationale:
            chunks.append(("rationale", decision_rationale))
        if outcome:
            chunks.append(("outcome", f"outcome: {outcome}"))

        embedding_rows: list[tuple[str, str, str]] = []  # (chunk_id, content, kind)
        for idx, (kind, body) in enumerate(chunks):
            if not body or not body.strip():
                continue
            chunk_id = _new_uuid()
            session.execute(
                text(
                    "INSERT INTO thesis_node_chunks "
                    "(chunk_id, node_id, workspace_id, chunk_index, "
                    " chunk_kind, content, token_count) "
                    "VALUES (:cid, :nid, :wid, :idx, :kind, :body, :tc)"
                ),
                {
                    "cid": chunk_id, "nid": node_id, "wid": workspace_id,
                    "idx": idx, "kind": kind, "body": body,
                    "tc": max(1, len(body) // 4),
                },
            )
            embedding_rows.append((chunk_id, body, kind))
        session.commit()

        # Embed in a separate session.
        if embedding_rows:
            try:
                emb_gen = get_embedding_generator()
                embeds = emb_gen.generate([row[1] for row in embedding_rows])
                with get_session() as esess:
                    for (chunk_id, _content, _kind), vec in zip(embedding_rows, embeds):
                        emb_str = "[" + ",".join(str(x) for x in vec.tolist()) + "]"
                        esess.execute(
                            text(
                                "INSERT INTO thesis_node_chunk_embeddings "
                                "(embedding_id, workspace_id, node_id, "
                                " chunk_id, embedding) "
                                "VALUES (:eid, :wid, :nid, :cid, "
                                " CAST(:emb AS vector))"
                            ),
                            {
                                "eid": _new_uuid(), "wid": workspace_id,
                                "nid": node_id, "cid": chunk_id,
                                "emb": emb_str,
                            },
                        )
                    esess.commit()
            except Exception as e:
                logger.warning("thesis node embed failed", error=str(e))

    return {"success": True, "node_id": node_id, "chunks": len(embedding_rows)}


def ingest_edge(
    *,
    user_id: str,
    workspace_id: str,
    source_external_id: str,
    target_external_id: str,
    edge_type: str,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """Create an edge (parent/child/blocks/derives_from/etc.). Idempotent
    on (source, target, edge_type)."""
    if not user_id:
        return {"success": False, "error": "auth_required"}
    with get_session() as session:
        if not _user_can_write_workspace(session, user_id, workspace_id):
            return {"success": False, "error": "access_denied"}
        # Resolve external ids → node_ids.
        rows = session.execute(
            text(
                "SELECT node_id, external_id FROM thesis_nodes "
                "WHERE workspace_id = :wid AND external_id IN (:s, :t)"
            ),
            {"wid": workspace_id, "s": source_external_id, "t": target_external_id},
        ).mappings().all()
        by_ext = {r["external_id"]: str(r["node_id"]) for r in rows}
        sid = by_ext.get(source_external_id)
        tid = by_ext.get(target_external_id)
        if not sid or not tid:
            return {
                "success": False,
                "error": "node_not_found",
                "missing": [
                    e for e in (source_external_id, target_external_id)
                    if e not in by_ext
                ],
            }
        edge_id = _new_uuid()
        session.execute(
            text(
                "INSERT INTO thesis_edges "
                "(edge_id, workspace_id, source_node_id, target_node_id, "
                " edge_type, metadata) "
                "VALUES (:eid, :wid, :sid, :tid, :et, :md) "
                "ON CONFLICT (source_node_id, target_node_id, edge_type) "
                "DO UPDATE SET metadata = EXCLUDED.metadata"
            ),
            {
                "eid": edge_id, "wid": workspace_id, "sid": sid, "tid": tid,
                "et": edge_type,
                "md": json.dumps(metadata) if metadata else None,
            },
        )
        session.commit()
    return {"success": True, "source_id": sid, "target_id": tid}


def ingest_artifact(
    *,
    user_id: str,
    workspace_id: str,
    node_external_id: str | None,
    kind: str,
    name: str | None = None,
    preview: str | None = None,
    uri: str | None = None,
    metadata: dict | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Attach an artifact (table/plot/log/diff/metric/model) to a node."""
    if not user_id:
        return {"success": False, "error": "auth_required"}
    with get_session() as session:
        if not _user_can_write_workspace(session, user_id, workspace_id):
            return {"success": False, "error": "access_denied"}
        node_id = None
        if node_external_id:
            row = session.execute(
                text(
                    "SELECT node_id FROM thesis_nodes "
                    "WHERE workspace_id=:wid AND external_id=:eid"
                ),
                {"wid": workspace_id, "eid": node_external_id},
            ).first()
            if row:
                node_id = str(row[0])
        artifact_id = _new_uuid()
        session.execute(
            text(
                "INSERT INTO thesis_artifacts "
                "(artifact_id, workspace_id, node_id, external_id, kind, "
                " name, preview, uri, metadata) "
                "VALUES (:aid, :wid, :nid, :ext, :kind, :name, :preview, "
                " :uri, :md)"
            ),
            {
                "aid": artifact_id, "wid": workspace_id, "nid": node_id,
                "ext": external_id, "kind": kind, "name": name,
                "preview": preview, "uri": uri,
                "md": json.dumps(metadata) if metadata else None,
            },
        )
        session.execute(
            text(
                "UPDATE thesis_workspaces SET artifacts_count = artifacts_count + 1 "
                "WHERE workspace_id = :wid"
            ),
            {"wid": workspace_id},
        )
        session.commit()
    return {"success": True, "artifact_id": artifact_id}


def ingest_execution(
    *,
    user_id: str,
    workspace_id: str,
    node_external_id: str | None,
    tool: str | None,
    status: str | None,
    started_at: str | None = None,
    ended_at: str | None = None,
    duration_ms: int | None = None,
    inputs: dict | None = None,
    output_summary: str | None = None,
    error: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Record an execution / tool call against a node."""
    if not user_id:
        return {"success": False, "error": "auth_required"}
    with get_session() as session:
        if not _user_can_write_workspace(session, user_id, workspace_id):
            return {"success": False, "error": "access_denied"}
        node_id = None
        if node_external_id:
            row = session.execute(
                text(
                    "SELECT node_id FROM thesis_nodes "
                    "WHERE workspace_id=:wid AND external_id=:eid"
                ),
                {"wid": workspace_id, "eid": node_external_id},
            ).first()
            if row:
                node_id = str(row[0])
        execution_id = _new_uuid()
        session.execute(
            text(
                "INSERT INTO thesis_executions "
                "(execution_id, workspace_id, node_id, external_id, tool, "
                " status, started_at, ended_at, duration_ms, inputs, "
                " output_summary, error) "
                "VALUES (:eid, :wid, :nid, :ext, :tool, :status, "
                " CAST(:sat AS timestamptz), CAST(:eat AS timestamptz), "
                " :dur, :inputs, :osum, :err)"
            ),
            {
                "eid": execution_id, "wid": workspace_id, "nid": node_id,
                "ext": external_id, "tool": tool, "status": status,
                "sat": started_at, "eat": ended_at, "dur": duration_ms,
                "inputs": json.dumps(inputs) if inputs else None,
                "osum": output_summary, "err": error,
            },
        )
        session.commit()
    return {"success": True, "execution_id": execution_id}


def ingest_tool_contract(
    *,
    user_id: str,
    tool_name: str,
    workspace_id: str | None = None,
    display_name: str | None = None,
    description: str | None = None,
    when_to_use: str | None = None,
    avoid_when: str | None = None,
    signature: dict | None = None,
    examples: list | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Register a tool-contract document so agents can ``retrieve_tool_contract``."""
    if not user_id:
        return {"success": False, "error": "auth_required"}
    with get_session() as session:
        if workspace_id and not _user_can_write_workspace(session, user_id, workspace_id):
            return {"success": False, "error": "access_denied"}
        existing = session.execute(
            text(
                "SELECT contract_id FROM thesis_tool_contracts "
                "WHERE tool_name = :tn "
                "AND COALESCE(workspace_id, '') = COALESCE(:wid, '')"
            ),
            {"tn": tool_name, "wid": workspace_id},
        ).first()
        if existing:
            contract_id = str(existing[0])
            session.execute(
                text(
                    "UPDATE thesis_tool_contracts SET display_name=:dn, "
                    "description=:desc, when_to_use=:when, avoid_when=:avoid, "
                    "signature=:sig, examples=:ex, tags=:tags "
                    "WHERE contract_id = :cid"
                ),
                {
                    "dn": display_name, "desc": description, "when": when_to_use,
                    "avoid": avoid_when,
                    "sig": json.dumps(signature) if signature else None,
                    "ex": json.dumps(examples) if examples else None,
                    "tags": json.dumps(tags) if tags else None,
                    "cid": contract_id,
                },
            )
        else:
            contract_id = _new_uuid()
            session.execute(
                text(
                    "INSERT INTO thesis_tool_contracts "
                    "(contract_id, workspace_id, tool_name, display_name, "
                    " description, when_to_use, avoid_when, signature, "
                    " examples, tags) "
                    "VALUES (:cid, :wid, :tn, :dn, :desc, :when, :avoid, "
                    " :sig, :ex, :tags)"
                ),
                {
                    "cid": contract_id, "wid": workspace_id, "tn": tool_name,
                    "dn": display_name, "desc": description, "when": when_to_use,
                    "avoid": avoid_when,
                    "sig": json.dumps(signature) if signature else None,
                    "ex": json.dumps(examples) if examples else None,
                    "tags": json.dumps(tags) if tags else None,
                },
            )
        session.commit()
    return {"success": True, "contract_id": contract_id}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Retrieval API — graph-aware
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def search_thesis_nodes(
    *,
    query: str,
    user_id: str,
    workspace_ids: list[str] | None = None,
    node_types: list[str] | None = None,
    only_committed: bool = False,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Hybrid search over Thesis nodes (vector + BM25 + artifact-aware boost).

    Boosts:
      - committed nodes (decisions that were locked in) get +0.05.
      - nodes that produced artifacts get +0.05 per artifact (max +0.15).
      - failed-outcome nodes are NOT downranked — agents specifically need
        to find those to answer "what shouldn't I repeat?".
    """
    if not user_id or not query.strip():
        return []
    qemb = get_embedding_generator().generate_single(query)
    emb_str = "[" + ",".join(str(x) for x in qemb.tolist()) + "]"

    params: dict[str, Any] = {
        "uid": user_id, "emb": emb_str, "q": query, "top_k": top_k * 2,
    }
    extra = ""
    if workspace_ids:
        ph = ", ".join([f":wid_{i}" for i in range(len(workspace_ids))])
        extra += f" AND tn.workspace_id IN ({ph})"
        for i, w in enumerate(workspace_ids):
            params[f"wid_{i}"] = w
    if node_types:
        ph = ", ".join([f":nt_{i}" for i in range(len(node_types))])
        extra += f" AND tn.node_type IN ({ph})"
        for i, nt in enumerate(node_types):
            params[f"nt_{i}"] = nt
    if only_committed:
        extra += " AND tn.is_committed = TRUE"

    sql = text(
        f"""
        WITH user_ws AS MATERIALIZED (
            SELECT workspace_id FROM user_thesis_workspaces WHERE user_id = :uid
        ),
        candidates AS (
            SELECT tnc.chunk_id, tnc.node_id, tnc.workspace_id,
                   tnc.chunk_kind, tnc.content,
                   1 - (tne.embedding <=> CAST(:emb AS vector)) AS vec,
                   ts_rank_cd(tnc.content_tsv,
                              websearch_to_tsquery('english', :q)) AS bm25
            FROM thesis_node_chunk_embeddings tne
            JOIN thesis_node_chunks tnc ON tnc.chunk_id = tne.chunk_id
            JOIN user_ws uw ON uw.workspace_id = tnc.workspace_id
            ORDER BY tne.embedding <=> CAST(:emb AS vector)
            LIMIT :top_k
        )
        SELECT c.chunk_id, c.node_id, c.workspace_id, c.chunk_kind, c.content,
               c.vec, c.bm25,
               tn.external_id, tn.node_type, tn.title, tn.summary,
               tn.status, tn.outcome, tn.is_committed,
               tn.decision_rationale, tn.tags,
               tw.name AS workspace_name, tw.external_id AS ws_external_id,
               (SELECT COUNT(*) FROM thesis_artifacts ta
                WHERE ta.node_id = tn.node_id) AS artifact_count
        FROM candidates c
        JOIN thesis_nodes tn ON tn.node_id = c.node_id
        JOIN thesis_workspaces tw ON tw.workspace_id = tn.workspace_id
        WHERE 1=1
        {extra}
        ORDER BY c.vec DESC
        """
    )
    try:
        with get_session() as session:
            rows = session.execute(sql, params).mappings().all()
    except Exception as e:
        logger.warning("thesis search failed", error=str(e))
        return []

    if not rows:
        return []

    max_bm25 = max((r["bm25"] or 0.0 for r in rows), default=1.0) or 1.0
    out: list[dict[str, Any]] = []
    for r in rows:
        vec = float(r["vec"] or 0.0)
        bm = float(r["bm25"] or 0.0) / max_bm25
        committed_boost = 0.05 if r["is_committed"] else 0.0
        artifact_boost = min(0.15, 0.05 * (r["artifact_count"] or 0))
        score = max(0.0, min(1.0,
                             0.6 * vec + 0.25 * bm + committed_boost + artifact_boost))
        out.append(
            {
                "chunk_id": str(r["chunk_id"]),
                "node_id": str(r["node_id"]),
                "workspace_id": str(r["workspace_id"]),
                "workspace_name": r["workspace_name"],
                "ws_external_id": r["ws_external_id"],
                "node_external_id": r["external_id"],
                "node_type": r["node_type"],
                "chunk_kind": r["chunk_kind"],
                "title": r["title"],
                "summary": r["summary"],
                "status": r["status"],
                "outcome": r["outcome"],
                "is_committed": r["is_committed"],
                "tags": r["tags"],
                "content": r["content"],
                "decision_rationale": r["decision_rationale"],
                "artifact_count": r["artifact_count"],
                "score": round(score, 4),
                "components": {
                    "vector": round(vec, 4),
                    "bm25": round(bm, 4),
                    "committed_boost": committed_boost,
                    "artifact_boost": artifact_boost,
                },
                # Citation-style stable reference:
                "ref": f"thesis://{r['ws_external_id']}/{r['external_id']}#{r['chunk_kind']}",
            }
        )
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top_k]


def find_related_nodes(
    *,
    user_id: str,
    node_id: str | None = None,
    question: str | None = None,
    max_depth: int = 2,
    edge_types: list[str] | None = None,
    top_k: int = 25,
) -> list[dict[str, Any]]:
    """Walk the graph from a starting node and return related nodes
    within ``max_depth`` hops.

    Either ``node_id`` (an explicit anchor) or ``question`` (we search
    for the closest matching node first) must be supplied. The spec
    expects ``find_related_nodes(question)`` so we accept either input.
    """
    if not user_id or (not node_id and not question):
        return []
    # If only a question was passed, anchor on the top hit.
    if not node_id and question:
        anchors = search_thesis_nodes(query=question, user_id=user_id, top_k=1)
        if not anchors:
            return []
        node_id = anchors[0]["node_id"]
    edge_filter = ""
    params: dict[str, Any] = {"nid": node_id, "uid": user_id, "top_k": top_k}
    if edge_types:
        ph = ", ".join([f":et_{i}" for i in range(len(edge_types))])
        edge_filter = f" AND e.edge_type IN ({ph})"
        for i, et in enumerate(edge_types):
            params[f"et_{i}"] = et

    # Recursive CTE: BFS up to max_depth.
    sql = text(
        f"""
        WITH RECURSIVE walk AS (
            SELECT e.target_node_id AS node_id, e.edge_type, 1 AS depth
            FROM thesis_edges e
            JOIN user_thesis_workspaces uw ON uw.workspace_id = e.workspace_id
            WHERE e.source_node_id = :nid
              AND uw.user_id = :uid
              {edge_filter}
            UNION ALL
            SELECT e.target_node_id, e.edge_type, w.depth + 1
            FROM thesis_edges e
            JOIN user_thesis_workspaces uw ON uw.workspace_id = e.workspace_id
            JOIN walk w ON e.source_node_id = w.node_id
            WHERE w.depth < {int(max_depth)}
              AND uw.user_id = :uid
              {edge_filter}
        )
        SELECT DISTINCT ON (tn.node_id)
            tn.node_id, tn.external_id, tn.node_type, tn.title, tn.summary,
            tn.status, tn.outcome, tn.is_committed, tn.tags,
            w.depth, w.edge_type, tw.external_id AS ws_external_id
        FROM walk w
        JOIN thesis_nodes tn ON tn.node_id = w.node_id
        JOIN thesis_workspaces tw ON tw.workspace_id = tn.workspace_id
        ORDER BY tn.node_id, w.depth ASC
        LIMIT :top_k
        """
    )
    try:
        with get_session() as session:
            rows = session.execute(sql, params).mappings().all()
    except Exception as e:
        logger.warning("find_related_nodes failed", error=str(e))
        return []
    return [
        {**dict(r), "node_id": str(r["node_id"]),
         "ref": f"thesis://{r['ws_external_id']}/{r['external_id']}"}
        for r in rows
    ]


def find_relevant_artifacts(
    *,
    user_id: str,
    query: str,
    workspace_ids: list[str] | None = None,
    kinds: list[str] | None = None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Search artifacts by preview text + linked-node similarity.

    The preview column has a trigram index, so this is fast even at scale.
    Pairs nicely with ``search_thesis_nodes`` — the artifact often answers
    "did this hypothesis pan out?".
    """
    if not user_id or not query.strip():
        return []
    needle = query.strip()[:200]
    params: dict[str, Any] = {
        "uid": user_id, "needle": f"%{needle}%", "top_k": top_k,
    }
    extra = ""
    if workspace_ids:
        ph = ", ".join([f":wid_{i}" for i in range(len(workspace_ids))])
        extra += f" AND ta.workspace_id IN ({ph})"
        for i, w in enumerate(workspace_ids):
            params[f"wid_{i}"] = w
    if kinds:
        ph = ", ".join([f":k_{i}" for i in range(len(kinds))])
        extra += f" AND ta.kind IN ({ph})"
        for i, k in enumerate(kinds):
            params[f"k_{i}"] = k

    sql = text(
        f"""
        SELECT ta.artifact_id, ta.workspace_id, ta.node_id, ta.external_id,
               ta.kind, ta.name, ta.preview, ta.uri, ta.metadata,
               tn.external_id AS node_external_id,
               tn.title AS node_title, tn.outcome AS node_outcome,
               tw.external_id AS ws_external_id
        FROM thesis_artifacts ta
        JOIN user_thesis_workspaces uw ON uw.workspace_id = ta.workspace_id
        LEFT JOIN thesis_nodes tn ON tn.node_id = ta.node_id
        JOIN thesis_workspaces tw ON tw.workspace_id = ta.workspace_id
        WHERE uw.user_id = :uid
          AND (
              ta.name ILIKE :needle
              OR ta.preview ILIKE :needle
              OR (tn.title IS NOT NULL AND tn.title ILIKE :needle)
              OR (tn.summary IS NOT NULL AND tn.summary ILIKE :needle)
          )
        {extra}
        ORDER BY ta.created_at DESC
        LIMIT :top_k
        """
    )
    try:
        with get_session() as session:
            rows = session.execute(sql, params).mappings().all()
    except Exception as e:
        logger.warning("find_relevant_artifacts failed", error=str(e))
        return []
    return [
        {
            **{k: (str(v) if k.endswith("_id") and v else v) for k, v in r.items()},
            "ref": (
                f"thesis://{r['ws_external_id']}/"
                f"{r['node_external_id'] or 'orphan'}#artifact/{r['artifact_id']}"
            ),
        }
        for r in rows
    ]


def retrieve_tool_contract(
    *,
    user_id: str,
    task: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Find tool-contract documents relevant to a task.

    Ranking: trigram similarity over ``when_to_use`` + ``description`` +
    ``tool_name``. Returns enough detail (signature + examples) for the
    agent to invoke the tool without hunting elsewhere.
    """
    if not user_id or not task.strip():
        return []
    sql = text(
        """
        SELECT contract_id, tool_name, display_name, description,
               when_to_use, avoid_when, signature, examples, tags,
               GREATEST(
                 similarity(coalesce(tool_name,''), :task),
                 similarity(coalesce(display_name,''), :task),
                 similarity(coalesce(when_to_use,''), :task) * 1.2,
                 similarity(coalesce(description,''), :task)
               ) AS score
        FROM thesis_tool_contracts
        WHERE
            tool_name ILIKE :pattern
            OR display_name ILIKE :pattern
            OR when_to_use ILIKE :pattern
            OR description ILIKE :pattern
            OR similarity(coalesce(when_to_use,''), :task) > 0.1
            OR similarity(coalesce(description,''), :task) > 0.1
        ORDER BY score DESC
        LIMIT :top_k
        """
    )
    try:
        with get_session() as session:
            rows = session.execute(
                sql,
                {
                    "task": task,
                    "pattern": f"%{task[:80]}%",
                    "top_k": top_k,
                },
            ).mappings().all()
    except Exception as e:
        logger.warning("retrieve_tool_contract failed", error=str(e))
        return []
    return [{**dict(r), "score": round(float(r["score"]), 4)} for r in rows]


def find_what_was_tried(
    *,
    user_id: str,
    question: str,
    workspace_ids: list[str] | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    """Answer "what has already been tried for X?".

    Returns the matched nodes plus their executions and outcomes — the
    agent gets the full "we tried Y, status was Z, here's the outcome"
    picture instead of just the claim text.
    """
    nodes = search_thesis_nodes(
        query=question, user_id=user_id, workspace_ids=workspace_ids,
        top_k=top_k,
    )
    if not nodes:
        return {"question": question, "matches": [], "found": 0}
    node_ids = [n["node_id"] for n in nodes]
    placeholders = ", ".join([f":nid_{i}" for i in range(len(node_ids))])
    params: dict[str, Any] = {f"nid_{i}": nid for i, nid in enumerate(node_ids)}

    with get_session() as session:
        execs = session.execute(
            text(
                f"""
                SELECT execution_id, node_id, tool, status, started_at,
                       ended_at, duration_ms, output_summary, error
                FROM thesis_executions
                WHERE node_id IN ({placeholders})
                ORDER BY started_at DESC NULLS LAST
                """
            ),
            params,
        ).mappings().all()
        artifacts = session.execute(
            text(
                f"""
                SELECT artifact_id, node_id, kind, name, preview, uri
                FROM thesis_artifacts
                WHERE node_id IN ({placeholders})
                """
            ),
            params,
        ).mappings().all()

    by_node: dict[str, dict] = {n["node_id"]: {**n, "executions": [], "artifacts": []} for n in nodes}
    for e in execs:
        nid = str(e["node_id"])
        if nid in by_node:
            by_node[nid]["executions"].append({**dict(e), "node_id": nid,
                                              "execution_id": str(e["execution_id"])})
    for a in artifacts:
        nid = str(a["node_id"]) if a["node_id"] else None
        if nid and nid in by_node:
            by_node[nid]["artifacts"].append({**dict(a), "node_id": nid,
                                             "artifact_id": str(a["artifact_id"])})

    return {
        "question": question,
        "matches": list(by_node.values()),
        "found": len(by_node),
    }


def find_what_not_to_repeat(
    *,
    user_id: str,
    question: str,
    workspace_ids: list[str] | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    """Answer "what should I not repeat?".

    Filters ``find_what_was_tried`` to nodes with outcome IN ('failed',
    'rejected', 'invalidated') OR executions with status='failed'. Keeps
    the agent from re-running known-failing experiments.
    """
    base = find_what_was_tried(
        user_id=user_id, question=question,
        workspace_ids=workspace_ids, top_k=top_k * 2,
    )
    failed_outcomes = {"failed", "rejected", "invalidated", "false", "negative"}
    matches = []
    for m in base["matches"]:
        outcome_bad = (m.get("outcome") or "").lower() in failed_outcomes
        any_failed_exec = any(
            (e.get("status") or "").lower() in {"failed", "error"}
            for e in m.get("executions", [])
        )
        if outcome_bad or any_failed_exec:
            matches.append(m)
    return {
        "question": question,
        "matches": matches[:top_k],
        "found": len(matches),
        "rationale": (
            "Listing nodes with negative outcomes or failed executions — "
            "skip these to avoid retrying known-failing approaches."
        ),
    }


def build_thesis_context(
    *,
    user_id: str,
    question: str,
    node_id: str | None = None,
    workspace_ids: list[str] | None = None,
    token_budget: int = 4000,
) -> dict[str, Any]:
    """Build a Thesis-flavored context pack: matched nodes + edges +
    artifacts + tool contracts.
    """
    if not user_id:
        return {"success": False, "error": "auth_required"}
    matched_nodes = search_thesis_nodes(
        query=question, user_id=user_id, workspace_ids=workspace_ids, top_k=8,
    )
    relations: list[dict] = []
    if node_id:
        relations = find_related_nodes(
            user_id=user_id, node_id=node_id, max_depth=2, top_k=20,
        )
    elif matched_nodes:
        relations = find_related_nodes(
            user_id=user_id, node_id=matched_nodes[0]["node_id"],
            max_depth=2, top_k=15,
        )
    artifacts = find_relevant_artifacts(
        user_id=user_id, query=question, workspace_ids=workspace_ids, top_k=8,
    )
    contracts = retrieve_tool_contract(user_id=user_id, task=question, top_k=5)
    tried = find_what_was_tried(
        user_id=user_id, question=question, workspace_ids=workspace_ids, top_k=5,
    )
    not_to_repeat = find_what_not_to_repeat(
        user_id=user_id, question=question, workspace_ids=workspace_ids, top_k=5,
    )

    # Token budgeting — drop tail items if we exceed budget.
    used = 0
    def _approx(s: str) -> int:
        return max(1, len(s) // 4)

    def _fits(blob: str) -> bool:
        nonlocal used
        c = _approx(blob)
        if used + c > token_budget:
            return False
        used += c
        return True

    pruned_nodes: list[dict] = []
    for n in matched_nodes:
        body = (n.get("title") or "") + (n.get("summary") or "") + (n.get("content") or "")
        if _fits(body):
            pruned_nodes.append(n)
        else:
            break

    return {
        "success": True,
        "question": question,
        "matched_nodes": pruned_nodes,
        "graph_relations": relations,
        "artifacts": artifacts,
        "tool_contracts": contracts,
        "what_was_tried": tried,
        "what_not_to_repeat": not_to_repeat,
        "used_tokens_estimate": used,
        "token_budget": token_budget,
    }


def summarize_relevant_subgraph(
    *,
    user_id: str,
    question: str,
    root_node_id: str | None = None,
    max_depth: int = 2,
) -> dict[str, Any]:
    """Return a compact subgraph summary for the matched region.

    Includes node titles + outcomes + artifact counts. Designed for an
    agent to quickly understand "what shape is this part of the graph?"
    before drilling in.
    """
    if not user_id:
        return {"success": False, "error": "auth_required"}
    if not root_node_id:
        hits = search_thesis_nodes(query=question, user_id=user_id, top_k=1)
        if not hits:
            return {"success": True, "subgraph": [], "nodes": 0}
        root_node_id = hits[0]["node_id"]
    related = find_related_nodes(
        user_id=user_id, node_id=root_node_id, max_depth=max_depth, top_k=50,
    )
    node_ids = [r["node_id"] for r in related]
    if root_node_id not in node_ids:
        node_ids.append(root_node_id)
    if not node_ids:
        return {"success": True, "subgraph": [], "nodes": 0}
    placeholders = ", ".join([f":nid_{i}" for i in range(len(node_ids))])
    params = {f"nid_{i}": nid for i, nid in enumerate(node_ids)}
    with get_session() as session:
        edges = session.execute(
            text(
                f"""
                SELECT source_node_id, target_node_id, edge_type
                FROM thesis_edges
                WHERE (source_node_id IN ({placeholders}))
                   OR (target_node_id IN ({placeholders}))
                """
            ),
            params,
        ).mappings().all()
    edge_list = [
        {
            "source": str(e["source_node_id"]),
            "target": str(e["target_node_id"]),
            "type": e["edge_type"],
        }
        for e in edges
    ]
    return {
        "success": True,
        "root": root_node_id,
        "node_count": len(node_ids),
        "edge_count": len(edge_list),
        "edges": edge_list,
        "nodes": related,
    }


def find_decisions(
    *,
    user_id: str,
    question: str,
    workspace_ids: list[str] | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Decision-memory ranking — surface committed decisions (locked-in
    rationale) related to a question. Higher-ranked than uncommitted
    speculation.
    """
    return search_thesis_nodes(
        query=question, user_id=user_id,
        workspace_ids=workspace_ids,
        node_types=["decision"], only_committed=True, top_k=top_k,
    )


def get_active_work_context(
    *,
    user_id: str,
    workspace_ids: list[str] | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    """The "current active work" mode — recent in-progress nodes + their
    open executions. Used by an agent that's resuming work to figure out
    "what was I doing?".
    """
    params: dict[str, Any] = {"uid": user_id, "top_k": top_k}
    extra = ""
    if workspace_ids:
        ph = ", ".join([f":wid_{i}" for i in range(len(workspace_ids))])
        extra += f" AND tn.workspace_id IN ({ph})"
        for i, w in enumerate(workspace_ids):
            params[f"wid_{i}"] = w
    sql = text(
        f"""
        SELECT tn.node_id, tn.external_id, tn.node_type, tn.title,
               tn.summary, tn.status, tn.updated_at,
               tw.external_id AS ws_external_id
        FROM thesis_nodes tn
        JOIN user_thesis_workspaces uw ON uw.workspace_id = tn.workspace_id
        JOIN thesis_workspaces tw ON tw.workspace_id = tn.workspace_id
        WHERE uw.user_id = :uid
          AND (tn.status IN ('in_progress', 'open', 'active')
               OR tn.is_committed = FALSE)
        {extra}
        ORDER BY tn.updated_at DESC
        LIMIT :top_k
        """
    )
    try:
        with get_session() as session:
            nodes = session.execute(sql, params).mappings().all()
    except Exception as e:
        logger.warning("get_active_work_context failed", error=str(e))
        return {"success": False, "error": str(e)}
    return {
        "success": True,
        "active_nodes": [
            {**dict(n), "node_id": str(n["node_id"])} for n in nodes
        ],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _new_uuid() -> str:
    from uuid import uuid4
    return str(uuid4())


def _user_can_write_workspace(
    session: Session, user_id: str, workspace_id: str
) -> bool:
    row = session.execute(
        text(
            "SELECT 1 FROM user_thesis_workspaces "
            "WHERE user_id = :uid AND workspace_id = :wid"
        ),
        {"uid": user_id, "wid": workspace_id},
    ).first()
    if row:
        return True
    # Indexer is also allowed.
    row = session.execute(
        text(
            "SELECT 1 FROM thesis_workspaces "
            "WHERE workspace_id = :wid AND indexed_by = :uid"
        ),
        {"uid": user_id, "wid": workspace_id},
    ).first()
    return bool(row)
