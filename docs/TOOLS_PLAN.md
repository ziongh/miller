# Miller MCP Server - Tools Strategy & Implementation Plan

**Last Updated:** 2025-11-20
**Status:** 8/9 Tools Complete (89%) - Production Ready

---

## Vision: Semantic Code Intelligence for Polyglot Codebases

Miller is not a port of Julie - it's a **refinement and improvement** that leverages Python's ML/AI ecosystem to provide superior code intelligence for AI coding agents.

### Core Mission

Help AI coding agents **write correct code on the first try** by providing:
1. **Accurate API information** upfront (no guessing about signatures/parameters)
2. **Cross-language understanding** (trace calls across TypeScript → Python → SQL)
3. **Semantic search** (find code by what it does, not just what it's called)
4. **Token-efficient operations** (minimal context usage, maximum value)

### Primary Users

- **AI Coding Agents** (Claude Code, OpenAI Codex, GitHub Copilot, Gemini CLI)
- **Human Developers** (onboarding in legacy codebases, documentation generation)

---

## Miller's Differentiators

### What Sets Us Apart from LSP Tools

1. **Cross-Language Call Tracing**
   - LSP: Single-language only (TypeScript LSP can't see Python)
   - Miller: Traces across language boundaries using tree-sitter + naming variants + embeddings
   - Example: `IUser` (TypeScript) → `UserDto` (C#) → `User` (domain) → `users` (SQL table)

2. **Semantic Understanding**
   - LSP: Text-based search only
   - Miller: Embeddings understand "code that creates list of available nurses" conceptually

3. **No LSP Server Overhead**
   - LSP: Slow, brittle, requires language servers running
   - Miller: Direct tree-sitter parsing, fast, reliable

### What Python Enables (vs Julie in Rust)

1. **Superior ML/AI Libraries**
   - `sentence-transformers` - Better embedding models, easier to upgrade
   - `scikit-learn` - Clustering, semantic grouping
   - `torch` with GPU acceleration - Faster embedding generation

2. **Easier Integration with LLM Workflows**
   - Agents already use Python tooling
   - Better ecosystem for semantic analysis
   - Faster iteration on ML features

---

## Research-Backed Design Principles

### 1. "Less is More" (MCP Best Practice)

**Source:** Multiple MCP best practice guides (2025)

- **Finding:** Too many tools confuse agents and waste context tokens
- **Implication:** 15 tools is the maximum; Miller targets 8-10 tools
- **Evidence:** Users report MCPs with "dozens of tools" make agents confused

### 2. "MCPs as Data Gateways, Not Actions"

**Source:** MCP design patterns research

- **Finding:** Best MCPs provide high-quality data that agents script against
- **Implication:** Miller provides **code intelligence**, agents use built-in tools for editing
- **Example:** `get_symbols` provides API data, agent uses `Read`/`Write` for file operations

### 3. "Search/Replace > Line Editing"

**Source:** LLM editing format analysis, aider research

- **Finding:** Search/replace is efficient, line-based editing is brittle
- **Evidence:**
  - OpenAI recommends avoiding line numbers
  - GPT-4.1 specifically trained on search/replace format
  - Fuzzy matching handles context shifts better
  - Usage data: `search_and_replace` was top-5 tool in codesearch
- **Implication:** Build search/replace, skip line-based editing tools

### 4. "Agents Prefer Built-in Tools for Editing"

**Source:** Julie usage data

- **Finding:** Julie's editing tools (EditLines, FuzzyReplace, RenameSymbol, EditSymbol) rarely used
- **Evidence:** Agents fall back to Claude Code's built-in Edit tool
- **Implication:** Don't compete with built-in tools; provide what they can't get elsewhere

---

## Miller Toolset (8 Tools)

### Search & Navigation (4 tools)

#### 1. `fast_search` ✅ **IMPLEMENTED**

**Status:** Complete, production-ready
**Purpose:** Multi-mode search (text/semantic/hybrid/pattern)

**Why Essential:**
- Token-efficient discovery (find code without reading entire files)
- Semantic mode enables natural language queries ("authentication logic")
- Pattern mode for code idioms (`: BaseClass`, `ILogger<`)

**Usage Example:**
```python
# Find by concept, not just keywords
fast_search("code that validates user permissions", method="semantic")
```

---

#### 2. `get_symbols` ✅ **IMPLEMENTED**

**Status:** Complete, production-ready (better than Julie!)
**Priority:** HIGH (foundation for other tools) - COMPLETE

**Current State:**
- Reads file and extracts symbols using miller_core
- Returns name, kind, signature, location

**Missing from Julie:**
- Reading modes: `structure` (default), `minimal`, `full`
- Max depth control (0=top-level, 1=include methods, 2+=nested)
- Target filtering (partial matching)
- Limit parameter
- Body extraction (mode="full")
- Workspace filtering (primary vs reference)

**Why Essential:**
- Most valuable for agents ("What methods does this class have?")
- Prevents API guessing (agent sees signatures before coding)
- High usage in Julie
- Foundation for documentation workflows

**Usage Example:**
```python
# See class structure without reading entire file
get_symbols("src/services/userService.ts", target="UserService", max_depth=1)
# Returns: class structure, method signatures, no implementation details
```

**Implementation Plan:**
- Port Julie's get_symbols implementation
- Add reading modes (structure/minimal/full)
- Add depth control and filtering
- Test with various file sizes

---

#### 3. `fast_refs` ✅ **IMPLEMENTED**

**Status:** Complete, production-ready
**Priority:** HIGH (essential for refactoring safety) - COMPLETE

**Purpose:** Find all references/usages of a symbol

**Why Essential:**
- **Refactoring safety:** "If I change this function signature, what breaks?"
- **Impact analysis:** "Where is this API used?"
- **Complements trace_call_path:** (refs = breadth, trace = depth)

**Distinction from `trace_call_path`:**
- `fast_refs`: Shows ALL places a symbol is used (breadth)
- `trace_call_path`: Shows call chains/execution flow (depth)
- Both needed: refs for "where used?", trace for "how does it flow?"

**Usage Example:**
```python
# Before refactoring calculateAge():
fast_refs("calculateAge")
# Returns: All call sites (files, line numbers, context)
# Agent sees: "This is called in 12 places, 3 different files"
```

**Implementation Plan:**
- Query symbol_relationships table (already populated during indexing)
- Filter by relationship_kind = "Reference" or "Call"
- Return file_path, line_number, context snippet
- Support workspace filtering

---

#### 4. `trace_call_path` ✅ **IMPLEMENTED** 🔥

**Status:** Complete, production-ready, battle-tested
**Priority:** HIGH (Miller's killer differentiator) - COMPLETE

**Purpose:** Trace execution flow across language boundaries

**Why This Is The Killer Feature:**
- **Unique:** LSP tools can't do this (language-specific)
- **Cross-language:** TypeScript → Python → SQL (naming variants + embeddings)
- **Polyglot understanding:** Essential for modern full-stack codebases
- **User validation:** "This is what sets Julie apart"

**How It Works:**
1. **Naming variants** - Generate all naming conventions:
   - `IUser` → `i_user` (snake_case), `iUser` (camelCase), `I_USER` (SCREAMING), etc.
2. **Cross-language matching** - Find symbols with matching variants in different languages
3. **Semantic similarity** - Use embeddings for conceptual matches
4. **Relationship traversal** - Follow calls/references across files/languages

**Example Use Case:**
```
Query: trace_call_path("IUser", direction="downstream")

Result:
  TypeScript: IUser (interface)
    ↓ (naming variant: IUser → i_user)
  Python API: i_user (function parameter)
    ↓ (naming variant: i_user → UserDto)
  C# Backend: UserDto (class)
    ↓ (naming variant: UserDto → User)
  Domain: User (entity)
    ↓ (naming variant: User → users)
  SQL: users (table)
```

**Parameters:**
- `symbol`: Symbol name to trace
- `direction`: "upstream" (callers), "downstream" (callees), "both"
- `max_depth`: 1-10 (default 3)
- `context_file`: Disambiguate symbols
- `output_format`: "json" or "tree"

**Implementation Plan:**
- Port Julie's trace_call_path module
- Implement naming variant generation (snake, camel, pascal, kebab, screaming)
- Query relationships table with variant matching
- Add semantic similarity fallback using embeddings
- Test with real polyglot codebases (TS/Python/SQL)

---

### Editing (1 tool)

#### 5. `search_and_replace` ❌ **NOT IMPLEMENTED**

**Status:** Not started
**Priority:** MEDIUM (proven usage, but agents handle editing well)

**Purpose:** Fuzzy search/replace for safe refactoring

**Why This (and Only This) Editing Tool:**
- **Proven usage:** Top-5 tool in codesearch MCP
- **Superior format:** Search/replace > line editing (research-backed)
- **Fuzzy matching:** Handles context shifts robustly
- **LLM training:** GPT-4.1 specifically trained on this format

**Why NOT Other Editing Tools:**
- Julie's line-based editing tools (EditLines, FuzzyReplace, RenameSymbol, EditSymbol) rarely used
- Agents prefer built-in Edit tool
- Line numbers are brittle, accuracy issues

**Format:**
```
<<<<<<< SEARCH
function calculateAge(birthdate) {
    return 2025 - birthdate.year;
}
=======
function calculateAge(birthdate: Date): number {
    const now = new Date();
    return now.getFullYear() - birthdate.getFullYear();
}
>>>>>>> REPLACE
```

**Features:**
- Fuzzy matching (handles minor whitespace differences)
- No line numbers required
- Only returns changed sections (token-efficient)
- Multiple replacements in one operation

**Implementation Plan:**
- Implement fuzzy string matching (difflib or similar)
- Support multiple search/replace blocks
- Return diff output for verification
- Add safety checks (no match, multiple matches)

---

### Workspace (1 tool)

#### 6. `manage_workspace` ✅ **IMPLEMENTED**

**Status:** Complete, production-ready
**Purpose:** Workspace operations (index, list, stats, add, remove, refresh, clean, health)

**Operations:**
- `index` - Index current or specified workspace
- `list` - Show all registered workspaces
- `stats` - Workspace statistics
- `add` - Add reference workspace
- `remove` - Remove workspace
- `refresh` - Re-index workspace
- `clean` - Clean up orphaned data
- `health` - System health check

**Why Essential:**
- Multi-workspace support (primary + reference libraries)
- Background indexing management
- Performance monitoring

---

### Memory System (3 tools)

#### 7-9. `checkpoint`, `recall`, `plan` ✅ **IMPLEMENTED**

**Status:** Complete, production-ready
**Purpose:** Development memory and task tracking

**Why Essential:**
- Persistent context across sessions
- Decision tracking
- Learning capture
- Mutable task plans

**Usage Patterns:**
- `checkpoint` - Save development memories (decisions, learnings, observations)
- `recall` - Retrieve memories (time-based, type-based, tag-based)
- `plan` - Mutable task tracking (save, get, list, activate, update, complete)

---

## Documented Workflows (Not Tools)

### Documentation Generation Workflow

**Decision:** Don't build a dedicated `generate_docs` tool

**Rationale:**
- Agents are already excellent at writing documentation
- They just need the right context (which our tools provide)
- Dedicated tool would be opinionated about doc format
- Workflow is more flexible, adapts to project style

**Recommended Workflow:**

```markdown
## Generating High-Quality Documentation

1. **Get symbol details:**
   get_symbols(file_path, target=symbol_name, mode="full")
   → Returns: signature, parameters, types, existing docs

2. **Find similar well-documented examples:**
   fast_search("well documented {similar_concept}", method="semantic")
   → Returns: Examples from codebase with good documentation

3. **Analyze usage patterns:**
   fast_refs(symbol_name)
   → Returns: How the symbol is actually used in the codebase

4. **Write documentation using context from steps 1-3**
   → Agent synthesizes docs matching project's style
```

**What Miller Provides:**
- Semantic search to find well-documented examples
- Symbol metadata (parameters, types, signatures)
- Usage patterns (via fast_refs)

**What Agent Does:**
- Synthesizes documentation using that context
- Matches project's doc style (JSDoc, Sphinx, GoDoc, etc.)
- Writes clear, helpful docs

---

## Implementation Priorities

### Phase 1: Complete Navigation Suite (CURRENT)

**Goal:** Provide complete, accurate code navigation

1. **Complete `get_symbols`** (HIGH PRIORITY)
   - Port Julie's implementation
   - Add modes, filtering, depth control
   - Foundation for other tools

2. **Implement `fast_refs`** (HIGH PRIORITY)
   - Essential for refactoring safety
   - Query relationships table
   - Simpler than trace_call_path

3. **Implement `trace_call_path`** (HIGH PRIORITY)
   - The killer differentiator
   - Cross-language call tracing
   - Naming variants + semantic matching

**Success Criteria:**
- Agent can explore unfamiliar codebase without reading entire files
- Agent can safely refactor (knows impact via fast_refs)
- Agent can trace execution across language boundaries

---

### Phase 2: Editing Support

4. **Implement `search_and_replace`** (MEDIUM PRIORITY)
   - Proven usage pattern
   - Fuzzy matching for robustness
   - Token-efficient (only changed code)

**Success Criteria:**
- Agent can safely refactor code with fuzzy matching
- Works with large files
- Handles minor context shifts

---

### Phase 3: Advanced Semantic Features (FUTURE)

**Potential Enhancements:**

1. **Semantic Clustering** (get_symbols enhancement)
   - Group related functions by semantic similarity
   - "Show me all authentication-related functions"

2. **Pattern Detection** (fast_search enhancement)
   - Find similar code patterns across languages
   - "Find all API endpoints that don't have rate limiting"

3. **Enhanced Cross-Language Matching** (trace_call_path enhancement)
   - Better semantic similarity using sklearn
   - Confidence scores for matches

**These are speculative - validate with usage data first.**

---

## Tools We're NOT Building

### From Julie (Low/No Usage)

1. **EditLines** - Line-based editing (brittle, agents prefer built-in Edit)
2. **RenameSymbol** - Workspace-wide renaming (brittle, low usage)
3. **EditSymbol** - Symbol-level editing (low usage)
4. **FindLogic** - Superseded by FastExplore (which we're also skipping)
5. **FastExplore** - Multi-mode exploration (overlaps with search, unproven value)

**Rationale:**
- Agents prefer built-in editing tools
- Line numbers are brittle
- Focus on what we do uniquely well (code intelligence, not editing)

### Fast Goto - Questionable Value

**Decision:** TBD - May skip entirely

**Reasoning:**
- `get_symbols` + `Read` tool provides same functionality
- Agent doesn't need "goto" - just needs file path and line number
- Built-in Read tool handles file access
- Fast refs + get_symbols might be sufficient

**We'll validate this with early users.**

---

## Success Metrics

### Agent Efficiency

- **Time to first correct code** - Reduced by 50% (no API guessing)
- **Rewrites per feature** - Down from 3x to 1x (accurate info upfront)
- **Tokens used** - 30% reduction (token-efficient tools)

### Human Developer Onboarding

- **Time to understand legacy codebase** - Reduced by 60%
- **Documentation coverage** - Improved with semantic search workflow

### Cross-Language Navigation

- **Successful traces across 3+ languages** - Unique capability, no comparison

---

## Open Questions & Future Research

### 1. Agent Tool Usage Patterns

**Question:** What tools do agents actually use most frequently?

**Action:** Instrument Miller with usage logging (anonymized)
- Track: Tool calls, parameters, success/failure
- Analyze: Which tools provide most value
- Iterate: Double down on high-value tools, deprecate low-usage

### 2. Semantic Search Quality

**Question:** How good are our semantic matches?

**Action:** Qualitative testing with real codebases
- Test: "Find authentication code" queries
- Measure: Relevance of top-10 results
- Improve: Tune embedding model, adjust ranking

### 3. Cross-Language Naming Variants

**Question:** Do our naming variants cover real-world conventions?

**Action:** Analyze popular polyglot codebases
- Languages: TypeScript, Python, Go, Rust, Java, C#, SQL
- Patterns: REST APIs, GraphQL, gRPC, database models
- Coverage: Measure match rate with current variants

### 4. Fast Goto Value

**Question:** Do agents actually need fast_goto, or is get_symbols + Read sufficient?

**Action:** Build without it, validate with early users
- If requested, implement
- If not requested after 3 months, skip it

---

## References

### Research Sources

1. **MCP Best Practices (2025)**
   - "Less is More" - Tool count limits
   - "Data Gateways" - MCPs provide data, not actions
   - Source: MCP documentation, MarkTechPost analysis

2. **LLM Editing Format Analysis**
   - Search/replace > line editing
   - OpenAI recommendations
   - Source: aider documentation, Codex CLI research

3. **Julie Usage Data**
   - Editing tools: Low usage
   - Search tools: High usage
   - search_and_replace: Top-5 in codesearch
   - Source: Real-world usage metrics

### Related Documentation

- **PLAN.md** - Original migration plan (Julie → Miller)
- **CLAUDE.md** - Project instructions and TDD guidelines
- **README.md** - User-facing documentation

---

## Changelog

### 2025-11-19 - Initial Strategy Document

- Documented tool strategy based on research
- Defined 8-tool target (down from Julie's 15)
- Prioritized cross-language tracing as differentiator
- Decided against dedicated generate_docs tool (workflow instead)
- Established research-backed design principles

---

**Next Steps:**
1. Create implementation plan using `plan` tool
2. Start with `get_symbols` completion (foundation)
3. Implement `fast_refs` (refactoring safety)
4. Implement `trace_call_path` (killer feature)
