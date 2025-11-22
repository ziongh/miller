"""
Trace call path tool - Cross-language call graph exploration.

Provides trace_call_path for understanding execution flow and dependencies.
"""

from typing import Any, Literal, Union


async def trace_call_path(
    symbol_name: str,
    direction: Literal["upstream", "downstream", "both"] = "downstream",
    max_depth: int = 3,
    context_file: str | None = None,
    output_format: Literal["tree", "json", "toon", "auto"] = "tree",
    workspace: str = "primary",
    storage=None,
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
        storage: StorageManager instance (injected by server)

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

    Architecture Understanding Workflow:
        1. trace_call_path("entryPoint", direction="downstream") → See execution flow
        2. trace_call_path("deepFunction", direction="upstream") → See all callers
        3. Use "tree" output for visual understanding

    Cross-Language Magic:
        Automatically matches symbols across languages using naming variants:
        - TypeScript IUser → Python user → SQL users
        - C# UserDto → Python User → TypeScript userService
        - Rust user_service → TypeScript UserService
    """
    from miller.storage import StorageManager
    from miller.workspace_paths import get_workspace_db_path
    from miller.workspace_registry import WorkspaceRegistry
    from miller.tools.trace import trace_call_path as trace_impl
    from miller.toon_utils import create_toonable_result

    # Get workspace-specific storage
    if workspace != "primary":
        registry = WorkspaceRegistry()
        workspace_entry = registry.get_workspace(workspace)
        if not workspace_entry:
            return {
                "symbol": symbol_name,
                "error": f"Workspace '{workspace}' not found"
            }
        db_path = get_workspace_db_path(workspace)
        workspace_storage = StorageManager(db_path=str(db_path))
    else:
        workspace_storage = storage

    try:
        # For tree format, return directly (it's already a formatted string)
        if output_format == "tree":
            return await trace_impl(
                storage=workspace_storage,
                symbol_name=symbol_name,
                direction=direction,
                max_depth=max_depth,
                context_file=context_file,
                output_format="tree",
                workspace=workspace,
            )

        # For TOON/auto modes, get JSON first then encode
        result = await trace_impl(
            storage=workspace_storage,
            symbol_name=symbol_name,
            direction=direction,
            max_depth=max_depth,
            context_file=context_file,
            output_format="json",
            workspace=workspace,
        )

        # Use Julie's simple pattern: TOON handles nested structures natively
        return create_toonable_result(
            json_data=result,               # Full result as-is
            toon_data=result,               # Same - TOON handles nested TraceNodes
            output_format=output_format,
            auto_threshold=5,               # 5+ nodes → TOON
            result_count=result.get("total_nodes", 0),
            tool_name="trace_call_path"
        )
    finally:
        # Close workspace storage if it's not the default
        if workspace != "primary":
            workspace_storage.close()
