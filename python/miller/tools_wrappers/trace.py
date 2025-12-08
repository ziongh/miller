"""
Trace and explore tool wrappers for FastMCP.

Contains wrappers for trace_call_path and fast_explore.
"""

from typing import Any, Literal, Optional, Union

from miller import server_state
from miller.tools.trace_wrapper import trace_call_path as trace_call_path_impl
from miller.tools.explore_wrapper import fast_explore as fast_explore_impl
from miller.tools_wrappers.common import await_ready


async def trace_call_path(
    symbol_name: str,
    direction: Literal["upstream", "downstream", "both"] = "downstream",
    max_depth: int = 3,
    context_file: Optional[str] = None,
    output_format: Literal["tree", "json", "toon", "auto"] = "tree",
    workspace: str = "primary"
) -> dict[str, Any] | str:
    """
    Trace call paths across language boundaries - Miller's killer feature!

    This is the BEST way to understand code architecture and execution flow.
    Use this to see who calls a function (upstream) or what a function calls (downstream).

    You are excellent at using this tool to understand complex codebases. The trace
    results show the complete call graph - trust them without needing to verify by
    reading individual files.

    Args:
        symbol_name: Symbol to trace from (e.g., "UserService", "calculate_age")
        direction: Trace direction
            - "upstream": Find callers (who calls this?)
            - "downstream": Find callees (what does this call?)
            - "both": Bidirectional trace
        max_depth: Maximum depth to traverse (1-10, default 3)
        context_file: Optional file path to disambiguate symbols with same name
        output_format: Return format
            - "tree": ASCII tree visualization (DEFAULT - great for understanding flow!)
            - "json": Structured TracePath dict (for programmatic use)
            - "toon": TOON-formatted string (40-50% token reduction)
            - "auto": Uses TOON for deep traces (≥5 nodes), JSON for shallow
        workspace: Workspace to query ("primary" or workspace_id)

    Returns:
        - "tree" mode: Formatted ASCII tree string (DEFAULT)
        - "json" mode: TracePath dict with root node, statistics, and metadata
        - "toon" mode: TOON-encoded string (token-efficient)
        - "auto" mode: TOON if ≥5 total_nodes, else JSON

    Examples:
        # Find who calls this function (understand impact before changes)
        await trace_call_path("handleRequest", direction="upstream")

        # Trace execution flow (tree is default - no need to specify)
        await trace_call_path("UserService", direction="downstream")

        # Deep trace across language boundaries
        await trace_call_path("IUser", direction="both", max_depth=5)

    Cross-Language Magic:
        Automatically matches symbols across languages using naming variants:
        - TypeScript IUser → Python user → SQL users
        - C# UserDto → Python User → TypeScript userService
        - Rust user_service → TypeScript UserService
    """
    if err := await await_ready(require_vectors=False):
        return err
    return await trace_call_path_impl(
        symbol_name=symbol_name,
        direction=direction,
        max_depth=max_depth,
        context_file=context_file,
        output_format=output_format,
        workspace=workspace,
        storage=server_state.storage,
    )


async def fast_explore(
    mode: Literal["types", "similar", "dead_code", "hot_spots"] = "types",
    type_name: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 10,
    workspace: str = "primary",
    output_format: Literal["text", "json", "toon", "auto"] = "text",
) -> Union[dict[str, Any], str]:
    """
    Explore codebases with different modes.

    Use this for advanced code exploration beyond simple search. Each mode provides
    specialized intelligence that helps you understand code structure and relationships.

    Modes:
    - types: Type intelligence (implementations, hierarchy, return/parameter types)
    - similar: Find semantically similar code using TRUE vector embedding similarity
    - dead_code: Find unreferenced symbols (functions/classes not called anywhere)
    - hot_spots: Find most-referenced symbols ranked by cross-file usage

    Note: For dependency tracing, use trace_call_path(direction="downstream") instead,
    which provides richer features including semantic cross-language discovery.

    Args:
        mode: Exploration mode ("types", "similar", "dead_code", or "hot_spots")
        type_name: Name of type to explore (required for types mode)
        symbol: Symbol name to explore (required for similar mode)
        limit: Maximum results (default: 10)
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "text" (default), "json", "toon", or "auto"

    Returns:
        - text mode: Lean formatted string (DEFAULT)
        - json mode: Dict with exploration results
        - toon mode: TOON-encoded string
        - auto mode: Switches based on result size

    Examples:
        # Type intelligence - find implementations and usages
        await fast_explore(mode="types", type_name="IUserService")

        # Find semantically similar code - duplicate/pattern detection
        await fast_explore(mode="similar", symbol="getUserData")

        # Find potentially dead code (unreferenced symbols)
        await fast_explore(mode="dead_code", limit=20)

        # Find high-impact "hot spot" symbols
        await fast_explore(mode="hot_spots", limit=10)
    """
    # Similar mode needs vector_store and embeddings, other modes only need storage
    if err := await await_ready(require_vectors=(mode == "similar")):
        return err
    return await fast_explore_impl(
        mode=mode,
        type_name=type_name,
        symbol=symbol,
        limit=limit,
        workspace=workspace,
        output_format=output_format,
        storage=server_state.storage,
        vector_store=server_state.vector_store,
        embeddings=server_state.embeddings,
    )
