---
git:
  branch: main
  commit: 730abdf
  dirty: true
  files_changed:
  - CLAUDE.md
  - python/miller/lifecycle.py
  - python/miller/reranker.py
  - python/miller/tools/navigation.py
  - python/miller/tools/search.py
  - python/tests/test_fast_search_toon.py
  - python/tests/test_reranker.py
  - python/tests/test_search_filters.py
  - python/tests/test_server.py
  - .memories/2025-11-24/153258_467a.json
  - .memories/2025-11-24/154255_570d.json
  - .memories/2025-11-24/155624_53ff.json
  - .memories/2025-11-24/160653_3c5b.json
id: plan_implement-renamesymbol-tool
status: pending
timestamp: 1764028575
title: Implement rename_symbol Tool
type: plan
---

# rename_symbol Tool Implementation Plan

## Overview
Replace the underused `fast_goto` with a genuinely useful `rename_symbol` tool that leverages Miller's unique advantages: tree-sitter symbol extraction, reference graph, and semantic embeddings.

## Progress Summary
**Status: Core Implementation Complete (29/29 tests passing)**

---

## Completed Phases

### Phase 1: Contract Definition ✅
- Created `python/miller/tools/refactor.py` with dataclasses
- Defined RenameEdit, RenamePreview, RenameResult, CascadeSuggestion types
- Documented function signatures, parameters, error conditions

### Phase 2: Test Suite (RED Phase) ✅
- Created `python/tests/test_refactor.py` with 29 comprehensive tests
- Tests cover: validation, preview, apply, errors, word boundaries, imports, cascade

### Phase 3: Core Implementation (GREEN Phase) ✅
- [x] `_validate_identifier()` - Python identifier validation
- [x] `_build_edit_plan()` - Convert refs to edit plan
- [x] `_check_name_collision()` - Detect name conflicts
- [x] `_format_preview_as_text/json()` - Preview formatting
- [x] `_format_result_as_text/json()` - Result formatting
- [x] `_apply_edits()` - Word-boundary-safe file modification
- [x] `rename_symbol()` - Main function using find_references
- [x] `find_cascade_suggestions()` - Pattern-based related symbol discovery

---

## Remaining Work

### Phase 4: Integration
- [ ] Remove `fast_goto` from navigation.py
- [ ] Remove from tools_wrappers.py
- [ ] Remove from server.py exports
- [ ] Add `rename_symbol` to tools_wrappers.py with @mcp.tool() decorator
- [ ] Update instructions.md documentation

### Phase 5: Future Enhancements (Noted, not blocking)
- [ ] Qualified name scoping (UserService.save vs OrderService.save)
- [ ] Semantic cascade suggestions using embeddings
- [ ] Cross-language symbol correlation

---

## Technical Notes

### Files Modified
- `python/miller/tools/refactor.py` - New module (implementation complete)
- `python/tests/test_refactor.py` - New test file (29 tests)

### Key Design Decisions
1. **dry_run=True by default** - Safe preview before changes
2. **Word-boundary regex** - Prevents substring renames (e.g., "get" in "get_user")
3. **Uses find_references** - Leverages existing reference graph
4. **Pattern-based cascade** - Uses naming variants for related symbol discovery

### Test Results
- 29/29 rename_symbol tests passing
- 755/755 total tests passing
- Coverage: 80.48%

