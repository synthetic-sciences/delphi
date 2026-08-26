# Agent-mode generated source indexing

## Problem

The strict independent-development gold-path preflight found one locked target,
`channelz/grpc_channelz_v1/channelz.pb.go`, absent from both the historical and
fresh Delphi indexes. The 114,500-byte file exists at the pinned commit and in
the materialized snapshot, but Delphi's global `*.pb.go` exclusion removes it
before the existing size, binary-content, chunk, and embedding guards run.

This is a general product-coverage gap: generated source can define APIs and
behavior that coding agents must inspect. It is not an Okapi failure, and a
benchmark-specific one-file exception, dropped case, or partial score is
forbidden.

## Decision

In `agent` quality mode, retain generated **source-code** files that match the
existing generated-name patterns:

- `*.generated.*`, `*.gen.*`, `*-generated.*`, `*_generated.*`
- `*.g.dart`, `*.g.go`, `*.pb.go`, `*_pb2.py`

Fast and balanced modes retain their current exclusions. Agent mode continues
to exclude minified, bundle, vendor, runtime, source-map, lock, binary, media,
archive, database, cache, and build-output patterns.

The existing extension allowlist remains authoritative, so removing a
generated-name exclusion cannot admit an unsupported file type. Existing
500,000-byte, NUL/binary-content, parser, chunk, embedding-provider, and
PostgreSQL `tsvector` safety guards remain unchanged.

## Implementation

Define the generated-source pattern family once beside Git file-selection
logic. When `_should_exclude` runs in agent mode, omit only those patterns from
the active exclusion list. Do not add repository, path, benchmark, or language
exceptions.

Required regressions:

1. Agent mode includes representative `*.pb.go`, `*_pb2.py`, `*.g.go`, and
   generic generated source names.
2. Fast mode still excludes the same files.
3. Minified/bundle/map/lock/binary patterns remain excluded in agent mode.
4. The normal extension allowlist still rejects unsupported generated files.
5. The existing size and NUL guards remain green.

## Development protocol amendment

The old independent disabled result cannot remain the equality reference
because its index omitted a now-searchable locked target. Before any
File-Okapi candidate request:

1. Rebuild the complete 48-source independent development index from an empty
   isolated database and a new manifest.
2. Require exact source, file/chunk/embedding, lexical version/count, and
   gold-path searchability audits.
3. Run two disabled-File-Okapi controls and require exact metric rows and
   top-20 lists between those two fresh controls.
4. Use the fresh disabled control—not the historical preflight-incomplete
   result—as the candidate baseline.
5. Build and audit ARB development under the same agent-mode indexing policy.
6. Keep both final partitions untouched until the development Okapi decision
   is frozen.

The File-Okapi candidate configuration and adoption gates remain unchanged.
No second weight, tokenizer, candidate cap, generated-source policy, or
benchmark-side exception may be tuned after candidate outcomes are observed.

## Failure handling

- Any generated file that trips the existing size, NUL, parser, chunk, or
  embedding safety guard remains unsearchable and fails the gold-path preflight
  if it is a required target.
- Any incomplete source, count mismatch, technical failure, serving-config
  mismatch, or disabled-control nondeterminism aborts scoring.
- If complete searchable coverage cannot be established under these general
  rules, close the Okapi experiment and retain the frozen exact/current stack.
