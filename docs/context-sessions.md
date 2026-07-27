# Context sessions and handoffs

Context sessions preserve decision-relevant work without storing an
unbounded chat transcript. A stable session identity points to append-only
revisions containing:

- objective and structured task state;
- immutable source-snapshot references;
- accepted and rejected evidence references;
- decisions and unresolved questions;
- a deterministic token-budget selection manifest;
- an optional model-generated summary with an explicit model and version;
- parent session and revision references for handoffs.

Every mutation advances a session-wide `write_version`. Revision appends,
sharing/lifecycle changes, and handoff parent checks all use that version so
concurrent writers cannot silently overwrite or continue archived work.

The existing `/v1/contexts` named-blob API remains available for compatibility.
New reproducible workflows use `/v2/context-sessions`.

## Reproducibility and authorization

A revision stores snapshot, locator, and content hashes rather than copying
unrestricted source text into mutable session state. Selection is deterministic:
accepted evidence is considered first, rejected evidence is excluded, remaining
items retain pinned-snapshot and item order, and selection stops at the first
item that would exceed the token budget. Increasing the budget therefore
extends the prior selection instead of reshuffling it.

Reads and exports rehydrate selected items through the snapshot authorization
layer. If source or record access is later revoked, the revision and its
provenance remain intact but the unavailable content is omitted and reported in
`unavailable_items`. This is especially important for synchronized connector
records with changing permissions.

Model-generated summaries are the only intentionally non-deterministic field.
They are accepted only when `summary`, `summary_model`, and `summary_version`
are all supplied.

## Lifecycle

Create a private context:

```bash
curl -X POST http://localhost:8742/v2/context-sessions \
  -H "Authorization: Bearer $DELPHI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "release-review",
    "objective": "Verify the release against pinned evidence",
    "snapshot_ids": ["SNAPSHOT_ID"],
    "token_budget": 8000,
    "task_state": {"status": "in_progress"},
    "sharing_policy": "private"
  }'
```

Append a revision using the current head as an optimistic fence:

```bash
curl -X POST \
  http://localhost:8742/v2/context-sessions/SESSION_ID/revisions \
  -H "Authorization: Bearer $DELPHI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "expected_version": 1,
    "task_state": {"status": "completed"},
    "decisions": [{"decision": "release"}],
    "unresolved_questions": []
  }'
```

A stale `expected_version` returns HTTP `409`; the service never overwrites an
intervening revision.

Create an explicitly linked child:

```bash
curl -X POST \
  http://localhost:8742/v2/context-sessions/SESSION_ID/handoffs \
  -H "Authorization: Bearer $DELPHI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "deployment-follow-up",
    "objective": "Continue deployment verification",
    "handoff_note": "Start from the approved release evidence"
  }'
```

The child records both `parent_session_id` and `parent_revision_id`. It rebuilds
the same deterministic manifest under current authorization.

## HTTP surface

- `POST /v2/context-sessions`
- `GET /v2/context-sessions`
- `GET /v2/context-sessions/{session_id}?revision=N`
- `POST /v2/context-sessions/{session_id}/revisions`
- `PATCH /v2/context-sessions/{session_id}`
- `POST /v2/context-sessions/{session_id}/handoffs`
- `GET /v2/context-sessions/{session_id}/export?revision=N`

Sessions are owner-scoped. Sharing policy is explicit (`private` or `shared`);
setting `shared` does not grant access to the owner's full index. Exports contain
only pinned references and selected content that the owner remains authorized
to read. Optional expiration applies to the complete session; expired sessions
fail closed with HTTP `410`.
