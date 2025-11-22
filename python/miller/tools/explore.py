"""
fast_explore tool - Multi-mode code exploration.

Provides different exploration strategies:
- types: Type intelligence (implementations, hierarchy, return/parameter types)
- More modes can be added in the future (logic, similar, dependencies)
"""

from typing import Any, Literal, Optional, Union

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


def _format_explore_as_text(result: dict[str, Any]) -> str:
    """Format type exploration result as lean text output.

    Output format:
    ```
    Type intelligence for "IUserService":

    Implementations (3):
      src/services/user.py:15 → class UserService
      src/services/admin.py:22 → class AdminService

    Returns this type (2):
      src/factory.py:30 → def create_service() -> IUserService

    Takes as parameter (1):
      src/api/auth.py:45 → def login(service: IUserService)
    ```
    """
    type_name = result.get("type_name", "?")
    total = result.get("total_found", 0)

    if total == 0:
        return f'No type information found for "{type_name}".'

    output = [f'Type intelligence for "{type_name}":', ""]

    # Implementations
    implementations = result.get("implementations", [])
    if implementations:
        output.append(f"Implementations ({len(implementations)}):")
        for impl in implementations:
            file_path = impl.get("file_path", "?")
            line = impl.get("start_line", 0)
            sig = impl.get("signature", impl.get("name", "?"))
            # Truncate signature
            if len(sig) > 60:
                sig = sig[:57] + "..."
            output.append(f"  {file_path}:{line} → {sig}")
        output.append("")

    # Returns
    returns = result.get("returns", [])
    if returns:
        output.append(f"Returns this type ({len(returns)}):")
        for ret in returns:
            file_path = ret.get("file_path", "?")
            line = ret.get("start_line", 0)
            sig = ret.get("signature", ret.get("name", "?"))
            if len(sig) > 60:
                sig = sig[:57] + "..."
            output.append(f"  {file_path}:{line} → {sig}")
        output.append("")

    # Parameters
    parameters = result.get("parameters", [])
    if parameters:
        output.append(f"Takes as parameter ({len(parameters)}):")
        for param in parameters:
            file_path = param.get("file_path", "?")
            line = param.get("start_line", 0)
            sig = param.get("signature", param.get("name", "?"))
            if len(sig) > 60:
                sig = sig[:57] + "..."
            output.append(f"  {file_path}:{line} → {sig}")
        output.append("")

    # Hierarchy
    hierarchy = result.get("hierarchy", {})
    parents = hierarchy.get("parents", [])
    children = hierarchy.get("children", [])
    if parents or children:
        output.append("Hierarchy:")
        if parents:
            output.append(f"  Parents ({len(parents)}):")
            for parent in parents:
                file_path = parent.get("file_path", "?")
                line = parent.get("start_line", 0)
                sig = parent.get("signature", parent.get("name", "?"))
                if len(sig) > 60:
                    sig = sig[:57] + "..."
                output.append(f"    {file_path}:{line} → {sig}")
        if children:
            output.append(f"  Children ({len(children)}):")
            for child in children:
                file_path = child.get("file_path", "?")
                line = child.get("start_line", 0)
                sig = child.get("signature", child.get("name", "?"))
                if len(sig) > 60:
                    sig = sig[:57] + "..."
                output.append(f"    {file_path}:{line} → {sig}")

    # Remove trailing empty lines
    while output and output[-1] == "":
        output.pop()

    return "\n".join(output)


async def fast_explore_with_format(
    mode: Literal["types"] = "types",
    type_name: Optional[str] = None,
    storage: Optional[StorageManager] = None,
    limit: int = 10,
    output_format: Literal["text", "json"] = "text",
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
        storage: StorageManager instance (uses global if not provided)
        limit: Maximum results per category (default: 10)
        output_format: Output format - "text" (default) or "json"
                      - "text": Lean formatted string - DEFAULT
                      - "json": Dict with full metadata

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
        await fast_explore_with_format(mode="types", type_name="IUserService")

        # Explore a base class hierarchy
        await fast_explore_with_format(mode="types", type_name="BaseController")

    Type Intelligence Workflow:
        1. fast_explore_with_format(type_name="IService") → See all implementations
        2. get_symbols on implementing class → Understand the implementation
        3. trace_call_path on implementation → See how it's used
    """
    result = await fast_explore(
        mode=mode,
        type_name=type_name,
        storage=storage,
        limit=limit,
    )

    if output_format == "text":
        return _format_explore_as_text(result)
    else:
        return result
