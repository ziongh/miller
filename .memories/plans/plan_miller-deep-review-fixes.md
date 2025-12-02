---
git:
  branch: main
  commit: a635220
  dirty: true
  files_changed:
  - .memories/2025-11-24/120551_d6c7.json
  - .memories/2025-11-24/135457_b696.json
id: plan_miller-deep-review-fixes
status: pending
timestamp: 1764014987
title: Miller Deep Review Fixes
type: plan
---

## Goal
Address all issues found in the Miller deep review comparing with Julie.

## Bugs (Tier 1 - Fix Now) ✅ COMPLETE

- [x] Fix `test_checkpoint_captures_git_context` - patch `miller.tools.checkpoint.get_git_context` not `miller.memory_utils.get_git_context`
- [x] Add `__del__` safety net to `StorageManager` for unclosed connections
- [x] Add `__del__` safety net to `VectorStore` for unclosed connections
- [x] Add backwards-compatible `_search_pattern`, `_search_text`, `_search_semantic`, `_search_hybrid` methods to VectorStore

## File Size Refactoring (Tier 2 - COMPLETE) ✅

- [x] Split `storage.py` (830→5 modules: schema 191, queries 312, mutations 408, manager 235, __init__ 15)
- [x] Split `vector_store.py` (831→4 modules: vector_store 378, fts_index 90, search_methods 278, search_enhancements 245)
- [x] Split `ignore_patterns.py` (609→422 + ignore_defaults.py 194)
- [x] Split `scanner.py` (582→500 + discovery.py 153)
- [x] Split `server.py` (814→142 + lifecycle.py 259 + tools_wrappers.py 461 + server_state.py 19)

## Missing Features (Tier 3 - Port from Julie) ✅ COMPLETE

- [x] Add semantic fallback when text search returns 0 results
- [x] Add `language` filter parameter to `fast_search`
- [x] Add `file_pattern` (glob) filter parameter to `fast_search`

## Test Coverage (Tier 4)

- [ ] Improve `recall.py` coverage (currently 32%)
- [ ] Improve `hash_tracking.py` coverage (currently 45%)
- [ ] Improve `indexer.py` coverage (currently 46%)
- [ ] Get overall coverage from 78.80% to 80%+

## Results

**706 tests passing!**
**All files now under 500 lines!**
**Coverage: 78.80% (close to 80% target)**
**All Tier 1-3 tasks complete!**
