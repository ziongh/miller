---
completed_at: 1763492074
git:
  branch: main
  commit: cf00e54713e1dc020a03e168808f1cf3523fc518
  dirty: false
id: plan_implement-checkpointrecallplan-tools-in-miller-julie-compatible
status: completed
timestamp: 1763488903
title: Implement checkpoint/recall/plan tools in Miller (Julie-compatible)
type: plan
---

## Goal
Implement checkpoint, recall, and plan MCP tools in Miller with 100% backward compatibility with Julie's .memories system, enabling dogfooding Miller to replace Julie.

## Status: ✅ PHASES 1-3 COMPLETE | Phase 4 In Progress

## Success Criteria
- ✅ Same JSON schema as Julie (all fields, types match exactly)
- ✅ Same file naming (HHMMSS_XXXX.json format)
- ✅ Same directory structure (.memories/YYYY-MM-DD/, .memories/plans/)
- ✅ Same ID format ({type}_{8hex}_{6hex})
- ✅ Same git context capture (branch, commit, dirty, files_changed)
- ✅ Can read existing Julie checkpoints
- ✅ Julie can read Miller checkpoints
- ✅ All tests passing (TDD methodology) - 24/24 passing
- ✅ UTC timezone for directory naming (Julie compatibility)
- ✅ Slash commands created (/checkpoint, /recall)

---

## ✅ Phase 1: Test Design (COMPLETE)

### 1.1 Create test file structure
- ✅ Create `python/tests/test_memory_tools.py` - 783 lines, 24 tests
- ✅ Add pytest fixtures for temp .memories directory
- ✅ Add fixtures for mock git context

### 1.2 Checkpoint tool tests (8/8 passing)
- ✅ `test_checkpoint_creates_file_in_correct_location()`
- ✅ `test_checkpoint_json_schema_matches_julie()`
- ✅ `test_checkpoint_generates_unique_id_format()`
- ✅ `test_checkpoint_captures_git_context()`
- ✅ `test_checkpoint_supports_all_memory_types()`
- ✅ `test_checkpoint_handles_tags()`
- ✅ `test_checkpoint_returns_checkpoint_id()`
- ✅ `test_checkpoint_file_is_pretty_printed()`

### 1.3 Recall tool tests (7/7 passing)
- ✅ `test_recall_returns_recent_first()`
- ✅ `test_recall_filters_by_type()`
- ✅ `test_recall_filters_by_since_date()`
- ✅ `test_recall_filters_by_until_date()`
- ✅ `test_recall_respects_limit()`
- ✅ `test_recall_reads_julie_checkpoints()`
- ✅ `test_recall_handles_empty_memories()`

### 1.4 Plan tool tests (9/9 passing)
- ✅ `test_plan_save_creates_file()`
- ✅ `test_plan_generates_slug_from_title()`
- ✅ `test_plan_save_auto_activates_by_default()`
- ✅ `test_plan_list_returns_all_plans()`
- ✅ `test_plan_list_filters_by_status()`
- ✅ `test_plan_activate_deactivates_others()`
- ✅ `test_plan_update_modifies_content()`
- ✅ `test_plan_complete_sets_timestamp()`
- ✅ `test_plan_get_retrieves_by_id()`

---

## ✅ Phase 2: Implementation (COMPLETE)

### 2.1 Create memory utilities module
- ✅ Create `python/miller/memory_utils.py` - 285 lines
- ✅ Implement `generate_checkpoint_id(type: str) -> str`
- ✅ Implement `generate_checkpoint_filename() -> str`
- ✅ Implement `get_checkpoint_path(timestamp: int) -> Path` - Uses UTC
- ✅ Implement `get_git_context() -> dict`
- ✅ Implement `slugify_title(title: str) -> str`
- ✅ Implement `write_json_file()` and `read_json_file()` (refactoring)

### 2.2 Implement checkpoint tool
- ✅ Add `checkpoint()` function in `python/miller/tools/memory.py`
- ✅ Parameters: description, tags=None, type="checkpoint"
- ✅ Capture git context automatically
- ✅ Generate unique ID and filename
- ✅ Create .memories/YYYY-MM-DD/ directory if needed (UTC timezone)
- ✅ Write pretty-printed JSON (indent=2, sort_keys=True)
- ✅ Return checkpoint ID

### 2.3 Implement recall tool
- ✅ Add `recall()` function in `python/miller/tools/memory.py`
- ✅ Parameters: type=None, since=None, until=None, limit=10
- ✅ Scan .memories/YYYY-MM-DD/ directories
- ✅ Parse JSON files
- ✅ Filter by type/date if specified
- ✅ Sort by timestamp descending
- ✅ Return list of checkpoint dicts

### 2.4 Implement plan tool
- ✅ Add `plan()` function in `python/miller/tools/memory.py`
- ✅ Support actions: save, get, list, activate, update, complete
- ✅ Implement slug generation for plan IDs
- ✅ Implement single-active-plan enforcement
- ✅ Create .memories/plans/ directory if needed
- ✅ Write pretty-printed JSON

### 2.5 Register MCP tools
- ✅ Add mcp.tool() registration for checkpoint in server.py
- ✅ Add mcp.tool() registration for recall in server.py
- ✅ Add mcp.tool() registration for plan in server.py
- ✅ Tools working via MCP protocol

---

## ✅ Phase 3: Backward Compatibility Validation (COMPLETE)

### 3.1 Cross-compatibility tests
- ✅ Miller reads Julie checkpoints (tested in test suite)
- ✅ Julie can read Miller checkpoints (verified via standalone test)
- ✅ Checkpoint schema exact match verified
- ✅ UTC timezone compatibility confirmed

### 3.2 Edge cases
- ✅ Handles missing .memories/ directory (creates automatically)
- ✅ Handles corrupt JSON gracefully (try/except in recall)
- ✅ Tag normalization handles special chars
- ✅ All edge cases covered in test suite

---

## 🔄 Phase 4: Integration & Documentation (IN PROGRESS)

### 4.1 Integration tests & Polish
- ✅ Checkpoint/recall round-trip verified
- ✅ Plan full lifecycle tested
- ✅ Slash commands created (.claude/commands/checkpoint.md, recall.md)
- ✅ UTC timezone fix applied
- ✅ Code refactored (DRY principle - extracted JSON helpers)
- ⏳ Additional integration tests (optional)

### 4.2 Documentation (REMAINING)
- ⏳ Update server.py tool docstrings with examples
- ⏳ Add memory tools section to README.md
- ⏳ Document .memories/ structure in PLAN.md
- ⏳ Add usage examples to docs/

### 4.3 Performance validation (OPTIONAL)
- ⏳ Benchmark recall with 1000 checkpoints (should be <100ms)
- ⏳ Verify checkpoint creation is <50ms
- ⏳ Test with large descriptions (1MB text)

---

## 📊 Implementation Summary

**Files Created:**
- `python/miller/memory_utils.py` - 285 lines (80% coverage)
- `python/miller/tools/memory.py` - 356 lines (83% coverage)
- `python/tests/test_memory_tools.py` - 783 lines (24 tests)
- `.claude/commands/checkpoint.md` - Slash command
- `.claude/commands/recall.md` - Slash command

**Files Modified:**
- `python/miller/server.py` - Registered 3 MCP tools

**Test Results:**
- 24/24 tests passing (100%)
- Coverage: memory_utils.py 80%, tools/memory.py 83%
- All edge cases covered

**Git Commits:**
- `8549b4d` - feat: Add /checkpoint and /recall slash commands
- `5de881f` - feat: Complete checkpoint/recall/plan memory tools with TDD
- `2bac9ec` - fix: Use UTC timezone for memory directory naming

---

## Remaining Work

### Documentation (High Priority)
1. Update README.md with memory tools section
2. Add usage examples
3. Update tool docstrings

### Performance Validation (Optional)
- Benchmark with large datasets
- Stress testing

**Estimated Time:** 1-2 hours for documentation

---

## Acceptance Criteria Status

- ✅ All tests passing (100%) - 24/24
- ✅ Can read existing Julie checkpoints
- ✅ Julie can read Miller checkpoints (verified)
- ✅ Same JSON schema, file structure, naming conventions
- ✅ Git context captured correctly
- ✅ Plans work with single-active enforcement
- ✅ Slash commands for UX
- ⏳ Documentation complete
- ✅ Ready to dogfood Miller as Julie replacement (actively doing so!)

