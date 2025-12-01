---
git:
  branch: main
  commit: 8beb2ed
  dirty: true
  files_changed:
  - python/miller/server.py
  - python/miller/tools/gpu_memory.py
id: plan_enhanced-toolset-fastgoto-and-reachability
status: pending
timestamp: 1764549803
title: Enhanced Toolset - fast_goto and Reachability
type: plan
---

# Enhanced Toolset: fast_goto + Reachability

## Context

From our analysis:
1. **fast_goto exists** but is intentionally NOT exposed (see `navigation.py` comment)
2. **Reachability table exists** with passing tests, but has 0 entries in production
3. **Closure computation exists** in `closure.py` and is called from `lifecycle.py` BUT only on fresh index
4. We have 482 relationships but 0 reachability entries - the closure never ran

## Goals

1. **Expose enhanced fast_goto** as MCP tool with structure options
2. **Fix reachability population** so it actually runs and stays populated
3. **Make reachability available to tools** for transitive impact queries
4. After these work, re-evaluate fast_refs and fast_explore

---

## Phase 1: Fix Reachability Population (TDD)

### Problem
- Closure only computes on fresh index (`needs_indexing=True`)
- Workspace was already indexed, so closure never ran
- Also: closure should recompute when relationships change

### Tasks
- [ ] Add test: closure should run on server startup if reachability is empty
- [ ] Add test: closure should recompute after incremental file changes
- [ ] Fix lifecycle.py to check reachability count, not just needs_indexing
- [ ] Add `refresh_closure()` to manage_workspace or as background task
- [ ] Verify: manual test shows reachability populated after restart

---

## Phase 2: Enhance fast_goto (TDD)

### Current State
- `fast_goto` exists in `navigation.py` with text/json output
- Returns: file_path, start_line, kind, signature
- NOT exposed as MCP tool (intentionally removed)

### Enhancement Goals
Return rich structure optionally:
```python
fast_goto("UserService", include_structure=True)
# → {
#     file_path, start_line, kind, signature,
#     structure: {
#         methods: ["get_user", "create_user"],
#         properties: ["db", "cache"],
#         base_classes: ["BaseService"],
#         interfaces: []
#     }
#   }
```

### Tasks
- [ ] Add tests for fast_goto with include_structure=False (current behavior)
- [ ] Add tests for fast_goto with include_structure=True
- [ ] Add tests for TOON output format
- [ ] Implement include_structure parameter
- [ ] Add TOON encoding support
- [ ] Expose fast_goto in tools_wrappers.py
- [ ] Update MCP instructions for fast_goto

---

## Phase 3: Make Reachability Available to Tools

### Goal
Tools can query "what symbols are transitively affected by changing X?"

### Tasks
- [ ] Add helper function: `get_transitive_dependents(symbol_id, max_depth)` 
- [ ] Add helper function: `get_transitive_dependencies(symbol_id, max_depth)`
- [ ] Add tests for these helpers
- [ ] Document availability for trace_call_path, fast_refs, etc.

---

## Phase 4: Re-evaluate fast_refs and fast_explore

After Phase 1-3 complete:
- [ ] Test fast_refs with reachability for transitive mode
- [ ] Test if trace_call_path covers fast_refs use cases
- [ ] Evaluate fast_explore usefulness with new tools
- [ ] Make keep/remove/enhance decision with real data

---

## Files to Modify

**Phase 1 (Reachability):**
- `python/miller/lifecycle.py` - Fix closure trigger logic
- `python/tests/test_reachability.py` - Add startup/incremental tests

**Phase 2 (fast_goto):**
- `python/miller/tools/navigation.py` - Enhance fast_goto
- `python/miller/tools_wrappers.py` - Expose fast_goto
- `python/tests/test_fast_goto.py` - New test file

**Phase 3 (Helpers):**
- `python/miller/storage/queries.py` or new file - Reachability helpers
- `python/tests/test_reachability.py` - Add helper tests

---

## Success Criteria

1. ✅ Reachability table has entries after server restart
2. ✅ fast_goto exposed with include_structure option
3. ✅ fast_goto has text, json, toon output formats
4. ✅ Tools can query transitive impact via helpers
5. ✅ All existing tests still pass
