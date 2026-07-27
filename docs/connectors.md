# Incremental connectors

Delphi connectors turn external records into the same immutable source
snapshots used by repositories, papers, datasets, and documentation. The
connector boundary is local-first: adapters return normalized records and
never write search indexes directly.

`local-folder` is built in. It reads UTF-8 text files from a directory on the
Delphi host and does not make network requests. Additional adapters can be
installed without changing the sync queue or snapshot model.

## Safety and durability

Connector configuration and incremental cursors are Fernet-encrypted with
`TOKEN_ENCRYPTION_KEY`. Neither value is returned by HTTP, MCP, source listing,
or job-status responses.

One sync page follows this order:

1. Claim a durable job lease for one source.
2. Decrypt that source's configuration and last activated cursor in memory.
3. Ask the provider for a bounded page of changes.
4. Merge additions, updates, permission revocations, and tombstones into a
   staged immutable snapshot.
5. Validate and seal the snapshot, activate its head, and advance the encrypted
   cursor in one database transaction.

If validation or activation fails, the transaction rolls back: the old head
and old cursor remain current. Concurrent enqueue requests reuse the same
active job, and workers claim with `FOR UPDATE SKIP LOCKED` plus lease
generation fencing.

Provider permission changes are materialized into the snapshot. A deleted
record or a record that no longer includes the connector owner becomes a
tombstone, so stale content cannot remain searchable.

## Local folder

Create and sync a local directory over HTTP:

```bash
curl -X POST http://localhost:8742/v2/connectors \
  -H "Authorization: Bearer $DELPHI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "local-folder",
    "display_name": "Project notes",
    "external_ref": "file:///absolute/path/to/notes",
    "classification": "local_sensitive",
    "configuration": {
      "path": "/absolute/path/to/notes",
      "include": ["*.md", "*.txt"],
      "exclude": [".git/*", "build/*"],
      "max_files": 10000,
      "max_file_bytes": 2000000,
      "max_total_bytes": 100000000
    },
    "schedule_seconds": 300
  }'

curl -X POST http://localhost:8742/v2/connectors/SOURCE_ID/sync \
  -H "Authorization: Bearer $DELPHI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"priority": 0}'

curl http://localhost:8742/v2/connector-sync-jobs/JOB_ID \
  -H "Authorization: Bearer $DELPHI_API_KEY"
```

The path is resolved on the API/worker host. Symlink targets are skipped,
binary files are ignored, and file-count and byte limits fail closed instead
of publishing an incomplete snapshot. Default includes cover common source,
documentation, configuration, and data-text formats.

Scheduled sync requires the worker process. A manual sync and a scheduled sync
use the same queue and idempotency rules.

## MCP tools

The `sources` and `all` MCP profiles expose five lifecycle tools:

- `connector_create`
- `connector_list`
- `connector_sync`
- `connector_status`
- `connector_delete`

Search the resulting content through the regular `search` tool with
`source_types=["connector"]`, or scope by the connector's `source_id`.

## Provider contract

Adapters implement `ConnectorProvider.sync(ConnectorSyncRequest)` and return a
`ConnectorSyncResponse`. Requests carry a page limit, deadline, cancellation
token, decrypted configuration, and the last activated cursor. Responses carry
normalized records, the next cursor, and `has_more`.

Every adapter must:

- honor page, time, file, and response-size bounds;
- use stable external record IDs;
- emit tombstones for deletions;
- include current accessible principals when the upstream exposes them;
- avoid logging credentials, cursors, or record content;
- perform no direct index or snapshot writes.

The durable service owns encryption, leases, retries, snapshot staging, head
activation, cursor advancement, schedules, and owner scoping.
