"""
Trace node building functions.
"""

from collections import defaultdict
from typing import Any, Optional
from miller.storage import StorageManager
from miller.tools.trace_types import TraceDirection, TraceNode
from miller.tools.naming import generate_variants
from .search import _find_variant_matches, _compute_semantic_similarity, semantic_neighbors


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
    cycles_detected_ref: list[int],
    enable_semantic: bool = False,
    embeddings=None,
    vector_store=None,  # NEW: For true semantic discovery
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
        storage, symbol_id, symbol["name"], direction, visited, cycles_detected_ref,
        enable_semantic, embeddings, vector_store, symbol  # Pass vector_store + full symbol for semantic discovery
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
            cycles_detected_ref=cycles_detected_ref,
            enable_semantic=enable_semantic,
            embeddings=embeddings,
            vector_store=vector_store,  # Pass through for recursive semantic discovery
        )

        # Normalize relationship kind (tree-sitter uses lowercase plural, we use singular capitalized)
        normalized_kind = relationship_kind.capitalize().rstrip("s") if relationship_kind.endswith("s") else relationship_kind.capitalize()
        child["relationship_kind"] = normalized_kind
        child["match_type"] = match_type

        # Set confidence if available (for semantic matches)
        if "confidence" in rel_symbol:
            child["confidence"] = rel_symbol["confidence"]

        node["children"].append(child)

    return node


def _find_related_symbols(
    storage: StorageManager,
    symbol_id: str,
    symbol_name: str,
    direction: TraceDirection,
    visited: set[str],
    cycles_detected_ref: list[int],
    enable_semantic: bool = False,
    embeddings=None,
    vector_store=None,  # NEW: For true semantic discovery
    source_symbol: dict[str, Any] = None,  # NEW: Full symbol for semantic search
) -> list[tuple[dict[str, Any], str, str]]:
    """
    Find symbols related to the given symbol via relationships.

    Uses naming variants for cross-language matching, and optionally
    TRUE semantic discovery via vector search.

    Args:
        storage: StorageManager instance
        symbol_id: ID of current symbol
        symbol_name: Name of current symbol
        direction: Trace direction
        visited: Set of already-visited symbol IDs
        vector_store: VectorStore for semantic discovery (optional)
        source_symbol: Full symbol dict for semantic embedding (optional)

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
                cycles_detected_ref[0] += 1
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

            # Determine match type: reflects HOW the match was found
            # "exact" = found via database relationship query
            # "variant" = name matches a naming variant
            # "semantic" = found via vector search (only from semantic_neighbors)
            related_name = symbol_dict["name"]
            if related_name in variant_names and related_name != symbol_name:
                match_type = "variant"
            else:
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
                cycles_detected_ref[0] += 1
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

            # Determine match type: reflects HOW the match was found
            related_name = symbol_dict["name"]
            if related_name in variant_names and related_name != symbol_name:
                match_type = "variant"
            else:
                match_type = "exact"
            results.append((symbol_dict, relationship_kind, match_type))

    # FALLBACK: Use identifiers table for upstream when relationships are missing
    # This handles the case where calls exist but relationships weren't created
    # (e.g., calls to imported functions that aren't resolved at extraction time)
    if (direction == "upstream" or direction == "both") and len(results) == 0:
        # Find identifiers that reference this symbol by name or target_symbol_id
        # Then look up their containing_symbol_id to find the calling functions
        cursor.execute(
            """
            SELECT DISTINCT s.id, s.name, s.kind, s.language, s.file_path,
                   s.start_line, s.end_line, s.signature, s.doc_comment
            FROM identifiers i
            JOIN symbols s ON i.containing_symbol_id = s.id
            WHERE (i.name = ? OR i.target_symbol_id = ?)
              AND i.containing_symbol_id IS NOT NULL
              AND i.containing_symbol_id != ?
            """,
            (symbol_name, symbol_id, symbol_id),
        )

        for row in cursor.fetchall():
            containing_symbol_id = row[0]

            if containing_symbol_id in visited:
                cycles_detected_ref[0] += 1
                continue  # Skip cycles

            symbol_dict = {
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

            # These are callers found via identifiers - mark as "Call" relationship
            results.append((symbol_dict, "Call", "exact"))

    # Add variant matching for cross-language relationships
    # This is the MAGIC: find symbols with different names but similar meanings
    # Example: UserService → user_service → users
    if len(results) < 5:  # Only do variant matching if we haven't found many exact matches
        variant_results = _find_variant_matches(
            storage, symbol_name, variant_names, visited, direction
        )
        results.extend(variant_results)

    # TRUE SEMANTIC DISCOVERY: Use vector search to find cross-language connections
    # This finds symbols with semantically similar names/docs even when:
    # - No database relationship exists
    # - No naming variant matches
    # Example: "authenticate" → "verifyCredentials" → "check_auth"
    if enable_semantic and vector_store is not None and source_symbol is not None:
        # Get IDs we've already found to avoid duplicates
        found_ids = {r[0].get("id") for r in results}

        semantic_matches = semantic_neighbors(
            storage=storage,
            vector_store=vector_store,
            embeddings=embeddings,
            symbol=source_symbol,
            limit=8,
            threshold=0.7,
            cross_language_only=True,  # Focus on cross-language discovery
        )

        for match in semantic_matches:
            match_id = match.get("symbol_id")

            # Skip if already found via other methods or already visited
            if match_id in found_ids or match_id in visited:
                continue

            # Convert SemanticMatch to symbol dict format
            symbol_dict = {
                "id": match["symbol_id"],
                "name": match["name"],
                "kind": match["kind"],
                "language": match["language"],
                "file_path": match["file_path"],
                "start_line": match["line"],
                "end_line": match.get("line", 0),  # Use same line if not available
                "signature": match.get("signature"),
                "doc_comment": match.get("doc_comment"),
                "confidence": match["similarity"],  # Store similarity as confidence
            }

            results.append((symbol_dict, match["relationship_kind"], "semantic"))
            found_ids.add(match_id)

    return results


