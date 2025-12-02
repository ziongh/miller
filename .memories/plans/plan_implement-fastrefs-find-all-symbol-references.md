---
completed_at: 1763592854
git:
  branch: main
  commit: af6b268
  dirty: true
  files_changed:
  - .memories/plans/plan_complete-getsymbols-better-than-julie.json
  - python/miller/tools/symbols.py
  - python/tests/test_get_symbols.py
  - .memories/2025-11-19/161543_a28d.json
  - .memories/2025-11-19/162459_53f7.json
  - .memories/2025-11-19/162914_f397.json
  - GET_SYMBOLS_GUIDE.md
  - benchmark_get_symbols.py
id: plan_implement-fastrefs-find-all-symbol-references
status: completed
timestamp: 1763591732
title: Implement fast_refs - Find All Symbol References
type: plan
---

## Goal: Build Essential Refactoring Safety Tool

`fast_refs` answers the critical question: **"Where is this symbol used?"**

This is essential for:
- Safe refactoring (know impact before changing code)
- Impact analysis (understand dependencies)
- Code exploration (find usage examples)
- Foundation for trace_call_path (refs = breadth, trace = depth)

---

## Success Criteria

**Core Functionality:**
- ✅ Find all references to a symbol by name
- ✅ Return file paths, line numbers, context snippets
- ✅ Support workspace filtering (primary vs reference)
- ✅ Filter by reference type (calls, imports, extends, implements)
- ✅ Performance: <100ms for typical symbols, <500ms for heavily-used symbols

**Output Quality:**
- ✅ Grouped by file (easier to read)
- ✅ Sorted by usage frequency (most-used files first)
- ✅ Context snippets show actual usage (line of code)
- ✅ Includes reference kind (Call, Import, Extends, etc.)

---

## Phase 1: Basic Implementation (Foundation)

### Task 1.1: Database Query Foundation
**Goal:** Query symbol_relationships table correctly

- [ ] Query relationships table by target symbol name
- [ ] Filter by relationship_kind (Call, Reference, Import, etc.)
- [ ] Join with symbols table to get file paths and locations
- [ ] Return basic data: file_path, line, kind

**Tests:**
- [ ] Test finding references for known symbol
- [ ] Test filtering by relationship kind
- [ ] Test handling symbol with no references
- [ ] Test handling non-existent symbol

---

### Task 1.2: Context Snippet Extraction
**Goal:** Show actual code where symbol is used

- [ ] Read source files for reference lines
- [ ] Extract line of code (with symbol usage)
- [ ] Add surrounding context (±1-2 lines optional)
- [ ] Handle file read errors gracefully

**Tests:**
- [ ] Test context extraction from Python file
- [ ] Test context extraction from TypeScript file
- [ ] Test handling deleted/moved files
- [ ] Test handling binary files

---

### Task 1.3: Workspace Filtering
**Goal:** Support primary vs reference workspace queries

- [ ] Add workspace parameter ("primary" or workspace_id)
- [ ] Query appropriate workspace database
- [ ] Handle cross-workspace references
- [ ] Filter results by workspace if specified

**Tests:**
- [ ] Test primary workspace filtering
- [ ] Test reference workspace filtering
- [ ] Test cross-workspace references
- [ ] Test invalid workspace handling

---

## Phase 2: Output Quality & UX

### Task 2.1: Grouping & Sorting
**Goal:** Make output easy to scan and understand

```python
# Example output structure:
{
  "symbol": "calculateAge",
  "total_references": 47,
  "files": [
    {
      "path": "src/user_service.py",
      "references_count": 23,
      "references": [
        {"line": 45, "kind": "Call", "context": "age = calculateAge(user.birthdate)"},
        {"line": 67, "kind": "Call", "context": "return calculateAge(dob)"}
      ]
    },
    {
      "path": "src/profile.py",
      "references_count": 12,
      ...
    }
  ]
}
```

**Implementation:**
- [ ] Group references by file
- [ ] Sort files by reference count (most-used first)
- [ ] Sort references within file by line number
- [ ] Add total_references count

**Tests:**
- [ ] Test grouping by file
- [ ] Test sorting by reference count
- [ ] Test line number ordering
- [ ] Test total count accuracy

---

### Task 2.2: Reference Kind Filtering
**Goal:** Filter by type of reference (calls only, imports only, etc.)

- [ ] Add kind parameter (optional filter)
- [ ] Support multiple kinds (["Call", "Import"])
- [ ] Map tree-sitter relationship types
- [ ] Document available kinds per language

**Tests:**
- [ ] Test filtering by single kind (Call)
- [ ] Test filtering by multiple kinds (Call, Reference)
- [ ] Test filtering by Import
- [ ] Test filtering by Extends/Implements

---

### Task 2.3: Symbol Disambiguation
**Goal:** Handle symbols with same name in different scopes

- [ ] Add context_file parameter (disambiguate by file)
- [ ] Add qualified_name support (Class.method)
- [ ] Handle overloaded functions/methods
- [ ] Provide disambiguation suggestions if ambiguous

**Tests:**
- [ ] Test disambiguating User class vs user variable
- [ ] Test qualified name resolution (UserService.create)
- [ ] Test handling multiple symbols with same name
- [ ] Test providing disambiguation suggestions

---

## Phase 3: Performance & Polish

### Task 3.1: Performance Optimization
**Target:** <100ms typical, <500ms heavily-used symbols

- [ ] Add database indexes on symbol_relationships(target_id)
- [ ] Batch file reads (don't read same file multiple times)
- [ ] Cache file contents during query (avoid re-reading)
- [ ] Limit results with pagination support
- [ ] Add performance logging

**Tests:**
- [ ] Benchmark query with 100+ references
- [ ] Benchmark query with 1000+ references
- [ ] Test pagination correctness
- [ ] Test cache effectiveness

---

### Task 3.2: Output Formats
**Goal:** Support different output formats for different use cases

- [ ] JSON format (default, structured data)
- [ ] Markdown format (human-readable)
- [ ] Summary format (just counts, no context)
- [ ] Tree format (nested by file)

**Tests:**
- [ ] Test JSON output structure
- [ ] Test markdown rendering
- [ ] Test summary format
- [ ] Test tree format

---

### Task 3.3: Error Handling & Edge Cases
**Goal:** Graceful degradation and helpful errors

- [ ] Handle symbol not found
- [ ] Handle symbol with no references
- [ ] Handle deleted/moved files
- [ ] Handle unparseable context lines
- [ ] Handle database query errors

**Tests:**
- [ ] Test non-existent symbol handling
- [ ] Test zero references handling
- [ ] Test missing file handling
- [ ] Test malformed data handling

---

### Task 3.4: Documentation & Examples
**Goal:** Make tool easy to use for agents and humans

- [ ] Document all parameters and defaults
- [ ] Add usage examples for common scenarios
- [ ] Add troubleshooting guide
- [ ] Update TOOLS_PLAN.md with implementation details

**Deliverables:**
- [ ] FAST_REFS_GUIDE.md (similar to GET_SYMBOLS_GUIDE.md)
- [ ] Usage examples in docstrings
- [ ] MCP tool description
- [ ] Performance benchmarks

---

## Implementation Notes

### Key Design Decisions

1. **Group by file for readability**
   - Easier to understand impact ("This file uses it 23 times")
   - Agents can focus on high-impact files first
   - Better than flat list of all references

2. **Include context snippets**
   - Shows actual usage (how symbol is called)
   - Helps understand different usage patterns
   - Valuable for refactoring decisions

3. **Workspace awareness**
   - Support primary + reference workspaces
   - Show cross-workspace references (library usage)
   - Essential for monorepos

4. **Graceful degradation**
   - If file missing, show reference without context
   - If relationship data incomplete, show what we have
   - Never fail completely, always return something useful

### Database Schema (Existing)

We already have the `symbol_relationships` table from indexing:
```sql
CREATE TABLE symbol_relationships (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL,
  target_id INTEGER NOT NULL,
  relationship_kind TEXT NOT NULL,
  location_start_line INTEGER,
  location_end_line INTEGER,
  FOREIGN KEY (source_id) REFERENCES symbols(id) ON DELETE CASCADE,
  FOREIGN KEY (target_id) REFERENCES symbols(id) ON DELETE CASCADE
);
```

**Key insight:** We just need to query this table efficiently!

### Performance Considerations

1. **Add index:** `CREATE INDEX idx_relationships_target ON symbol_relationships(target_id)`
2. **Batch file reads:** If 50 refs in same file, read file once
3. **Limit results:** Default to top 100 references, support pagination
4. **Cache:** Cache file contents during single query execution

---

## Test Strategy

### Unit Tests (per task)
- Test each function in isolation
- Mock database and file system
- Cover edge cases

### Integration Tests
- Test with real indexed workspace
- Verify relationships table is queried correctly
- Validate output format

### Performance Tests
- Benchmark with symbols having 10, 100, 1000+ refs
- Measure query time, file I/O time
- Validate caching effectiveness

### Comparison Tests
- Compare with Julie's find_references (if exists)
- Validate correctness against manual inspection
- Ensure we're not missing references

---

## Milestones

- **M1: Basic Query** - Can find references and return file/line (1 day)
- **M2: Context & Grouping** - Beautiful output with context snippets (1 day)
- **M3: Performance & Polish** - Fast, robust, documented (1 day)

**Total Estimate:** 2-3 days of focused work

---

## Success Metrics

**Quantitative:**
- Performance: <100ms for typical symbols
- Accuracy: 100% of references found (validate against manual inspection)
- Test coverage: >85% of fast_refs code

**Qualitative:**
- Agent feedback: "fast_refs shows me exactly what will break if I change this"
- Human feedback: "Best way to understand symbol usage I've seen"
- Refactoring confidence: "I can safely refactor knowing the impact"

---

## Next Steps After Completion

1. Checkpoint this milestone
2. Update TOOLS_PLAN.md with implementation status
3. Create FAST_REFS_GUIDE.md with usage examples
4. Move on to trace_call_path (the killer feature!)
5. Consider: fast_refs could be enhanced with usage pattern analysis later
