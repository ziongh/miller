---
name: explore-codebase
description: Autonomously explore unfamiliar codebases using Miller's code intelligence. Use semantic search, symbol navigation, and call path tracing to understand architecture without reading entire files. Activates when user asks to understand, explore, or learn about a codebase.
allowed-tools: mcp__miller__fast_search, mcp__miller__get_symbols, mcp__miller__fast_refs, mcp__miller__trace_call_path, mcp__miller__fast_explore
---

# Explore Codebase Skill

## Purpose
Understand unfamiliar codebases **efficiently** using Miller's code intelligence without reading entire files. This skill uses **semantic search**, **symbol navigation**, and **execution flow tracing** to build a mental model of the code.

## When to Activate
Use when the user:
- **Wants to understand code**: "how does authentication work?", "explain the architecture"
- **Needs to find something**: "where is error handling?", "find the database layer"
- **Explores new codebase**: "I'm new to this project", "help me understand this code"
- **Investigates functionality**: "how does X feature work?", "trace this execution flow"

## Miller's Code Intelligence Tools

### Search & Discovery

**fast_search** - Semantic + text search
```
method: "semantic" - Understands intent ("find authentication logic")
method: "text" - Fast text search ("find all imports")
method: "pattern" - Code idioms (": BaseClass", "[Fact]")
```

**fast_explore** - Multi-mode exploration
```
mode: "types" - Type intelligence (implementations, hierarchy)
mode: "similar" - Semantic duplicate detection
```

### Symbol Understanding

**get_symbols** - File structure overview (70-90% token savings!)
```
mode: "structure" - High-level overview (classes, functions, imports)
mode: "full" - Complete symbol details with code bodies
mode: "minimal" - Top-level symbols only
```

**Key benefit:** See file structure WITHOUT reading entire file!

### Navigation

**fast_refs** - Find all references
```
See everywhere a symbol is used
REQUIRED before modifying any symbol
```

### Execution Flow Tracing

**trace_call_path** - Cross-language call graphs
```
direction: "upstream" - What calls this? (callers)
direction: "downstream" - What does this call? (callees)
direction: "both" - Full call graph
```

**Unique feature:** Traces across language boundaries!

## Orchestration Strategy

### Pattern 1: Top-Down Exploration
**Goal:** Understand overall architecture

```
1. fast_search({ query: "main entry point", method: "semantic" })
2. get_symbols(mode="structure") on key files
3. trace_call_path(direction="downstream") on entry points
4. Identify patterns and layers
```

### Pattern 2: Feature Investigation
**Goal:** Understand specific feature

```
1. fast_search(query="feature name", method="semantic")
2. get_symbols on relevant files
3. trace_call_path to understand execution flow
4. fast_refs to see all usage points
```

### Pattern 3: Bug Investigation
**Goal:** Find where something is broken

```
1. fast_search for error messages or symptoms
2. fast_refs on relevant symbols
3. trace_call_path(direction="upstream") to find callers
4. Analyze execution flow for root cause
```

## Token Efficiency Strategy

**Traditional approach:**
```
Read entire file (500 lines) -> 12,000 tokens
Analyze -> Extract relevant parts
```

**Miller approach:**
```
get_symbols(mode="structure") -> 800 tokens (93% savings!)
See structure -> Navigate precisely
Only read specific symbols if needed
```

### When to Use What

**get_symbols** (PREFERRED):
- Understanding file structure
- Seeing available symbols
- Quick orientation
- Before deep dive

**Full file read** (SPARINGLY):
- After identifying specific target
- When understanding implementation details
- After narrowing down with symbols

## Key Behaviors

### DO
- Start with semantic search for relevant code
- Use get_symbols before reading files (massive token savings)
- Trace execution paths to understand flow
- Navigate with fast_refs
- Build mental model incrementally
- Explain findings clearly to user

### DON'T
- Read entire files without checking symbols first
- Do random grep searches (use semantic search!)
- Ignore call path tracing (understanding flow is critical)
- Overwhelm user with too much detail
- Skip symbol structure overview

## Success Criteria

This skill succeeds when:
- User understands codebase architecture quickly
- Minimal tokens used (via get_symbols)
- Clear execution flow explained
- Relevant code located efficiently
- User can navigate codebase independently afterward
