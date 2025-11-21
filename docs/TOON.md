# TOON Format: Token-Optimized Object Notation

## What Is TOON?

**TOON (Token-Oriented Object Notation)** is a compact tabular encoding format that reduces token consumption by 30-60% compared to JSON for large result sets. Developed originally in Julie and migrated to Miller, TOON transforms verbose JSON objects into space-efficient tables.

## Why TOON Matters

**Token efficiency directly impacts performance and cost:**
- Claude API charges by tokens (input + output)
- Large search results (50-100+ symbols) consume thousands of tokens in JSON
- TOON achieves 33.8% average reduction (measured across real queries)
- Faster responses, lower costs, better UX

## How TOON Works

### JSON Format (verbose)
```json
[
  {
    "name": "calculate_age",
    "kind": "Function",
    "signature": "(birth_year: int) -> int",
    "doc_comment": "Calculate age from birth year",
    "file_path": "src/user.py",
    "start_line": 15,
    "end_line": 17
  },
  {
    "name": "UserService",
    "kind": "Class",
    "signature": null,
    "doc_comment": "Service for user operations",
    "file_path": "src/services.py",
    "start_line": 23,
    "end_line": 45
  }
]
```

### TOON Format (compact)
```
name|kind|signature|doc_comment|file_path|start_line|end_line
calculate_age|Function|(birth_year: int) -> int|Calculate age from birth year|src/user.py|15|17
UserService|Class||Service for user operations|src/services.py|23|45
```

### Key Principles

1. **Schema homogeneity**: All objects must have identical fields (TOON requirement)
2. **CSV-like structure**: Header row + data rows
3. **Null representation**: Empty string for null values
4. **Escaping**: Pipe characters in data are escaped as `\|`

---

## Implementation

**Code location**: `python/miller/toon_utils.py`

All major Miller tools support three output modes:

```python
# Tools with TOON support:
fast_search(query, output_format="auto")      # Auto-switches at 20 results
get_symbols(file, output_format="auto")       # Auto-switches at 20 symbols
fast_refs(symbol, output_format="auto")       # Auto-switches at 10 references
trace_call_path(symbol, output_format="auto") # Auto-switches at 5 nodes
```

### Output Modes

- `"json"` - Standard JSON (default for backward compatibility)
- `"toon"` - Always use TOON encoding
- `"auto"` - Smart switching based on result count (recommended)

### Auto-Mode Thresholds

| Tool | Threshold | Rationale |
|------|-----------|-----------|
| `fast_search` | 20 results | Typical search returns 10-50 results |
| `get_symbols` | 20 symbols | Large files have 50+ symbols |
| `fast_refs` | 10 references | Popular symbols have many refs |
| `trace_call_path` | 5 nodes | Deep traces can have 20+ nodes |

---

## Testing TOON

### Test Files

- `python/tests/test_toon_format.py` - Core TOON encoding tests (29 tests)
- `python/tests/test_fast_search_toon.py` - fast_search integration (12 tests)
- `python/tests/test_get_symbols_toon.py` - get_symbols integration (10 tests)
- `python/tests/test_fast_refs_toon.py` - fast_refs integration (10 tests)
- `python/tests/test_trace_toon.py` - trace_call_path integration (10 tests)

### Test Examples

```python
def test_toon_encoding_basic():
    """Verify TOON encoding produces correct table format."""
    symbols = [
        {"name": "foo", "kind": "Function", "file_path": "test.py"},
        {"name": "bar", "kind": "Class", "file_path": "test.py"}
    ]
    result = toon_encode(symbols)

    lines = result.strip().split("\n")
    assert lines[0] == "name|kind|file_path"  # Header
    assert lines[1] == "foo|Function|test.py"
    assert lines[2] == "bar|Class|test.py"

def test_auto_mode_threshold():
    """Verify auto mode switches to TOON at threshold."""
    # Small result set (<20) should stay JSON
    result = await fast_search(ctx, "rare_symbol", output_format="auto")
    assert isinstance(result, list)  # JSON

    # Large result set (>=20) should switch to TOON
    result = await fast_search(ctx, "common_term", output_format="auto")
    assert isinstance(result, str)  # TOON string
    assert "|" in result  # Table format
```

---

## Performance Measurements

### Verified Token Reduction

| Tool | Reduction | Status |
|------|-----------|--------|
| `fast_search` | 37.2% | Validated |
| `trace_call_path` | 45.6% | Validated |
| `fast_refs` | 44% | Validated |
| `get_symbols` | 35-40% | Estimated |
| **Average** | **33.8%** | Across all tools |

**Measurement script**: `python/tests/measure_token_reduction.py`

---

## Schema Enforcement

**Critical**: TOON requires all objects in a batch to have identical fields. This is enforced at conversion time:

```python
def format_symbol_for_toon(symbol: dict) -> dict:
    """Enforce ToonSymbol schema (all fields present)."""
    return {
        "name": symbol.get("name", ""),
        "kind": symbol.get("kind", ""),
        "signature": symbol.get("signature"),  # May be None
        "doc_comment": truncate_doc(symbol.get("doc_comment")),  # Truncated
        "file_path": symbol.get("file_path", ""),
        "start_line": symbol.get("start_line"),
        "end_line": symbol.get("end_line"),
    }
```

**Why this matters**: If symbols have different fields (some have `signature`, some don't), TOON encoding fails. The schema enforcement ensures consistency.

---

## Graceful Degradation

**Fallback pattern**: If TOON encoding fails, tools automatically fall back to JSON:

```python
try:
    if output_format == "toon" or (output_format == "auto" and len(results) >= threshold):
        return toon_encode(results)
except Exception as e:
    logger.warning(f"TOON encoding failed: {e}, falling back to JSON")
    return results  # JSON fallback
```

**This ensures**:
- No service disruption if TOON fails
- Backward compatibility maintained
- Errors are logged but don't break the tool

---

## Development Guidelines

1. **Always test auto-mode thresholds** - ensure switching logic works correctly
2. **Verify schema homogeneity** - test with diverse symbol types
3. **Test escaping** - ensure pipe characters in data don't break parsing
4. **Measure token reduction** - validate actual savings with real queries
5. **Test fallback** - ensure JSON fallback works when TOON fails

---

## Future Optimizations

**Potential improvements** (not implemented):
- Column ordering optimization (frequent fields first)
- Field omission (skip columns with all-null values)
- Compression (gzip for very large result sets)

**Current philosophy**: Keep it simple. The current implementation achieves 30-60% reduction with minimal complexity.
