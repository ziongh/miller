# Miller Tool Audit Checklist

*Created: 2025-11-23*
*Based on: Julie Tool Audit (2025-11-11)*

## Purpose

This document establishes a systematic framework for auditing all Miller MCP tools to ensure each tool:

1. **Leverages Miller's unique capabilities** (semantic search, re-ranker, transitive closure, graph expansion)
2. **Uses optimal defaults** for all parameters (smart defaults = less cognitive load)
3. **Has lean output formats** (text default, optional json/toon for programmatic use)
4. **Provides excellent behavioral adoption** (guides agents to use tools correctly)
5. **Avoids parameter exposure that causes iteration** (hardcoded thresholds where appropriate)
6. **Minimizes token usage** in both tool descriptions and output
7. **Maintains clear separation of concerns** (no redundancy with other tools)

---

## Context: Miller's Unique Capabilities

**What Miller Has That Julie Doesn't:**
- ✅ **Re-ranker** (cross-encoder): Improves search relevance 15-30%
- ✅ **Transitive closure table**: O(1) reachability queries
- ✅ **Graph expansion**: Search results include callers/callees
- ✅ **TOON format**: 30-60% token reduction for structured output
- ✅ **Python flexibility**: Easier to iterate on tool improvements

**Core Philosophy:** Return *understanding*, not just *locations*.

---

## Tool Inventory

### Search & Discovery
| Tool | Priority | Status |
|------|----------|--------|
| `fast_search` | P1 | 🔄 Audit needed |
| `fast_explore` | P3 | 🔄 Audit needed |

### Navigation
| Tool | Priority | Status |
|------|----------|--------|
| `fast_goto` | P2 | 🔄 Audit needed |
| `fast_refs` | P2 | 🔄 Audit needed |
| `trace_call_path` | P2 | 🔄 Audit needed |
| `get_symbols` | P2 | 🔄 Audit needed |

### Memory System
| Tool | Priority | Status |
|------|----------|--------|
| `checkpoint` | P2 | 🔄 Audit needed |
| `recall` | P2 | 🔄 Audit needed |
| `plan` | P2 | 🔄 Audit needed |

### Workspace Management
| Tool | Priority | Status |
|------|----------|--------|
| `manage_workspace` | P3 | 🔄 Audit needed |

---

## Audit Framework

For each tool, evaluate against these 7 dimensions:

### 1. API Design & Smart Defaults

**Checklist:**
- [ ] All optional parameters have smart defaults
- [ ] Required parameters are truly required
- [ ] Defaults optimize for 80% use case
- [ ] workspace parameter defaults to "primary" (not None requiring explicit value)
- [ ] limit/count parameters have sensible defaults (10-50 depending on use case)
- [ ] No exposed thresholds that agents might iterate through
- [ ] Parameters that can be inferred from context ARE inferred

**Anti-patterns to avoid:**
```python
# BAD: Exposed threshold invites iteration
similarity_threshold: float = 0.7  # Agent will try 0.9, 0.8, 0.7...

# GOOD: Hardcoded internally
# Threshold is 0.7 internally, not exposed as parameter
```

**Parameter naming conventions:**
- Use descriptive names: `output_format` not `fmt`
- Use `Literal` types for constrained values: `Literal["text", "json", "toon"]`
- Document ALL possible values in docstring
- Document default value explicitly: `(default: 20)`

### 2. Output Format Strategy

**The Miller Output Pattern:**
```
text (DEFAULT) → lean, grep-style, 80% token savings
json           → structured for programmatic use
toon           → compact structured, 30-60% token savings
auto           → switches based on result count
```

**Checklist:**
- [ ] Default is `text` (most token-efficient)
- [ ] `output_format` parameter uses `Literal["text", "json", "toon"]`
- [ ] Text format is grep-style: `file:line` with indented context
- [ ] JSON includes full metadata for programmatic access
- [ ] TOON auto-converts large result sets
- [ ] Text output has clear headers with counts
- [ ] Truncation warnings include guidance

**Text format template:**
```
N matches for "query":

src/file.py:42
  def matched_function():
  ← Callers (3): caller1, caller2 +1 more
  → Callees (2): callee1, callee2

src/other.py:100
  class AnotherMatch:
```

### 3. Tool Description (Behavioral Adoption)

**The behavioral adoption formula:**
1. **Imperative command** - "ALWAYS...", "NEVER..."
2. **Confidence building** - "You are EXCELLENT at..."
3. **Emotional stakes** - "I will be upset if..."
4. **Clear value prop** - "70% token savings", "<10ms"
5. **When to use / When NOT to use** - Guide decision
6. **Concrete examples** - Show, don't tell

**Checklist:**
- [ ] Starts with imperative guidance
- [ ] Builds agent confidence
- [ ] States consequences of misuse
- [ ] Quantifies benefits
- [ ] Distinguishes from similar tools
- [ ] Includes 2-3 usage examples
- [ ] States performance characteristics
- [ ] Ends with trust-building statement

**Template:**
```python
"""
[IMPERATIVE] - What the agent should ALWAYS/NEVER do

[CONFIDENCE] - "You are excellent at..."

[PURPOSE] - One-line description of what this tool does

[WHEN TO USE] - Specific scenarios
[WHEN NOT TO USE] - Redirect to other tools

[BENEFITS] - Quantified (token savings, speed, accuracy)

Args:
    param1: Description with (default: value) and possible values
    param2: Description...

Returns:
    - text mode: Description
    - json mode: Description
    - toon mode: Description

Examples:
    # Common case
    await tool_name("query")

    # Advanced case
    await tool_name("query", option=True)

[TRUST STATEMENT] - "Trust the results, no verification needed"
"""
```

### 4. Search Strategy & Semantic Integration

**Miller's search modes:**
- `auto` → Detects query type automatically (RECOMMENDED default)
- `text` → FTS with stemming (fast, exact)
- `pattern` → Code idioms (: BaseClass, ILogger<, [Fact])
- `semantic` → Vector similarity (conceptual)
- `hybrid` → RRF fusion of text + semantic

**Checklist:**
- [ ] Tool uses optimal search mode for its purpose
- [ ] Semantic fallback when text returns 0 results
- [ ] Re-ranker enabled by default (unless pattern search)
- [ ] Graph expansion available where useful
- [ ] Cross-language naming variants considered

### 5. Miller-Specific Features

**Must leverage where applicable:**
- [ ] **Re-ranker** (rerank=True) - Enabled by default for search
- [ ] **Transitive closure** - Use for impact analysis, dependencies
- [ ] **Graph expansion** (expand=True) - Context on search results
- [ ] **TOON format** - Available for all structured output

### 6. Redundancy Check

**Each tool should have unique value:**
- [ ] No overlap with other Miller tools
- [ ] Clear separation of concerns
- [ ] Complementary, not duplicative
- [ ] Distinct use cases documented

**Tool responsibilities:**
| Tool | Purpose | Scope |
|------|---------|-------|
| `fast_search` | Find code by content/semantics | Workspace-wide |
| `fast_goto` | Find symbol definition | Workspace-wide |
| `fast_refs` | Find symbol usages | Workspace-wide |
| `get_symbols` | Show file structure | Single file |
| `trace_call_path` | Trace execution flow | Workspace-wide |
| `fast_explore` | Type/similarity/dependency analysis | Workspace-wide |

### 7. Token Efficiency

**Tool description token budget:**
- Aim for <500 tokens per tool description
- Trim redundant explanations
- Use examples sparingly but effectively
- Don't repeat information available in return type

**Checklist:**
- [ ] Tool description is concise but complete
- [ ] Examples are minimal but illustrative
- [ ] No verbose output mode by default
- [ ] Large results auto-truncate with guidance

---

## Per-Tool Audit Template

Copy this for each tool audit:

```markdown
## [Tool Name] - Priority [P1/P2/P3]

### Current State Analysis
- **Purpose**: [What does this tool do?]
- **Search Strategy**: [text/semantic/hybrid/none]
- **Default Output**: [text/json/toon]
- **Token Efficiency**: [Estimate]

### Parameters Review
| Parameter | Default | Smart? | Notes |
|-----------|---------|--------|-------|
| param1    | value   | ✅/⚠️/❌ | ... |

### Behavioral Adoption Review
- [ ] Imperative command present
- [ ] Confidence building present
- [ ] Emotional stakes present
- [ ] Clear value proposition
- [ ] When to use / not use
- [ ] Examples included
- [ ] Performance stated
- [ ] Trust statement present

### Output Format Review
- [ ] Text is default
- [ ] Text format is grep-style
- [ ] JSON available
- [ ] TOON available
- [ ] Auto-switch implemented
- [ ] Truncation handled

### Miller-Specific Features
- [ ] Re-ranker used where applicable
- [ ] Graph expansion used where applicable
- [ ] Transitive closure used where applicable
- [ ] TOON format available

### Findings
#### Strengths ✅
1. ...

#### Issues ⚠️
1. ...

#### Recommendations
**Priority**: HIGH/MEDIUM/LOW
1. ...

### Final Verdict
**Status**: ✅ EXCELLENT / ⚠️ NEEDS WORK / ❌ CRITICAL ISSUES
**Confidence**: X%
```

---

## Audit Execution Plan

### Phase 1: Priority 1 Tools
1. `fast_search` - Crown jewel, most used

### Phase 2: Priority 2 Tools
2. `fast_goto` - Navigation essential
3. `fast_refs` - Refactoring critical
4. `get_symbols` - File exploration
5. `trace_call_path` - Architecture understanding
6. `checkpoint` - Memory creation
7. `recall` - Memory retrieval
8. `plan` - Task management

### Phase 3: Priority 3 Tools
9. `fast_explore` - Advanced exploration
10. `manage_workspace` - Admin operations

---

## Key Learnings from Julie

### What Julie Got Right (Copy These)
1. **Three-stage CASCADE**: exact → variants → semantic fallback
2. **INTENTIONALLY HARDCODED thresholds**: Prevents agent iteration
3. **Behavioral adoption language**: Confidence-building, imperative
4. **Smart Read modes**: structure/minimal/full for get_symbols
5. **Context-aware prioritization**: context_file, line_number hints
6. **Token-efficient output**: Minimal text + rich structured

### What Miller Can Do Better
1. **Re-ranker by default**: Julie doesn't have this
2. **Graph expansion**: Show callers/callees on search results
3. **Transitive closure**: O(1) impact analysis
4. **TOON format**: More compact than Julie's output
5. **Python flexibility**: Easier to add features

---

## Success Metrics

After audit completion, each tool should:
- [ ] Have all 7 dimensions ✅
- [ ] Default to text output
- [ ] Use smart defaults for all optional params
- [ ] Have <500 token description
- [ ] Leverage at least one Miller-specific feature
- [ ] Pass behavioral adoption checklist

---

## Appendix: Common Refactoring Patterns

### Adding output_format Parameter
```python
# Before
async def tool(query: str) -> list[dict]:
    results = get_results(query)
    return results

# After
from typing import Literal, Union

async def tool(
    query: str,
    output_format: Literal["text", "json", "toon"] = "text"
) -> Union[list[dict], str]:
    results = get_results(query)

    if output_format == "text":
        return format_as_text(results)
    elif output_format == "toon":
        from miller.toon_types import encode_toon
        return encode_toon(results)
    else:  # json
        return results
```

### Adding Smart workspace Default
```python
# Before
workspace: Optional[str] = None  # Requires explicit value

# After
workspace: str = "primary"  # Smart default, can be overridden
```

### Hardcoding Thresholds
```python
# Before (exposed - bad)
async def search(query: str, threshold: float = 0.7) -> list:
    # Agent will try 0.9, 0.8, 0.7, 0.6... wasting tool calls

# After (hardcoded - good)
async def search(query: str) -> list:
    # INTENTIONALLY HARDCODED: 0.7 is optimal based on testing
    # Exposing this would cause agents to iterate through values
    SIMILARITY_THRESHOLD = 0.7
    ...
```
