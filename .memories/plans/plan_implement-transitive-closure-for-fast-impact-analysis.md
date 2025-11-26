---
completed_at: 1763929970
git:
  branch: main
  commit: e944ca7
  dirty: true
  files_changed:
  - .claude/settings.local.json
id: plan_implement-transitive-closure-for-fast-impact-analysis
status: completed
timestamp: 1763929515
title: Implement Transitive Closure for Fast Impact Analysis
type: plan
---

## Goal

Pre-compute call graph reachability so "what breaks if I change X?" becomes O(1) lookup instead of BFS traversal.

## Status: ✅ Phase 1-3 COMPLETE | Phase 4 Optional

## Why This Matters

Current `trace_call_path` does BFS traversal:
- Each query visits N nodes, each with SQL lookup
- For deep call chains: slow (100ms+)
- For impact analysis: need to traverse entire upstream graph

With transitive closure:
- "Can A reach B?" → O(1) lookup
- "What depends on X?" → Single indexed query
- Impact analysis: instant

---

## Implementation Phases

### ✅ Phase 1: Schema & Basic Computation (TDD) - COMPLETE
- [x] Add `reachability` table to schema (storage.py)
- [x] Implement BFS-based closure computation (closure.py)
- [x] Test with small fixture graph (17 tests)
- [x] Verify correctness against manual BFS

### ✅ Phase 2: Integration with Indexing - COMPLETE  
- [x] Compute closure after file indexing completes (server.py)
- [ ] Handle incremental updates (only recompute affected subgraph) - DEFERRED
- [x] Add workspace isolation (uses workspace's StorageManager)

### ✅ Phase 3: Query Interface - COMPLETE
- [x] `get_reachability_for_target(target_id)` → all upstream symbols (what breaks)
- [x] `get_reachability_from_source(source_id)` → all downstream symbols (what I depend on)
- [x] `can_reach(source_id, target_id)` → boolean reachability check
- [x] `get_distance(source_id, target_id)` → shortest path length

### ⏳ Phase 4: Optimize trace_call_path - OPTIONAL
- [ ] Use reachability table instead of BFS for simple queries
- [ ] Fall back to BFS for tree-building (need path structure)
- [ ] Add `fast_impact` MCP tool for instant impact analysis

---

## Files Created/Modified

**New files:**
- `python/miller/closure.py` - BFS transitive closure computation
- `python/tests/test_reachability.py` - 17 TDD tests

**Modified files:**
- `python/miller/storage.py` - Added reachability table + 6 methods
- `python/miller/server.py` - Integrated closure computation after indexing

---

## Test Results

```
17/17 reachability tests passing:
- 3 schema tests (table, columns, indexes)
- 8 storage operation tests (CRUD, can_reach, get_distance)
- 6 closure computation tests (chains, cycles, diamonds, depth limits)
```

---

## Success Criteria Status

- [x] Impact query < 10ms (O(1) lookup via can_reach/get_distance)
- [ ] Closure computation < 5s for Miller-sized codebase (TO BE MEASURED)
- [ ] Incremental update < 500ms per file change (DEFERRED)
- [x] Space overhead < 20MB for 10K symbol codebase (estimated)
- [x] All existing tests pass (36 tests: 17 reachability + 19 storage)

---

## Design Decisions

### Approach: Bounded Closure with BFS

1. **Bounded depth** (max 10 levels) - practical limit for code
2. **Call relationships only** - not imports, extends, etc.
3. **Full recompute on indexing** - simpler than incremental (for now)

### Schema

```sql
CREATE TABLE reachability (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    min_distance INTEGER NOT NULL,
    PRIMARY KEY (source_id, target_id)
);

CREATE INDEX idx_reach_source ON reachability(source_id);
CREATE INDEX idx_reach_target ON reachability(target_id);
```

---

## Next Steps (Optional)

1. **Measure real performance** - Run on Miller codebase, measure closure time
2. **Add fast_impact tool** - MCP tool exposing get_reachability_for_target
3. **Incremental updates** - Recompute only affected symbols on file changes

