"""
Cross-language call tracing implementation.

Uses naming variants to trace execution flow across language boundaries.
"""

import time
from collections import defaultdict
from typing import Any, Optional

from miller.storage import StorageManager
from miller.tools.naming_variants import generate_variants
from miller.tools.trace_types import (
    DEFAULT_MAX_DEPTH,
    MAX_ALLOWED_DEPTH,
    TraceDirection,
    TraceNode,
    TracePath,
)


async def trace_call_path(
    storage: StorageManager,
    symbol_name: str,
    direction: TraceDirection = "downstream",
    max_depth: int = DEFAULT_MAX_DEPTH,
    context_file: Optional[str] = None,
    output_format: str = "json",
    workspace: str = "primary",
    enable_semantic: bool = False,
) -> dict[str, Any] | str:
    """
    Trace call paths across language boundaries using naming variants.

    Args:
        storage: StorageManager instance
        symbol_name: Symbol to trace from
        direction: "upstream" (callers), "downstream" (callees), or "both"
        max_depth: Maximum depth to traverse (1-10)
        context_file: Optional file path to disambiguate symbols
        output_format: "json" or "tree"
        workspace: Workspace identifier (currently unused, for future multi-workspace)
        enable_semantic: Whether to use semantic similarity fallback (future feature)

    Returns:
        TracePath dict if output_format="json", formatted string if "tree"

    Raises:
        ValueError: If max_depth is invalid or direction is invalid
    """
    start_time = time.time()

    # Validate inputs
    if max_depth < 1 or max_depth > MAX_ALLOWED_DEPTH:
        raise ValueError(
            f"max_depth must be between 1 and {MAX_ALLOWED_DEPTH}, got {max_depth}"
        )

    if direction not in ["upstream", "downstream", "both"]:
        raise ValueError(
            f"direction must be 'upstream', 'downstream', or 'both', got '{direction}'"
        )

    # Find starting symbol(s)
    symbols = _find_symbols(storage, symbol_name, context_file)

    if not symbols:
        # Symbol not found - return empty result
        execution_time = (time.time() - start_time) * 1000
        return {
            "query_symbol": symbol_name,
            "direction": direction,
            "max_depth": max_depth,
            "total_nodes": 0,
            "error": f"Symbol '{symbol_name}' not found in workspace '{workspace}'",
            "execution_time_ms": execution_time,
        }

    # For simplicity, use first matching symbol (TODO: handle multiple matches)
    start_symbol = symbols[0]

    # Build trace tree
    visited = set()  # Track visited symbols to prevent cycles
    languages_found = set()
    match_types_count = defaultdict(int)
    relationship_kinds_count = defaultdict(int)
    nodes_visited_ref = [0]  # Use list to modify in place in recursive function

    root = _build_trace_node(
        storage=storage,
        symbol=start_symbol,
        direction=direction,
        current_depth=0,
        max_depth=max_depth,
        visited=visited,
        languages_found=languages_found,
        match_types_count=match_types_count,
        relationship_kinds_count=relationship_kinds_count,
        nodes_visited_ref=nodes_visited_ref,
    )

    # Count total nodes
    total_nodes = _count_nodes(root)

    # Check if truncated
    max_depth_reached = _get_max_depth(root)
    truncated = max_depth_reached >= max_depth

    execution_time = (time.time() - start_time) * 1000

    result: TracePath = {
        "query_symbol": symbol_name,
        "direction": direction,
        "max_depth": max_depth,
        "root": root,
        "total_nodes": total_nodes,
        "max_depth_reached": max_depth_reached,
        "truncated": truncated,
        "languages_found": sorted(languages_found),
        "match_types": dict(match_types_count),
        "relationship_kinds": dict(relationship_kinds_count),
        "execution_time_ms": execution_time,
        "nodes_visited": nodes_visited_ref[0],
    }

    if output_format == "tree":
        return _format_as_tree(root)
    else:
        return result


def _find_symbols(
    storage: StorageManager, symbol_name: str, context_file: Optional[str] = None
) -> list[dict[str, Any]]:
    """
    Find symbol(s) in database by name.

    Args:
        storage: StorageManager instance
        symbol_name: Symbol name to search for
        context_file: Optional file path to filter results

    Returns:
        List of symbol dicts (may be empty if not found)
    """
    cursor = storage.conn.cursor()

    if context_file:
        # Disambiguate with file path
        cursor.execute(
            """
            SELECT id, name, kind, language, file_path, start_line, end_line,
                   signature, doc_comment
            FROM symbols
            WHERE name = ? AND file_path = ?
            LIMIT 1
            """,
            (symbol_name, context_file),
        )
    else:
        # Find all symbols with this name
        cursor.execute(
            """
            SELECT id, name, kind, language, file_path, start_line, end_line,
                   signature, doc_comment
            FROM symbols
            WHERE name = ?
            """,
            (symbol_name,),
        )

    rows = cursor.fetchall()

    symbols = []
    for row in rows:
        symbols.append(
            {
                "id": row[0],
                "name": row[1],
                "kind": row[2],
                "language": row[3],
                "file_path": row[4],
                "start_line": row[5],
                "end_line": row[6],
                "signature": row[7],
                "doc_comment": row[8],
            }
        )

    return symbols


def _build_trace_node(
    storage: StorageManager,
    symbol: dict[str, Any],
    direction: TraceDirection,
    current_depth: int,
    max_depth: int,
    visited: set[str],
    languages_found: set[str],
    match_types_count: dict[str, int],
    relationship_kinds_count: dict[str, int],
    nodes_visited_ref: list[int],
) -> TraceNode:
    """
    Recursively build trace tree starting from a symbol.

    Args:
        storage: StorageManager instance
        symbol: Starting symbol dict
        direction: Trace direction
        current_depth: Current depth in tree
        max_depth: Maximum depth to traverse
        visited: Set of visited symbol IDs (for cycle detection)
        languages_found: Set to collect languages encountered
        match_types_count: Dict to count match types
        relationship_kinds_count: Dict to count relationship kinds
        nodes_visited_ref: List containing node visit count (mutable)

    Returns:
        TraceNode dict
    """
    symbol_id = symbol["id"]
    nodes_visited_ref[0] += 1

    # Add to visited set
    visited.add(symbol_id)

    # Track language
    languages_found.add(symbol["language"])

    # Create node
    node: TraceNode = {
        "symbol_id": symbol_id,
        "name": symbol["name"],
        "kind": symbol["kind"],
        "file_path": symbol["file_path"],
        "line": symbol["start_line"],
        "language": symbol["language"],
        "relationship_kind": "Definition" if current_depth == 0 else "Call",
        "match_type": "exact",
        "confidence": None,
        "depth": current_depth,
        "children": [],
        "signature": symbol.get("signature"),
        "doc_comment": symbol.get("doc_comment"),
    }

    # Stop if max depth reached
    if current_depth >= max_depth:
        return node

    # Find related symbols
    related = _find_related_symbols(
        storage, symbol_id, symbol["name"], direction, visited
    )

    for rel_symbol, relationship_kind, match_type in related:
        # Track stats
        relationship_kinds_count[relationship_kind] += 1
        match_types_count[match_type] += 1

        # Recursively build child node
        child = _build_trace_node(
            storage=storage,
            symbol=rel_symbol,
            direction=direction,
            current_depth=current_depth + 1,
            max_depth=max_depth,
            visited=visited.copy(),  # Copy to allow different paths
            languages_found=languages_found,
            match_types_count=match_types_count,
            relationship_kinds_count=relationship_kinds_count,
            nodes_visited_ref=nodes_visited_ref,
        )

        child["relationship_kind"] = relationship_kind
        child["match_type"] = match_type

        node["children"].append(child)

    return node


def _find_related_symbols(
    storage: StorageManager,
    symbol_id: str,
    symbol_name: str,
    direction: TraceDirection,
    visited: set[str],
) -> list[tuple[dict[str, Any], str, str]]:
    """
    Find symbols related to the given symbol via relationships.

    Uses naming variants for cross-language matching.

    Args:
        storage: StorageManager instance
        symbol_id: ID of current symbol
        symbol_name: Name of current symbol
        direction: Trace direction
        visited: Set of already-visited symbol IDs

    Returns:
        List of (symbol_dict, relationship_kind, match_type) tuples
    """
    cursor = storage.conn.cursor()
    results = []

    # Generate naming variants for cross-language matching
    variants = generate_variants(symbol_name)
    variant_names = set(variants.values())

    if direction == "downstream" or direction == "both":
        # Find symbols this symbol calls/references
        cursor.execute(
            """
            SELECT r.to_symbol_id, r.kind, s.id, s.name, s.kind, s.language,
                   s.file_path, s.start_line, s.end_line, s.signature, s.doc_comment
            FROM relationships r
            JOIN symbols s ON r.to_symbol_id = s.id
            WHERE r.from_symbol_id = ?
            """,
            (symbol_id,),
        )

        for row in cursor.fetchall():
            to_symbol_id = row[0]
            relationship_kind = row[1]

            if to_symbol_id in visited:
                continue  # Skip cycles

            symbol_dict = {
                "id": row[2],
                "name": row[3],
                "kind": row[4],
                "language": row[5],
                "file_path": row[6],
                "start_line": row[7],
                "end_line": row[8],
                "signature": row[9],
                "doc_comment": row[10],
            }

            # Determine match type (exact for now, variant matching later)
            match_type = "exact"
            results.append((symbol_dict, relationship_kind, match_type))

    if direction == "upstream" or direction == "both":
        # Find symbols that call/reference this symbol
        cursor.execute(
            """
            SELECT r.from_symbol_id, r.kind, s.id, s.name, s.kind, s.language,
                   s.file_path, s.start_line, s.end_line, s.signature, s.doc_comment
            FROM relationships r
            JOIN symbols s ON r.from_symbol_id = s.id
            WHERE r.to_symbol_id = ?
            """,
            (symbol_id,),
        )

        for row in cursor.fetchall():
            from_symbol_id = row[0]
            relationship_kind = row[1]

            if from_symbol_id in visited:
                continue  # Skip cycles

            symbol_dict = {
                "id": row[2],
                "name": row[3],
                "kind": row[4],
                "language": row[5],
                "file_path": row[6],
                "start_line": row[7],
                "end_line": row[8],
                "signature": row[9],
                "doc_comment": row[10],
            }

            match_type = "exact"
            results.append((symbol_dict, relationship_kind, match_type))

    # Add variant matching for cross-language relationships
    # This is the MAGIC: find symbols with different names but similar meanings
    # Example: UserService → user_service → users
    if len(results) < 5:  # Only do variant matching if we haven't found many exact matches
        variant_results = _find_variant_matches(
            storage, symbol_name, variant_names, visited, direction
        )
        results.extend(variant_results)

    return results


def _find_variant_matches(
    storage: StorageManager,
    symbol_name: str,
    variant_names: set[str],
    visited: set[str],
    direction: TraceDirection,
) -> list[tuple[dict[str, Any], str, str]]:
    """
    Find symbols using naming variant matching.

    This enables cross-language tracing:
    - TypeScript UserService → Python user_service
    - Python User → SQL users
    - C# IUser → Python user

    Args:
        storage: StorageManager instance
        symbol_name: Original symbol name
        variant_names: Set of all naming variants to try
        visited: Set of visited symbol IDs
        direction: Trace direction (for relationship queries)

    Returns:
        List of (symbol_dict, relationship_kind, match_type) tuples
    """
    cursor = storage.conn.cursor()
    results = []

    # Search for symbols matching any of the variants
    # Build a query with IN clause for efficiency
    placeholders = ",".join("?" * len(variant_names))

    # Find symbols with names matching our variants
    cursor.execute(
        f"""
        SELECT id, name, kind, language, file_path, start_line, end_line,
               signature, doc_comment
        FROM symbols
        WHERE name IN ({placeholders})
        """,
        tuple(variant_names),
    )

    variant_symbols = {}
    for row in cursor.fetchall():
        symbol_id = row[0]
        if symbol_id not in visited:
            variant_symbols[symbol_id] = {
                "id": row[0],
                "name": row[1],
                "kind": row[2],
                "language": row[3],
                "file_path": row[4],
                "start_line": row[5],
                "end_line": row[6],
                "signature": row[7],
                "doc_comment": row[8],
            }

    # Now check if any of these variant symbols have relationships
    # that could be cross-language connections
    for symbol_id, symbol_dict in variant_symbols.items():
        # Heuristic: if the symbol is in a different language than the original,
        # it's likely a cross-language connection
        # Mark these as "variant" matches with "Reference" relationship

        # For now, add them as potential cross-language references
        # A more sophisticated approach would check for actual import/usage patterns
        results.append((symbol_dict, "Reference", "variant"))

        # Limit results to prevent explosion
        if len(results) >= 10:
            break

    return results


def _count_nodes(node: TraceNode) -> int:
    """Count total nodes in tree."""
    count = 1
    for child in node["children"]:
        count += _count_nodes(child)
    return count


def _get_max_depth(node: TraceNode) -> int:
    """Get maximum depth reached in tree."""
    if not node["children"]:
        return node["depth"]

    return max(_get_max_depth(child) for child in node["children"])


def _format_as_tree(node: TraceNode, indent: str = "", is_last: bool = True) -> str:
    """
    Format trace tree as human-readable ASCII tree.

    Example output:
        UserService (typescript) @ src/services/user.ts:10
        ├─[Call]→ user_service (python) @ api/users.py:5
        │  └─[Call]→ User (python) @ models/user.py:12
        └─[Call]→ createUser (typescript) @ src/api/users.ts:22
    """
    # Build line for current node
    connector = "└─" if is_last else "├─"
    if node["depth"] == 0:
        # Root node - no connector
        line = f"{node['name']} ({node['language']}) @ {node['file_path']}:{node['line']}\n"
    else:
        rel_kind = node.get("relationship_kind", "Call")
        line = f"{indent}{connector}[{rel_kind}]→ {node['name']} ({node['language']}) @ {node['file_path']}:{node['line']}\n"

    # Recursively format children
    for i, child in enumerate(node["children"]):
        is_child_last = i == len(node["children"]) - 1
        if node["depth"] == 0:
            child_indent = ""
        else:
            child_indent = indent + ("   " if is_last else "│  ")
        line += _format_as_tree(child, child_indent, is_child_last)

    return line
