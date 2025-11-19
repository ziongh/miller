"""
Symbol overview tools - Miller's enhanced get_symbols implementation

Provides different levels of code context based on reading mode and filtering options.
Better than Julie's implementation with Python/ML enhancements.
"""

from typing import Any, Optional
from pathlib import Path


def build_parent_to_children(symbols: list) -> dict[str, list[int]]:
    """Build a parent_id -> children indices map for efficient hierarchy navigation."""
    parent_to_children: dict[str, list[int]] = {}

    for idx, symbol in enumerate(symbols):
        parent_id = getattr(symbol, "parent_id", None)
        if parent_id:
            if parent_id not in parent_to_children:
                parent_to_children[parent_id] = []
            parent_to_children[parent_id].append(idx)

    return parent_to_children


def find_top_level_symbols(symbols: list) -> list[int]:
    """Find all top-level symbols (those with no parent)."""
    top_level = []
    for idx, symbol in enumerate(symbols):
        parent_id = getattr(symbol, "parent_id", None)
        if parent_id is None:
            top_level.append(idx)
    return top_level


def collect_symbols_by_depth(
    indices: list[int],
    depth: int,
    max_depth: int,
    all_symbols: list,
    parent_to_children: dict[str, list[int]],
    result: list[int]
):
    """Recursively collect symbols up to maximum depth."""
    if depth > max_depth:
        return

    for idx in indices:
        result.append(idx)

        if depth < max_depth:
            symbol_id = getattr(all_symbols[idx], "id", None)
            if symbol_id and symbol_id in parent_to_children:
                children_indices = parent_to_children[symbol_id]
                collect_symbols_by_depth(
                    children_indices,
                    depth + 1,
                    max_depth,
                    all_symbols,
                    parent_to_children,
                    result
                )


def apply_max_depth_filter(all_symbols: list, max_depth: int) -> list:
    """Apply max_depth filtering to symbols.

    Returns filtered symbols in original order, keeping only those within
    the maximum depth from top-level symbols.
    """
    parent_to_children = build_parent_to_children(all_symbols)
    top_level_indices = find_top_level_symbols(all_symbols)

    indices_to_include = []
    collect_symbols_by_depth(
        top_level_indices,
        0,
        max_depth,
        all_symbols,
        parent_to_children,
        indices_to_include
    )

    # Preserve original order
    indices_to_include.sort()

    return [all_symbols[idx] for idx in indices_to_include]


def apply_target_filter(symbols: list, target: str) -> list:
    """Filter symbols by target name (case-insensitive partial matching).

    Returns symbols matching the target AND their children (up to max_depth already applied).
    """
    if not target:
        return symbols

    target_lower = target.lower()
    matching_indices = set()

    # First pass: Find all symbols that match the target
    for idx, symbol in enumerate(symbols):
        symbol_name = getattr(symbol, "name", "")
        if target_lower in symbol_name.lower():
            matching_indices.add(idx)

    # Second pass: Include children of matching symbols
    parent_to_children = build_parent_to_children(symbols)

    def include_children(symbol_idx: int):
        """Recursively include all children of a symbol."""
        matching_indices.add(symbol_idx)
        symbol_id = getattr(symbols[symbol_idx], "id", None)
        if symbol_id and symbol_id in parent_to_children:
            for child_idx in parent_to_children[symbol_id]:
                include_children(child_idx)

    # Build final set including all children
    initial_matches = list(matching_indices)
    for idx in initial_matches:
        include_children(idx)

    # Return in original order
    result_indices = sorted(matching_indices)
    return [symbols[idx] for idx in result_indices]


def apply_limit(symbols: list, limit: Optional[int]) -> tuple[list, bool]:
    """Apply limit to symbols, preserving hierarchy.

    Returns (limited_symbols, was_truncated).
    """
    if limit is None or len(symbols) <= limit:
        return symbols, False

    # Simple truncation for now (preserve hierarchy in future enhancement)
    return symbols[:limit], True


def extract_code_bodies(
    symbols: list,
    file_path: str,
    mode: str
) -> list:
    """Extract code bodies for symbols based on mode parameter.

    Modes:
    - "structure": No code bodies (just names and signatures)
    - "minimal": Code bodies for top-level symbols only
    - "full": Code bodies for all symbols
    """
    if mode == "structure":
        # No code bodies in structure mode
        return symbols

    # Read source file for body extraction
    try:
        with open(file_path, "rb") as f:
            source_bytes = f.read()
    except Exception:
        # If file can't be read, return symbols without bodies
        return symbols

    # Extract bodies based on mode
    for symbol in symbols:
        should_extract = False

        if mode == "minimal":
            # Only top-level symbols (no parent)
            should_extract = getattr(symbol, "parent_id", None) is None
        elif mode == "full":
            # All symbols
            should_extract = True

        if should_extract:
            start_byte = getattr(symbol, "start_byte", 0)
            end_byte = getattr(symbol, "end_byte", 0)

            if 0 <= start_byte < len(source_bytes) and start_byte < end_byte <= len(source_bytes):
                code_bytes = source_bytes[start_byte:end_byte]
                # Store as attribute (will be included in dict conversion)
                symbol.code_body = code_bytes.decode("utf-8", errors="replace")
            else:
                symbol.code_body = None
        else:
            symbol.code_body = None

    return symbols


def symbol_to_dict(symbol) -> dict[str, Any]:
    """Convert a symbol object to a dictionary."""
    # Normalize kind to PascalCase for consistency with Julie
    kind_raw = getattr(symbol, "kind", "")
    kind = kind_raw.capitalize() if kind_raw else ""

    result = {
        "name": getattr(symbol, "name", ""),
        "kind": kind,
        "start_line": getattr(symbol, "start_line", 0),
        "end_line": getattr(symbol, "end_line", 0),
    }

    # Optional fields
    if hasattr(symbol, "signature") and symbol.signature:
        result["signature"] = symbol.signature
    if hasattr(symbol, "doc_comment") and symbol.doc_comment:
        result["doc_comment"] = symbol.doc_comment
    if hasattr(symbol, "code_body") and symbol.code_body:
        result["code_body"] = symbol.code_body
    if hasattr(symbol, "parent_id"):
        result["parent_id"] = symbol.parent_id

    return result


async def get_symbols_enhanced(
    file_path: str,
    mode: str = "structure",
    max_depth: int = 1,
    target: Optional[str] = None,
    limit: Optional[int] = None,
    workspace: str = "primary"
) -> list[dict[str, Any]]:
    """
    Get file structure with enhanced filtering and modes.

    Args:
        file_path: Path to file (relative or absolute)
        mode: Reading mode - "structure" (default), "minimal", or "full"
        max_depth: Maximum nesting depth (0=top-level only, 1=include direct children, etc.)
        target: Filter to symbols matching this name (case-insensitive partial match)
        limit: Maximum number of symbols to return
        workspace: Workspace to query ("primary" or workspace_id)

    Returns:
        List of symbol dictionaries with metadata based on mode
    """
    # Import miller_core from server module (it handles the Rust binding import)
    from miller import server

    path = Path(file_path)

    # Handle nonexistent files
    if not path.exists():
        return []

    # Check if miller_core is available
    if server.miller_core is None:
        return []

    # Read and extract symbols
    try:
        content = path.read_text(encoding="utf-8")
        language = server.miller_core.detect_language(str(path))

        if not language:
            return []

        result = server.miller_core.extract_file(content, language, str(path))
        symbols = list(result.symbols)

        if not symbols:
            return []

        # Apply filters in order
        # 1. Max depth filter
        symbols = apply_max_depth_filter(symbols, max_depth)

        # 2. Target filter (if specified)
        if target:
            symbols = apply_target_filter(symbols, target)

        # 3. Extract code bodies based on mode
        symbols = extract_code_bodies(symbols, str(path), mode)

        # 4. Apply limit
        symbols, was_truncated = apply_limit(symbols, limit)

        # Convert to dicts
        result_dicts = [symbol_to_dict(sym) for sym in symbols]

        return result_dicts

    except Exception:
        return []
