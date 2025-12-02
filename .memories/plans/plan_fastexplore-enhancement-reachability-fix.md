---
completed_at: 1764559794
git:
  branch: main
  commit: 8beb2ed
  dirty: true
  files_changed:
  - .memories/plans/plan_miller-performance-optimization-sprint.md
  - python/miller/closure.py
  - python/miller/instructions.md
  - python/miller/lifecycle.py
  - python/miller/server.py
  - python/miller/tools/gpu_memory.py
  - python/miller/tools/navigation.py
  - python/miller/tools_wrappers.py
  - python/tests/test_reachability.py
  - .memories/2025-12-01/
  - .memories/plans/plan_enhanced-toolset-fastgoto-and-reachability.md
  - .memories/plans/plan_fastlookup-review-fixes.md
  - .memories/plans/plan_fastlookup-smart-symbol-resolution-tool.md
  - python/miller/tools/nav_impl/
  - python/tests/test_fast_lookup.py
id: plan_fastexplore-enhancement-reachability-fix
status: completed
timestamp: 1764558304
title: fast_explore Enhancement + Reachability Fix
type: plan
---

# fast_explore Enhancement + Reachability Fix

## Context

From our analysis session, we identified:
1. **fast_refs and fast_explore should be kept** - they serve distinct purposes
2. **Reachability table was underpopulated** (396 entries vs 509 relationships)
3. **"Cold start into legacy codebase"** is a key use case we want to nail
4. **fast_explore is the natural home for discovery modes**

## Goals

1. ~~Fix reachability population so transitive queries work~~ ✅
2. ~~Add `dead_code` mode to fast_explore~~ ✅
3. ~~Add `hot_spots` mode for finding high-impact symbols~~ ✅
4. ~~Consider `entry_points` mode~~ 🎯 Deferred (overlaps with hot_spots)
5. Consider `overview` mode for codebase orientation (stretch)

---

## Phase 1: Fix Reachability ✅ COMPLETE

### Problem (Fixed)
- Reachability had 396 entries, should have more given 509 relationships
- Closure only computed on fresh index (`needs_indexing=True`)
- Now recomputes after incremental changes

### Tasks
- [x] Add test: reachability should be populated after indexing
- [x] Add test: reachability count should be >= relationships count
- [x] Add `is_reachability_stale()` to detect missing/orphaned entries
- [x] Add `refresh_reachability()` to recompute closure
- [x] Integrate into lifecycle for automatic refresh
- [x] Verify with real data after fix

### Files Changed
- `python/miller/lifecycle.py`
- `python/miller/closure.py`
- `python/tests/test_reachability.py`

---

## Phase 2: dead_code Mode ✅ COMPLETE

### Implementation
Finds unreferenced symbols (functions/classes) that are:
- Not in test files
- Not private (no `_` prefix)
- Not test-prefixed
- Not referenced in relationships table
- Not referenced textually in identifiers from other files

### Tasks
- [x] Add test for dead_code mode returning expected structure
- [x] Add test for dead_code mode filtering test files
- [x] Add test for dead_code mode filtering private symbols
- [x] Implement dead_code mode in explore.py
- [x] Add text output formatter

### Files Changed
- `python/miller/tools/explore.py`
- `python/tests/test_explore_dead_code.py`

---

## Phase 3: hot_spots Mode ✅ COMPLETE

### Implementation
Finds most-referenced symbols ranked by cross-file reference count:
- Excludes test files
- Includes `file_count` for coupling analysis
- 7 tests passing

### Tasks
- [x] Add test for hot_spots mode returning ranked symbols
- [x] Add test for filtering test files
- [x] Implement hot_spots mode
- [x] Add text output formatter
- [x] All 7 tests pass

### Files Changed
- `python/miller/tools/explore.py`
- `python/tests/test_explore_hot_spots.py`

---

## Phase 4: entry_points Mode 🎯 DEFERRED

**Decision:** Deferred due to significant overlap with hot_spots mode. 
High-impact symbols found by hot_spots often ARE the entry points.
If needed later, would be a separate tool (find_entry_points) not a mode.

---

## Phase 5: overview Mode (Stretch Goal - Not Started)

This would provide codebase orientation:
- File/directory statistics
- Language breakdown
- Top symbols by category
- Maybe: semantic clustering to identify "topics"

### Open Questions
- Is this one tool or multiple?
- How much should be automated vs. queried?
- Would vector clustering add value here?

---

## Documentation ✅ COMPLETE

- [x] Update instructions.md with new modes (dead_code, hot_spots)
- [x] Update explore-codebase skill with new modes
- [x] Add "Codebase Health Check" pattern to skill

---

## Remaining Work

- [ ] Manual verification on real codebase (optional)
- [ ] Consider overview mode if time permits (stretch)

---

## Success Criteria

1. ✅ Reachability populates correctly (verify via stats)
2. ✅ `fast_explore(mode="dead_code")` returns unused symbols
3. ✅ `fast_explore(mode="hot_spots")` returns high-impact symbols  
4. ✅ All existing tests pass
5. ✅ Instructions updated with new modes
6. ⬜ Cold-start use case verification (manual)
