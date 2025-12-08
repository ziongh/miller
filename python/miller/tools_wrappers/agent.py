"""
Agent tooling wrappers for FastMCP.

Contains wrappers for get_architecture_map, validate_imports, find_similar_implementation.
"""

from typing import Literal, Optional

from miller import server_state
from miller.tools.architecture import get_architecture_map as get_architecture_map_impl
from miller.tools.validation import validate_imports as validate_imports_impl
from miller.tools.code_search import find_similar_implementation as find_similar_impl
from miller.tools_wrappers.common import await_ready


async def get_architecture_map(
    depth: int = 2,
    output_format: Literal["mermaid", "ascii", "json"] = "mermaid",
    min_edge_count: int = 3,
) -> str:
    """
    Generate a high-level architecture map of module dependencies.

    This tool provides a "zoom out" view of the codebase, showing how
    directories/modules depend on each other. Use this to:
    - Understand system architecture before making changes
    - Plan cross-module refactors
    - Identify tightly coupled modules
    - Find potential circular dependencies

    Args:
        depth: Directory depth to aggregate at (default: 2).
               Example: depth=2 for "src/auth" from "src/auth/login.py"
        output_format: Output format:
            - "mermaid": Mermaid.js flowchart (paste into docs/diagrams)
            - "ascii": ASCII tree (for quick terminal viewing)
            - "json": Structured data with statistics
        min_edge_count: Minimum relationships to show an edge (default: 3).
                       Higher values show only strong dependencies.

    Returns:
        Architecture diagram/data in the requested format

    Examples:
        # Get Mermaid diagram for documentation
        get_architecture_map(depth=2, output_format="mermaid")

        # Quick ASCII overview
        get_architecture_map(depth=1, output_format="ascii")

        # Detailed stats for analysis
        get_architecture_map(depth=3, output_format="json", min_edge_count=1)
    """
    if err := await await_ready(require_vectors=False):
        return err
    return await get_architecture_map_impl(
        depth=depth,
        output_format=output_format,
        min_edge_count=min_edge_count,
        storage=server_state.storage,
    )


async def validate_imports(
    code_snippet: str,
    language: Optional[str] = None,
) -> str:
    """
    Validate that imports in a code snippet reference existing symbols.

    Use this tool BEFORE writing code that imports from the codebase.
    It prevents the "hallucinated import" bug where agents write imports
    to symbols that don't exist, then loop on compilation errors.

    The tool parses the code snippet, extracts import statements, and
    checks each imported symbol against the indexed codebase.

    Args:
        code_snippet: Code you intend to write (can be partial, just imports)
        language: Programming language (auto-detected if not provided).
                 Supported: python, typescript, javascript, rust, go

    Returns:
        Validation report with status for each import:
        - valid: Symbol exists and is public/exported
        - invalid: Symbol does not exist (with suggestions)
        - ambiguous: Multiple matching symbols found
        - private: Symbol exists but is not exported

    Examples:
        # Validate before writing Python code
        validate_imports('''
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager
        from miller.utils import NonExistentClass
        ''', language="python")

        # Auto-detect language from code
        validate_imports('''
        import { UserService } from './services/user';
        import { NonExistent } from './services/fake';
        ''')
    """
    if err := await await_ready(require_vectors=False):
        return err
    return await validate_imports_impl(
        code_snippet=code_snippet,
        language=language,
        storage=server_state.storage,
    )


async def find_similar_implementation(
    code_snippet: str,
    limit: int = 10,
    min_score: float = 0.5,
    language: Optional[str] = None,
    kind_filter: Optional[list[str]] = None,
) -> str:
    """
    Find existing implementations similar to the provided code snippet.

    Use this tool BEFORE writing new code to check if similar code already
    exists in the codebase. This prevents:
    - Duplicating existing functionality
    - Reinventing patterns already established
    - Creating inconsistent implementations of the same concept

    The tool uses code-to-code embeddings (Jina similarity task) to find
    semantically similar code, not just text matches.

    Args:
        code_snippet: The code you're about to write or a description of
                     the pattern you're looking for
        limit: Maximum number of results (default: 10)
        min_score: Minimum similarity score 0.0-1.0 (default: 0.5)
        language: Filter to specific language (e.g., "python", "rust")
        kind_filter: Filter to specific symbol kinds (e.g., ["function", "method"])

    Returns:
        Report showing similar implementations with:
        - Similarity score (higher = more similar)
        - File path and line number
        - Symbol name and kind
        - Code preview

    Examples:
        # Before writing a cache implementation
        find_similar_implementation('''
        def get_cached(key):
            if key in cache:
                return cache[key]
            result = compute(key)
            cache[key] = result
            return result
        ''')

        # Find similar error handling patterns
        find_similar_implementation('''
        try:
            result = api.call()
        except TimeoutError:
            logger.warning("API timeout")
            return default_value
        ''', kind_filter=["function", "method"])
    """
    if err := await await_ready(require_vectors=True):
        return err
    return await find_similar_impl(
        code_snippet=code_snippet,
        limit=limit,
        min_score=min_score,
        language=language,
        kind_filter=kind_filter,
        embeddings=server_state.embeddings,
        vector_store=server_state.vector_store,
        storage=server_state.storage,
    )
