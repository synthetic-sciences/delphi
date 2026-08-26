# Agent-Mode Generated Source Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make readable generated source code searchable in agent mode, then replace the preflight-incomplete independent control with a fresh deterministic disabled-Okapi baseline.

**Architecture:** File selection remains centralized in `GitClient._should_exclude`. Agent mode removes only the generated-source pattern family from the active exclusion list; extension inclusion and all downstream size, binary, parser, chunk, embedding, and PostgreSQL safety guards remain unchanged. Evaluation rebuilds the entire independent development cohort from an empty database before making any candidate request.

**Tech Stack:** Python 3.12, Pydantic configuration, pathlib/fnmatch Git filtering, pytest, PostgreSQL 14 + pgvector, Delphi round-3 harness.

## Global Constraints

- Development splits only; do not inspect or score either final partition.
- No repository, path, case, gold-file, or benchmark-specific exception.
- Keep the 500,000-byte and NUL/binary-content guards unchanged.
- Keep minified, bundle, vendor, runtime, source-map, lock, binary, media, archive, database, cache, and build-output exclusions unchanged.
- Do not change the frozen File-Okapi weight, tokenizer, candidate cap, BM25 constants, or serving configuration.
- The historical independent result is provenance only; candidate comparisons use the new two-repeat disabled control.

---

### Task 1: Agent-mode generated source selection

**Files:**
- Modify: `backend/synsc/core/git_client.py:479-511`
- Modify: `backend/synsc/workers/indexing_worker.py:52-70`
- Test: `backend/tests/test_quality_mode.py:109-123`
- Test: `backend/tests/test_indexing_worker.py:102-120`

**Interfaces:**
- Consumes: `GitClient.effective_quality_mode`, `GitConfig.exclude_patterns`, and `_should_include(path: Path) -> bool`.
- Produces: module constant `_AGENT_GENERATED_SOURCE_PATTERNS: frozenset[str]`; unchanged `_should_exclude(path: Path, repo_root: Path) -> bool` signature.

- [ ] **Step 1: Write failing generated-source selection tests**

Add:

```python
def test_should_exclude_keeps_generated_source_only_in_agent_mode(tmp_path):
    from synsc.core.git_client import GitClient

    agent = GitClient(repos_dir=tmp_path, quality_mode="agent")
    fast = GitClient(repos_dir=tmp_path, quality_mode="fast")
    for name in (
        "channelz.pb.go",
        "messages_pb2.py",
        "model.g.go",
        "client.generated.ts",
    ):
        path = tmp_path / name
        path.write_text("// generated source")
        assert agent._should_include(path) is True
        assert agent._should_exclude(path, tmp_path) is False
        assert fast._should_exclude(path, tmp_path) is True


def test_agent_mode_keeps_non_source_and_minified_exclusions(tmp_path):
    from synsc.core.git_client import GitClient

    agent = GitClient(repos_dir=tmp_path, quality_mode="agent")
    for name in ("app.min.js", "bundle.js.map", "package-lock.json", "asset.png"):
        path = tmp_path / name
        path.write_text("excluded")
        assert agent._should_exclude(path, tmp_path) is True


def test_read_repository_file_rejects_oversized_generated_source(
    tmp_path, monkeypatch
):
    source = tmp_path / "channelz.pb.go"
    source.write_text("x" * 101)
    monkeypatch.setattr(indexing_worker, "_MAX_INDEXED_FILE_BYTES", 100)
    assert indexing_worker._read_repository_file(
        tmp_path, {"path": source.name}
    )["error"] == "file_too_large"


def test_read_repository_file_rejects_nul_generated_source(tmp_path):
    source = tmp_path / "messages_pb2.py"
    source.write_bytes(b"prefix\x00suffix")
    assert indexing_worker._read_repository_file(
        tmp_path, {"path": source.name}
    )["error"] == "binary_content"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=backend backend/.venv/bin/pytest -q \
  backend/tests/test_quality_mode.py::test_should_exclude_keeps_generated_source_only_in_agent_mode \
  backend/tests/test_quality_mode.py::test_agent_mode_keeps_non_source_and_minified_exclusions \
  backend/tests/test_indexing_worker.py::test_read_repository_file_rejects_oversized_generated_source \
  backend/tests/test_indexing_worker.py::test_read_repository_file_rejects_nul_generated_source
```

Expected: the generated-source test fails because agent mode still applies `*.pb.go`, `*_pb2.py`, `*.g.go`, and `*.generated.*`.

- [ ] **Step 3: Implement the minimal agent-mode pattern exemption**

In `git_client.py`, define:

```python
_AGENT_GENERATED_SOURCE_PATTERNS = frozenset(
    {
        "*.generated.*",
        "*.gen.*",
        "*-generated.*",
        "*_generated.*",
        "*.g.dart",
        "*.g.go",
        "*.pb.go",
        "*_pb2.py",
    }
)
```

In `_should_exclude`, after copying `exclude_patterns`:

```python
if self.effective_quality_mode == "agent":
    patterns = [
        pattern
        for pattern in patterns
        if pattern not in _AGENT_GENERATED_SOURCE_PATTERNS
    ]
```

In the legacy queued worker's `_read_repository_file`, reject a file before
reading when its stat size exceeds `_MAX_INDEXED_FILE_BYTES`, and reject
content containing `"\x00"` before it reaches chunking or PostgreSQL. Reuse
the same configured cap as the direct indexing service. Do not alter
`_should_include` or weaken any direct indexing safety guard.

- [ ] **Step 4: Verify GREEN and regression coverage**

Run:

```bash
PYTHONPATH=backend backend/.venv/bin/pytest -q \
  backend/tests/test_quality_mode.py \
  backend/tests/test_indexing_worker.py \
  backend/tests/test_file_okapi.py \
  backend/tests/test_file_okapi_indexing.py
```

Expected: all pass.

- [ ] **Step 5: Run full verification**

Run:

```bash
cd backend
env -u DATABASE_URL PYTHONPATH="$PWD" \
  /Users/aayambansal/Desktop/syntheticsciences/delphi/backend/.venv/bin/pytest -q
PYTHONPATH="$PWD" \
  /Users/aayambansal/Desktop/syntheticsciences/delphi/backend/.venv/bin/ruff check synsc tests
PYTHONPATH="$PWD" \
  /Users/aayambansal/Desktop/syntheticsciences/delphi/backend/.venv/bin/mypy synsc
git diff --check
```

Expected: full suite, Ruff, mypy, and diff check pass.

- [ ] **Step 6: Request defect-focused review**

Review the complete uncommitted diff against
`docs/superpowers/specs/2026-08-24-agent-generated-source-indexing-design.md`.
Fix every Critical/Important issue and rerun Step 5.

- [ ] **Step 7: Commit the reviewed product change**

After explicit commit authorization:

```bash
git add \
  backend/synsc/core/git_client.py \
  backend/synsc/workers/indexing_worker.py \
  backend/tests/test_quality_mode.py \
  backend/tests/test_indexing_worker.py
git add -f \
  docs/superpowers/specs/2026-08-24-agent-generated-source-indexing-design.md \
  docs/superpowers/plans/2026-08-24-agent-generated-source-indexing.md
git commit -m "fix(indexing): retain generated source in agent mode"
```

### Task 2: Fresh independent control and candidate handoff

**Files:**
- Create: `new/round3/results/native-delphi-independent-okapi-dev-sources-v3.jsonl`
- Create: `new/round3/results/native-delphi-independent-okapi-dev-index-audit-v3.json`
- Create: disabled-control and paired-analysis result artifacts under `new/round3/results/`

**Interfaces:**
- Consumes: reviewed Task 1 commit; independent development lock; `provision_delphi_local.py`, `audit_delphi_index.py`, and `run_arb.py`.
- Produces: complete searchable 48-source cohort and two exact disabled-control runs suitable as the File-Okapi candidate baseline.

- [ ] **Step 1: Recreate the isolated independent database**

Stop its API, drop only `delphi_file_okapi_independent_dev_20260824`, recreate
it, apply `database/supabase/setup_local.sql`, and upgrade to the feature
branch migration head.

- [ ] **Step 2: Provision all 48 sources serially**

Launch the reviewed feature API with `SYNSC_FILE_OKAPI=false`, exact vectors,
and the frozen serving settings. Run:

```bash
PYTHONPATH=. /Users/aayambansal/Desktop/syntheticsciences/delphi/backend/.venv/bin/python \
  -u harness/provision_delphi_local.py \
  --sample-files corpus/independent/v1/development.jsonl \
  --bare-root corpus/independent/bare \
  --snapshot-root corpus/snapshots \
  --container-root "$PWD/corpus/snapshots" \
  --base-url http://127.0.0.1:28943 \
  --api-key file-okapi-independent-admin \
  --manifest results/native-delphi-independent-okapi-dev-sources-v3.jsonl \
  --workers 1
```

Expected: 48/48 indexed, zero failures.

- [ ] **Step 3: Run strict source and lexical audits**

Require exactly 48 repositories and exact manifest/database IDs. For each
snapshot, compute the complete eligible path set with the reviewed agent-mode
Git selection plus the unchanged 500,000-byte and NUL guards; require exact set
equality with `repository_files`, not merely positive counts. Then require
positive chunks, chunk/embedding equality, every repository at lexical version
`v1`, declared lexical count equal to actual count, non-empty JSONB maps, and
gold-path searchability for all 48 cases. Write the expected/actual path counts,
missing paths, and extra paths to a hashed
`generated_source_file_coverage_v1` artifact.

- [ ] **Step 4: Run two disabled controls**

Run `I-dev-delphi-native-generated-source-okapi-disabled-top20-r1` and `r2`
with `file_okapi_configured=false`, API `top_k=20`, and the complete frozen
expected-config subset.

- [ ] **Step 5: Require fresh-control repeatability**

Compare r1/r2 case sets, metric dictionaries, and ranked top-20 files.
Require exact equality for all 48; abort candidate scoring otherwise.

- [ ] **Step 6: Recreate and provision ARB development under the same policy**

Recreate only `delphi_file_okapi_arb_dev_20260824`, apply bootstrap SQL and the
reviewed feature migration head, then provision all 68 ARB development
snapshot pairs serially to
`results/native-delphi-arb-okapi-dev-sources-v3.jsonl`.

- [ ] **Step 7: Run exact ARB source, file, lexical, and gold-path audits**

Require exactly 68 repositories and exact manifest/database identities. Compute
eligible snapshot paths with the same reviewed agent selection plus size/NUL
guards and require exact set equality with `repository_files`. Require positive
chunks, chunk/embedding equality, lexical `v1`, exact declared/actual lexical
document counts, valid non-empty term maps, and searchable gold paths for all
75 cases.

- [ ] **Step 8: Establish a fresh repeated ARB disabled control**

With `SYNSC_FILE_OKAPI=false`, run two config-attested API-top-20 controls and
require exact case sets, metric dictionaries, and top-20 rankings between
repeats. Historical pre-amendment ARB runs remain provenance only.

- [ ] **Step 9: Run and repeat the independent File-Okapi candidate**

Only after both independent and ARB source/file/lexical/gold audits and both
fresh disabled-control repeatability gates pass, restart the independent
API/database with `SYNSC_FILE_OKAPI=true`. Run the single fixed candidate and
exact repeat, then apply the preregistered independent-development gates. Do
not tune after the result.

- [ ] **Step 10: Run and repeat the fixed ARB File-Okapi candidate**

Restart only with `SYNSC_FILE_OKAPI=true`, run the single fixed candidate and
exact repeat, then apply all preregistered ARB gates, including zero any-gold
loss and at least two newly acquired diagnostic cases. Any failed independent
or ARB gate closes the experiment without a second configuration.
