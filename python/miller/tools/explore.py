"""
fast_explore tool - Multi-mode code exploration.

Provides different exploration strategies:
- types: Type intelligence (implementations, hierarchy, return/parameter types)
- similar: Find semantically similar code for duplicate detection
- dependencies: Trace transitive dependencies for impact analysis
"""

from typing import Any, Literal, Optional

from miller.storage import StorageManager


async def fast_explore(
    mode: Literal["types", "similar"] = "types",
    type_name: Optional[str] = None,
    symbol: Optional[str] = None,
    threshold: float = 0.7,
    storage: Optional[StorageManager] = None,
    vector_store: Optional[Any] = None,  # VectorStore for similar mode
    embeddings: Optional[Any] = None,  # EmbeddingManager for similar mode
    limit: int = 10,
) -> dict[str, Any]:
    """
    Explore codebases with different modes.

    Supported modes:
    - types: Type intelligence (implementations, hierarchy, returns, parameters)
    - similar: Find semantically similar code using vector embeddings

    Note: For dependency tracing, use trace_call_path(direction="downstream") instead,
    which provides richer features including semantic cross-language discovery.

    Args:
        mode: Exploration mode ("types" or "similar")
        type_name: Name of type to explore (required for types mode)
        symbol: Symbol name to explore (required for similar mode)
        threshold: Minimum similarity score for similar mode (0.0-1.0, default 0.7)
        storage: StorageManager instance (uses global if not provided)
        vector_store: VectorStore instance (for similar mode)
        embeddings: EmbeddingManager instance (for similar mode)
        limit: Maximum results (default: 10)

    Returns:
        Dict with exploration results based on mode
    """
    if mode == "types":
        return await _explore_types(type_name, storage, limit)
    elif mode == "similar":
        return await _explore_similar(symbol, threshold, storage, vector_store, embeddings, limit)
    else:
        raise ValueError(f"Unknown exploration mode: {mode}. Valid modes: 'types', 'similar'")


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


async def _explore_similar(
    symbol: Optional[str],
    threshold: float,
    storage: Optional[StorageManager],
    vector_store: Optional[Any],
    embeddings: Optional[Any],
    limit: int,
) -> dict[str, Any]:
    """
    Find semantically similar symbols using TRUE vector embedding similarity.

    Unlike a text search, this:
    1. Looks up the actual symbol from the database
    2. Builds an embedding from its name + signature + docstring
    3. Searches for other symbols with similar embeddings

    This enables finding similar code patterns across different naming conventions
    and even different languages (e.g., getUserData ↔ fetch_user_info).
    """
    if not symbol:
        return {"symbol": None, "error": "symbol parameter is required", "similar": [], "total_found": 0}

    # Get storage
    if storage is None:
        import miller.server as server
        storage = server.storage
        if storage is None:
            return {"symbol": symbol, "error": "Storage not available", "similar": [], "total_found": 0}

    # Find the target symbol in the database
    target = storage.get_symbol_by_name(symbol)
    if not target:
        return {"symbol": symbol, "error": "Symbol not found", "similar": [], "total_found": 0}

    # Get vector store and embeddings for similarity search
    try:
        if vector_store is None:
            import miller.server as server
            vector_store = server.vector_store
        if vector_store is None:
            return {"symbol": symbol, "error": "Vector store not available", "similar": [], "total_found": 0}

        if embeddings is None:
            import miller.server as server
            embeddings = getattr(server, 'embeddings', None)
            if embeddings is None:
                # Try server_state as fallback
                from miller import server_state
                embeddings = server_state.embeddings
        if embeddings is None:
            return {"symbol": symbol, "error": "Embeddings not available", "similar": [], "total_found": 0}

        # Use semantic_neighbors for TRUE semantic similarity search
        from miller.tools.trace.search import semantic_neighbors

        matches = semantic_neighbors(
            storage=storage,
            vector_store=vector_store,
            embeddings=embeddings,
            symbol=target,
            limit=limit,
            threshold=threshold,
            cross_language_only=False,  # Include same-language matches for similar mode
        )

        # Format results to match expected output structure
        similar = []
        for match in matches:
            similar.append({
                "name": match.get("name"),
                "kind": match.get("kind"),
                "file_path": match.get("file_path"),
                "start_line": match.get("line", match.get("start_line", 0)),
                "signature": match.get("signature"),
                "similarity": round(match.get("similarity", 0), 3),
                "language": match.get("language"),
            })

        return {"symbol": symbol, "similar": similar, "total_found": len(similar)}

    except Exception as e:
        return {"symbol": symbol, "error": str(e), "similar": [], "total_found": 0}


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


def _format_similar_as_text(result: dict[str, Any]) -> str:
    """Format similar mode result as lean text output."""
    symbol = result.get("symbol", "?")
    total = result.get("total_found", 0)
    error = result.get("error")

    if error:
        return f'Similar to "{symbol}": Error - {error}'

    if total == 0:
        return f'Similar to "{symbol}": No similar symbols found (0 matches).'

    output = [f'Similar to "{symbol}" ({total} matches):', ""]

    for item in result.get("similar", []):
        name = item.get("name", "?")
        file_path = item.get("file_path", "?")
        line = item.get("start_line", 0)
        similarity = item.get("similarity", 0)
        sig = item.get("signature", name)
        if sig and len(sig) > 50:
            sig = sig[:47] + "..."

        # Show as percentage
        pct = int(similarity * 100)
        output.append(f"  {pct}% {file_path}:{line} → {sig}")

    return "\n".join(output)
