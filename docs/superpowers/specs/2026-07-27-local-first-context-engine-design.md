# Local-First Context Engine Design

**Status:** Approved product direction; implementation specification

**Date:** 2026-07-27

**Scope:** Delphi open-source engine and the private production-like staging mirror

## Summary

Delphi will be a local-first hybrid context engine. Its complete indexing,
retrieval, versioning, context assembly, and private-source workflow will remain
open-source, self-hostable, and usable without a cloud account. Optional
providers may add web discovery, crawling, connector synchronization, hosted
models, collaboration, and compute-heavy research, but they will not be
dependencies of the local data plane.

The implementation will evolve the existing modular monolith rather than
replace it. Stable provider contracts, immutable source snapshots, a
policy-aware query planner, and durable research jobs will become the seams
between capabilities. Existing HTTP, MCP, CLI, database, and deployment
surfaces will remain compatible while callers migrate to the new contracts.

## Goals

1. Make local indexing and retrieval complete enough that a user never needs a
   hosted service for private repositories, folders, papers, datasets, or
   documentation.
2. Produce reproducible answers and context packs whose evidence resolves to an
   exact source revision.
3. Support current documentation, package versions, repositories, websites,
   papers, datasets, and connector-backed sources through one source model.
4. Offer optional web search, crawling, remote connectors, hosted reranking,
   and deep research through replaceable provider contracts.
5. Give agents a small, stable set of high-value operations through HTTP, MCP,
   CLI, and SDK surfaces.
6. Preserve privacy by making outbound data flow explicit, inspectable, and
   denied by default for private content.
7. Make ingestion and research jobs durable, observable, resumable, and safe
   under concurrent workers.
8. Validate quality with deterministic contracts, end-to-end tests, deployment
   smoke tests, and local-only comparative benchmarks.

## Non-goals

- Replacing PostgreSQL and pgvector with a new primary database.
- Splitting the backend into networked microservices before scale requires it.
- Requiring a Delphi-hosted account, billing system, or control plane.
- Sending local source content to an external model by default.
- Rewriting all existing source-specific tables in one migration.
- Publishing comparative benchmark artifacts or credentials to either
  repository.

## Product invariants

1. **Local completeness:** indexing, search, reading, context assembly, and
   version pinning work without hosted Delphi services.
2. **Default-deny egress:** private or local content cannot leave the machine
   unless an explicit policy permits the provider, purpose, and source.
3. **Immutable evidence:** a completed answer always points to immutable source
   snapshots, even after the source refreshes.
4. **Atomic visibility:** an incomplete refresh never replaces the last healthy
   active snapshot.
5. **Provider independence:** core services depend on provider protocols, not
   vendor SDKs.
6. **Backward compatibility:** existing HTTP routes and MCP tools keep working
   during migration, with deprecation metadata before removal.
7. **Auditable budgets:** remote calls, tokens, elapsed time, sources, and job
   steps are bounded and recorded.
8. **Recoverable rollout:** database changes use expand/migrate/switch/contract;
   deploys have health gates and a tested rollback target.

## Architecture

```text
CLI / SDK / HTTP / MCP / dashboard
                |
          Query application layer
     (policy, scope, budget, planning)
          /                 \
 Local data plane       Optional providers
 - source catalog       - web search
 - immutable snapshots  - crawling
 - parsers/chunkers      - connector sync
 - local embeddings     - hosted models
 - lexical/vector index - heavy research
 - symbol/code graph    - collaboration/sync
 - context store
          \                 /
          PostgreSQL + pgvector
```

The backend stays a modular monolith with an API process and durable worker
processes. Modules communicate through Python contracts and persisted job
records. The contracts make later process separation possible without making
it a prerequisite.

### Module boundaries

New code will be organized around these boundaries:

- `domain/sources`: source identities, snapshots, artifacts, citations, and
  policies.
- `domain/query`: typed query modes, scope, budgets, plans, and result models.
- `providers`: capability protocols, registry, local implementations, optional
  remote adapters, and normalized failures.
- `services/ingestion`: snapshot construction, incremental diffing, manifests,
  and activation.
- `services/retrieval`: candidate generation, fusion, reranking, and evidence
  selection.
- `services/context`: token-budgeted context assembly and persisted context
  sessions.
- `services/research`: durable plans, execution steps, events, synthesis, and
  follow-ups.
- `services/sync`: connector cursors, schedules, and conflict handling.
- `api`: transport-only validation and mapping for HTTP and MCP.

Existing modules will move behind these boundaries incrementally. File moves
are not required merely to satisfy the design; dependency direction and typed
contracts matter more than directory churn.

## Source and version model

### Entities

| Entity | Purpose |
|---|---|
| `Source` | Stable logical origin, ownership, visibility, locator, and source type |
| `SourceSnapshot` | Immutable revision with content identity and activation state |
| `Artifact` | File, page, document, package entry, or connector record in a snapshot |
| `Chunk` | Searchable content with exact coordinates and structural metadata |
| `IndexManifest` | Parser, schema, embedding, ranker, and completeness versions |
| `SyncCursor` | Encrypted connector-specific incremental state |
| `Citation` | Answer span mapped to snapshot, artifact, and source coordinates |

`Source` is mutable catalog metadata. All evidence-bearing content lives below
an immutable `SourceSnapshot`.

### Revision identity

A snapshot records both a normalized content digest and the strongest
source-native revision available:

- Git commit SHA, branch, and tag for repositories.
- Package name, registry, version, and distribution digest for packages.
- ETag, Last-Modified value, canonical URL, and crawl timestamp for web
  documentation.
- File digest and stable relative path for local folders.
- Document digest, edition/version, and page map for PDFs and papers.
- Dataset revision/config/split fingerprints.
- Connector revision token and record identifiers for remote workspaces.

Branch names and mutable URLs are selectors, not immutable evidence
identifiers.

### Refresh transaction

1. Resolve the requested selector to a source-native revision.
2. Create a pending snapshot and persist an ingestion job.
3. Inventory artifacts and compare their digests with the last active snapshot.
4. Reuse unchanged artifact/chunk records where processing manifests match.
5. Parse and index changed artifacts; write tombstones for removed artifacts.
6. Validate row counts, manifests, references, and vector dimensions.
7. Atomically activate the new snapshot and supersede the previous active one.
8. Retain prior snapshots according to local retention policy.

Failure before activation leaves the old snapshot active and records a
diagnostic failure. Retrying a job uses an idempotency key derived from source,
revision, and processing manifest.

### Compatibility migration

The first database release adds snapshot metadata without renaming or deleting
existing repository, paper, dataset, documentation, and chunk tables.
Compatibility adapters will:

1. Backfill a source and initial snapshot for every existing indexed entity.
2. Dual-write legacy entity identifiers and new snapshot identifiers.
3. Move reads to the snapshot-aware repository layer.
4. stop dual-writing only after compatibility tests pass across two releases.
5. Remove obsolete columns only in a separately approved contract migration.

The SQLAlchemy models, Alembic migrations, and local bootstrap SQL must change
together.

## Query, retrieval, and research

### Query modes

- `search`: ranked evidence without synthesis.
- `answer`: citation-backed synthesis over selected evidence.
- `context`: task-specific, token-budgeted agent context.
- `web`: optional web discovery and crawling followed by local normalization.
- `research`: durable, resumable multi-step investigation.
- `agent`: policy-constrained selection of the preceding operations.

### Planning flow

Every request resolves:

1. intent and output mode;
2. source scope and source selectors;
3. exact snapshots or freshness constraints;
4. egress policy;
5. cost, latency, token, source, and provider-call budgets;
6. evidence and confidence thresholds.

Local retrieval runs before optional remote expansion:

1. lexical, vector, path, symbol, and graph candidate generation;
2. rank fusion with query-intent features;
3. optional local or permitted hosted reranking;
4. diversity and coverage selection;
5. context expansion around symbols, imports, callers, tests, docs, and config;
6. citation construction and result validation.

The planner returns a typed explanation of selected snapshots, providers,
budgets used, fallback behavior, and omitted evidence. Internal ranker scores
remain diagnostic and are not presented as calibrated factual confidence.

### Web material

Web search results are discovery records, not durable evidence. A result becomes
queryable evidence only after the crawler:

1. validates its URL and network policy;
2. fetches with size, content-type, redirect, and private-address limits;
3. records provenance and retrieval time;
4. normalizes the content into an immutable snapshot;
5. runs the standard ingestion and activation checks.

Ephemeral web evidence used during one research job is still frozen under that
job so its citations remain inspectable.

### Research jobs

Research plans and steps are stored in PostgreSQL rather than process memory.
Each job includes:

- objective, plan, scope, policy, and terminal condition;
- a hard budget ledger;
- leased steps with heartbeat and retry state;
- captured evidence and rejected evidence;
- append-only progress events;
- synthesis revisions and citations;
- terminal status and normalized stop reason.

Workers reclaim expired leases safely. Cancellation is cooperative but durable.
Follow-ups create a child turn that reuses the original frozen evidence set and
may add new evidence only under the current policy.

## Provider system

### Contracts

The provider layer exposes capability-specific protocols:

- `EmbeddingProvider`
- `RerankProvider`
- `SearchProvider`
- `CrawlerProvider`
- `ConnectorProvider`
- `SynthesisProvider`
- `ResearchProvider`
- `SyncProvider`

Providers declare:

- capability and semantic version;
- local or remote execution;
- accepted content classifications;
- streaming, cancellation, and retry support;
- cost-estimation support;
- request and response size limits;
- health and readiness state.

All provider responses are normalized into domain records before they reach
retrieval or research services. HTTP and MCP handlers never instantiate vendor
clients directly.

### Registry and configuration

The registry loads built-in local providers without network access. Optional
providers load from explicit configuration or Python entry points. Missing
optional dependencies produce a capability-unavailable result with installation
guidance; they do not prevent the server from starting.

Provider selection is deterministic for a given request, policy, health
snapshot, and configuration. Automatic fallback may change the implementation
but cannot broaden the egress policy or exceed the budget.

### Normalized failures

Provider failures map to:

- `unavailable`
- `unauthorized`
- `forbidden_by_policy`
- `rate_limited`
- `budget_exhausted`
- `timeout`
- `invalid_response`
- `content_rejected`
- `cancelled`
- `internal_error`

Responses carry retryability and an optional safe retry-after duration. Secrets,
authorization headers, signed URLs, and private excerpts are removed from logs
and persisted error details.

## Privacy and security

### Source classifications

Every source and snapshot has one of these classifications:

- `public`
- `unlisted`
- `private`
- `local_sensitive`

The default egress rules are:

| Classification | Local processing | Remote discovery | Remote content processing |
|---|---:|---:|---:|
| `public` | allowed | policy-controlled | policy-controlled |
| `unlisted` | allowed | denied by default | explicit opt-in |
| `private` | allowed | denied | explicit provider/source opt-in |
| `local_sensitive` | allowed | denied | denied unless a one-request override is confirmed |

Queries and URLs may themselves reveal sensitive information. Their disclosure
is evaluated separately from source-content disclosure.

### Egress enforcement

Policy is checked at the provider boundary, not only in UI code. Every remote
call receives an `EgressDecision` containing the allowed fields, purpose,
provider, request identifier, and policy basis. A redacted audit event records
the decision without persisting disclosed secret material.

An offline test mode blocks outbound sockets except explicitly started local
test services. Zero-egress acceptance tests run against this mode.

### Credentials and connector data

- Provider and connector credentials are encrypted at rest.
- Secret values are never returned by read APIs after creation.
- Connector cursors are encrypted if they contain opaque access state.
- Web crawlers reject local, link-local, metadata-service, and disallowed
  redirect targets.
- Archive and document extraction enforce decompression, nesting, page, and
  file-size limits.
- Authorization is checked before source resolution to avoid metadata leaks.

## Connectors, synchronization, and collaboration

Connectors translate external records into the same source/snapshot/artifact
model. A connector does not write search indexes directly.

Synchronization is incremental and idempotent:

1. acquire a per-source lease;
2. read the last encrypted cursor;
3. fetch bounded changes;
4. stage a snapshot;
5. validate and activate it atomically;
6. advance the cursor only after activation.

Deletion and permission changes propagate as tombstones. Losing access to a
remote record makes it unavailable to future queries without rewriting
historical research evidence the user is still authorized to inspect.

Collaboration and hosted synchronization are optional. Local contexts remain
local until explicitly shared. Shared contexts contain snapshot references and
selected content, not implicit access to the sender's entire index.

## Context memory and agent handoffs

A context session stores:

- objective and task state;
- pinned source snapshots;
- accepted and rejected evidence;
- token-budgeted context revisions;
- decisions and unresolved questions;
- parent/child handoff relationships;
- expiration and sharing policy.

Context sessions are not unconstrained chat-history stores. They retain
decision-relevant evidence and provenance. Rebuilding a context pack from the
same snapshots and configuration must be deterministic aside from explicitly
versioned model-generated summaries.

## Product surfaces

### HTTP

New typed endpoints live under `/v2` while existing routes remain available:

- source catalog, snapshot listing, refresh, pinning, and freshness;
- unified query execution;
- context-session lifecycle;
- research job lifecycle and event streaming;
- provider capability and policy inspection;
- connector configuration and synchronization.

OpenAPI schemas are the transport source of truth. Error envelopes include a
stable code, safe message, request identifier, retryability, and structured
details.

### MCP

The recommended MCP profile stays small:

- `resolve_source`
- `search`
- `read`
- `context`
- `research`
- `research_status`

Capability discovery describes optional modes and providers. Specialized
existing tools remain available in explicit profiles for compatibility.
Default tool registration must not require remote credentials.

### CLI and SDK

The CLI exposes the same application services:

- source add/list/refresh/pin/remove;
- search/answer/context;
- research start/status/watch/cancel/follow-up;
- provider list/doctor;
- policy inspect/test;
- diagnostics and export.

Machine-readable JSON is available for every non-interactive command. SDK
generation begins from the stable OpenAPI schema after the `/v2` contracts pass
compatibility review.

### Dashboard

The dashboard focuses on operational clarity:

- sources, revisions, freshness, and ingestion health;
- query evidence and citations;
- provider status and outbound-data policy;
- research progress and budget;
- connector synchronization;
- context sessions and sharing;
- deployment and worker diagnostics for administrators.

The frontend continues to use HTTP only and never accesses the database
directly.

## Observability and operations

Structured logs and metrics use request, job, source, snapshot, provider, and
worker identifiers. They never contain raw credentials or unrestricted source
content.

Required metrics include:

- ingestion throughput, reuse ratio, failures, and activation latency;
- queue depth, lease age, retry count, and dead-letter count;
- retrieval latency by stage and candidate counts;
- provider calls, latency, fallback, errors, and budget use;
- research step progress and stop reasons;
- snapshot age and freshness-check results;
- citation validation failures;
- HTTP/MCP error rates and rate-limit activity.

Health endpoints distinguish:

- liveness: process event loop responds;
- readiness: database schema and mandatory local providers are ready;
- capability health: optional provider status without failing global readiness.

## Error handling and recovery

- Ingestion writes are resumable and idempotent.
- Snapshot activation is a single database transaction.
- Worker steps use leases and bounded retry with jitter.
- Permanent failures enter a visible dead-letter state.
- Provider timeouts and rate limits respect the remaining request budget.
- A remote failure cannot delete or invalidate local results.
- Schema-version mismatches fail readiness with migration guidance.
- Context or research exports remain readable even if an optional provider is
  removed.

## Performance and scaling

The first implementation optimizes the modular monolith:

- incremental parsing and embedding reuse;
- bounded batch sizes and streaming reads;
- PostgreSQL advisory or row locks for conflicting source jobs;
- HNSW/vector, lexical, trigram, path, and symbol indexes;
- queue leases that support multiple worker processes;
- cached query plans and embeddings keyed by complete processing manifests;
- backpressure when queue, memory, or provider budgets are exhausted.

Horizontal API and worker scaling must be safe, but separate network services
are deferred until profiling demonstrates a need.

## Delivery sequence

Each phase is a separate design/plan/build/verify/merge loop. The shared
implementation must remain releasable after every phase.

1. **Baseline and contracts**
   - Freeze compatibility fixtures and quality baselines.
   - Introduce domain result/error types, policy primitives, and provider
     registry without changing default behavior.
2. **Immutable source snapshots**
   - Add schema, repositories, compatibility adapters, backfill, incremental
     manifests, and atomic activation.
3. **Query planner and retrieval pipeline**
   - Unify modes, scope/version resolution, fusion, reranking, evidence
     validation, budgets, and explainability.
4. **Web discovery and crawling**
   - Add provider contracts, a safe crawler, capture semantics, freshness, and
     package/documentation version discovery.
5. **Durable research**
   - Persist plans, leases, events, budgets, cancellation, follow-ups, and
     citation-checked synthesis.
6. **Connector synchronization**
   - Implement connector lifecycle, encrypted cursors, incremental sync, local
     folder watching, permission changes, and scheduling.
7. **Context sessions and handoffs**
   - Add reproducible context revisions, task state, sharing policy, and export.
8. **Unified product surfaces**
   - Stabilize `/v2` HTTP, compact MCP, CLI, SDK, and dashboard workflows.
9. **Hardening and release**
   - Security review, load/concurrency testing, packaging, migrations,
     observability, deployment, rollback, and operator documentation.
10. **Local comparative evaluation**
    - Run fair retrieval and downstream-task benchmarks, validity review, and
      failure analysis without committing results.

## Verification strategy

### Test layers

1. Unit tests for policies, revisions, budgets, provider normalization, fusion,
   context assembly, and state machines.
2. Property tests for idempotency, deterministic manifests, budget monotonicity,
   and citation coordinate round-trips.
3. Provider contract suites reusable by local and optional provider adapters.
4. PostgreSQL integration tests for concurrency, atomic activation, lease
   recovery, migrations, access control, and vector/lexical retrieval.
5. Docker end-to-end tests spanning API, worker, database, MCP proxy, and
   frontend.
6. Offline zero-egress tests that fail any unexpected outbound connection.
7. Security tests for SSRF, archive limits, secret redaction, source isolation,
   authorization-before-resolution, and policy bypass attempts.
8. Compatibility tests for existing HTTP routes, MCP tools, CLI behavior,
   stored sources, and migration from current releases.
9. Deployment smoke tests against the private Render/Vercel staging system.

### Release gates

- Existing tests, strict type checking, lint, frontend build, and package tests
  remain green.
- A failed refresh never changes the active snapshot.
- Version-pinned queries resolve only evidence from the requested revision.
- Citation fixtures resolve to exact stored content and coordinates.
- Offline/local-only requests produce zero outbound connections.
- A one-artifact source change reuses all unaffected chunks and embeddings.
- Concurrent workers cannot activate duplicate snapshots or execute the same
  leased step simultaneously.
- Provider failure and removal leave local retrieval operational.
- No secret or private excerpt appears in structured logs or error responses.
- Search latency and retrieval quality do not regress beyond pre-registered
  tolerances without an explicit, evidence-backed decision.
- New features remain disabled or safely degradable until their migrations and
  required providers are ready.

## Benchmark policy

Comparative benchmarks run locally after functional and deployment validation.
The benchmark corpus, queries, judge prompts, expected evidence, scoring rules,
and statistical analysis are frozen before the final run. Corpus coverage and
source availability are reported separately from retrieval quality.

Results include confidence intervals, per-category failures, and threats to
validity. Results and credentials are not committed or pushed to Delphi or the
staging repository.

## Private staging rollout

The private `synthetic-sciences/synsci-context` repository is a
production-like test target, not the implementation source of truth. Once the
corresponding Delphi phases pass their release gates:

1. Fetch and verify the current staging `main`.
2. Record a recoverable pre-sync commit/tag reference.
3. Port the shared source, query, provider, research, and frontend contracts
   while preserving the staging repository's Supabase authentication, SaaS
   migrations, and deployment-specific modules.
4. Run backend, migration, frontend, and compatibility suites against the
   staging shape.
5. Commit as Aayam Bansal and push directly to staging `main`, as explicitly
   requested.
6. Apply expand-phase database migrations before enabling dependent features.
7. Observe the Render API and worker deployment and the Vercel frontend
   deployment to terminal state.
8. Run authenticated smoke tests for health, source ingest, incremental
   refresh, version-pinned search, context, research events, cancellation,
   persistence, and authorization.
9. Inspect logs and metrics for migration, worker, provider, security, and
   latency failures.
10. Roll back to the recorded pre-sync revision if a release gate fails, then
    diagnose in Delphi before retrying.

Staging secrets remain in the deployment platforms. They are never copied into
the repository, test output, benchmark artifacts, or chat.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Schema migration disrupts existing indexes | Additive schema, backfill, dual-write compatibility, atomic switch |
| Provider abstraction loses capability detail | Capability-specific protocols and explicit feature discovery |
| Remote features compromise local privacy | Enforced egress decisions, source classification, zero-egress tests |
| Research jobs become expensive or unbounded | Persisted hard budgets, terminal conditions, cancellation, step leases |
| MCP surface grows beyond agent usability | Compact default profile and capability discovery |
| Incremental refresh serves mixed revisions | Pending snapshots and transactional activation |
| Staging diverges from open-source behavior | Shared contract fixtures and explicit divergence adapters |
| Benchmark gains reflect corpus bias | Frozen balanced corpus, coverage accounting, downstream tasks, validity report |

## Completion criteria

The program is complete only when:

1. all delivery phases are merged through Delphi's reviewed branch workflow;
2. every release gate passes locally and in CI;
3. the private staging mirror is synchronized directly to `main`;
4. Render and Vercel deployments reach healthy terminal states;
5. authenticated deployment smoke tests pass;
6. fair local comparative benchmarks and a threats-to-validity review are
   reported to the user;
7. no required behavior depends on an optional hosted service.
