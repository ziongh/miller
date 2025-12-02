---
completed_at: 1763567981
git:
  branch: main
  commit: a437e91
  dirty: true
  files_changed:
  - .memories/plans/plan_implement-checkpointrecallplan-tools-in-miller-julie-compatible.json
  - .memories/2025-11-18/124215_de9a.json
  - .memories/2025-11-18/124348_36fc.json
  - .memories/2025-11-18/125434_fede.json
  - .memories/2025-11-18/132517_615f.json
  - .memories/2025-11-18/140635_54de.json
  - .memories/2025-11-18/141302_e014.json
  - docs/SEARCH_FOUNDATION_ANALYSIS.md
  - docs/SEARCH_TOOL_DESIGN.md
  - docs/TANTIVY_LANCEDB_RESEARCH.md
  - python/tests/test_pattern_search_poc.py
id: plan_implement-pattern-search-with-auto-detection
status: completed
timestamp: 1763500204
title: Implement Pattern Search with Auto-Detection
type: plan
---

## Goal
Add code idiom search to Miller with smart auto-detection, enabling searches for patterns like `ILogger<`, `: BaseClass`, `[Fact]`.

## Status: Ready to Implement (POC Validated ✅)

## Context
- **POC validated**: Whitespace tokenizer + phrase search works perfectly
- **Tool design decided**: Option C (auto-detection with override)
- **Fallback pattern**: Consider text → semantic fallback (Julie pattern)

---

## Implementation Plan

### Phase 1: Add Pattern Field & Index (4-6 hours)

**1.1 Update LanceDB Schema** (1 hour)
```python
# In embeddings.py:130-142
SCHEMA = pa.schema([
    # ... existing fields ...
    pa.field("code_pattern", pa.string(), nullable=False),  # NEW
    # ... vector field ...
])
```

**1.2 Populate Pattern Field** (2 hours)
```python
# In embeddings.py:205-247 (add_symbols)
def add_symbols(self, symbols: List[Any], vectors: np.ndarray) -> int:
    for sym, vec in zip(symbols, vectors):
        # Build pattern-preserving content
        pattern_parts = []
        if sym.signature:
            pattern_parts.append(sym.signature)
        pattern_parts.append(sym.name)
        if sym.kind:
            pattern_parts.append(sym.kind)
        
        code_pattern = " ".join(pattern_parts)
        
        data.append({
            # ... existing fields ...
            "code_pattern": code_pattern,  # NEW
            # ...
        })
```

**1.3 Create Whitespace FTS Index** (1 hour)
```python
# In embeddings.py:179-203 (_create_fts_index)
def _create_fts_index(self):
    # Create whitespace-tokenized index on pattern field
    self._table.create_fts_index(
        ["code_pattern"],  # Pattern field only
        use_tantivy=True,
        base_tokenizer="whitespace",  # Preserves : < > [ ] ( )
        with_position=True,
        replace=True
    )
    self._fts_index_created = True
```

**1.4 Add Pattern Search Method** (1-2 hours)
```python
# In embeddings.py:VectorStore - add new method
def _search_pattern(self, query: str, limit: int) -> List[Dict]:
    """Search code patterns using whitespace-tokenized field."""
    from lancedb.query import MatchQuery
    
    # Auto-wrap in quotes for phrase search (handles special chars)
    if not query.startswith('"'):
        query = f'"{query}"'
    
    results = (
        self._table
        .search(MatchQuery(query, "code_pattern"), query_type="fts")
        .limit(limit)
        .to_list()
    )
    
    # Normalize scores
    if results:
        max_score = max(r.get("_score", 0.0) for r in results)
        for r in results:
            raw_score = r.get("_score", 0.0)
            r["score"] = raw_score / max_score if max_score > 0 else 0.0
    
    return results
```

---

### Phase 2: Auto-Detection Logic (2-3 hours)

**2.1 Query Type Detection** (1 hour)
```python
# In embeddings.py or search_utils.py
def detect_search_method(query: str) -> str:
    """
    Detect optimal search method from query characteristics.
    
    Returns: "pattern" | "hybrid"
    """
    # Code pattern indicators
    pattern_chars = [':', '<', '>', '[', ']', '(', ')', '{', '}']
    
    # Check for code patterns
    if any(ch in query for ch in pattern_chars):
        return "pattern"
    
    # Default to hybrid (best quality for general search)
    return "hybrid"
```

**2.2 Update VectorStore.search()** (1-2 hours)
```python
# In embeddings.py:249-274 (search method)
def search(
    self,
    query: str,
    method: Literal["auto", "text", "pattern", "semantic", "hybrid"] = "auto",
    limit: int = 50
) -> List[Dict]:
    """
    Search symbols by query with auto-detection.
    
    Args:
        query: Search query
        method: Search method (auto/text/pattern/semantic/hybrid)
        limit: Maximum results
        
    Returns:
        List of dicts with symbol metadata + score
    """
    if self._table is None:
        return []
    
    # Auto-detect if needed
    if method == "auto":
        method = detect_search_method(query)
    
    # Route to appropriate search
    if method == "pattern":
        return self._search_pattern(query, limit)
    elif method == "text":
        return self._search_text(query, limit)
    elif method == "semantic":
        return self._search_semantic(query, limit)
    else:  # hybrid
        return self._search_hybrid(query, limit)
```

---

### Phase 3: Fallback Logic (Optional - 1-2 hours)

**Julie's Pattern**: If text search returns 0 results → try semantic

```python
def search(self, query: str, method: str = "auto", limit: int = 50):
    # ... detection logic ...
    
    results = []
    
    # Primary search
    if method == "pattern":
        results = self._search_pattern(query, limit)
    elif method == "text":
        results = self._search_text(query, limit)
    # ... etc
    
    # Fallback: If text/pattern returns nothing, try semantic
    if len(results) == 0 and method in ["text", "pattern"]:
        logger.info(f"Primary search ({method}) returned 0 results, falling back to semantic")
        results = self._search_semantic(query, limit)
        
        # Add metadata indicating fallback
        for r in results:
            r["_fallback"] = True
            r["_fallback_reason"] = f"{method} → semantic (0 results)"
    
    return results
```

**Note**: May not need this if Tantivy FTS is good enough!

---

### Phase 4: Update MCP Tool (1 hour)

**4.1 Update fast_search Tool**
```python
# In server.py:165-200
def fast_search(
    query: str,
    method: Literal["auto", "text", "pattern", "semantic", "hybrid"] = "auto",
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Search codebase using text, semantic, or hybrid methods.
    
    Method selection (default: auto):
    - auto: Detects query type automatically
      * Has special chars (: < > [ ]) → pattern search (code idioms)
      * Natural language → hybrid search (text + semantic)
    - text: Full-text search with stemming (general code search)
    - pattern: Code idioms (: BaseClass, ILogger<, [Fact], etc.)
    - semantic: Vector similarity (conceptual matches)
    - hybrid: Combines text + semantic with RRF fusion
    
    Examples:
        # Auto-detection (recommended)
        fast_search("authentication logic")        # Auto: hybrid
        fast_search(": BaseClass")                 # Auto: pattern
        fast_search("ILogger<UserService>")        # Auto: pattern
        fast_search("[Fact]")                      # Auto: pattern
        
        # Manual override
        fast_search("map<int, string>", method="text")  # Force text
        fast_search("user auth", method="semantic")     # Force semantic
    
    Args:
        query: Search query (code, patterns, or natural language)
        method: Search method (auto-detects by default)
        limit: Maximum results to return
        
    Returns:
        List of matching symbols with scores and metadata
    """
    # Delegate to vector store (handles auto-detection)
    return vector_store.search(query, method, limit)
```

---

### Phase 5: Testing (3 hours)

**5.1 Unit Tests** (1 hour)
- Test pattern field creation
- Test whitespace tokenizer preserves special chars
- Test phrase wrapping logic
- Test auto-detection heuristic

**5.2 Integration Tests** (1 hour)
- Test end-to-end: index C# code → search for `: BaseClass`
- Test end-to-end: index C# code → search for `ILogger<`
- Test end-to-end: index C# code → search for `[Fact]`
- Test fallback logic (if implemented)

**5.3 Real-World Testing** (1 hour)
- Index Miller itself
- Index Julie codebase
- Test patterns:
  - `: BaseService` (inheritance)
  - `ILogger<` (generics)
  - `?.` (null-conditional)
  - `=>` (lambda)
- Measure accuracy (>95% target)

---

### Phase 6: Documentation (1-2 hours)

**6.1 Update Tool Descriptions**
- Add pattern search examples to `fast_search` docstring
- Document auto-detection behavior
- Show when to override with `method=`

**6.2 Update README**
- Add "Code Idiom Search" section
- Show examples of pattern queries
- Explain auto-detection

**6.3 Update PLAN.md**
- Mark pattern search as implemented
- Document architecture decisions

---

## Success Criteria

Before marking complete:

- ✅ Can search for `: BaseClass` and find all inheritance
- ✅ Can search for `ILogger<` and find all generic usages
- ✅ Can search for `[Fact]` and find all test attributes
- ✅ Auto-detection works >95% of time
- ✅ Manual override available for edge cases
- ✅ Performance <100ms (no regression)
- ✅ Tests cover 15+ code idiom patterns
- ✅ Documentation with clear examples

---

## Timeline

- **Phase 1**: 4-6 hours (pattern field + index)
- **Phase 2**: 2-3 hours (auto-detection)
- **Phase 3**: 1-2 hours (fallback - optional)
- **Phase 4**: 1 hour (MCP tool)
- **Phase 5**: 3 hours (testing)
- **Phase 6**: 1-2 hours (docs)

**Total**: 12-17 hours (with fallback), 11-15 hours (without)

---

## Open Questions

1. **Fallback logic**: Implement text→semantic fallback or wait to see if Tantivy FTS is good enough?
   - **Decision**: Start without, add if needed after testing

2. **Pattern detection heuristic**: Just check for special chars or more sophisticated?
   - **Decision**: Start simple (special char check), refine if needed

3. **Phrase wrapping**: Always wrap pattern queries or only if not already wrapped?
   - **Decision**: Check if already wrapped, wrap if needed (defensive)

---

## References

- **POC Test**: `python/tests/test_pattern_search_poc.py` (all tests passing ✅)
- **Research Doc**: `docs/TANTIVY_LANCEDB_RESEARCH.md`
- **Tool Design**: `docs/SEARCH_TOOL_DESIGN.md`
- **Analysis**: `docs/SEARCH_FOUNDATION_ANALYSIS.md`
- **COA Reference**: `~/source/coa-codesearch-mcp/` (proven patterns)

---

## Implementation Notes

- Pattern field uses whitespace tokenizer (preserves all special chars)
- Phrase search (quotes) required to avoid Tantivy syntax errors
- Auto-detection checks for: `: < > [ ] ( ) { }`
- Fallback logic is optional (may not need with good FTS)
- One tool (`fast_search`), minimal context overhead

---

**Ready to implement!**

