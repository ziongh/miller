---
git:
  branch: main
  commit: 57f38e0
  dirty: false
  files_changed: []
id: plan_toon-format-migration-fastsearch-pilot
status: pending
timestamp: 1763670995
title: TOON Format Migration - fast_search Pilot
type: plan
---

## Goal
Implement TOON format support in `fast_search` tool to achieve 30-60% token reduction for symbol search results. Use Julie's proven three-mode approach (json/toon/auto) as reference.

## Success Criteria
- [ ] `fast_search` supports `output_format` parameter: "json" (default), "toon", "auto"
- [ ] TOON mode returns text-only (no structured content duplication)
- [ ] JSON mode returns structured-only (no text duplication)
- [ ] Auto mode uses TOON for large responses (≥20 results), JSON for small
- [ ] Graceful fallback to JSON if TOON encoding fails
- [ ] Token count reduction measured: Target 30-40% for 50+ result queries
- [ ] All existing tests pass (backward compatibility)
- [ ] New tests added for TOON encoding/decoding

## Implementation Steps

### Phase 1: Setup & Dependencies
- [ ] Add `toon-format>=0.9` to `pyproject.toml`
- [ ] Install: `uv pip install toon-format`
- [ ] Test TOON import: `from toon_format import encode, decode`
- [ ] Read TOON docs for Python usage patterns

### Phase 2: Data Structure Adaptation
- [ ] Create `ToonSymbol` class/dict with primitives only
  - Convert from current Symbol dict format
  - String types for: id, name, kind, language, file_path
  - Numbers: start_line, end_line
  - Optional: signature, doc_comment, confidence (float)
- [ ] Test TOON encoding with sample symbol list
  ```python
  sample = [
      {"name": "UserService", "kind": "Class", "file_path": "user.py", "line": 10},
      {"name": "get_user", "kind": "Method", "file_path": "user.py", "line": 15}
  ]
  toon_str = encode(sample)
  decoded = decode(toon_str)
  assert decoded == sample
  ```

### Phase 3: Modify fast_search Signature
**Current:**
```python
async def fast_search(
    query: str,
    method: Literal["auto", "text", "pattern", "semantic", "hybrid"] = "auto",
    limit: int = 50,
    workspace_id: Optional[str] = None,
) -> list[dict[str, Any]]:
```

**New:**
```python
async def fast_search(
    query: str,
    method: Literal["auto", "text", "pattern", "semantic", "hybrid"] = "auto",
    limit: int = 50,
    workspace_id: Optional[str] = None,
    output_format: Literal["json", "toon", "auto"] = "json",  # NEW
) -> Union[list[dict[str, Any]], str]:  # Can return TOON string
```

### Phase 4: Implement Three-Mode Logic
```python
# After getting results from vector_store.search()
formatted_results = [format_symbol(r) for r in results]

# Mode selection
if output_format == "toon":
    return encode_toon(formatted_results)
elif output_format == "auto":
    if len(formatted_results) >= 20:  # Threshold
        return encode_toon(formatted_results, fallback=True)
    else:
        return formatted_results  # JSON
else:  # "json"
    return formatted_results
```

**Helper functions:**
- [ ] `encode_toon(data, fallback=False)` - Encode to TOON with optional JSON fallback
- [ ] `format_symbol_for_toon(symbol)` - Convert Symbol to TOON-friendly dict

### Phase 5: FastMCP Integration
Current FastMCP likely auto-JSONifies return values. Check if it handles string returns properly:
- [ ] Test: Does FastMCP send string returns as-is (for TOON)?
- [ ] If not: Return `TextContent` object for TOON mode
  ```python
  if output_format == "toon":
      toon_str = encode(formatted_results)
      return {"content": [{"type": "text", "text": toon_str}]}
  ```

### Phase 6: Testing
**Unit Tests:**
- [ ] Test TOON encoding of symbol list (2, 10, 50 symbols)
- [ ] Test decode → encode → decode roundtrip
- [ ] Test fallback when TOON encoding fails
- [ ] Test auto mode threshold (19 results → JSON, 20 results → TOON)

**Integration Tests:**
- [ ] Query that returns 5 results (should be JSON in auto mode)
- [ ] Query that returns 50 results (should be TOON in auto mode)
- [ ] Explicitly request "toon" format
- [ ] Explicitly request "json" format

**Token Measurement:**
```python
import tiktoken
enc = tiktoken.encoding_for_model("gpt-4")

json_str = json.dumps(results)
toon_str = encode(results)

json_tokens = len(enc.encode(json_str))
toon_tokens = len(enc.encode(toon_str))
reduction = (json_tokens - toon_tokens) / json_tokens * 100

print(f"JSON: {json_tokens} tokens")
print(f"TOON: {toon_tokens} tokens")
print(f"Reduction: {reduction:.1f}%")
```

### Phase 7: Documentation
- [ ] Update `fast_search` docstring with `output_format` parameter
- [ ] Add examples of TOON usage
- [ ] Document token savings in CLAUDE.md
- [ ] Update TODO.md Phase 1 checklist

## Reference: Julie's Implementation
Study these files in `~/source/julie`:
- `src/tools/shared.rs` → `create_toonable_result()` (three-mode logic)
- `src/tools/search/formatting.rs` → `ToonSymbol` struct, TOON encoding
- `src/tests/tools/search/toon_formatting_tests.rs` → Test patterns

## Edge Cases to Handle
- Empty results (0 symbols) → Return empty array in both formats
- TOON encoding failure → Fallback to JSON with warning log
- Very large results (500+ symbols) → TOON should handle well (CSV-style)
- Special characters in symbol names → TOON should escape properly
- Optional fields (None values) → TOON should handle or omit

## Rollback Plan
If TOON causes issues:
1. Default stays "json" (backward compatible)
2. Can disable TOON by always returning JSON
3. Remove `output_format` parameter in future if unused

## Metrics to Track
- Token reduction %: Target 30-40% for 50+ results
- Encoding overhead: Should be < 10ms
- Decode success rate: Should be 100% (roundtrip test)
- Client compatibility: Does Claude Code parse TOON correctly?

## Next Steps After Pilot
If successful:
1. Extend to `trace_call_path` (highest impact - nested trees)
2. Extend to `get_symbols`, `fast_refs`
3. Consider making "auto" the default (after validation)
4. Measure aggregate token savings across all tools

