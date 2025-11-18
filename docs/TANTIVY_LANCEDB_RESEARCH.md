# Tantivy & LanceDB FTS Research Findings
**Date**: 2025-11-18
**Purpose**: Validate technical feasibility of multi-field indexing for code idiom search

---

## Research Question

**Can we implement COA CodeSearch's multi-field strategy in Miller using LanceDB + Tantivy?**

Specifically:
1. Can we create fields with different tokenizers (standard vs whitespace)?
2. Can we search specific fields independently?
3. Can we achieve pattern-preserving search for code idioms like `ILogger<`, `: BaseClass`?

---

## Key Findings

### ✅ **GOOD NEWS: Tantivy Has What We Need**

**1. Whitespace Tokenizer Exists** ✅
- Tantivy has built-in `WhitespaceTokenizer`
- Splits ONLY on whitespace (spaces, tabs, newlines)
- **Preserves ALL punctuation**: `:`, `<`, `>`, `[`, `]`, `(`, `)`
- Perfect for code pattern preservation!

**2. LanceDB Exposes It** ✅
- Parameter: `base_tokenizer="whitespace"`
- Alternative options: `"simple"` (default), `"raw"`, `"ngram"`
- Example:
  ```python
  table.create_fts_index(
      ["field_name"],
      use_tantivy=True,
      base_tokenizer="whitespace",  # KEY!
      replace=True
  )
  ```

**3. Can Search Specific Fields** ✅
- Use `MatchQuery` to target one field:
  ```python
  from lancedb.query import MatchQuery
  results = table.search(
      MatchQuery("ILogger<", "code_patterns"),
      query_type="fts"
  ).to_list()
  ```
- Use `MultiMatchQuery` for multiple fields with boosts:
  ```python
  from lancedb.query import MultiMatchQuery
  results = table.search(
      MultiMatchQuery("query", ["field1", "field2"], boosts=[1.0, 2.0]),
      query_type="fts"
  ).to_list()
  ```

### ⚠️ **CONSTRAINT: Single Tokenizer Per Index**

**The Limitation**:
- `create_fts_index()` accepts ONE tokenizer configuration
- That tokenizer applies to ALL fields in the list
- **Cannot** do: `create_fts_index(["name", "signature"], tokenizers=["en_stem", "whitespace"])`
- **Can only** do: `create_fts_index(["name", "signature"], base_tokenizer="whitespace")`

**Example of what DOESN'T work**:
```python
# ❌ IMPOSSIBLE - Can't mix tokenizers in one index
table.create_fts_index(
    ["name", "signature", "code_patterns"],
    tokenizers={
        "name": "en_stem",
        "signature": "en_stem",
        "code_patterns": "whitespace"  # Want different tokenizer here!
    }
)
```

**What DOES work**:
```python
# ✅ POSSIBLE - All fields use same tokenizer
table.create_fts_index(
    ["name", "signature", "code_patterns"],
    base_tokenizer="whitespace"  # Applies to ALL fields
)
```

---

## Workaround Strategies

### **Strategy 1: Duplicate Fields with Different Content** ⭐ RECOMMENDED

**Approach**: Add new columns to schema with pattern-preserving content

**Schema Design**:
```python
SCHEMA = pa.schema([
    # Original fields (for semantic search)
    pa.field("name", pa.string()),
    pa.field("signature", pa.string()),
    pa.field("doc_comment", pa.string()),

    # NEW: Pattern-preserving fields (whitespace tokenization)
    pa.field("code_pattern", pa.string()),  # Combines sig + name + context

    # Vector for semantic search
    pa.field("vector", pa.list_(pa.float32(), 384)),
])
```

**Content Population**:
```python
# For a C# class:
# signature: "public class UserService : BaseService"
# name: "UserService"
# doc_comment: "Handles user operations"

# Build pattern-preserving field:
code_pattern = f"{signature} {name}"
# Result: "public class UserService : BaseService UserService"
# Now searchable for: ": BaseService", "UserService", "public class"
```

**FTS Index Creation**:
```python
# Index ONLY the pattern field with whitespace tokenizer
table.create_fts_index(
    ["code_pattern"],  # Single field, whitespace tokenizer
    use_tantivy=True,
    base_tokenizer="whitespace",  # Preserves : < > [ ] ( )
    with_position=True,
    replace=True
)
```

**Search Strategy**:
```python
def search_code_patterns(query: str, table) -> List[Dict]:
    """Search for code idioms using pattern field."""
    results = table.search(
        MatchQuery(query, "code_pattern"),  # Search ONLY pattern field
        query_type="fts"
    ).limit(50).to_list()
    return results

# Examples:
search_code_patterns("ILogger<", table)     # Finds ILogger<T>, ILogger<IService>
search_code_patterns(": BaseService", table) # Finds all classes inheriting BaseService
search_code_patterns("[Fact]", table)        # Finds test methods with [Fact] attribute
```

**Pros**:
- ✅ Clean separation of concerns (pattern search vs semantic search)
- ✅ No conflicts with existing fields
- ✅ Can still use `name`/`signature` for other purposes
- ✅ Explicit control over what's searchable as patterns

**Cons**:
- ❌ Increases storage (duplicate text in pattern field)
- ❌ Need to populate pattern field during indexing
- ❌ Two separate search paths (pattern vs standard)

**Estimated Storage Impact**:
- Per symbol: ~100-200 bytes for pattern field (signature + name)
- 100K symbols: ~10-20MB additional storage
- **Acceptable tradeoff** for code idiom search capability

---

### **Strategy 2: Create Two Separate Indexes**

**Approach**: Create two FTS indexes - one standard, one pattern-preserving

**Implementation**:
```python
# Index 1: Standard fields with English stemming
table.create_fts_index(
    ["name", "signature", "doc_comment"],
    use_tantivy=True,
    tokenizer_name="en_stem",
    with_position=True,
    replace=False  # Don't replace, create additional index
)

# Index 2: Pattern field with whitespace tokenizer
table.create_fts_index(
    ["code_pattern"],
    use_tantivy=True,
    base_tokenizer="whitespace",
    with_position=True,
    replace=False  # Add to existing indexes
)
```

**Question**: Does LanceDB support multiple FTS indexes per table?
- ⚠️ **UNKNOWN** - Documentation doesn't explicitly confirm this
- Need to test: Call `create_fts_index()` twice with `replace=False`
- Risk: Second call might overwrite first index

**Status**: **REQUIRES TESTING**

---

### **Strategy 3: Use Whitespace for Everything**

**Approach**: Use whitespace tokenizer for ALL fields

**Implementation**:
```python
table.create_fts_index(
    ["name", "signature", "doc_comment", "code_pattern"],
    use_tantivy=True,
    base_tokenizer="whitespace",  # ALL fields use whitespace
    with_position=True,
    replace=True
)
```

**Pros**:
- ✅ Simple - one index, one tokenizer
- ✅ Pattern search works across all fields
- ✅ No complex routing logic needed

**Cons**:
- ❌ **Loses stemming** - "running" won't find "run"
- ❌ **Loses CamelCase splitting** - "UserService" won't match "user" or "service"
- ❌ **Worse for natural language search** - doc comments become less searchable
- ❌ **Regression** - Current search quality degrades

**Verdict**: **NOT RECOMMENDED** - Too many tradeoffs

---

## Recommended Implementation: Strategy 1

### Phase 1: Add Pattern Field (4-6 hours)

**1.1 Update Schema** (1 hour)
```python
# In embeddings.py:130-142
SCHEMA = pa.schema([
    pa.field("id", pa.string(), nullable=False),
    pa.field("name", pa.string(), nullable=False),
    pa.field("kind", pa.string(), nullable=False),
    pa.field("language", pa.string(), nullable=False),
    pa.field("file_path", pa.string(), nullable=False),
    pa.field("signature", pa.string(), nullable=True),
    pa.field("doc_comment", pa.string(), nullable=True),
    pa.field("start_line", pa.int32(), nullable=True),
    pa.field("end_line", pa.int32(), nullable=True),

    # NEW: Pattern-preserving search field
    pa.field("code_pattern", pa.string(), nullable=False),  # Never null

    pa.field("vector", pa.list_(pa.float32(), 384), nullable=False),
])
```

**1.2 Populate Pattern Field** (2 hours)
```python
# In embeddings.py:205-247 (add_symbols method)
def add_symbols(self, symbols: List[Any], vectors: np.ndarray) -> int:
    data = []
    for sym, vec in zip(symbols, vectors):
        # Build pattern-preserving content
        pattern_parts = []
        if sym.signature:
            pattern_parts.append(sym.signature)
        pattern_parts.append(sym.name)
        if sym.kind:
            pattern_parts.append(sym.kind)  # Add kind for context

        code_pattern = " ".join(pattern_parts)

        data.append({
            "id": sym.id,
            "name": sym.name,
            # ... existing fields ...
            "code_pattern": code_pattern,  # NEW
            "vector": vec.tolist(),
        })
    # ... rest of method
```

**1.3 Create Pattern-Only FTS Index** (1 hour)
```python
# In embeddings.py:179-203 (_create_fts_index method)
def _create_fts_index(self):
    """Create TWO FTS indexes with different tokenizers."""
    if self._table is None:
        return

    try:
        # Index 1: Pattern field with whitespace tokenizer (CODE IDIOMS)
        self._table.create_fts_index(
            ["code_pattern"],
            use_tantivy=True,
            base_tokenizer="whitespace",  # Preserves : < > [ ] ( )
            with_position=True,
            replace=True
        )

        # TODO: Test if we can create second index with replace=False
        # Index 2: Standard fields with English stemming (NATURAL LANGUAGE)
        # self._table.create_fts_index(
        #     ["name", "signature", "doc_comment"],
        #     use_tantivy=True,
        #     tokenizer_name="en_stem",
        #     with_position=True,
        #     replace=False  # TESTING: Does this work?
        # )

        self._fts_index_created = True
    except Exception as e:
        self._fts_index_created = False
```

**1.4 Add Pattern Search Method** (1-2 hours)
```python
# In embeddings.py - add new method
def search_patterns(self, query: str, limit: int = 50) -> List[Dict]:
    """
    Search for code patterns using whitespace-tokenized field.

    Use this for code idioms: ILogger<, : BaseClass, [Fact], etc.

    Args:
        query: Code pattern to search for (preserves special chars)
        limit: Maximum results

    Returns:
        List of matching symbols with scores
    """
    from lancedb.query import MatchQuery

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

### Phase 2: Smart Query Routing (2-3 hours)

**2.1 Detect Pattern Queries**
```python
def is_pattern_query(query: str) -> bool:
    """Detect if query contains code patterns."""
    pattern_chars = [':', '<', '>', '[', ']', '(', ')', '{', '}']
    return any(ch in query for ch in pattern_chars)

def route_search(query: str, method: str, limit: int):
    """Route to appropriate search based on query characteristics."""
    if method == "text" and is_pattern_query(query):
        # Use pattern search for code idioms
        return vector_store.search_patterns(query, limit)
    else:
        # Use standard search
        return vector_store.search(query, method, limit)
```

**2.2 Update Server Tool**
```python
# In server.py:165-200 (fast_search tool)
def fast_search(query: str, method: str = "hybrid", limit: int = 50):
    # ... existing code ...

    # Smart routing
    if method == "text" and is_pattern_query(query):
        logger.info(f"Pattern query detected: '{query}' - using whitespace tokenizer")
        return vector_store.search_patterns(query, limit)

    # ... existing search logic ...
```

---

## Testing Plan

### Test 1: Pattern Field Creation ✅
```python
def test_pattern_field_preserves_special_chars():
    """Verify pattern field contains special characters."""
    code = "public class UserService : BaseService { }"
    result = miller_core.extract_file(code, "csharp")

    # Build pattern field
    sym = result.symbols[0]
    pattern = f"{sym.signature} {sym.name}"

    assert ":" in pattern
    assert "BaseService" in pattern
    assert pattern == "public class UserService : BaseService UserService"
```

### Test 2: Whitespace Tokenizer Works ✅
```python
def test_whitespace_tokenizer_preserves_colon():
    """Verify we can search for ': BaseService' pattern."""
    # Create test data with pattern field
    vector_store = VectorStore(db_path=":memory:")

    # Add symbol with inheritance
    # ... (index code with pattern field)

    # Search for inheritance pattern
    results = vector_store.search_patterns(": BaseService", limit=10)

    assert len(results) > 0
    assert any(": BaseService" in r.get("code_pattern", "") for r in results)
```

### Test 3: Generic Types Search ✅
```python
def test_search_for_generic_type_pattern():
    """Verify we can search for 'ILogger<' pattern."""
    # Index: "private readonly ILogger<UserService> _logger;"
    results = vector_store.search_patterns("ILogger<", limit=10)

    assert len(results) > 0
    # Should find ILogger<UserService>, ILogger<T>, etc.
```

### Test 4: Attribute Search ✅
```python
def test_search_for_attribute_pattern():
    """Verify we can search for '[Fact]' attribute."""
    # Index: "[Fact] public void TestMethod() { }"
    results = vector_store.search_patterns("[Fact]", limit=10)

    assert len(results) > 0
    assert all(r.get("kind") == "Method" for r in results)  # Should be test methods
```

---

## Open Questions

### Q1: Can LanceDB have multiple FTS indexes?
**Status**: UNKNOWN
**Test**: Call `create_fts_index()` twice with different fields and `replace=False`
**Impact**: If NO → must use Strategy 1 (duplicate pattern field)

### Q2: Does whitespace tokenizer handle all languages?
**Status**: LIKELY YES (Tantivy is Unicode-aware)
**Test**: Index Python, C#, Rust, Go code and verify pattern search works
**Impact**: If NO for specific languages → may need language-specific handling

### Q3: Performance impact of duplicate field?
**Status**: MINIMAL (estimated ~10-20MB for 100K symbols)
**Test**: Benchmark indexing speed before/after adding pattern field
**Impact**: If SIGNIFICANT → consider lazy indexing pattern field

---

## Decision Matrix

| Criteria | Strategy 1 (Duplicate Field) | Strategy 2 (Two Indexes) | Strategy 3 (Whitespace All) |
|----------|------------------------------|--------------------------|------------------------------|
| **Pattern Search Works** | ✅ YES | ⚠️ UNKNOWN (needs test) | ✅ YES |
| **Stemming Preserved** | ✅ YES (on name/signature) | ✅ YES | ❌ NO |
| **Storage Overhead** | ⚠️ +10-20MB per 100K symbols | ✅ Minimal | ✅ None |
| **Implementation Complexity** | 🟡 Medium (4-6 hours) | 🟡 Medium (test required) | 🟢 Simple (2 hours) |
| **Search Quality** | ✅ Best (specialized fields) | ✅ Best (if it works) | ❌ Regression |
| **Risk** | 🟢 Low | 🟡 Medium (might not work) | 🔴 High (breaks existing) |

**Recommendation**: **Strategy 1** (Duplicate Field)
- Proven approach (COA CodeSearch uses similar strategy)
- Low risk - doesn't break existing functionality
- Clear implementation path
- Acceptable storage tradeoff

---

## Next Steps

1. **✅ Create POC** (2 hours)
   - Add `code_pattern` field to test data
   - Create whitespace FTS index
   - Test: Can we search for `ILogger<`?

2. **Validate Accuracy** (1 hour)
   - Create test suite with 10+ code idiom queries
   - Measure: Do we get expected results?

3. **Implement Phase 1** (4-6 hours)
   - Update schema with pattern field
   - Populate pattern field during indexing
   - Add `search_patterns()` method
   - Write comprehensive tests

4. **Implement Phase 2** (2-3 hours)
   - Add smart query routing
   - Update `fast_search` tool
   - Add pattern detection logic

**Total Estimated Time**: 9-12 hours for full implementation

---

## Success Criteria

Before marking this complete:

- ✅ Can search for `ILogger<` and find all `ILogger<T>` usages
- ✅ Can search for `: BaseClass` and find all classes inheriting BaseClass
- ✅ Can search for `[Fact]` and find all test methods
- ✅ Can search for `?.` and find null-conditional operators
- ✅ Pattern search is <100ms (no performance regression)
- ✅ Standard text search still works (stemming preserved)
- ✅ Tests cover 15+ code idiom patterns across 5+ languages

---

**End of Research Document**
