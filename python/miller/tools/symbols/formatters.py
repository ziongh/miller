"""Output formatting and metadata calculation for symbols."""

from typing import Any, Optional


def extract_code_bodies(
    symbols: list,
    file_path: str,
    mode: str
) -> dict[str, str]:
    """Extract code bodies for symbols based on mode parameter.

    Returns a dict mapping symbol.id -> code_body string.

    Modes:
    - "structure": No code bodies (just names and signatures)
    - "minimal": Code bodies for top-level symbols only
    - "full": Code bodies for all symbols
    """
    code_bodies = {}

    if mode == "structure":
        # No code bodies in structure mode
        return code_bodies

    # Read source file for body extraction
    try:
        with open(file_path, "rb") as f:
            source_bytes = f.read()
    except Exception:
        # If file can't be read, return empty dict
        return code_bodies

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
                symbol_id = getattr(symbol, "id", "")
                if symbol_id:
                    code_bodies[symbol_id] = code_bytes.decode("utf-8", errors="replace")

    return code_bodies


def calculate_usage_frequency(references_count: int) -> str:
    """
    Calculate usage frequency tier from reference count.

    Tiers:
    - none: 0 references
    - low: 1-5 references
    - medium: 6-20 references
    - high: 21-50 references
    - very_high: 51+ references

    Args:
        references_count: Number of times symbol is referenced

    Returns:
        Frequency tier string
    """
    if references_count == 0:
        return "none"
    elif references_count <= 5:
        return "low"
    elif references_count <= 20:
        return "medium"
    elif references_count <= 50:
        return "high"
    else:
        return "very_high"


def calculate_doc_quality(doc_comment: Optional[str]) -> str:
    """
    Calculate documentation quality tier from docstring length.

    Tiers:
    - none: No documentation
    - poor: <50 characters (too brief)
    - good: 50-200 characters (adequate)
    - excellent: >200 characters (comprehensive)

    Args:
        doc_comment: Docstring content (None or empty string means no docs)

    Returns:
        Quality tier string
    """
    if not doc_comment or len(doc_comment.strip()) == 0:
        return "none"

    doc_length = len(doc_comment)

    if doc_length < 50:
        return "poor"
    elif doc_length <= 200:
        return "good"
    else:
        return "excellent"


def calculate_importance_tier(importance_score: float) -> str:
    """
    Calculate importance tier from PageRank score.

    Tiers:
    - low: 0.0-0.25 (rarely called, low impact)
    - medium: 0.25-0.5 (occasionally used)
    - high: 0.5-0.75 (frequently used, important)
    - critical: 0.75-1.0 (central to codebase, high impact)

    Args:
        importance_score: PageRank score (0.0 to 1.0)

    Returns:
        Importance tier string
    """
    if importance_score <= 0.25:
        return "low"
    elif importance_score <= 0.5:
        return "medium"
    elif importance_score <= 0.75:
        return "high"
    else:
        return "critical"


def symbol_to_dict(symbol, code_bodies: dict[str, str]) -> dict[str, Any]:
    """Convert a symbol object to a dictionary.

    Args:
        symbol: Symbol object from miller_core
        code_bodies: Dict mapping symbol.id -> code_body string
    """
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
    if hasattr(symbol, "parent_id") and symbol.parent_id:
        result["parent_id"] = symbol.parent_id

    # Add code body if available
    symbol_id = getattr(symbol, "id", "")
    if symbol_id and symbol_id in code_bodies:
        result["code_body"] = code_bodies[symbol_id]

    return result
