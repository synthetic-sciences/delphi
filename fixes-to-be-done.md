# Fixes to be done

Tracks deferred improvements where the current implementation is correct but
not the cleanest available approach. Each entry has enough detail to pick up
in a fresh session — file paths, line numbers, the rationale, and the exact
edit.

---

## 1. `_build_chunk_relationships`: switch from pre-load to `ON CONFLICT DO NOTHING`

**Status:** ✅ Done in Delphi (commit on `feat/upstream-sync-2026-04`). ⏳ Open in `synsc-context` (upstream).
**Affected repos:** ~~Synsci-Delphi (this repo)~~, `synsc-context` (upstream).
**Priority:** medium — not blocking, but should land before the resilience batch is ported, so all idempotent writes share one pattern.

### Current implementation

[`backend/synsc/services/indexing_service.py:73-89`](backend/synsc/services/indexing_service.py#L73-L89) (Delphi)
[`synsc/services/indexing_service.py:73-89`](https://github.com/synthetic-sciences/synsc-context/blob/main/synsc/services/indexing_service.py#L73-L89) (upstream — needs same fix)

Pre-loads existing `(source_chunk_id, target_chunk_id, relationship_type)`
keys for the repo into a Python `set`, then uses the existing dedup helper
to skip already-persisted edges.

```python
existing_rows = session.execute(
    text(
        """
        SELECT cr.source_chunk_id::text,
               cr.target_chunk_id::text,
               cr.relationship_type
        FROM chunk_relationships cr
        JOIN code_chunks cc ON cc.chunk_id = cr.source_chunk_id
        WHERE cc.repo_id = :rid
        """
    ),
    {"rid": repo_id},
).all()
seen.update((src, tgt, rtype) for src, tgt, rtype in existing_rows)

def _add(src: str, tgt: str, rtype: str, weight: float = 1.0) -> None:
    key = (str(src), str(tgt), rtype)
    if key not in seen:
        seen.add(key)
        relationships.append(ChunkRelationship(...))
```

### Why this isn't ideal

1. **Extra round-trip.** Every reindex now issues a SELECT against
   `chunk_relationships` even for fresh first-indexes where the result is
   empty. Single indexed query, ~ms cost — but unnecessary.
2. **Memory cost is unbounded in theory.** Loads every existing edge into a
   Python `set`. Upstream comment says "few thousand rows for typical
   repos" — fine in practice. For a giant monorepo with hundreds of
   thousands of chunks, less fine.
3. **Diverges from the resilience batch pattern.** Upstream commit
   `7f12458` (`feat(resilience): idempotent chunk + symbol writes via ON
   CONFLICT upserts`) already standardised on
   `pg_insert(...).on_conflict_do_update()` for `code_chunks` and
   `symbols`. Relationships should use the same idiom for consistency.
4. **Race window** between SELECT and bulk INSERT. Not actually a problem
   here because `_build_chunk_relationships` runs inside a single
   transaction, but the pattern is fragile if the function ever gets
   refactored to commit mid-flight.

### Better fix

Drop the pre-load entirely. Replace `session.add_all(relationships)` with
a Postgres-native conflict-ignoring insert keyed on the existing
`unique_chunk_relationship` constraint.

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

# ... build `relationships` list as before, but without the pre-load and
# without the str() casts in _add (no longer needed) ...

if relationships:
    rows = [
        {
            "source_chunk_id": r.source_chunk_id,
            "target_chunk_id": r.target_chunk_id,
            "relationship_type": r.relationship_type,
            "weight": r.weight,
        }
        for r in relationships
    ]
    stmt = pg_insert(ChunkRelationship.__table__).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        constraint="unique_chunk_relationship"
    )
    session.execute(stmt)
    session.flush()
```

`DO NOTHING` (not `DO UPDATE`) because relationship rows are immutable — a
duplicate (source, target, type) with the same weight is genuinely the
same edge, no fields to refresh.

### Verification checklist

- [ ] Confirm the constraint is named `unique_chunk_relationship` in both
      Delphi (`backend/synsc/database/models.py`, search `ChunkRelationship`)
      and upstream. If named differently, pass the correct constraint name
      to `on_conflict_do_nothing`.
- [ ] The existing tests in
      [`backend/tests/test_reindex_relationships_idempotent.py`](backend/tests/test_reindex_relationships_idempotent.py)
      mock `session.execute` and assert the pre-load query runs. They
      will need rewriting against the `pg_insert` path. New test shape:
      patch `pg_insert(...).on_conflict_do_nothing` and assert the
      `session.execute` call is made with the expected statement.
- [ ] Drop the `existing_rows = session.execute(...)` block.
- [ ] Drop the `str(src), str(tgt)` casts inside `_add` — no longer needed
      because dedup happens in Postgres, not in Python.
- [ ] Full test suite passes: `cd backend && uv run pytest -v`.
- [ ] Run a real reindex against a small repo locally to confirm no
      regression in the relationship count.

### Where to land it

- **Delphi:** as a follow-up commit on `feat/upstream-sync-2026-04` (if
  the branch is still open) or a fresh `fix/relationships-on-conflict`
  branch off `master`.
- **Upstream:** open a PR against `synsc-context:main` titled
  `fix(reindex): use ON CONFLICT DO NOTHING for chunk_relationships`.
  The current upstream code at `synsc/services/indexing_service.py:73`
  is the pre-load workaround; same swap applies. Coordinate with the
  resilience batch (commits `65aa9f5`..`fd43e9a` on local feat branches)
  so that batch's eventual merge to `main` doesn't conflict.

### Estimated effort

Single PR, < 1 hour each side: ~10 lines of code change, ~30 lines of
test rewrite, plus the verification step above.

---

---

## 2. Per-user research API keys (Gemini / Anthropic / OpenAI)

**Status:** ⏳ Open. Currently the research provider key lives globally on
`config.research.api_key` (env var `GEMINI_API_KEY`). Multi-tenant Delphi
deployments need each user to bring their own key.

**Affected repos:** Synsci-Delphi (this repo). Upstream uses Supabase storage,
non-applicable.

**Priority:** medium — feature gap, not a correctness bug. Today's structured
`error_code: provider_not_configured` response is the agent-facing safety net
until this lands.

### What exists today

- `/v1/research` and the MCP `research` tool both pre-flight check
  `config.research.api_key` and return a structured 503 / tool error with
  `error_code: provider_not_configured`, `provider`, `action_required:
  configure_api_key`, and a human message naming `GEMINI_API_KEY`.
- The MCP tool docstring (visible to LLMs at tool-list time) flags the
  provider requirement so the agent knows the tool may be unavailable on a
  fresh Delphi instance.
- LLMs / agents pattern-match on `error_code` to surface the message to the
  end user without retrying.

### What's missing

A per-user storage path that lets each user bring their own key:

1. Migration: `user_research_credentials (user_id, provider, encrypted_key,
   created_at, updated_at)` — same encryption pattern as
   [`backend/synsc/services/token_encryption.py`](backend/synsc/services/token_encryption.py)
   (already used for GitHub + HuggingFace tokens).
2. HTTP endpoints mirroring the GitHub-token surface:
   - `PUT /v1/keys/research` — body `{provider, api_key}`; encrypt + upsert.
   - `GET /v1/keys/research` — return `{configured: bool, provider}` (never
     the key itself).
   - `DELETE /v1/keys/research`.
3. Wire-up in `ResearchService.provider`: look up the caller's encrypted
   key first, fall back to `config.research.api_key`, error with
   `provider_not_configured` only if both are missing.
4. The `/v1/research` 503 message should change to point at
   `/v1/keys/research` when per-user keys are enabled, not just the env var.

### Estimated effort

~150 LOC + Alembic migration + 6–8 tests. One PR. No upstream coupling —
this is a Delphi-only feature.

---

## How to use this file

- Add new entries below as additional "correct but not optimal" fixes
  surface. Keep entries self-contained — assume the reader has zero
  context on the original session.
- When an item ships, move it to a `## Done` section at the bottom with a
  link to the PR/commit instead of deleting, so the rationale stays
  searchable.
