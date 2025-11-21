"""
Type definitions for trace_call_path tool.

Defines the contract for cross-language call tracing functionality.
This file serves as the specification before implementation (TDD Phase 1).
"""

from typing import Literal, Optional, TypedDict


class TraceNode(TypedDict):
    """
    A single node in a call trace path.

    Represents a symbol in the call chain, including its location and metadata.
    """
    # Symbol identification
    symbol_id: str  # Unique symbol ID from database
    name: str  # Symbol name (e.g., "UserService", "calculate_age")
    kind: str  # Symbol kind (Function, Class, Method, etc.)

    # Location
    file_path: str  # Relative path to file containing symbol
    line: int  # Line number where symbol is defined
    language: str  # Language of the file (python, typescript, rust, etc.)

    # Relationship metadata
    relationship_kind: str  # How this node relates to next (Call, Reference, Import, etc.)
    match_type: Literal["exact", "variant", "semantic"]  # How this match was found
    confidence: Optional[float]  # Confidence score (0.0-1.0) for semantic matches

    # Call chain
    depth: int  # Depth in trace (0 = starting symbol, 1 = first hop, etc.)
    children: list["TraceNode"]  # Downstream calls (if direction is downstream/both)

    # Optional context
    signature: Optional[str]  # Function/method signature if available
    doc_comment: Optional[str]  # Documentation comment if available


class TracePath(TypedDict):
    """
    Complete trace result containing all paths from a starting symbol.

    This is the return type for trace_call_path tool.
    """
    # Query metadata
    query_symbol: str  # Symbol name that was queried
    direction: Literal["upstream", "downstream", "both"]  # Trace direction
    max_depth: int  # Maximum depth limit used

    # Results
    root: TraceNode  # Root node (the symbol being traced)
    total_nodes: int  # Total number of nodes found
    max_depth_reached: int  # Actual maximum depth reached
    truncated: bool  # True if results were limited by max_depth

    # Statistics
    languages_found: list[str]  # All languages encountered in trace
    match_types: dict[str, int]  # Count of each match type (exact, variant, semantic)
    relationship_kinds: dict[str, int]  # Count of each relationship kind

    # Execution metadata
    execution_time_ms: float  # Time taken to execute trace
    nodes_visited: int  # Total nodes visited (including duplicates/cycles)


class NamingVariant(TypedDict):
    """
    A naming variant for cross-language symbol matching.

    Example: "UserService" → ["user_service", "userService", "USER_SERVICE", ...]
    """
    original: str  # Original symbol name
    snake_case: str  # user_service
    camel_case: str  # userService
    pascal_case: str  # UserService
    kebab_case: str  # user-service
    screaming_snake: str  # USER_SERVICE
    screaming_kebab: str  # USER-SERVICE


# Type alias for direction parameter
TraceDirection = Literal["upstream", "downstream", "both"]

# Type alias for match type
MatchType = Literal["exact", "variant", "semantic"]


# Constants for configuration
SEMANTIC_SIMILARITY_THRESHOLD = 0.7  # Minimum cosine similarity for semantic matches
DEFAULT_MAX_DEPTH = 3  # Default maximum trace depth
MAX_ALLOWED_DEPTH = 10  # Maximum allowed depth (prevent infinite recursion)
MAX_NODES_PER_LEVEL = 100  # Maximum nodes to explore at each level (prevent explosion)


# Error conditions (for documentation purposes)
"""
Error Conditions:

1. SymbolNotFound: Query symbol doesn't exist in database
   - Return: Empty TracePath with total_nodes=0
   - Example: Querying "NonexistentFunction"

2. InvalidDepth: max_depth < 1 or max_depth > MAX_ALLOWED_DEPTH
   - Raise: ValueError with helpful message
   - Example: max_depth = 0 or max_depth = 100

3. InvalidDirection: direction not in ["upstream", "downstream", "both"]
   - Raise: ValueError with valid options
   - Example: direction = "sideways"

4. CyclicReference: Symbol references itself (direct or indirect)
   - Handle: Track visited nodes, skip cycles, mark in metadata
   - Example: A calls B calls A

5. AmbiguousSymbol: Multiple symbols with same name in different files
   - Handle: Return all matches, include file_path for disambiguation
   - Example: "User" class in user.py and admin.py
   - Use context_file parameter to disambiguate if provided

6. WorkspaceNotFound: Specified workspace doesn't exist
   - Return: Error dict with message
   - Example: workspace="nonexistent_workspace_id"
"""

# Boundary Conditions (for test coverage)
"""
Boundary Conditions:

1. Empty codebase: No symbols indexed
   - Result: SymbolNotFound error

2. Single symbol: Symbol exists but has no relationships
   - Result: TracePath with root node only, total_nodes=1

3. Max depth = 1: Only immediate children/parents
   - Result: Root + first level only, truncated=True if more exist

4. Deep recursion: Call chain deeper than max_depth
   - Result: Truncated at max_depth, truncated=True

5. Wide fan-out: Symbol called by 100+ other symbols
   - Result: Limited by MAX_NODES_PER_LEVEL, include count in metadata

6. Cross-language: TypeScript → Python → SQL
   - Result: All languages in languages_found, variants used for matching

7. No variant matches: Symbol names don't match any variant
   - Fallback: Use semantic similarity with embeddings

8. Semantic threshold not met: Similarity < 0.7
   - Result: No match, branch terminates

9. Multiple match types: Same path found via exact + variant
   - Handle: Prefer exact > variant > semantic, deduplicate

10. Circular imports: A imports B imports A
    - Handle: Track visited, don't revisit same symbol in same path
"""

# Expected Inputs/Outputs
"""
Expected Inputs:

1. symbol_name: str (required)
   - Non-empty string
   - Can be simple ("User") or qualified ("User.save")
   - Case-sensitive for exact matching, case-insensitive for variants

2. direction: "upstream" | "downstream" | "both" (default: "downstream")
   - upstream: Find callers (who calls this symbol?)
   - downstream: Find callees (what does this symbol call?)
   - both: Bidirectional trace

3. max_depth: int (default: 3, range: 1-10)
   - Controls how many hops to explore
   - Larger = more comprehensive but slower

4. context_file: Optional[str] (default: None)
   - Disambiguates symbols with same name
   - Only traces symbol defined in this file

5. output_format: "json" | "tree" (default: "json")
   - json: Returns TracePath dict (for programmatic use)
   - tree: Returns formatted tree string (for human reading)

6. workspace: str (default: "primary")
   - Which workspace to query
   - "primary" or specific workspace_id


Expected Outputs:

1. Success (JSON format):
   {
     "query_symbol": "UserService",
     "direction": "downstream",
     "max_depth": 3,
     "root": {
       "symbol_id": "sym_123",
       "name": "UserService",
       "kind": "Class",
       "file_path": "src/services/user.ts",
       "line": 10,
       "language": "typescript",
       "relationship_kind": "Definition",
       "match_type": "exact",
       "confidence": null,
       "depth": 0,
       "children": [
         {
           "name": "user_service",
           "kind": "Function",
           "file_path": "api/users.py",
           "language": "python",
           "match_type": "variant",
           "depth": 1,
           "children": [...]
         }
       ]
     },
     "total_nodes": 15,
     "max_depth_reached": 3,
     "truncated": false,
     "languages_found": ["typescript", "python", "sql"],
     "match_types": {"exact": 5, "variant": 8, "semantic": 2},
     "relationship_kinds": {"Call": 12, "Import": 3},
     "execution_time_ms": 45.3,
     "nodes_visited": 18
   }

2. Success (tree format):
   UserService (typescript) @ src/services/user.ts:10
   ├─[Call]→ user_service (python) @ api/users.py:5
   │  ├─[Call]→ UserDto (python) @ models/user.py:12
   │  │  └─[Reference]→ users (sql) @ schema.sql:45
   │  └─[Call]→ validate_user (python) @ validators.py:8
   └─[Call]→ createUser (typescript) @ src/api/users.ts:22

3. Error (symbol not found):
   {
     "query_symbol": "NonexistentFunction",
     "direction": "downstream",
     "max_depth": 3,
     "total_nodes": 0,
     "error": "Symbol 'NonexistentFunction' not found in workspace 'primary'"
   }

4. Error (workspace not found):
   {
     "query_symbol": "User",
     "workspace": "invalid_workspace",
     "error": "Workspace 'invalid_workspace' not found"
   }
"""
