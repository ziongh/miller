---
completed_at: 1764552030
git:
  branch: main
  commit: 8beb2ed
  dirty: true
  files_changed:
  - .memories/plans/plan_miller-performance-optimization-sprint.md
  - python/miller/closure.py
  - python/miller/instructions.md
  - python/miller/lifecycle.py
  - python/miller/server.py
  - python/miller/tools/gpu_memory.py
  - python/miller/tools/navigation.py
  - python/miller/tools_wrappers.py
  - python/tests/test_reachability.py
  - .memories/2025-12-01/
  - .memories/plans/plan_enhanced-toolset-fastgoto-and-reachability.md
  - python/tests/test_fast_goto.py
id: plan_fastlookup-smart-symbol-resolution-tool
status: completed
timestamp: 1764551606
title: 'fast_lookup: Smart Symbol Resolution Tool'
type: plan
---

# fast_lookup: Smart Symbol Resolution Tool

## Goal
Replace `fast_goto` with a smarter, batch-capable tool that resolves symbols with semantic fallback.

## Why This Tool?
- **Batch**: One call instead of N `fast_goto` calls
- **Smart fallback**: Semantic match when exact match fails
- **Complete**: Location + import statement + structure in one response
- **Pre-flight validation**: Verify symbols exist before writing code

## Interface

```python
async def fast_lookup(
    symbols: list[str],           # What you're looking for (1-N symbols)
    context_file: str = None,     # Where you're writing (for relative imports)
    include_body: bool = False,   # Include source code
    max_depth: int = 1,           # Structure depth: 0=signature, 1=methods, 2=nested
    workspace: str = "primary",
) -> str:  # Always lean text output
```

## Output Format (Lean Text)

```
═══ fast_lookup: 3 symbols ═══

AuthService ✓
  src/services/auth.py:42 (class)
  from services.auth import AuthService
  class AuthService(BaseService):
    def __init__(self, db: Database, config: AuthConfig)
    def authenticate(self, token: str) -> User

UserDTO ✗ → User (semantic match, 0.87)
  src/models/user.py:8 (class)
  from models.user import User
  class User(BaseModel):
    id: int
    email: str

FooBarBaz ✗
  No match found
```

## Implementation Tasks

- [ ] Write failing tests for fast_lookup
  - [ ] Single symbol exact match
  - [ ] Multiple symbols batch lookup
  - [ ] Semantic fallback when exact match fails
  - [ ] Import path generation (absolute)
  - [ ] Import path generation (relative to context_file)
  - [ ] include_body parameter
  - [ ] max_depth parameter (0, 1, 2)
  - [ ] Symbol not found (no match)
  - [ ] Mixed results (some found, some semantic, some missing)

- [ ] Implement fast_lookup in python/miller/tools/navigation.py
  - [ ] Batch exact lookup via storage
  - [ ] Semantic fallback for misses (vector search)
  - [ ] Import path computation
  - [ ] Structure extraction (reuse _get_symbol_structure from fast_goto)
  - [ ] Lean text output formatting

- [ ] Expose as MCP tool
  - [ ] Add wrapper in tools_wrappers.py
  - [ ] Register in server.py

- [ ] Remove fast_goto
  - [ ] Remove from tools/navigation.py
  - [ ] Remove from tools_wrappers.py
  - [ ] Remove from server.py
  - [ ] Remove tests (or convert to fast_lookup tests)
  - [ ] Update instructions.md

- [ ] Update documentation
  - [ ] Update instructions.md with fast_lookup docs
  - [ ] Update CLAUDE.md if needed

## Key Design Decisions

1. **Always show import statement** - If resolving symbols, you need the import
2. **Semantic fallback is transparent** - Show `✗ → Match (semantic, 0.87)` so agent knows it's a suggestion
3. **Structure by default** - max_depth=1 shows methods/properties
4. **Lean text only** - No JSON output, optimized for AI reading
5. **Context-aware imports** - Relative paths when context_file provided

## Success Criteria

- [ ] All tests pass
- [ ] Replaces fast_goto completely (no functionality loss)
- [ ] Batch lookup works efficiently
- [ ] Semantic fallback finds reasonable matches
- [ ] Import paths are correct for Python (start simple)
