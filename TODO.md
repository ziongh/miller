# Miller - TODO

*Last updated: 2025-11-24*

<!-- Add your notes below -->

## 🔴 CRITICAL BUGS (Found via Dogfooding 2025-11-24)

**Root Cause**: Julie's extractors aren't populating relationship data during indexing. This breaks multiple tools.

### Critical Severity

| Issue | Tool | Status |
|-------|------|--------|
| ~~**`fast_refs` only queries relationships, not identifiers**~~ | `fast_refs` | ✅ FIXED - now queries both tables |
| ~~**`fast_refs` returns empty** for classes~~ | Works for function calls, not class instantiation | ✅ FIXED - finds 79 refs for StorageManager |
| ~~**`fast_explore` "Vector store not available"**~~ | Similar mode throws error | ✅ FIXED - now passes workspace-specific vector_store |
| ~~**`fast_explore` types/deps empty**~~ | Returns nothing for known types | ✅ NOT A BUG - works for types WITH relationships (TypedDict: 6, UserRepository: 1) |

### Medium Severity

| Issue | Tool | Status |
|-------|------|--------|
| **`code_context` always null** | `fast_search` | Falls back to signature instead of grep-style context |
| ~~**`get_symbols` mode="full" broken**~~ | Doesn't show code bodies as documented | ✅ NOT A BUG - use `output_format="code"` to see bodies, `mode` controls extraction scope |
| ~~**`trace_call_path` JSON explodes**~~ | Duplicate "variant" nodes, 25k+ tokens | ✅ BY DESIGN - tree format (default) is compact; JSON includes full metadata |

### Low Severity

| Issue | Tool | Status |
|-------|------|--------|
| **`get_symbols` JSON bloated** | Unused fields: doc_quality, importance_score, cross_language_hints |
| **`get_symbols` TOON missing file_path** | Shows empty string for file_path column |

### What's Working ✅

- `fast_search` - All formats and methods work (text/json/toon, auto/text/semantic/pattern/hybrid)
- `fast_goto` - Clean output both formats
- `trace_call_path` tree format - ASCII tree looks excellent
- `checkpoint` / `recall` - Working perfectly
- `plan` - Working well with task counting
- `manage_workspace` - Concise and useful

---

## ✅ COMPLETED

1. ~~Deep review project startup indexing, incremental indexing, and the manage_workspace functionality.~~ **DONE (2025-11-23)**
   - Achieved parity with Julie PLUS additional improvements
   - Added: `.millerignore` with smart vendor detection
   - Added: Staleness detection (mtime vs DB timestamp)
   - Added: Blake3 hashing in Rust (3x faster)
   - Added: Atomic batch updates with INSERT OR REPLACE
   - Added: Per-workspace database paths
   - Added: `fast_explore` similar and dependencies modes

---

## IN PROGRESS / TODO

2. ~~Audit data capture and storage~~ **PARTIALLY DONE (2025-11-23)**
   - ✅ Verified 100% schema parity with Julie (symbols, identifiers, relationships, files tables)
   - ✅ Confirmed LanceDB/Tantivy for FTS (NOT SQLite FTS5)
   - ✅ PyO3 bindings expose all extractor fields
   - ✅ LanceDB has `code_pattern` field (Miller-only advantage for pattern search)
   - ⏳ Remaining: Implement enhancements from "Future Enhancements" section below

3. We need to check the issues on github in Julie, a user posted a comment there about RAG and embeddings that I want us to discuss.

4. Plan tool token efficiency and task management
   - Added summary mode to `list` action (excludes content/git by default)
   - Added `include_content=True` option for full plan retrieval
   - Added `task_count` and `completed_count` fields (parses `- [ ]` / `- [x]` checkboxes)
   - Updated docstring with Task Counting section
   - Updated server instructions.md with plan tool best practices
   - All 13 plan tests pass
   - we made some good progress but the plan tool is still very inefficient with token usage
   - we need to reduce the tokens needed and returned for each operation too

5. ~~In Julie we created a set of rules to follow when auditing each tool and then went one by one validating each tool (/Users/murphy/source/julie/docs/archive/TOOL_AUDIT_2025-11-11_COMPLETE.md) we should do something similar in Miller to make sure that every tool is leveraging our unique functionality to highest level it can. Also part of this audit should be the specialized output formats. Another point: as we audit the tools we should explore how Julie implemented the same tool, not to copy it but make sure that Julie hasn't already solved some issue we haven't encountered yet or maybe Julie has some genuinely clever implementation we can build on. All params that can be optional with a smart default should be.~~ ✅ **DONE (2025-11-24)**
   - Created `docs/TOOL_AUDIT_CHECKLIST.md` with 7-dimension audit framework
   - Created `docs/TOOL_AUDIT_FINDINGS.md` with per-tool analysis
   - All 10 tools audited: 7 FIXED, 3 EXCELLENT (no changes needed)
   - Key fixes: hardcoded threshold in fast_explore, added TOON to all tools, text defaults everywhere

6. We should look at the skills defined in Julie and create our own version for Miller ~/source/julie/.claude/skills https://code.claude.com/docs/en/skills

7. We have some custom commands we've created at .claude/commands, we should discuss if there are others we should add. We should also discuss if there are any hooks we should create https://code.claude.com/docs/en/hooks-guide

8. Here's a comment I got on the Julie repo that might have some info in it we should discuss: What if we instead of using SQLlite + ONXX cutom embedding storage, we used something like LanceDB and we could also add some improvements, like a ReRanker step at the end of extraction. And LanceDB can do both FTS5 search plus embeddings.
   - ✅ **Re-ranker: DONE** (2025-11-23) - Implemented cross-encoder re-ranking in `fast_search`
   - ✅ **LanceDB: Already using it** - Miller uses LanceDB with Tantivy FTS
   - ⏳ **LoRA finetuning**: Still an interesting idea for future

We could also create a small script for Finetunning an Embedding model like "jinaai/jina-code-embeddings-0.5b" using LoRa. It has a context window of 32K tokens, which would allow larger methods/classes/ etc to be better indexed (I know that in a good code base this shouldn't exsit). And by using something like LoRa (Fine-tuning) it would allow companies to embed some of their specific framework knowledge. For instance, on a company there may exist a specific way to access DB in C# that is not simple Dapper or simple EfCore, but a in-house framework. And with fine-tuning the embeddings, we could improve the understanding and parsing of existing code.

9. ~~manage_workspace tool should always default to the primary workspace and the workspace parameter should be optional.~~ ✅ **DONE** - `workspace_id` now defaults to primary workspace for `stats`, `remove`, `refresh` operations

10. Using our existing embeddings tools we can use semantic similarity to help power tools like our rename_symbol, fast_refs, etc. Let's discuss and make a plan to leverage this even more and we should probably build a set of utilities to make it even easier to integrate into more tools to further power our cross language intelligence.

---

## Future Enhancements (Ranked by Impact)

*Added 2025-11-23 after data audit confirmed parity with Julie. These are ideas to push Miller beyond Julie.*

### Tier 1: Game Changers 🏆

| Rank | Feature | Impact |
|------|---------|--------|
| **#1** | ~~**Re-ranker (cross-encoder)**~~ ✅ **DONE** | Implemented! `rerank=True` by default in `fast_search`. Uses `ms-marco-MiniLM-L6-v2` (~33ms for 50 results). See `python/miller/reranker.py`. |
| **#2** | ~~**Transitive closure table**~~ ✅ **DONE** | Implemented! `reachability` table with BFS closure computation. `can_reach()`, `get_distance()` for O(1) lookups. Computed after indexing. See `python/miller/closure.py`. |
| **#3** | ~~**Graph expansion on search**~~ ✅ **DONE** | Implemented! `expand=True` in `fast_search` includes direct callers/callees. Uses reachability table (distance=1) for O(1) lookups. Text format shows ← Callers and → Callees. |

### Tier 2: Significant Improvements 🎯

| Rank | Feature | Impact |
|------|---------|--------|
| **#4** | **Dual embeddings** | Code model + NL model. "Find auth logic" (NL) vs "IAuthService" (code) use different models for better recall. |
| **#5** | **Query expansion** | "auth" → also search "authenticate authorization credentials". Catches synonyms embeddings miss. |
| **#6** | **Field boosting (Tantivy)** | `name^3 signature^2 doc_comment^1`. Name matches rank higher. Simple config, measurable improvement. |

### Tier 3: Valuable Additions 📈

| Rank | Feature | Impact |
|------|---------|--------|
| **#7** | **Entry point detection** | Mark symbols as main/handler/test/route. "Show me entry points" for codebase understanding. |
| **#8** | **Contextual boosting** | Boost results from recently touched files. Workflow-aware search. |
| **#9** | **Fuzzy search (Tantivy ~)** | Typo tolerance via edit distance. "authentcation~1" finds "authentication". |
| **#10** | **Call frequency counts** | Track how many times A calls B. Hot path detection. |

### Tier 4: Polish 💅

| Rank | Feature | Impact |
|------|---------|--------|
| **#11** | Symbol metrics (LOC, complexity) | Code quality insights |
| **#12** | Scalar indexes in LanceDB | Performance (already fast enough) |
| **#13** | AST fingerprints | Structural similarity (embeddings handle this) |

### Key Insight

The top 3 share a theme: **returning understanding, not just locations**. ✅ **ALL COMPLETE!**
- Re-ranker → return the *right* results ✅
- Transitive closure → return *impact*, not just direct calls ✅
- Graph expansion → return *context*, not just the symbol ✅

Miller now answers "what do I need to know about X?" not just "where is X?"
