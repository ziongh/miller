# Miller Search Tool Design
**Date**: 2025-11-18
**Status**: Decision Needed

---

## The Question

Now that we know **how** to do pattern search (whitespace tokenizer + phrase search), we need to decide **what tools** to expose.

**Core tension**: Balance between:
- **Simplicity** (few tools, easy to remember)
- **Clarity** (obvious what each tool does)
- **Power** (advanced use cases possible)

---

## Comparison: Julie vs COA CodeSearch

### Julie's Approach: Single Tool with Methods

**Tool**: `fast_search(query, method="text|semantic|hybrid")`

```rust
// Julie's design (src/tools/search/mod.rs):
@tool fast_search {
    query: String,
    method: "text" | "semantic" | "hybrid" (default: "hybrid")
}
```

**User experience**:
```
fast_search("authentication", method="text")      # FTS only
fast_search("user auth logic", method="semantic") # Vector only
fast_search("TODO fix bug", method="hybrid")      # Both (default)
```

**Pros**:
- ✅ Single tool to learn
- ✅ Method is explicit (no guessing)
- ✅ Easy to document ("use method=X for Y")

**Cons**:
- ❌ No code pattern search (Julie's limitation)
- ❌ Users must choose method every time
- ❌ `method` parameter adds cognitive load

---

### COA CodeSearch: Multiple Specialized Tools

**Tools**:
- `text_search()` - Full-text (Lucene)
- `symbol_search()` - Exact symbol names
- `line_search()` - Line-by-line (like grep)
- Semantic is Tier 3 fallback (not a separate tool)

```csharp
// COA's design (Tools/TextSearchTool.cs, SymbolSearchTool.cs):
text_search(query, searchMode="auto|exact|fuzzy|regex")
symbol_search(symbol_name)
line_search(query, context_lines=3)
```

**User experience**:
```
text_search("class UserService")           # General code search
symbol_search("UserService")               # Find exact symbol
line_search("TODO", context_lines=5)       # Grep-style
```

**Pros**:
- ✅ Clear intent (tool name tells you what it does)
- ✅ Each tool can have focused parameters
- ✅ Can optimize each tool independently

**Cons**:
- ❌ More tools to remember (14 total in COA!)
- ❌ Overlap between tools (when to use which?)
- ❌ Documentation burden (explain all tools)

---

## Miller's Requirements

Based on our research, we need to support:

1. **Text search** - Standard FTS with stemming (current)
2. **Pattern search** - Code idioms (NEW - requires phrase wrapping)
3. **Semantic search** - Vector similarity (current)
4. **Hybrid search** - Combined RRF (current)

**Key constraint**: Pattern search requires different handling (phrase wrapping)

---

## Design Options for Miller

### **Option A: Julie's Model + Pattern Mode**

**Single tool with modes**:

```python
fast_search(
    query: str,
    method: "text" | "pattern" | "semantic" | "hybrid" = "hybrid"
)
```

**Implementation**:
```python
def fast_search(query: str, method: str = "hybrid", limit: int = 50):
    if method == "pattern":
        # Auto-wrap in quotes for phrase search
        query = f'"{query}"'
        return vector_store.search(query, method="text", limit=limit)
    elif method == "text":
        # Standard FTS (stemming)
        return vector_store.search(query, method="text", limit=limit)
    elif method == "semantic":
        # Vector similarity
        return vector_store.search(query, method="semantic", limit=limit)
    else:  # hybrid
        return vector_store.search(query, method="hybrid", limit=limit)
```

**User experience**:
```python
# General search (default hybrid)
fast_search("authentication logic")

# Code pattern search
fast_search(": BaseClass", method="pattern")
fast_search("ILogger<", method="pattern")

# Semantic only
fast_search("user authorization", method="semantic")
```

**Pros**:
- ✅ Single tool (simple)
- ✅ Explicit mode selection (no guessing)
- ✅ Easy to extend (add more modes later)
- ✅ Pattern mode clearly signals "special handling"

**Cons**:
- ⚠️ Users must remember to use `method="pattern"` for code idioms
- ⚠️ Mode parameter on every call (verbose)
- ⚠️ What if user searches for `: BaseClass` in text mode? (silently fails)

**Verdict**: **Good baseline, but mode selection burden is high**

---

### **Option B: Separate Code Pattern Tool**

**Two search tools**:

```python
# General search (smart hybrid)
fast_search(
    query: str,
    method: "text" | "semantic" | "hybrid" = "hybrid"
)

# Code pattern search (NEW)
search_code_patterns(
    pattern: str,  # Auto-wrapped in quotes
    limit: int = 50
)
```

**Implementation**:
```python
def fast_search(query: str, method: str = "hybrid", limit: int = 50):
    # Standard search (no special handling)
    return vector_store.search(query, method=method, limit=limit)

def search_code_patterns(pattern: str, limit: int = 50):
    # Auto-wrap for phrase search
    query = f'"{pattern}"'
    # Use pattern field with whitespace tokenizer
    return vector_store.search_patterns(query, limit=limit)
```

**User experience**:
```python
# General search
fast_search("authentication logic")                  # Hybrid
fast_search("TODO fix bug", method="text")          # Text only
fast_search("user auth", method="semantic")         # Semantic only

# Code pattern search (separate tool)
search_code_patterns(": BaseClass")                 # Auto-wrapped
search_code_patterns("ILogger<")                    # Auto-wrapped
search_code_patterns("[Fact]")                      # Auto-wrapped
```

**Pros**:
- ✅ Clear separation of concerns
- ✅ Pattern search is obvious (tool name says it)
- ✅ No mode confusion (tool = intent)
- ✅ Can optimize each independently

**Cons**:
- ⚠️ Two tools instead of one
- ⚠️ Users must know which tool to use
- ⚠️ Documentation needs to explain both

**Verdict**: **Clean, explicit, but adds a tool**

---

### **Option C: Smart Auto-Detection**

**Single tool with smart routing**:

```python
fast_search(
    query: str,
    method: "auto" | "text" | "pattern" | "semantic" | "hybrid" = "auto"
)
```

**Implementation**:
```python
def fast_search(query: str, method: str = "auto", limit: int = 50):
    # Auto-detect pattern queries
    if method == "auto":
        if is_pattern_query(query):  # Has : < > [ ] ( )
            method = "pattern"
            query = f'"{query}"'  # Auto-wrap
        else:
            method = "hybrid"  # Default to hybrid

    # Route to appropriate search
    if method == "pattern":
        query = f'"{query}"' if not query.startswith('"') else query
        return vector_store.search_patterns(query, limit=limit)
    else:
        return vector_store.search(query, method=method, limit=limit)

def is_pattern_query(query: str) -> bool:
    """Detect if query looks like code pattern."""
    pattern_chars = [':', '<', '>', '[', ']', '(', ')', '{', '}']
    return any(ch in query for ch in pattern_chars)
```

**User experience**:
```python
# Auto-detection (default)
fast_search(": BaseClass")           # Auto-detects pattern, auto-wraps
fast_search("ILogger<")              # Auto-detects pattern
fast_search("authentication logic")  # Auto-detects text/hybrid

# Manual override when needed
fast_search("map<string, int>", method="text")  # Force text (not pattern)
```

**Pros**:
- ✅ Single tool (simplest API)
- ✅ No mode selection burden (works automatically)
- ✅ Power users can override with `method=`
- ✅ Best of both worlds

**Cons**:
- ⚠️ "Magic" behavior (surprises users)
- ⚠️ What if detection is wrong? (e.g., `:` in text)
- ⚠️ Less explicit (harder to predict behavior)

**Verdict**: **Most ergonomic, but hides complexity**

---

### **Option D: COA Model (Multiple Specialized Tools)**

**Three search tools**:

```python
# Text search (FTS with stemming)
text_search(
    query: str,
    mode: "standard" | "fuzzy" | "exact" = "standard"
)

# Code search (pattern-preserving)
code_search(
    pattern: str  # Auto-wrapped for phrase search
)

# Semantic search (vector similarity)
semantic_search(
    query: str
)

# Note: No "fast_search" - users choose the right tool
```

**User experience**:
```python
# Text search for general queries
text_search("authentication logic")
text_search("TODO", mode="fuzzy")

# Code search for patterns
code_search(": BaseClass")
code_search("ILogger<")

# Semantic for concepts
semantic_search("user authorization flow")
```

**Pros**:
- ✅ Crystal clear intent (tool name = what it does)
- ✅ No mode confusion (each tool is focused)
- ✅ Easy to document (one tool = one purpose)
- ✅ Matches COA's proven design

**Cons**:
- ❌ Three tools to remember
- ❌ No hybrid search (have to call multiple tools)
- ❌ More documentation burden

**Verdict**: **Clearest intent, but removes hybrid convenience**

---

## Recommendation Matrix

| Criteria | Option A (Modes) | Option B (Separate) | Option C (Auto) | Option D (Multiple) |
|----------|------------------|---------------------|-----------------|---------------------|
| **Simplicity** | 🟡 1 tool, complex API | 🟡 2 tools, simple APIs | 🟢 1 tool, simple API | 🔴 3 tools |
| **Clarity** | 🟡 Mode names | 🟢 Tool names | 🔴 Hidden magic | 🟢 Tool names |
| **Discoverability** | 🟡 Must read docs | 🟢 Obvious from name | 🟢 Just works | 🟡 Must know all tools |
| **Control** | 🟢 Explicit | 🟢 Explicit | 🟡 Override available | 🟢 Explicit |
| **Maintenance** | 🟢 Single tool | 🟢 Two focused tools | 🟡 Detection logic | 🔴 Three tools |
| **User Burden** | 🔴 Choose mode | 🟡 Choose tool | 🟢 No choice | 🔴 Choose tool |

---

## My Recommendation: **Option B** (Separate Code Pattern Tool)

**Why**:
1. **Clear intent** - `search_code_patterns()` is obvious
2. **No surprises** - Explicit beats implicit
3. **Focused tools** - Each does one thing well
4. **Easy to extend** - Can add more specialized tools later
5. **COA validation** - Similar to their proven design

**API Design**:
```python
# Primary search tool (keeps current behavior)
fast_search(
    query: str,
    method: "text" | "semantic" | "hybrid" = "hybrid",
    limit: int = 50
) -> List[Dict]

# New: Code pattern search
search_code_patterns(
    pattern: str,  # E.g., ": BaseClass", "ILogger<", "[Fact]"
    limit: int = 50
) -> List[Dict]
```

**Tool descriptions** (for MCP):
```python
fast_search.__doc__ = """
Search codebase using text (FTS) or semantic (vector) methods.

Use this for:
- General code search: "authentication logic"
- TODO/FIXME comments: "TODO fix"
- Natural language: "user authorization flow"

For code patterns (: < > [ ]), use search_code_patterns() instead.
"""

search_code_patterns.__doc__ = """
Search for code-specific patterns and idioms.

Use this for:
- Inheritance: ": BaseClass"
- Generic types: "ILogger<", "IEnumerable<"
- Attributes: "[Fact]", "[Test]"
- Operators: "?.", "=>", "::"

This tool preserves special characters for exact pattern matching.
"""
```

**Migration path**:
- Phase 1: Add `search_code_patterns()` (NEW)
- Phase 2: Update `fast_search()` docs to mention patterns
- Phase 3: (Optional) Add auto-detection later if users want it

---

## Alternative: **Option C** (Auto-Detection) If You Want Simplicity

If you prioritize "just works" over explicitness:

```python
fast_search(
    query: str,
    method: "auto" | "text" | "pattern" | "semantic" | "hybrid" = "auto",
    limit: int = 50
)

# 90% of calls: just query (auto-detects everything)
fast_search(": BaseClass")          # Auto: pattern
fast_search("authentication")       # Auto: hybrid
fast_search("ILogger<")             # Auto: pattern

# 10% of calls: override when auto-detection wrong
fast_search("map<int>", method="text")  # Force text (not pattern)
```

This is **more ergonomic** but **less predictable**.

---

## Questions to Decide

1. **How often will agents search for code patterns?**
   - Often (>20%) → Separate tool makes sense
   - Rarely (<5%) → Mode parameter is fine

2. **Do you want "magic" or "explicit"?**
   - Magic (auto-detection) → Option C
   - Explicit (user chooses) → Option B

3. **How many tools is too many?**
   - 2 tools OK → Option B
   - 3+ tools too many → Option A or C

4. **What's your philosophy?**
   - "Make common things easy" → Option C (auto)
   - "Make all things explicit" → Option B (separate tools)
   - "Keep it simple" → Option A (modes)

---

## Next Steps

1. **Decide on tool design** (A, B, C, or D)
2. **Prototype the API** (write tool signatures + docs)
3. **Get user feedback** (dogfood it yourself)
4. **Implement** (9-12 hours based on POC)

**Don't rush this decision** - tool design is hard to change later.

---

**End of Document**
