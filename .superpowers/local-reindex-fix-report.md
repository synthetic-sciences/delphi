# Local force reindex fix report

**Branch:** `feature/file-okapi`  
**Date:** 2026-08-24  
**Database:** `postgresql://$USER@127.0.0.1:5432/delphi_file_okapi_test_20260824`

## Problem

`POST /v1/repositories/index/local` with `force_reindex=true` on a 147-file / 1007-chunk source took **773s**. Logs showed **732s** between file listing and `_index_files`, spent at the old path:

```python
session.delete(existing)
session.flush()
```

ORM cascade deleted the entire repository subtree before creating a **new** `repo_id`, breaking durable source references (manifest `3b835c1d…` → new `20e1c9b0…`). Actual indexing took only **41s**.

Repository reindex already had the correct pattern: row-lock → `_purge_repository_index` → `_index_files(existing_repo_id=…)`.

## Fix

In `index_local_folder`, when content changed or `force_reindex`:

1. Capture `reindex_repo_id` and baseline `commit_sha` from the existing row.
2. `_lock_repository_for_reindex(session, repo_id, baseline_sha)` — stale-write protection.
3. `_purge_repository_index(session, repo_id)` — targeted SQL deletes, keep repository + `user_repositories`.
4. `_index_files(..., existing_repo_id=reindex_repo_id)` — reuse the row.

New-repo and unchanged-short-circuit paths are unchanged.

## TDD evidence

### RED (before fix)

```text
pytest tests/test_local_force_reindex.py \
  tests/test_atomic_reindex_postgres.py::test_local_force_reindex_preserves_repo_id_and_user_mapping \
  tests/test_atomic_reindex_postgres.py::test_local_failed_force_reindex_restores_last_good_index

FAILED test_local_force_reindex_purges_and_passes_existing_repo_id
  assert calls['purge_repo_ids'] == [existing.repo_id]  →  []  (purge never called)
  assert calls['deleted_objects'] == []                 →  [Repository(...)]  (ORM delete)

FAILED test_local_changed_content_reindex_reuses_existing_repo_id
  same: purge skipped, Repository deleted

FAILED test_local_new_repo_skips_purge_and_existing_repo_id
  KeyError: 'existing_repo_id'  (_index_files mock kwargs missing key on new path — OK after fix)

FAILED test_local_force_reindex_preserves_repo_id_and_user_mapping
  assert result['repo_id'] == seeded['repo_id']  →  new UUID minted

FAILED test_local_failed_force_reindex_restores_last_good_index
  error "'existing_repo_id'"  (atomic path not wired; rollback contract untestable)

5 failed, 0 passed
```

### GREEN (after fix)

```text
pytest tests/test_local_force_reindex.py \
  tests/test_atomic_reindex_postgres.py \
  tests/test_file_okapi_indexing.py \
  tests/test_local_folder.py \
  tests/test_local_folder_connector.py

34 passed in 0.60s
```

### Contract coverage

| Contract | Test |
|---|---|
| (a) Preserves `repo_id` + `user_repositories` | `test_local_force_reindex_purges_and_passes_existing_repo_id`, `test_local_force_reindex_preserves_repo_id_and_user_mapping` |
| (b) Purges via `_purge_repository_index`, passes `existing_repo_id`, no `session.delete(Repository)` | `test_local_force_reindex_purges_and_passes_existing_repo_id`, `test_local_changed_content_reindex_reuses_existing_repo_id`, `test_local_new_repo_skips_purge_and_existing_repo_id` |
| (c) Rollback restores last-good index on replacement failure | `test_local_failed_force_reindex_restores_last_good_index` (mirrors existing `test_failed_full_reindex_restores_last_good_index`) |

## Lint / types

```text
ruff check synsc/services/indexing_service.py tests/test_local_force_reindex.py tests/test_atomic_reindex_postgres.py
→ All checks passed!

mypy synsc/services/indexing_service.py
→ Success: no issues found in 1 source file
```

## Files changed

- `backend/synsc/services/indexing_service.py` — atomic local reindex path
- `backend/tests/test_local_force_reindex.py` — new unit contracts
- `backend/tests/test_atomic_reindex_postgres.py` — new Postgres regressions

## Expected production impact

- **Stable `repo_id`** across local force/changed reindexes — manifests and Atlas source bindings survive.
- **Much faster purge** — targeted DELETEs replace ORM cascade `session.delete(existing); flush()` (732s → seconds for large indexes).
- **Atomic rollback** — failed replacement leaves prior index intact (same semantics as GitHub full reindex).

## Residual concerns

1. **`_purge_repository_index` does not explicitly DELETE lexical tables** — relies on `ON DELETE CASCADE` from `repository_files`. Consistent with repository reindex; worth a follow-up explicit purge if cascade ever diverges.
2. **Local reindex still lists all files before opening the DB session** — large folders pay full disk walk up front; acceptable but separate from this fix.
3. **No integration test for concurrent local force reindex** — stale-candidate rejection is covered for `_lock_repository_for_reindex` on GitHub path; local path now calls the same helper but lacks a dedicated concurrent local test.
