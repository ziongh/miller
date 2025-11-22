"""
Fast explore tool - Type intelligence and relationship exploration.

Provides fast_explore for understanding type hierarchies and implementations.
"""

from typing import Any, Literal, Union, Optional


async def fast_explore(
    mode: Literal["types"] = "types",
    type_name: Optional[str] = None,
    limit: int = 10,
    workspace: str = "primary",
    output_format: Literal["text", "json"] = "text",
    storage=None,
) -> Union[dict[str, Any], str]:
    """
    Explore codebases with different modes - currently supports type intelligence.

    Use this to understand type relationships in OOP codebases:
    - What classes implement an interface?
    - What's the inheritance hierarchy?
    - What functions return or take a specific type?

    Args:
        mode: Exploration mode - currently only "types" is supported
        type_name: Name of type to explore (required for types mode)
              Examples: "IUser", "PaymentProcessor", "BaseService"
        limit: Maximum results per category (default: 10)
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "text" (default) or "json"
                      - "text": Lean formatted string - DEFAULT
                      - "json": Dict with full metadata
        storage: StorageManager instance (injected by server)

    Returns:
        - Text mode: Formatted string with type relationships
        - JSON mode: Dict with exploration results:
          - type_name: The queried type
          - implementations: Classes implementing this interface
          - hierarchy: {parents: [...], children: [...]} - inheritance tree
          - returns: Functions that return this type
          - parameters: Functions taking this type as parameter
          - total_found: Total matches across all categories

    Examples:
        # Find what implements an interface
        await fast_explore(mode="types", type_name="IUserService")

        # Explore a base class hierarchy
        await fast_explore(mode="types", type_name="BaseController")

    Type Intelligence Workflow:
        1. fast_explore(type_name="IService") → See all implementations
        2. get_symbols on implementing class → Understand the implementation
        3. trace_call_path on implementation → See how it's used
    """
    from miller.tools.explore import fast_explore_with_format
    from miller.storage import StorageManager
    from miller.workspace_paths import get_workspace_db_path
    from miller.workspace_registry import WorkspaceRegistry

    # Get workspace-specific storage if needed
    if workspace != "primary":
        registry = WorkspaceRegistry()
        workspace_entry = registry.get_workspace(workspace)
        if not workspace_entry:
            return {
                "type_name": type_name,
                "error": f"Workspace '{workspace}' not found"
            }
        db_path = get_workspace_db_path(workspace)
        workspace_storage = StorageManager(db_path=str(db_path))
    else:
        workspace_storage = storage

    try:
        return await fast_explore_with_format(
            mode=mode,
            type_name=type_name,
            storage=workspace_storage,
            limit=limit,
            output_format=output_format,
        )
    finally:
        if workspace != "primary" and workspace_storage:
            workspace_storage.close()
