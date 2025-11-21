"""
Type definitions for TOON format support in Miller.

This module defines the contract for TOON (Token-Oriented Object Notation) support,
which reduces token usage by 30-60% compared to JSON for LLM contexts.
"""

from typing import Any, Literal, TypedDict, Union


# Output format modes
OutputFormat = Literal["json", "toon", "auto"]


class ToonSymbol(TypedDict, total=False):
    """
    Symbol representation optimized for TOON encoding.

    TOON requires primitive types (str, int, float, bool) only. No nested objects.
    This is a flattened version of the full Symbol structure for efficient encoding.

    Required fields:
        name: Symbol name (e.g., "UserService", "calculate_age")
        kind: Symbol kind (e.g., "Class", "Function", "Method")
        file_path: Relative path to file containing symbol
        start_line: Starting line number (1-indexed)

    Optional fields:
        signature: Function/method signature (e.g., "(name: str) -> str")
        doc_comment: First line of docstring/comment (truncated to 100 chars)
        score: Search relevance score (0.0-1.0)
        end_line: Ending line number (1-indexed)
        language: Programming language (e.g., "python", "rust")
    """

    # Required fields
    name: str
    kind: str
    file_path: str
    start_line: int

    # Optional fields
    signature: str
    doc_comment: str
    score: float
    end_line: int
    language: str


# Union type for fast_search return value
# - JSON mode: Returns list of dicts (structured data)
# - TOON mode: Returns string (text-only format)
FastSearchResult = Union[list[dict[str, Any]], str]


class ToonConfig(TypedDict):
    """
    Configuration for TOON encoding behavior.

    threshold: Number of results where auto mode switches from JSON to TOON.
               Default: 20 results (based on Julie's proven threshold)
    fallback_on_error: If True, return JSON when TOON encoding fails.
                       Default: True (graceful degradation)
    max_doc_length: Maximum doc_comment length to include in TOON output.
                    Default: 100 chars (prevents token bloat)
    """

    threshold: int
    fallback_on_error: bool
    max_doc_length: int


# Default TOON configuration (matches Julie's proven settings)
DEFAULT_TOON_CONFIG: ToonConfig = {
    "threshold": 20,  # ≥20 results → use TOON in auto mode
    "fallback_on_error": True,  # Graceful fallback to JSON
    "max_doc_length": 100,  # Truncate long docstrings
}


def format_symbol_for_toon(symbol: dict[str, Any], max_doc_length: int = 100) -> ToonSymbol:
    """
    Convert a Symbol dict to ToonSymbol format (primitives only).

    Flattens nested structures and truncates long strings to keep TOON output compact.

    Args:
        symbol: Full symbol dict from vector store
        max_doc_length: Maximum length for doc_comment field

    Returns:
        ToonSymbol dict with only primitive types

    Error conditions:
        - Missing required fields: Fills with empty string/"Unknown"/0
        - Long doc_comment: Truncated to max_doc_length with "..." suffix
        - Non-primitive values: Converted to string via str()

    Examples:
        >>> symbol = {"name": "hello", "kind": "Function", "file_path": "test.py",
        ...           "start_line": 1, "doc_comment": "A" * 200}
        >>> toon_sym = format_symbol_for_toon(symbol, max_doc_length=100)
        >>> len(toon_sym["doc_comment"])
        100
        >>> toon_sym["doc_comment"].endswith("...")
        True
    """
    # CRITICAL: All symbols must have IDENTICAL fields for TOON table format
    # Always include all fields (use None for missing) to ensure schema homogeneity

    # Required fields (always present)
    toon: ToonSymbol = {
        "name": symbol.get("name", ""),
        "kind": symbol.get("kind", "Unknown"),
        "file_path": symbol.get("file_path", ""),
        "start_line": symbol.get("start_line", 0),
    }

    # Optional fields (ALWAYS include, even if None, for schema consistency)
    # Process doc_comment
    if "doc_comment" in symbol and symbol["doc_comment"]:
        doc = str(symbol["doc_comment"])
        toon["doc_comment"] = doc[: max_doc_length - 3] + "..." if len(doc) > max_doc_length else doc
    else:
        toon["doc_comment"] = None

    # Process end_line
    toon["end_line"] = int(symbol["end_line"]) if "end_line" in symbol else None

    # Process language
    toon["language"] = str(symbol["language"]) if "language" in symbol else None

    # Process score
    if "score" in symbol:
        try:
            toon["score"] = float(symbol["score"])
        except (ValueError, TypeError):
            toon["score"] = None
    else:
        toon["score"] = None

    # Process signature
    toon["signature"] = str(symbol["signature"]) if ("signature" in symbol and symbol["signature"]) else None

    return toon


def encode_toon(
    symbols: list[dict[str, Any]], config: ToonConfig = DEFAULT_TOON_CONFIG
) -> Union[str, list[dict[str, Any]]]:
    """
    Encode symbols to TOON format with graceful fallback.

    Converts list of symbol dicts to TOON string format. If encoding fails,
    returns original JSON format (graceful degradation).

    Args:
        symbols: List of symbol dicts from vector store
        config: TOON configuration (threshold, fallback behavior, etc.)

    Returns:
        - Success: TOON-encoded string
        - Failure (if fallback_on_error=True): Original symbols list (JSON format)
        - Failure (if fallback_on_error=False): Raises exception

    Error conditions:
        - Empty input: Returns "# No results found" (TOON format)
        - TOON encoding fails: Returns original symbols list if fallback enabled
        - Invalid symbol structure: Converts to ToonSymbol with safe defaults

    Boundary conditions:
        - 0 symbols: Returns "# No results found"
        - 1 symbol: TOON encoding still works (no minimum)
        - 1000+ symbols: TOON handles efficiently (CSV-like tabular format)

    Examples:
        >>> symbols = [
        ...     {"name": "test", "kind": "Function", "file_path": "test.py", "start_line": 1}
        ... ]
        >>> result = encode_toon(symbols)
        >>> isinstance(result, str)
        True
        >>> "name: test" in result or isinstance(result, list)  # TOON string or fallback
        True
    """
    # Import here to avoid circular dependency and keep module lightweight
    from toon_format import encode as toon_encode

    # Handle empty results
    if not symbols:
        return "# No results found"

    try:
        # Convert all symbols to TOON-compatible format
        toon_symbols = [
            format_symbol_for_toon(sym, max_doc_length=config["max_doc_length"])
            for sym in symbols
        ]

        # Encode to TOON format
        toon_str = toon_encode(toon_symbols)

        return toon_str

    except Exception as e:
        # Fallback to JSON if TOON encoding fails
        if config["fallback_on_error"]:
            # Log the error for debugging (don't raise)
            from miller.logging_config import setup_logging

            logger = setup_logging()
            logger.warning(
                f"TOON encoding failed, falling back to JSON: {e}", exc_info=True
            )
            return symbols
        else:
            # Re-raise if fallback disabled
            raise


def should_use_toon(
    output_format: OutputFormat, result_count: int, config: ToonConfig = DEFAULT_TOON_CONFIG
) -> bool:
    """
    Determine whether to use TOON format based on mode and result count.

    Implements three-mode logic:
    - "json": Always return JSON (structured data)
    - "toon": Always return TOON (text-only format)
    - "auto": Use TOON if result_count >= threshold, else JSON

    Args:
        output_format: Format mode ("json", "toon", "auto")
        result_count: Number of results being returned
        config: TOON configuration with threshold

    Returns:
        True if TOON should be used, False for JSON

    Examples:
        >>> should_use_toon("json", 100)
        False
        >>> should_use_toon("toon", 5)
        True
        >>> should_use_toon("auto", 25)  # ≥20 threshold
        True
        >>> should_use_toon("auto", 15)  # <20 threshold
        False
    """
    if output_format == "json":
        return False
    elif output_format == "toon":
        return True
    else:  # "auto"
        return result_count >= config["threshold"]


def format_trace_node_for_toon(node: dict[str, Any]) -> dict[str, Any]:
    """
    **DEPRECATED**: Use encode_hierarchical_toon() instead for better token efficiency.

    This function produces nested TOON format which does NOT guarantee schema homogeneity
    and results in YAML-style output with repeated keys (~45% reduction vs 63% with hierarchical).

    Only used for testing and benchmarking. Production code should use:
    - encode_hierarchical_toon() for trace_call_path (63% token reduction)
    - encode_toon() for flat lists like fast_search (60%+ reduction)

    Convert a TraceNode dict to TOON-compatible format (primitives + nested arrays).

    Recursively processes children nodes while keeping structure flat enough for TOON.

    Args:
        node: TraceNode dict with potential nested children

    Returns:
        TOON-compatible dict with children as array

    Examples:
        >>> node = {
        ...     "name": "UserService",
        ...     "kind": "Class",
        ...     "file_path": "user.ts",
        ...     "line": 10,
        ...     "children": [{"name": "save", "kind": "Method", "line": 15, "children": []}]
        ... }
        >>> toon_node = format_trace_node_for_toon(node)
        >>> "name" in toon_node
        True
        >>> isinstance(toon_node["children"], list)
        True
    """
    # Create base TOON node (primitives only, no nested objects)
    toon_node: dict[str, Any] = {
        "name": node.get("name", ""),
        "kind": node.get("kind", "Unknown"),
        "file_path": node.get("file_path", ""),
        "line": node.get("line", 0),
        "language": node.get("language", ""),
        "depth": node.get("depth", 0),
    }

    # Add optional primitive fields
    if "symbol_id" in node:
        toon_node["symbol_id"] = str(node["symbol_id"])

    if "relationship_kind" in node:
        toon_node["relationship_kind"] = str(node["relationship_kind"])

    if "match_type" in node:
        toon_node["match_type"] = str(node["match_type"])

    if "confidence" in node and node["confidence"] is not None:
        toon_node["confidence"] = float(node["confidence"])

    if "signature" in node and node["signature"]:
        # Truncate long signatures
        sig = str(node["signature"])
        toon_node["signature"] = sig[:100] + "..." if len(sig) > 100 else sig

    if "doc_comment" in node and node["doc_comment"]:
        # Truncate long doc comments
        doc = str(node["doc_comment"])
        toon_node["doc_comment"] = doc[:100] + "..." if len(doc) > 100 else doc

    # Recursively process children
    children = node.get("children", [])
    if children:
        toon_node["children"] = [format_trace_node_for_toon(child) for child in children]
    else:
        toon_node["children"] = []

    return toon_node


def encode_trace_path_toon(
    trace_path: dict[str, Any], config: ToonConfig = DEFAULT_TOON_CONFIG
) -> Union[str, dict[str, Any]]:
    """
    **DEPRECATED**: Use encode_hierarchical_toon() with TracePathFlattener instead.

    This function produces nested TOON format (~45% reduction) instead of the superior
    flat table format with parent_id references (~63% reduction).

    Only used for testing and benchmarking. Production code (server.py) correctly uses:
    - TracePathFlattener to flatten the tree structure
    - encode_hierarchical_toon() for CSV-like compact encoding

    Encode TracePath to TOON format with graceful fallback.

    Handles deeply nested TraceNode structures efficiently. TOON's hierarchical
    syntax eliminates repeated braces/brackets at each nesting level.

    Args:
        trace_path: TracePath dict with nested root TraceNode
        config: TOON configuration (threshold, fallback behavior, etc.)

    Returns:
        - Success: TOON-encoded string
        - Failure (if fallback_on_error=True): Original trace_path dict (JSON format)
        - Failure (if fallback_on_error=False): Raises exception

    Examples:
        >>> trace_path = {
        ...     "query_symbol": "User",
        ...     "direction": "downstream",
        ...     "max_depth": 3,
        ...     "root": {"name": "User", "kind": "Class", "line": 10, "children": []},
        ...     "total_nodes": 1
        ... }
        >>> result = encode_trace_path_toon(trace_path)
        >>> isinstance(result, str)
        True
    """
    from toon_format import encode as toon_encode

    try:
        # Format root node for TOON (recursive)
        if "root" in trace_path and trace_path["root"]:
            formatted_root = format_trace_node_for_toon(trace_path["root"])
        else:
            # No root node - empty trace
            formatted_root = None

        # Create TOON-friendly TracePath structure
        toon_trace = {
            "query_symbol": trace_path.get("query_symbol", ""),
            "direction": trace_path.get("direction", "downstream"),
            "max_depth": trace_path.get("max_depth", 3),
            "total_nodes": trace_path.get("total_nodes", 0),
            "max_depth_reached": trace_path.get("max_depth_reached", 0),
            "truncated": trace_path.get("truncated", False),
        }

        # Add root if present
        if formatted_root:
            toon_trace["root"] = formatted_root

        # Add optional metadata fields
        if "languages_found" in trace_path:
            toon_trace["languages_found"] = trace_path["languages_found"]

        if "match_types" in trace_path:
            toon_trace["match_types"] = trace_path["match_types"]

        if "relationship_kinds" in trace_path:
            toon_trace["relationship_kinds"] = trace_path["relationship_kinds"]

        if "execution_time_ms" in trace_path:
            toon_trace["execution_time_ms"] = float(trace_path["execution_time_ms"])

        if "nodes_visited" in trace_path:
            toon_trace["nodes_visited"] = int(trace_path["nodes_visited"])

        # Handle error case
        if "error" in trace_path:
            toon_trace["error"] = str(trace_path["error"])

        # Encode to TOON
        toon_str = toon_encode(toon_trace)
        return toon_str

    except Exception as e:
        # Fallback to JSON if TOON encoding fails
        if config["fallback_on_error"]:
            from miller.logging_config import setup_logging

            logger = setup_logging()
            logger.warning(
                f"TOON encoding failed for TracePath, falling back to JSON: {e}",
                exc_info=True,
            )
            return trace_path
        else:
            raise


def encode_hierarchical_toon(
    hierarchical_data: "HierarchicalToonable",
    config: ToonConfig = DEFAULT_TOON_CONFIG,
) -> Union[str, list[dict[str, Any]]]:
    """
    Encode hierarchical data to TOON format using flat table with parent_id.

    This is the generic hierarchical TOON encoder that flattens recursive tree
    structures into a single flat table, achieving 60-70% token reduction.

    Args:
        hierarchical_data: Data implementing flatten() method (HierarchicalToonable protocol)
        config: TOON configuration (threshold, fallback behavior, etc.)

    Returns:
        - Success: TOON-encoded string (flat table format)
        - Failure (if fallback_on_error=True): Original data as list[dict] (JSON format)
        - Failure (if fallback_on_error=False): Raises exception

    Error conditions:
        - Empty tree: Returns "# No results found"
        - TOON encoding fails: Returns flattened nodes as JSON if fallback enabled

    Token Savings:
        - 63% reduction for trace_call_path (28,800 chars → 10,680 chars)
        - Works by eliminating repeated keys at each nesting level

    Example:
        >>> tree = TracePath(...)  # Has flatten() method
        >>> result = encode_hierarchical_toon(tree)
        >>> isinstance(result, str)  # TOON string
        True
        >>> "parent_id" in result  # Uses flat table format
        True
    """
    from toon_format import encode as toon_encode

    try:
        # Step 1: Flatten the hierarchical structure
        flattened_nodes = hierarchical_data.flatten()

        if not flattened_nodes:
            return "# No results found"

        # Step 2: Convert FlatNode objects to dicts for TOON encoding
        # This mimics #[serde(flatten)] by putting data fields at top level
        flat_dicts = [node.to_dict() for node in flattened_nodes]

        # Step 3: Encode to TOON format
        # IMPORTANT: Pass list directly (not wrapped in a dict) for true tabular encoding
        toon_str = toon_encode(flat_dicts)

        return toon_str

    except Exception as e:
        # Fallback to JSON if TOON encoding fails
        if config["fallback_on_error"]:
            from miller.logging_config import setup_logging

            logger = setup_logging()
            logger.warning(
                f"Hierarchical TOON encoding failed, falling back to JSON: {e}",
                exc_info=True,
            )
            # Return flattened nodes as JSON (still better than nested!)
            return [node.to_dict() for node in hierarchical_data.flatten()]
        else:
            raise
