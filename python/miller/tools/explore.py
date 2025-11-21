"""
fast_explore tool - Multi-mode code exploration.

Provides different exploration strategies:
- types: Type intelligence (implementations, hierarchy, return/parameter types)
- More modes can be added in the future (logic, similar, dependencies)
"""

from typing import Any, Literal, Optional

from miller.storage import StorageManager


async def fast_explore(
    mode: Literal["types"] = "types",
    type_name: Optional[str] = None,
    storage: Optional[StorageManager] = None,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Explore codebases with different modes.

    Currently supported modes:
    - types: Type intelligence (implementations, hierarchy, returns, parameters)

    Args:
        mode: Exploration mode
        type_name: Name of type to explore (required for types mode)
        storage: StorageManager instance (uses global if not provided)
        limit: Maximum results per category (default: 10)

    Returns:
        Dict with exploration results based on mode
    """
    if mode == "types":
        return await _explore_types(type_name, storage, limit)
    else:
        raise ValueError(f"Unknown exploration mode: {mode}")


async def _explore_types(
    type_name: Optional[str],
    storage: Optional[StorageManager],
    limit: int,
) -> dict[str, Any]:
    """
    Explore type intelligence for a given type.

    Finds:
    - implementations: Classes that implement this interface
    - hierarchy: Parent/child types (extends relationships)
    - returns: Functions that return this type
    - parameters: Functions that take this type as a parameter

    Args:
        type_name: Name of type to explore
        storage: StorageManager instance
        limit: Maximum results per category

    Returns:
        Dict with type intelligence results
    """
    if not type_name:
        raise ValueError("type_name is required for types mode")

    # Use provided storage or try to get global
    if storage is None:
        import miller.server as server
        storage = server.storage
        if storage is None:
            raise ValueError("Storage not available. Index workspace first.")

    # Query all type relationships
    implementations = storage.find_type_implementations(type_name)[:limit]
    parents, children = storage.find_type_hierarchy(type_name)
    returns = storage.find_functions_returning_type(type_name)[:limit]
    parameters = storage.find_functions_with_parameter_type(type_name)[:limit]

    # Format results (simplified symbol dict)
    def format_symbol(sym: dict) -> dict:
        return {
            "name": sym.get("name"),
            "kind": sym.get("kind"),
            "file_path": sym.get("file_path"),
            "start_line": sym.get("start_line"),
            "signature": sym.get("signature"),
        }

    return {
        "type_name": type_name,
        "implementations": [format_symbol(s) for s in implementations],
        "hierarchy": {
            "parents": [format_symbol(s) for s in parents[:limit]],
            "children": [format_symbol(s) for s in children[:limit]],
        },
        "returns": [format_symbol(s) for s in returns],
        "parameters": [format_symbol(s) for s in parameters],
        "total_found": len(implementations) + len(parents) + len(children) + len(returns) + len(parameters),
    }
