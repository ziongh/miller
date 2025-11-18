# Miller Search Foundation Analysis
**Date**: 2025-11-18
**Goal**: Make Miller's text search EXCELLENT for code idiom matching

---

## Executive Summary

**Problem**: Need to search for code-specific patterns like `ILogger<`, `: BaseClass`, `[Fact]`, etc.
**Current State**: Tantivy FTS with English stemming - breaks apart code patterns
**Solution**: Multi-field indexing + code-aware tokenization (learned from COA CodeSearch)

---

## What We Learned from COA CodeSearch (Lucene.NET)

### 1. **Multi-Field Index Architecture** ⭐ CRITICAL

They index the SAME content into **3 specialized fields**:

| Field | Tokenizer | Purpose | Example Query | Result |
|-------|-----------|---------|---------------|--------|
| `content` | Standard + CamelCase | General search | `user authentication` | Splits CamelCase, standard tokens |
| `content_symbols` | Identifier-only | Symbol matching | `UserService` | Alphanumeric only, aggressive splitting |
| **`content_patterns`** | **Whitespace-only** | **Code idioms** | `ILogger<`, `: BaseClass` | **Preserves ALL special chars!** |

**Key Insight**: By using whitespace-only tokenization on `content_patterns`, they preserve:
- `: ITool` → single token (can search for interface inheritance)
- `ILogger<T>` → single token (can search for generic types)
- `[Fact]` → single token (can search for attributes)
- `std::cout` → single token (can search for C++ namespaces)

### 2. **Smart Query Routing** ⭐ HIGH VALUE

Their `SmartQueryPreprocessor` detects query type and routes to best field:

```csharp
if (query.contains_special_chars([':', '<', '>', '[', ']', '(', ')']))
    → search content_patterns field  // Preserves patterns!

else if (query.is_camelcase() || query.is_code_keyword())
    → search content_symbols field    // Exact symbol matching

else
    → search content field            // Standard text search
```

**Examples**:
- `ILogger<` → `content_patterns` (finds all `ILogger<T>`, `ILogger<IService>`)
- `: BaseClass` → `content_patterns` (finds all classes inheriting BaseClass)
- `UserService` → `content_symbols` (finds UserService class definition)
- `TODO authentication` → `content` (standard search)

### 3. **Custom Code Tokenizer** ⭐ THE SECRET SAUCE

Their `CodeTokenizer` (CodeAnalyzer.cs:111+) has **special pattern recognition**:

```csharp
// Pseudo-code from their implementation:
if (firstChar == ':' && next_char == whitespace && next_is_identifier())
    // Keep ": Type" as single token
    // Enables ": BaseClass" searches!

if (firstChar == '<' && prev_is_identifier())
    // Keep "ILogger<T>" together
    // Enables "ILogger<" searches!

if (firstChar == '[' && contains_alphanumeric())
    // Keep "[Fact]" together
    // Enables attribute searches!
```

**Key behaviors**:
- Recognizes code patterns during tokenization
- Keeps multi-character operators together (`::`, `->`, `=>`, `?.`)
- Preserves generic type syntax (`ILogger<T>`, `IEnumerable<>`)
- Handles C# attributes (`[Fact]`, `[Theory]`)

### 4. **Multi-Factor Scoring** (Nice to have)

They boost/deboo

st relevance with 6 factors:
1. **PathRelevanceFactor**: Deboost test files (reduce noise)
2. **FilenameRelevanceFactor**: Boost if query matches filename
3. **FileTypeRelevanceFactor**: Prioritize `.cs`, `.py` over `.txt`, `.md`
4. **RecencyBoostFactor**: Boost recently modified files
5. **ExactMatchBoostFactor**: Boost exact phrase matches
6. **InterfaceImplementationFactor**: Reduce mock/test implementations for interface searches

### 5. **3-Tier Search** (We already have this!)

1. **Tier 1**: Lucene FTS (fast, accurate for exact matches)
2. **Tier 2**: Fallback to `content` field if specialized field returns 0 results
3. **Tier 3**: Semantic vector search (conceptual similarity)

Miller equivalent:
1. **Tier 1**: Tantivy FTS ✅
2. **Tier 2**: Hybrid search (FTS + vector) ✅
3. **Tier 3**: Pure semantic search ✅

---

## Current Miller Capabilities

### ✅ What We Have

1. **Tantivy FTS** with BM25 scoring (equivalent to Lucene quality)
2. **English stemming** ("running" finds "run", "runs", "runner")
3. **Phrase search** (quoted strings for exact matches)
4. **SQL injection protection** (Tantivy rejects malformed queries)
5. **Semantic vector search** (sentence-transformers + LanceDB HNSW)
6. **Hybrid RRF fusion** (combines text + semantic)

### ❌ What We're Missing

1. **Multi-field indexing** - Only index `name`/`signature`/`doc_comment` as text
   - **Impact**: Can't route queries to specialized fields
   - **Fix**: Create pattern-preserving field with whitespace tokenizer

2. **Code-aware tokenization** - English stemmer breaks code patterns
   - **Impact**: `ILogger<T>` becomes `ilogger` + `t` (can't search for `ILogger<`)
   - **Fix**: Configure Tantivy tokenizer or use custom analyzer

3. **Smart query routing** - All queries go through same pipeline
   - **Impact**: Pattern queries don't get special handling
   - **Fix**: Detect pattern queries, route to pattern field

4. **Relevance boosting** - Only BM25, no path/filename/recency factors
   - **Impact**: Test files rank equally with production code
   - **Fix**: Add custom scoring (lower priority)

---

## Testing Current Capabilities

### Test 1: Can We Search for `ILogger<` Now?

**Expected**: Should NOT work (English tokenizer breaks it apart)

```python
# Create test file
test_code = """
public class UserService {
    private readonly ILogger<UserService> _logger;
    private readonly ILogger<IUserRepository> _repoLogger;

    public UserService(ILogger<UserService> logger) {
        _logger = logger;
    }
}
"""

# Index with current Miller
# Search for "ILogger<"
# Result: Probably finds nothing or finds "ilogger" without the '<'
```

### Test 2: Can We Search for `: BaseClass`?

**Expected**: Should NOT work (English tokenizer removes punctuation)

```python
test_code = """
public class UserService : BaseService {
    // ...
}

public class OrderService : BaseService {
    // ...
}
"""

# Search for ": BaseService"
# Result: Probably finds "baseservice" but not the inheritance pattern
```

### Test 3: Current Tantivy Configuration

Need to check:
```python
# In embeddings.py:179-199
table.create_fts_index(
    ["name", "signature", "doc_comment"],
    use_tantivy=True,
    tokenizer_name="en_stem",      # English stemmer - breaks patterns!
    with_position=True,
    replace=True
)
```

**Issue**: `tokenizer_name="en_stem"` is English-focused, not code-aware.

---

## Proposed Miller Improvements

### Phase 1: Add Pattern-Preserving Field (CRITICAL)

**Goal**: Enable searches like `ILogger<`, `: BaseClass`, `[Fact]`

**Implementation**:
1. Add new field to LanceDB schema: `code_patterns`
2. Index symbols with pattern-preserving content:
   ```python
   code_patterns = f"{symbol.signature} {symbol.name}"
   # For class: "public class UserService : BaseService UserService"
   # Preserves ALL special characters
   ```
3. Create FTS index on `code_patterns` with **whitespace tokenizer**:
   ```python
   table.create_fts_index(
       ["code_patterns"],
       use_tantivy=True,
       tokenizer_name="whitespace",  # KEY: Only split on whitespace!
       with_position=True
   )
   ```
4. Update search to query both fields:
   ```python
   # If query contains special chars:
   results_patterns = table.search(query, query_type="fts", fields=["code_patterns"])
   # Else:
   results_standard = table.search(query, query_type="fts", fields=["name", "signature"])
   ```

**Estimated effort**: 4-6 hours
**Impact**: **HIGH** - Enables all code idiom searches

### Phase 2: Smart Query Detection (HIGH VALUE)

**Goal**: Route queries to best field automatically

**Implementation**:
1. Create `SmartQueryRouter` class
2. Detect query type:
   ```python
   def detect_query_type(query: str) -> QueryType:
       if has_special_chars(query, [':', '<', '>', '[', ']', '(', ')']):
           return QueryType.PATTERN
       elif is_camelcase(query) or is_code_keyword(query):
           return QueryType.SYMBOL
       else:
           return QueryType.STANDARD
   ```
3. Route to appropriate field:
   ```python
   if query_type == QueryType.PATTERN:
       search_fields = ["code_patterns"]
   elif query_type == QueryType.SYMBOL:
       search_fields = ["name"]  # Exact matching
   else:
       search_fields = ["name", "signature", "doc_comment"]
   ```

**Estimated effort**: 3-4 hours
**Impact**: **HIGH** - Automatic best-field routing

### Phase 3: Multi-Factor Scoring (NICE TO HAVE)

**Goal**: Improve relevance (deboost tests, boost recent files)

**Implementation**:
1. Add scoring metadata to LanceDB:
   ```python
   {
       "file_path": "src/UserService.cs",
       "is_test": False,  # Derived from path
       "last_modified": 1699564800,
       "file_type": "cs"
   }
   ```
2. Apply boost/deboost in search:
   ```python
   # Post-process results
   for result in results:
       score = result.score
       if "/test/" in result.file_path:
           score *= 0.5  # Deboost tests
       if result.last_modified > recent_threshold:
           score *= 1.2  # Boost recent
       result.score = score
   ```

**Estimated effort**: 4-6 hours
**Impact**: **MEDIUM** - Better relevance, less noise

### Phase 4: Code-Aware Token Analysis (RESEARCH NEEDED)

**Goal**: Custom tokenization for better code understanding

**Questions**:
- Can Tantivy support custom tokenizers like Lucene?
- Can we configure token filters for code patterns?
- Alternative: Pre-process queries before sending to Tantivy?

**Research needed**: 2-3 hours to investigate Tantivy's tokenization options

---

## Immediate Next Steps

### 1. **Validate Current Limitations** (1 hour)
- Write test: Search for `ILogger<` in test data
- Write test: Search for `: BaseClass` in test data
- Confirm: Current setup CANNOT handle these patterns

### 2. **Proof of Concept: Pattern Field** (2 hours)
- Add `code_patterns` field to schema
- Index one file with pattern-preserving content
- Test: Can we now search for `ILogger<`?
- If yes → proceed with full implementation

### 3. **Implement Phase 1** (4-6 hours)
- Add pattern field to all symbols
- Create whitespace-tokenized FTS index
- Update search logic to query pattern field
- Write comprehensive tests

### 4. **Benchmark Accuracy** (2 hours)
- Create test suite with code idiom queries
- Measure: % of queries that return correct results
- Compare: Before vs After pattern field
- Goal: >95% accuracy on code idiom searches

---

## Success Criteria

**Before starting new tools, search must meet**:

1. ✅ **Code Idiom Searches Work**
   - `ILogger<` finds all `ILogger<T>` usages
   - `: BaseClass` finds all classes inheriting BaseClass
   - `[Fact]` finds all test methods with Fact attribute
   - `?.` finds all null-conditional operators

2. ✅ **High Accuracy**
   - >95% of queries return expected results in top 5
   - <5% false negatives (missed relevant results)
   - <10% false positives (irrelevant results in top 5)

3. ✅ **Fast Performance**
   - <100ms for typical queries (no regression vs current)
   - <200ms for complex pattern queries
   - Indexing speed: >100 files/sec (no regression)

4. ✅ **Comprehensive Tests**
   - Test suite covering 20+ code idiom patterns
   - Tests for all major languages (C#, Python, TypeScript, Rust, Go)
   - Tests for edge cases (escaped chars, nested patterns)

---

## References

- **COA CodeSearch**: `~/source/coa-codesearch-mcp`
  - `TextSearchTool.cs` - Multi-tier search with fallbacks
  - `CodeAnalyzer.cs` - Custom tokenization for code
  - `SmartQueryPreprocessor.cs` - Query routing logic
  - `LineAwareSearchService.cs` - Accurate line number matching

- **Tantivy Documentation**: https://docs.rs/tantivy/
- **LanceDB FTS**: https://lancedb.github.io/lancedb/fts/

---

## Questions for User

1. **Priority**: Is code idiom search (Phase 1) blocking for other work?
2. **Scope**: Should we support all languages or start with C#/.NET patterns?
3. **Testing**: Do you have example queries you want to work? (e.g., your dotnet project examples)
4. **Timeline**: How much time should we allocate to this before moving to tools?

---

**End of Analysis**
