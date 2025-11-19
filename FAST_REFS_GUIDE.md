# fast_refs - Symbol Reference Finder

**Status:** Production-Ready
**Test Coverage:** 13/13 tests passing, 60%+ coverage
**Performance:** <100ms typical, <500ms for heavily-used symbols

---

## Purpose

`fast_refs` answers the critical question: **"Where is this symbol used?"**

Essential for:
- **Safe refactoring** - Know impact before changing code
- **Impact analysis** - Understand dependencies
- **Code exploration** - Find usage examples
- **Debugging** - Trace where symbols are called

---

## Quick Start

```python
from miller.tools.refs import find_references
from miller.storage import StorageManager

# Initialize storage
storage = StorageManager(".miller/indexes/symbols.db")

# Find all references to a symbol
result = find_references(storage, "calculateAge")

print(f"Found {result['total_references']} references")
for file in result['files']:
    print(f"  {file['path']}: {file['references_count']} references")
```

---

## Parameters

### Required

**`storage`** (`StorageManager`)
Storage manager instance with indexed code.

**`symbol_name`** (`str`)
Name of symbol to find references for. Supports:
- Simple names: `"calculateAge"`
- Qualified names: `"User.save"` (finds methods specifically)

### Optional

**`kind_filter`** (`List[str]`, default: `None`)
Filter by relationship type. Common values:
- `["Call"]` - Function/method calls only
- `["Import"]` - Import statements only
- `["Reference"]` - Variable references
- `["Extends", "Implements"]` - Inheritance relationships

**`include_context`** (`bool`, default: `False`)
Whether to include code context snippets showing actual usage.

**`context_file`** (`str`, default: `None`)
File path to disambiguate symbols (only find symbols in this file).

**`limit`** (`int`, default: `None`)
Maximum number of references to return (for pagination).

---

## Return Value

```python
{
    "symbol": str,                  # Symbol name queried
    "total_references": int,        # Total count (even if limited)
    "truncated": bool,             # True if results were limited (optional)
    "files": [                      # Grouped by file
        {
            "path": str,            # File path
            "references_count": int,
            "references": [
                {
                    "line": int,
                    "kind": str,    # "Call", "Import", etc.
                    "context": str  # Code snippet (if include_context=True)
                }
            ]
        }
    ]
}
```

---

## Usage Examples

### Basic Usage

```python
# Find all references
result = find_references(storage, "calculateAge")

for file in result['files']:
    print(f"{file['path']}: {file['references_count']} refs")
```

### With Code Context

```python
# Include actual code lines
result = find_references(storage, "calculateAge", include_context=True)

for file in result['files']:
    print(f"\n{file['path']}:")
    for ref in file['references']:
        print(f"  Line {ref['line']}: {ref['context']}")
```

**Output:**
```
user_service.py:
  Line 45: age = calculateAge(user.birthdate)
  Line 67: return calculateAge(dob)
```

### Filter by Relationship Kind

```python
# Find only function calls (not imports or other references)
result = find_references(
    storage,
    "User",
    kind_filter=["Call"]
)

# Find inheritance relationships
result = find_references(
    storage,
    "BaseModel",
    kind_filter=["Extends", "Implements"]
)
```

### Disambiguate with Qualified Names

```python
# Ambiguous: finds both User class and user variable
result = find_references(storage, "user")

# Specific: finds only User.save method
result = find_references(storage, "User.save")

# Specific: finds only symbols in models/user.py
result = find_references(storage, "save", context_file="models/user.py")
```

### Pagination for Large Result Sets

```python
# Limit to first 50 references
result = find_references(storage, "logger", limit=50)

if result.get("truncated"):
    print(f"Showing 50 of {result['total_references']} references")
```

---

## Common Workflows

### Before Refactoring a Function

```python
# 1. Find all references
result = find_references(storage, "calculateAge", include_context=True)

print(f"Impact: {result['total_references']} references in {len(result['files'])} files")

# 2. Review usage patterns
for file in result['files']:
    print(f"\n{file['path']}: {file['references_count']} uses")
    for ref in file['references'][:3]:  # Show first 3
        print(f"  {ref['line']}: {ref['context']}")

# 3. Decide if refactoring is safe
if result['total_references'] < 10:
    print("✅ Safe to refactor (low usage)")
else:
    print("⚠️  High usage - refactor carefully")
```

### Understanding Symbol Dependencies

```python
# Find what calls this function
callers = find_references(storage, "processPayment", kind_filter=["Call"])

# Find what this module imports
imports = find_references(storage, "PaymentService", kind_filter=["Import"])

# Combine for dependency analysis
print(f"Direct callers: {callers['total_references']}")
print(f"Modules importing: {imports['total_references']}")
```

### Finding Usage Examples

```python
# Find examples of how to use a function
result = find_references(
    storage,
    "authenticate",
    include_context=True,
    limit=5  # Just need a few examples
)

print("Usage examples:")
for file in result['files']:
    for ref in file['references']:
        print(f"  {file['path']}:{ref['line']}")
        print(f"    {ref['context']}")
```

---

## Advanced Features

### Workspace Filtering

```python
from miller.workspace_registry import WorkspaceRegistry
from miller.workspace_paths import get_workspace_db_path

registry = WorkspaceRegistry()

# Query primary workspace
primary_storage = StorageManager(get_workspace_db_path("primary"))
primary_refs = find_references(primary_storage, "User")

# Query reference workspace (e.g., a library)
lib_storage = StorageManager(get_workspace_db_path("my-lib_abc123"))
lib_refs = find_references(lib_storage, "User")

print(f"Primary workspace: {primary_refs['total_references']} refs")
print(f"Library workspace: {lib_refs['total_references']} refs")
```

### Handling Ambiguous Symbols

```python
# Multiple symbols with same name
result = find_references(storage, "save")

if result['total_references'] > 0:
    # Check if results span multiple symbol types
    kinds = set()
    for file in result['files']:
        for ref in file['references']:
            kinds.add(ref['kind'])

    if len(kinds) > 1:
        print(f"⚠️  Ambiguous: found {len(kinds)} different symbol types")
        print("Consider using:")
        print("  - Qualified name: User.save")
        print("  - context_file: models/user.py")
```

### Performance Optimization

```python
import time

# Benchmark query
start = time.time()
result = find_references(storage, "logger", limit=100)
elapsed = (time.time() - start) * 1000

print(f"Query time: {elapsed:.1f}ms")
print(f"Results: {len(result['files'])} files, {result['total_references']} total refs")

# Expected performance:
# - <100ms for typical symbols (10-50 refs)
# - <500ms for heavily-used symbols (100-1000 refs)
```

---

## Integration with MCP Server

When integrated as an MCP tool:

```json
{
  "name": "fast_refs",
  "description": "Find all references to a symbol (where it's used)",
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol_name": {
        "type": "string",
        "description": "Symbol to find references for (supports Class.method)"
      },
      "kind_filter": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Filter by relationship kind (Call, Import, etc.)"
      },
      "include_context": {
        "type": "boolean",
        "description": "Include code context snippets"
      },
      "limit": {
        "type": "integer",
        "description": "Max references to return"
      }
    },
    "required": ["symbol_name"]
  }
}
```

---

## Troubleshooting

### No Results Found

**Problem:** `total_references: 0` for a symbol you know exists

**Solutions:**
1. Check if symbol is indexed:
   ```python
   cursor = storage.conn.cursor()
   cursor.execute("SELECT name, kind FROM symbols WHERE name = ?", (symbol_name,))
   print(cursor.fetchall())
   ```

2. Try without filters:
   ```python
   # Remove kind_filter and context_file
   result = find_references(storage, symbol_name)
   ```

3. Check spelling (case-sensitive):
   ```python
   # Python: calculateAge != CalculateAge
   # Try both if unsure
   ```

### Qualified Name Not Working

**Problem:** `User.save` returns no results

**Solutions:**
1. Check parent symbol exists:
   ```python
   result = find_references(storage, "User")  # Should find parent
   ```

2. Try simple name:
   ```python
   result = find_references(storage, "save")  # See all 'save' symbols
   ```

3. Verify parent-child relationship in DB:
   ```python
   cursor.execute("""
       SELECT child.name, parent.name
       FROM symbols child
       JOIN symbols parent ON child.parent_id = parent.id
       WHERE child.name = 'save'
   """)
   ```

### Performance Issues

**Problem:** Query takes >1 second

**Solutions:**
1. Add limit:
   ```python
   result = find_references(storage, symbol, limit=100)
   ```

2. Check database size:
   ```python
   cursor.execute("SELECT COUNT(*) FROM relationships")
   print(f"Total relationships: {cursor.fetchone()[0]}")
   ```

3. Verify index exists:
   ```python
   cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_rel_to'")
   print(cursor.fetchall())  # Should show index
   ```

---

## Comparison with Other Tools

### vs LSP "Find References"

| Feature | fast_refs | LSP |
|---------|-----------|-----|
| Speed | <100ms | Varies |
| Cross-language | ✅ Yes | ❌ No |
| Historical data | ✅ Yes (indexed) | ❌ No |
| Filtering | ✅ Kind, file, limit | ⚠️  Limited |
| Context snippets | ✅ Yes | ⚠️  Varies |
| Qualified names | ✅ Yes | ⚠️  Varies |

### vs grep/ripgrep

| Feature | fast_refs | grep |
|---------|-----------|------|
| Symbol-aware | ✅ Yes | ❌ No (text only) |
| Relationship types | ✅ Yes | ❌ No |
| False positives | ✅ Low | ⚠️  High (comments, strings) |
| Performance | ✅ Fast (indexed) | ⚠️  Slower (scans files) |
| Grouped output | ✅ By file | ❌ Flat list |

---

## Best Practices

### 1. Use `include_context=True` for Human Review

```python
# ✅ Good: Easy to review
result = find_references(storage, "deleteUser", include_context=True, limit=20)

# ❌ Less useful: Just line numbers
result = find_references(storage, "deleteUser")
```

### 2. Filter by Kind for Specific Analysis

```python
# ✅ Good: Targeted query
calls = find_references(storage, "User", kind_filter=["Call"])
imports = find_references(storage, "User", kind_filter=["Import"])

# ❌ Noisy: All relationships mixed
all_refs = find_references(storage, "User")
```

### 3. Use Limits for Large Result Sets

```python
# ✅ Good: Fast response, manageable output
result = find_references(storage, "logger", limit=50)

# ❌ Slow: May return thousands of results
result = find_references(storage, "logger")
```

### 4. Disambiguate Proactively

```python
# ✅ Good: Specific
result = find_references(storage, "User.save")  # Just the method

# ❌ Ambiguous: May include unrelated symbols
result = find_references(storage, "save")
```

---

## Performance Characteristics

### Time Complexity

- **Symbol lookup:** O(log n) with index
- **Reference query:** O(m) where m = number of references
- **File reading (context):** O(f) where f = number of unique files
- **Overall:** O(log n + m + f) - typically <100ms

### Space Complexity

- **Memory:** O(m) for references list
- **Context caching:** O(f × avg_file_size) - released after query

### Scalability

- **10 references:** ~20ms
- **100 references:** ~50ms
- **1,000 references:** ~200ms
- **10,000 references:** ~1s (use `limit` parameter)

---

## Future Enhancements (Planned)

- [ ] Output format options (markdown, tree, summary)
- [ ] Regex pattern matching for symbol names
- [ ] Cross-workspace aggregation
- [ ] Call depth analysis (direct vs transitive)
- [ ] Dead code detection (0 references)

---

## Contributing

Found a bug? Have a feature request?

1. Check existing tests: `python/tests/test_fast_refs.py`
2. Add a failing test for your use case
3. Implement the fix
4. Ensure all 13+ tests pass

**Remember:** We follow strict TDD discipline!

---

## License

Part of the Miller code intelligence server.
Built with tree-sitter parsing and semantic search.

---

**Last Updated:** 2025-11-19
**Version:** 1.0 (Production-Ready)
