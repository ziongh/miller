---
completed_at: 1763591624
git:
  branch: main
  commit: 7e83742
  dirty: true
  files_changed:
  - .memories/2025-11-19/122349_727b.json
  - .memories/2025-11-19/131950_43ff.json
id: plan_complete-getsymbols-better-than-julie
status: completed
timestamp: 1763580121
title: Complete get_symbols - Better Than Julie
type: plan
---

## Goal: Build the Best Symbol Overview Tool for AI Agents

Miller's `get_symbols` will be better than Julie's by leveraging Python's ML capabilities
to provide not just structure, but **intelligence about the code**.

---

## Success Criteria

**Feature Parity with Julie:**
- ✅ Multiple reading modes (structure/minimal/full)
- ✅ Max depth control (0=top-level, 1=methods, 2+=nested)
- ✅ Target filtering with partial matching
- ✅ Limit parameter for large files
- ✅ Body extraction (mode="full" returns implementation)
- ✅ Workspace filtering (primary vs reference)

**Miller's Enhancements (Better Than Julie):**
- ✅ Semantic relevance scores for filtered symbols
- ✅ Usage frequency indicators (how often symbol is referenced)
- ✅ Documentation quality scores (highlight undocumented code)
- ✅ Related symbols suggestions (using embeddings)
- ✅ Cross-language variant hints (symbol has naming variants in other langs)
- ✅ Symbol importance ranking (PageRank on call graph)
- ✅ Performance: <50ms for typical files, <200ms for large files

---

## Phase 1: Feature Parity with Julie (Foundation)

### Task 1.1: Reading Modes
- [ ] Implement "structure" mode (default): names, kinds, signatures, locations
- [ ] Implement "minimal" mode: names and kinds only (ultra-compact)
- [ ] Implement "full" mode: everything including body/implementation

### Task 1.2: Depth Control
- [ ] Add max_depth parameter (0=top-level only, 1=include methods, 2+=nested)
- [ ] Implement depth filtering in tree-sitter traversal
- [ ] Test with deeply nested code (classes in classes in modules)

### Task 1.3: Target Filtering
- [ ] Add target parameter (symbol name to filter)
- [ ] Implement partial matching (case-insensitive substring)
- [ ] Return matching symbols + their children (up to max_depth)

### Task 1.4: Limit & Pagination
- [ ] Add limit parameter (max symbols to return)
- [ ] Implement smart limiting (preserve hierarchy when limiting)
- [ ] Add "truncated" indicator if limit reached

### Task 1.5: Workspace Filtering
- [ ] Support workspace parameter ("primary" or workspace_id)
- [ ] Query appropriate workspace database
- [ ] Handle reference workspace symbol resolution

**Tests:**
- [ ] Test each mode with Python, TypeScript, Rust files
- [ ] Test depth control (0, 1, 2, 3)
- [ ] Test target filtering with partial matches
- [ ] Test limit with large files (500+ symbols)
- [ ] Test workspace filtering with reference workspace

---

## Phase 2: Python/ML Enhancements (Better Than Julie)

### Task 2.1: Semantic Relevance Scores
**Goal:** When filtering by target, rank results by semantic relevance

```python
# Example: get_symbols("auth.py", target="login")
# Returns symbols ranked by relevance:
# 1. "login" (exact match) - score: 1.0
# 2. "handle_login" (contains target) - score: 0.8
# 3. "authenticate_user" (semantically similar) - score: 0.6
```

**Implementation:**
- [ ] Compute embeddings for symbol names + signatures
- [ ] Calculate cosine similarity between target and symbols
- [ ] Add "relevance_score" field to output
- [ ] Sort by relevance when target specified

### Task 2.2: Usage Frequency Indicators
**Goal:** Show how "important" each symbol is based on usage

```python
# Example output:
# {
#   "name": "calculateAge",
#   "kind": "Function",
#   "usage_frequency": "high",  # Referenced 47 times
#   "references_count": 47
# }
```

**Implementation:**
- [ ] Query symbol_relationships table for reference counts
- [ ] Add reference_count field
- [ ] Add usage_frequency tier (low/medium/high/very_high)
- [ ] Thresholds: low=1-5, medium=6-20, high=21-50, very_high=50+

### Task 2.3: Documentation Quality Scores
**Goal:** Highlight undocumented code (help agents prioritize what needs docs)

```python
# Example:
# {
#   "name": "processPayment",
#   "doc_quality": "poor",  # No docstring
#   "has_docs": false,
#   "doc_comment": null
# }
```

**Implementation:**
- [ ] Check if doc_comment exists and is non-empty
- [ ] Measure doc quality (length, completeness)
- [ ] Add doc_quality field (none/poor/good/excellent)
- [ ] Criteria: none=no docs, poor=<50 chars, good=50-200, excellent=200+

### Task 2.4: Related Symbols Suggestions
**Goal:** Suggest similar/related symbols using embeddings

```python
# Example: get_symbols("user.py", target="User")
# Returns:
# {
#   "name": "User",
#   "related_symbols": [
#     {"name": "UserProfile", "similarity": 0.85},
#     {"name": "UserService", "similarity": 0.78},
#     {"name": "UserRepository", "similarity": 0.72}
#   ]
# }
```

**Implementation:**
- [ ] Compute embedding for target symbol
- [ ] Search vector_store for top-5 similar symbols
- [ ] Filter to same file or closely related files
- [ ] Add related_symbols field with similarity scores

### Task 2.5: Cross-Language Variant Hints
**Goal:** Show if symbol has variants in other languages (supports trace_call_path)

```python
# Example:
# {
#   "name": "IUser",
#   "language": "typescript",
#   "cross_language_hints": {
#     "has_variants": true,
#     "variants_count": 3,
#     "languages": ["python", "csharp", "sql"]
#   }
# }
```

**Implementation:**
- [ ] Generate naming variants for symbol (snake, camel, pascal, etc.)
- [ ] Query database for variants in different languages
- [ ] Add cross_language_hints field
- [ ] Include variant count and languages found

### Task 2.6: Symbol Importance Ranking
**Goal:** Use call graph analysis to rank symbol importance

```python
# Example:
# {
#   "name": "authenticate",
#   "importance": "critical",  # PageRank in top 5%
#   "importance_score": 0.87,
#   "is_entry_point": true  # Called by many, calls few
# }
```

**Implementation:**
- [ ] Build call graph from relationships table
- [ ] Compute PageRank scores (use networkx)
- [ ] Add importance_score and importance tier (low/medium/high/critical)
- [ ] Flag entry points (high in-degree, low out-degree)

**Tests:**
- [ ] Test semantic relevance with fuzzy targets
- [ ] Test usage frequency calculation accuracy
- [ ] Test doc quality scoring
- [ ] Test related symbols suggestions
- [ ] Test cross-language variant detection
- [ ] Test importance ranking with call graph

---

## Phase 3: Performance & Polish

### Task 3.1: Performance Optimization
**Target:** <50ms for typical files, <200ms for large files

- [ ] Profile current implementation
- [ ] Cache embeddings for symbols (avoid recomputation)
- [ ] Lazy load body content (only compute if mode="full")
- [ ] Batch database queries
- [ ] Add performance logging

### Task 3.2: Output Format & Agent UX
**Goal:** Make output maximally useful for agents

- [ ] Add structured JSON output (easy to parse)
- [ ] Add markdown tree view option (human-readable)
- [ ] Include file metadata (language, LOC, symbol count)
- [ ] Add next_actions suggestions based on results
- [ ] Include query performance metrics

### Task 3.3: Error Handling & Edge Cases
- [ ] Handle binary files gracefully
- [ ] Handle very large files (>10k lines)
- [ ] Handle unparseable code (syntax errors)
- [ ] Handle missing embeddings gracefully
- [ ] Handle empty files

### Task 3.4: Documentation
- [ ] Update TOOLS_PLAN.md with final implementation
- [ ] Add usage examples for each mode
- [ ] Document all parameters and defaults
- [ ] Add troubleshooting guide

**Tests:**
- [ ] Benchmark against Julie (should be faster)
- [ ] Test with 100+ file corpus
- [ ] Test error handling with malformed files
- [ ] Test output format parsing by agents

---

## Implementation Notes

### Key Design Decisions

1. **Compute semantic features lazily**
   - Only compute embeddings/relevance when target specified
   - Avoid expensive operations for simple structure queries

2. **Cache aggressively**
   - Cache embeddings in vector_store
   - Cache call graph PageRank scores
   - Invalidate on file changes

3. **Graceful degradation**
   - If embeddings unavailable, skip semantic features
   - If relationships table empty, skip usage frequency
   - Always return basic structure (never fail completely)

4. **Agent-first output**
   - Structured JSON for programmatic access
   - Include metadata agents need (relevance, usage, docs)
   - Provide next_actions suggestions

### Python Libraries to Use

- `miller_core` - Tree-sitter parsing (already implemented)
- `networkx` - Call graph analysis, PageRank
- `numpy` - Vector operations
- `sentence-transformers` - Already integrated for embeddings

### Test Strategy

1. **Unit tests** for each mode/feature
2. **Integration tests** with real codebases
3. **Performance tests** with large files
4. **Comparison tests** against Julie's output (validate parity)

---

## Milestones

- **M1: Feature Parity** - All Julie features working (1-2 days)
- **M2: Semantic Enhancements** - ML features implemented (2-3 days)
- **M3: Performance & Polish** - Optimized and documented (1 day)

**Total Estimate:** 4-6 days of focused work

---

## Success Metrics

**Quantitative:**
- Performance: <50ms typical, <200ms large files
- Feature coverage: 100% parity + 6 enhancements
- Test coverage: >90% of get_symbols code

**Qualitative:**
- Agent feedback: "get_symbols gives me everything I need to understand code"
- Human feedback: "Best code overview tool I've used for onboarding"
- Comparison: "Noticeably better than Julie's get_symbols"

---

## Next Steps After Completion

1. Update TOOLS_PLAN.md with final implementation details
2. Create usage examples in documentation
3. Gather early user feedback
4. Move on to fast_refs implementation
