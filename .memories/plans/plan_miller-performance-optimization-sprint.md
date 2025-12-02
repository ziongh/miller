---
git:
  branch: main
  commit: a663127
  dirty: false
  files_changed: []
id: plan_miller-performance-optimization-sprint
status: pending
timestamp: 1764098532
title: Miller Performance Optimization Sprint
type: plan
---

## Goal
Optimize Miller's performance across file discovery, database operations, and search queries before public launch.

## ✅ COMPLETED - All High Priority Items

### 1. Single-Pass File Discovery ✅
**Files:** `python/miller/workspace/discovery.py`, `scanner.py`
- [x] Created `scan_workspace()` function that does single walk
- [x] Returns `WorkspaceScanResult` dataclass with: indexable_files, max_mtime, all_paths_set
- [x] Updated `check_if_indexing_needed()` to use single scan result
- [x] Updated `_walk_directory()` to use scan_workspace internally
- [x] All tests pass (21 workspace tests)

### 2. Batch Inserts in Atomic Update ✅
**Files:** `python/miller/storage/mutations.py`
- [x] Refactored `incremental_update_atomic()` to use `executemany()` for all inserts
- [x] Batch file inserts, symbol inserts, identifier inserts, relationship inserts
- [x] Kept atomic transaction semantics (BEGIN IMMEDIATE...COMMIT)
- [x] All tests pass (42 storage + workspace tests)

### 3. Batch Search Hydration ✅
**Files:** `python/miller/tools/search.py`, `python/miller/storage/queries.py`
- [x] Added `get_symbols_by_ids(ids: list[str])` to queries.py
- [x] Added wrapper to StorageManager
- [x] Refactored `_hydrate_search_results()` to use batch lookup
- [x] Reduces 20 queries to 1 for typical search results
- [x] All tests pass (31 fast_search_toon tests)

### 4. Batch Search Expansion ✅
**Files:** `python/miller/tools/search.py`, `python/miller/storage/queries.py`
- [x] Added `get_reachability_for_targets_batch()` with min_distance filtering
- [x] Added `get_reachability_from_sources_batch()` with min_distance filtering
- [x] Added wrappers to StorageManager
- [x] Refactored `_expand_search_results()` to use 3 batch queries total
- [x] Reduces ~240 queries to ~3 queries when expand=True
- [x] All tests pass (72 search tests)

### 5. Composite Reachability Indexes ✅
**Files:** `python/miller/storage/schema.py`
- [x] Added `idx_reach_target_dist ON reachability(target_id, min_distance)`
- [x] Added `idx_reach_source_dist ON reachability(source_id, min_distance)`
- [x] Optimizes batch queries with distance filtering

### 6. Batch File Cleanup ✅
**Files:** `python/miller/storage/mutations.py`, `scanner.py`
- [x] Added `delete_files_batch(file_paths: list[str])` to mutations.py
- [x] Added wrapper to StorageManager
- [x] Updated scanner.py cleanup phase to use batch delete
- [x] Single transaction instead of N commits

## Success Metrics
- [x] All 747 tests pass
- [x] `check_if_indexing_needed()` now does 1 filesystem walk instead of 3
- [x] Batch inserts use `executemany()` (10-100x faster for large files)
- [x] Search hydration: 20 queries → 1 query
- [x] Search expansion: ~240 queries → ~3 queries
- [x] File cleanup: N commits → 1 commit
