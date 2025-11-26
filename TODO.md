# Miller - TODO

*Last updated: 2025-11-26*

<!-- Add your notes below -->

## Current Tasks

1. Need to make sure github workflow still building properly and prepare for a 1.0 release

2. We need to review the toolkit as a whole and decide if fast_refs needs to be removed and replaced with a better tool or if we just need to make it better and keep it.

3. We've got to do another deep review of the indexing process for sqlite and lancedb, apparently we have duplicates happening.

4. WTF IS THIS SHIT: ⏺ miller - fast_search (MCP)(query: "test vector_store search file_filter", file_pattern: "python/tests/**/*.py", limit: 10)
  ⎿  Error: Error calling tool 'fast_search': lance error: LanceError(IO): External error: Not found:
     Users/murphy/source/miller/.miller/indexes/miller_816288f4/vectors.lance/symbols.lance/data/1010000101111000100110117538ea4021a8a9206158af6da6.lance,
     /Users/runner/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/lance-io-0.39.0/src/local.rs:122:31,
     /Users/runner/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/lance-0.39.0/src/dataset/scanner.rs:3677:83
---

## Future Enhancements (Ranked by Impact)

*Ideas to push Miller beyond Julie. Add new ideas here.*

### Tier 2: Significant Improvements

| Rank | Feature | Impact |
|------|---------|--------|
| **#4** | **Dual embeddings** | Code model + NL model. "Find auth logic" (NL) vs "IAuthService" (code) use different models for better recall. |
| **#5** | **Query expansion** | "auth" → also search "authenticate authorization credentials". Catches synonyms embeddings miss. |
| **#6** | **Field boosting (Tantivy)** | `name^3 signature^2 doc_comment^1`. Name matches rank higher. Simple config, measurable improvement. |

### Tier 3: Valuable Additions

| Rank | Feature | Impact |
|------|---------|--------|
| **#7** | **Entry point detection** | Mark symbols as main/handler/test/route. "Show me entry points" for codebase understanding. |
| **#8** | **Contextual boosting** | Boost results from recently touched files. Workflow-aware search. |
| **#9** | **Fuzzy search (Tantivy ~)** | Typo tolerance via edit distance. "authentcation~1" finds "authentication". |
| **#10** | **Call frequency counts** | Track how many times A calls B. Hot path detection. |

### Tier 4: Polish

| Rank | Feature | Impact |
|------|---------|--------|
| **#11** | Symbol metrics (LOC, complexity) | Code quality insights |
| **#12** | Scalar indexes in LanceDB | Performance (already fast enough) |
| **#13** | AST fingerprints | Structural similarity (embeddings handle this) |

---

## Completed (Archive)

<details>
<summary>Click to expand completed items</summary>

### 2025-11-26
- ✅ Fixed DirectML not working on Windows - was passing "dml" string to SentenceTransformer, but PyTorch needs actual `torch_directml.device()` object
- ✅ README overhaul - now features tool-specific lean formats (70-90% token savings), moved TOON to secondary

### 2025-11-25
- ✅ Fixed `code_context` always null in `fast_search` (computed during indexing)
- ✅ Fixed `get_symbols` TOON missing `file_path`
- ✅ Copied skills from Julie to `.claude/skills/`

### 2025-11-24
- ✅ Tool audit complete - all 10 tools audited, 7 fixed, 3 excellent
- ✅ `fast_refs` now queries both tables
- ✅ `fast_explore` similar mode fixed
- ✅ Implemented re-ranker (cross-encoder)
- ✅ Implemented transitive closure table
- ✅ Implemented graph expansion on search
- ✅ Added `rename_symbol` tool

### 2025-11-23
- ✅ Deep review of startup/indexing
- ✅ Achieved parity with Julie + improvements
- ✅ Added `.millerignore` with smart vendor detection
- ✅ Added staleness detection
- ✅ Added Blake3 hashing in Rust

</details>
