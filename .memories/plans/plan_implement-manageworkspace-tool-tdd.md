---
completed_at: 1763575905
git:
  branch: main
  commit: 724ff83
  dirty: false
  files_changed: []
id: plan_implement-manageworkspace-tool-tdd
status: completed
timestamp: 1763569356
title: Implement manage_workspace Tool (TDD)
type: plan
---

## Goal
Implement Miller's `manage_workspace` MCP tool with reference workspace support, following strict TDD methodology.

## Architecture Overview

**Workspace Isolation Model** (matches Julie):
```
.miller/indexes/
├── miller_primary_abc123/      ← PRIMARY workspace
│   ├── symbols.db              ← SQLite database
│   └── vectors.lance           ← LanceDB vectors
│
└── my-framework_def456/        ← REFERENCE workspace
    ├── symbols.db              ← Separate SQLite
    └── vectors.lance           ← Separate LanceDB
```

**Key Principles:**
- Physical isolation: Each workspace = separate DB + vectors
- Primary workspace: Where Miller is running (has `.miller/` directory)
- Reference workspaces: Other codebases to search (indexed in primary's `.miller/indexes/`)
- Project-level storage: `.miller/` at project root (NOT `~/.miller/`)

---

## ✅ Phase 1: Core Foundation (COMPLETE - 4 hours)

**Status**: ✅ **COMPLETE** - All 23 tests passing, committed and pushed

**What We Built:**
1. ✅ WorkspaceRegistry (10 tests, 88% coverage)
   - Workspace metadata tracking
   - Persistent JSON storage
   - Add/get/remove/list operations
   - Stable workspace ID generation

2. ✅ Workspace Paths (5 tests, 100% coverage)
   - Consistent path generation for DB/vectors
   - Directory creation utilities
   - Isolated workspace storage

3. ✅ manage_workspace Tool (8 tests, 88% coverage)
   - List operation (show all workspaces)
   - Stats operation (detailed workspace info)
   - Formatted output with metadata

4. ✅ MCP Registration
   - Tool registered in server.py
   - Available via MCP protocol

**TDD Discipline:**
- ✅ All 23 tests written FIRST
- ✅ All tests failed initially
- ✅ Implementation made them pass
- ✅ No code without tests

**Committed**: Commit 9af0947 - "feat: Implement manage_workspace Phase 1 (list/stats) with TDD"

---

## Phase 2: Reference Workspaces (6-8 hours) - NEXT

### Goals
- Implement add/remove operations
- Support multiple workspace databases
- Add workspace parameter to search tools

### 2.1 Add Reference Workspace (TDD - 3 hours)

**Tests First:**
```python
def test_add_reference_workspace():
    """Can add reference workspace and index it."""
    result = await manage_workspace(
        operation="add",
        path="/path/to/other-project",
        name="Other Project"
    )
    
    assert "Successfully added" in result
    assert "Other Project" in result
    
    # Verify it's in registry
    registry = WorkspaceRegistry()
    workspaces = registry.list_workspaces()
    assert len(workspaces) == 2  # primary + reference
    
def test_add_indexes_reference_workspace():
    """Adding reference workspace triggers indexing."""
    result = await manage_workspace(
        operation="add",
        path="/path/to/real-project",
        name="Real Project"
    )
    
    # Should have indexed files
    registry = WorkspaceRegistry()
    workspace = [w for w in registry.list_workspaces() if w["name"] == "Real Project"][0]
    assert workspace["symbol_count"] > 0
    assert workspace["file_count"] > 0
```

**Implementation:** Extend manage_workspace with add operation

### 2.2 Remove Workspace (TDD - 1 hour)

**Tests First:**
```python
def test_remove_workspace_deletes_files():
    """Remove operation deletes workspace data."""
    # Add workspace
    workspace_id = add_test_workspace()
    
    # Remove it
    result = await manage_workspace(
        operation="remove",
        workspace_id=workspace_id
    )
    
    assert "Successfully removed" in result
    
    # Verify files deleted
    db_path = get_workspace_db_path(workspace_id)
    assert not db_path.exists()
```

### 2.3 Multi-Workspace Search (TDD - 2 hours)

**Tests First:**
```python
def test_search_filters_by_workspace():
    """fast_search can filter by workspace_id."""
    # Index two workspaces
    ws1_id = index_workspace("/project1")
    ws2_id = index_workspace("/project2")
    
    # Search specific workspace
    results = await fast_search(
        "function",
        workspace_id=ws1_id
    )
    
    # All results should be from ws1
    assert all(r["workspace_id"] == ws1_id for r in results)

def test_search_all_workspaces_by_default():
    """fast_search searches all workspaces if no filter."""
    results = await fast_search("function")
    
    # Should have results from multiple workspaces
    workspace_ids = {r["workspace_id"] for r in results}
    assert len(workspace_ids) > 1
```

**Implementation:** 
- Add `workspace_id` parameter to fast_search
- Query correct database based on workspace_id
- Merge results from multiple workspaces if no filter

---

## Phase 3: Maintenance (4-6 hours)

### 3.1 Refresh Operation (TDD - 2 hours)

**Tests First:**
```python
def test_refresh_reindexes_workspace():
    """Refresh re-indexes workspace with new files."""
    workspace_id = create_test_workspace()
    
    # Add new file to workspace
    add_file_to_workspace(workspace_id, "new.py")
    
    # Refresh
    result = await manage_workspace(
        operation="refresh",
        workspace_id=workspace_id
    )
    
    # Should show updated counts
    stats = get_workspace_stats(workspace_id)
    assert stats["file_count"] increased
```

### 3.2 Clean Operation (TDD - 2 hours)

**Tests First:**
```python
def test_clean_removes_orphaned_workspaces():
    """Clean removes workspaces with deleted paths."""
    # Create workspace for non-existent path
    workspace_id = registry.add_workspace(
        path="/does/not/exist",
        name="Orphaned"
    )
    
    result = await manage_workspace(operation="clean")
    
    assert "Removed 1 orphaned workspace" in result
    assert registry.get_workspace(workspace_id) is None
```

### 3.3 Health Check (TDD - 1 hour)

**Tests First:**
```python
def test_health_shows_system_status():
    """Health check shows registry, DB, vector status."""
    result = await manage_workspace(
        operation="health",
        detailed=True
    )
    
    assert "Registry:" in result
    assert "Databases:" in result
    assert "Vector indexes:" in result
```

---

## Success Criteria

**Phase 1 Complete When:**
- ✅ WorkspaceRegistry tests passing (10/10 tests)
- ✅ Workspace paths tests passing (5/5 tests)
- ✅ manage_workspace list/stats working (8/8 tests)
- ✅ Can list workspaces via MCP tool
- ✅ Committed and pushed (9af0947)

**Phase 2 Complete When:**
- ⏳ Can add reference workspace
- ⏳ Reference workspace auto-indexes
- ⏳ Can remove workspace (deletes files)
- ⏳ fast_search has workspace_id filter
- ⏳ Can search across multiple workspaces

**Phase 3 Complete When:**
- ⏳ Refresh re-indexes workspace
- ⏳ Clean removes orphaned data
- ⏳ Health check shows system status
- ⏳ All operations tested and documented

---

## TDD Discipline Checklist

For EVERY feature:
1. ✅ Write failing test FIRST
2. ✅ Run test, verify it fails
3. ✅ Write minimal code to pass
4. ✅ Run test, verify it passes
5. ✅ Refactor if needed
6. ✅ Commit with test + implementation together

**No code without tests. No exceptions.**

---

## Timeline Estimate

- **Phase 1**: ✅ COMPLETE (4 hours actual)
- **Phase 2**: 6-8 hours (reference workspaces + multi-DB)
- **Phase 3**: 4-6 hours (maintenance ops)

**Total**: 14-20 hours over 2-3 sessions

---

## Progress Summary

**✅ Phase 1 COMPLETE**:
- 23 tests passing (10 registry + 5 paths + 8 tool)
- 88-100% coverage on new code
- Full TDD methodology followed
- Commit: 9af0947

**⏳ Phase 2 NEXT**: Reference workspaces
**⏳ Phase 3 PENDING**: Maintenance operations

---

## References

- Julie's workspace architecture: `~/source/julie/docs/WORKSPACE_ARCHITECTURE.md`
- Julie's ManageWorkspaceTool: `~/source/julie/src/tools/workspace/commands/mod.rs`
- Julie 2.0 Plan: `~/source/julie/docs/JULIE_2_PLAN.md`

