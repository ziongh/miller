---
completed_at: 1763605797
git:
  branch: main
  commit: 37c47d4
  dirty: false
  files_changed: []
id: plan_implement-tracecallpath-cross-language-call-tracing
status: completed
timestamp: 1763604848
title: Implement trace_call_path - Cross-Language Call Tracing
type: plan
---

## Goal
Implement Miller's killer differentiator: cross-language call tracing using naming variants + semantic embeddings.

## Success Criteria
- Trace execution flow across language boundaries (TypeScript → Python → SQL)
- Use naming variants (IUser → i_user → users) for matching
- Fallback to semantic similarity for conceptual matches
- Support upstream (callers), downstream (callees), both directions
- Return results as JSON or tree format
- Handle max_depth limiting (1-10, default 3)

## Implementation Phases

### Phase 1: Define Contract (Current - TDD Phase 1)
- [ ] Define function signature and parameters
- [ ] Define return types (TraceNode, TracePath)
- [ ] Document expected inputs/outputs
- [ ] List error conditions
- [ ] Document boundary conditions

### Phase 2: Write Tests (TDD Phase 2)
- [ ] Test: Basic downstream trace (function → called functions)
- [ ] Test: Basic upstream trace (function → callers)
- [ ] Test: Cross-language trace (TS → Python → SQL)
- [ ] Test: Naming variant matching (IUser → i_user)
- [ ] Test: Max depth limiting
- [ ] Test: Semantic similarity fallback
- [ ] Test: Error handling (symbol not found)

### Phase 3: Implement Core (TDD Phase 3)
- [ ] Naming variant generator (snake, camel, pascal, kebab, screaming)
- [ ] Relationship traversal logic (BFS/DFS)
- [ ] Cross-language matching using variants
- [ ] Semantic similarity scoring (embedding cosine distance)
- [ ] Result formatting (JSON and tree)

### Phase 4: Refactor (TDD Phase 4)
- [ ] Extract variant logic to separate module
- [ ] Optimize relationship queries
- [ ] Add caching for repeated queries
- [ ] Performance testing with large codebases

## Technical Approach

**Naming Variants:**
- `UserService` → `user_service`, `userService`, `user-service`, `USER_SERVICE`
- Query relationships table with all variants
- Match symbols across languages

**Semantic Fallback:**
- If no variant matches, compute embedding similarity
- Use threshold (>0.7) for conceptual matches
- Useful for: `IUser` → `UserModel` → `UserEntity`

**Data Sources:**
- `symbol_relationships` table (already populated during indexing)
- `symbols` table (for symbol metadata)
- `embeddings` LanceDB (for semantic similarity)

## References
- TOOLS_PLAN.md lines 191-240 (trace_call_path specification)
- Julie's trace_call_path module (reference implementation)
