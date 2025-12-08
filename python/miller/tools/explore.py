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
    mode: Literal["types", "similar", "dead_code", "hot_spots"] = "types",
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
    - dead_code: Find unreferenced symbols (potential cleanup candidates)
    - hot_spots: Find most-referenced symbols (high-impact code)

    Note: For dependency tracing, use trace_call_path(direction="downstream") instead,
    which provides richer features including semantic cross-language discovery.

    Args:
        mode: Exploration mode ("types", "similar", "dead_code", or "hot_spots")
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
    elif mode == "dead_code":
        return await _explore_dead_code(storage, limit)
    elif mode == "hot_spots":
        return await _explore_hot_spots(storage, limit)
    else:
        raise ValueError(f"Unknown exploration mode: {mode}. Valid modes: 'types', 'similar', 'dead_code', 'hot_spots'")


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


async def _explore_dead_code(
    storage: Optional[StorageManager],
    limit: int,
) -> dict[str, Any]:
    """
    Find unreferenced symbols (potential dead code) using graph analysis.

    Uses Rust-based graph processing with SCC detection to find:
    1. Isolated functions (no one calls them)
    2. Dead cycles ("islands") - groups of functions that only call each other
       but are never called from outside

    The algorithm:
    1. Build call graph from relationships
    2. Identify entry points (main, test_*, *Controller, handlers)
    3. Use Rust GraphProcessor.find_dead_nodes() for fast reachability analysis
    4. Verify candidates aren't textually referenced (safety check for dynamic languages)

    Args:
        storage: StorageManager instance
        limit: Maximum results to return

    Returns:
        Dict with dead_code list, dead_cycles list, and counts
    """
    # Get storage from global if not provided
    if storage is None:
        import miller.server as server
        storage = server.storage

    if storage is None:
        return {"error": "Storage not initialized", "dead_code": [], "dead_cycles": [], "total_found": 0}

    try:
        from miller import miller_core

        cursor = storage.conn.cursor()

        # Step 1: Fetch all call relationships for the graph
        cursor.execute("""
            SELECT from_symbol_id, to_symbol_id
            FROM relationships
            WHERE kind IN ('call', 'calls', 'Call')
        """)
        edges = [(row[0], row[1]) for row in cursor.fetchall()]

        if not edges:
            # No relationships, fall back to simple query
            return await _explore_dead_code_simple(storage, limit)

        # Step 2: Identify entry points (symbols that should be considered "alive")
        # Entry points include: main functions, test functions, handlers, controllers
        cursor.execute("""
            SELECT id FROM symbols
            WHERE (
                name = 'main'
                OR name LIKE 'test\\_%' ESCAPE '\\'
                OR name LIKE 'Test%'
                OR name LIKE '%Controller'
                OR name LIKE '%Handler'
                OR name LIKE 'handle\\_%' ESCAPE '\\'
                OR name LIKE '%Endpoint'
                OR name = '__init__'
                OR name = '__main__'
            )
            AND kind IN ('function', 'method', 'class')
        """)
        entry_points = [row[0] for row in cursor.fetchall()]

        # Step 3: Use Rust graph processor for dead code detection
        processor = miller_core.PyGraphProcessor(edges)
        structurally_dead = set(processor.find_dead_nodes(entry_points))
        dead_cycles_raw = processor.find_dead_cycles(entry_points)

        if not structurally_dead:
            return {"dead_code": [], "dead_cycles": [], "total_found": 0}

        # Step 4: Filter to only functions/classes that are:
        # - Not in test files
        # - Not private (underscore prefix)
        # - In the structurally dead set
        dead_ids_list = list(structurally_dead)
        placeholders = ",".join("?" * len(dead_ids_list))

        cursor.execute(f"""
            SELECT s.id, s.name, s.kind, s.file_path, s.start_line, s.signature
            FROM symbols s
            WHERE s.id IN ({placeholders})
            AND s.kind IN ('function', 'method', 'class')
            AND s.name NOT LIKE '\\_%' ESCAPE '\\'
            AND s.file_path NOT LIKE '%test%'
            AND s.file_path NOT LIKE '%fixture%'
            ORDER BY s.file_path, s.name
        """, dead_ids_list)

        candidates = cursor.fetchall()

        # Step 5: Safety check - verify candidates aren't textually referenced
        # (protects against dynamic languages where calls may not be in relationships)
        dead_code = []
        for row in candidates:
            sym_id, sym_name, sym_kind, file_path, start_line, signature = row

            # Check if this symbol name appears in identifiers from other files
            cursor.execute("""
                SELECT COUNT(*) FROM identifiers
                WHERE name = ? AND file_path != ?
            """, (sym_name, file_path))
            ref_count = cursor.fetchone()[0]

            if ref_count == 0:
                dead_code.append({
                    "id": sym_id,
                    "name": sym_name,
                    "kind": sym_kind,
                    "file_path": file_path,
                    "start_line": start_line,
                    "signature": signature,
                    "reason": "unreachable_from_entry_points",
                })

            if len(dead_code) >= limit:
                break

        # Format dead cycles
        dead_cycles = []
        for cycle_nodes, cycle_size in dead_cycles_raw[:5]:  # Top 5 cycles
            # Get symbol names for the cycle
            cycle_ids = [n for n in cycle_nodes if n in structurally_dead]
            if cycle_ids:
                placeholders = ",".join("?" * len(cycle_ids))
                cursor.execute(f"""
                    SELECT name, file_path FROM symbols WHERE id IN ({placeholders})
                """, cycle_ids)
                cycle_info = [{"name": r[0], "file_path": r[1]} for r in cursor.fetchall()]
                if cycle_info:
                    dead_cycles.append({
                        "size": cycle_size,
                        "symbols": cycle_info,
                    })

        return {
            "dead_code": dead_code,
            "dead_cycles": dead_cycles,
            "total_found": len(dead_code),
            "cycles_found": len(dead_cycles),
        }

    except Exception as e:
        return {"error": str(e), "dead_code": [], "dead_cycles": [], "total_found": 0}


async def _explore_dead_code_simple(
    storage: StorageManager,
    limit: int,
) -> dict[str, Any]:
    """
    Simple dead code detection fallback when no relationships exist.

    Uses basic SQL query to find symbols with no references.
    """
    cursor = storage.conn.cursor()

    cursor.execute("""
        SELECT s.id, s.name, s.kind, s.file_path, s.start_line, s.signature
        FROM symbols s
        WHERE s.kind IN ('function', 'class')
        AND s.name NOT LIKE 'test\\_%' ESCAPE '\\'
        AND s.name NOT LIKE 'Test%'
        AND s.name NOT LIKE '\\_%' ESCAPE '\\'
        AND s.file_path NOT LIKE '%test%'
        AND s.file_path NOT LIKE '%fixture%'
        AND s.name NOT IN (
            SELECT DISTINCT i.name FROM identifiers i
            WHERE i.file_path != s.file_path
        )
        ORDER BY s.file_path, s.name
        LIMIT ?
    """, (limit,))

    dead_code = []
    for row in cursor.fetchall():
        dead_code.append({
            "name": row[1],
            "kind": row[2],
            "file_path": row[3],
            "start_line": row[4],
            "signature": row[5],
            "reason": "no_cross_file_references",
        })

    return {
        "dead_code": dead_code,
        "dead_cycles": [],
        "total_found": len(dead_code),
        "cycles_found": 0,
    }


async def _explore_hot_spots(
    storage: Optional[StorageManager],
    limit: int,
) -> dict[str, Any]:
    """
    Find most-referenced symbols (high-impact code).

    Hot spots = symbols that are referenced most frequently across the codebase.
    These are high-impact areas where changes need careful consideration.

    Only counts cross-file references (not self-references within the same file).
    Only includes project-defined symbols (joins with symbols table).

    Args:
        storage: StorageManager instance
        limit: Maximum results to return

    Returns:
        Dict with hot_spots list (ranked by ref_count) and total_found count
    """
    # Get storage from global if not provided
    if storage is None:
        import miller.server as server
        storage = server.storage

    if storage is None:
        return {"error": "Storage not initialized", "hot_spots": [], "total_found": 0}

    try:
        cursor = storage.conn.cursor()

        # Find symbols with most cross-file references
        # Only count references from files OTHER than where the symbol is defined
        cursor.execute("""
            SELECT
                s.id,
                s.name,
                s.kind,
                s.file_path,
                s.start_line,
                s.signature,
                COUNT(*) as ref_count,
                COUNT(DISTINCT i.file_path) as file_count
            FROM symbols s
            INNER JOIN identifiers i ON s.name = i.name
            WHERE s.kind IN ('function', 'method', 'class')
            AND s.file_path NOT LIKE '%test%'
            AND s.file_path NOT LIKE '%fixture%'
            AND i.file_path != s.file_path  -- Cross-file references only
            GROUP BY s.id
            HAVING ref_count > 0
            ORDER BY ref_count DESC, file_count DESC
            LIMIT ?
        """, (limit,))

        hot_spots = []
        for row in cursor.fetchall():
            hot_spots.append({
                "name": row[1],
                "kind": row[2],
                "file_path": row[3],
                "start_line": row[4],
                "signature": row[5],
                "ref_count": row[6],
                "file_count": row[7],
            })

        return {
            "hot_spots": hot_spots,
            "total_found": len(hot_spots),
        }

    except Exception as e:
        return {"error": str(e), "hot_spots": [], "total_found": 0}


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


def _format_dead_code_as_text(result: dict[str, Any]) -> str:
    """Format dead_code mode result as lean text output.

    Output format:
    ```
    Dead code candidates (3 symbols):

      src/orphan.py:15 → def unused_helper()
      src/legacy.py:42 → class OldHandler
      src/utils.py:88 → def deprecated_func()
    ```
    """
    total = result.get("total_found", 0)
    error = result.get("error")

    if error:
        return f"Dead code scan: Error - {error}"

    if total == 0:
        return "Dead code scan: No unreferenced symbols found. ✨"

    output = [f"Dead code candidates ({total} symbols):", ""]

    for item in result.get("dead_code", []):
        name = item.get("name", "?")
        kind = item.get("kind", "symbol")
        file_path = item.get("file_path", "?")
        line = item.get("start_line", 0)
        sig = item.get("signature", name)
        if sig and len(sig) > 55:
            sig = sig[:52] + "..."

        output.append(f"  {file_path}:{line} → {sig}")

    output.append("")
    output.append("Note: Review before deleting - may be used dynamically or externally.")

    return "\n".join(output)


def _format_hot_spots_as_text(result: dict[str, Any]) -> str:
    """Format hot_spots mode result as lean text output.

    Output format:
    ```
    High-impact symbols (10 most referenced):

      395 refs (29 files) src/utils.py:15 → def helper_func()
      210 refs (18 files) src/core.py:42 → class StorageManager
      ...
    ```
    """
    total = result.get("total_found", 0)
    error = result.get("error")

    if error:
        return f"Hot spots scan: Error - {error}"

    if total == 0:
        return "Hot spots scan: No frequently-referenced symbols found."

    output = [f"High-impact symbols ({total} most referenced):", ""]

    for item in result.get("hot_spots", []):
        name = item.get("name", "?")
        file_path = item.get("file_path", "?")
        line = item.get("start_line", 0)
        ref_count = item.get("ref_count", 0)
        file_count = item.get("file_count", 0)
        sig = item.get("signature", name)
        if sig and len(sig) > 45:
            sig = sig[:42] + "..."

        output.append(f"  {ref_count} refs ({file_count} files) {file_path}:{line} → {sig}")

    return "\n".join(output)
