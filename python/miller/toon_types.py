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
               Default: 5 results (matches Julie's proven threshold)
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
    "threshold": 5,  # ≥5 results → use TOON in auto mode (matches Julie)
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
        >>> should_use_toon("toon", 2)
        True
        >>> should_use_toon("auto", 10)  # ≥5 threshold
        True
        >>> should_use_toon("auto", 3)  # <5 threshold
        False
    """
    if output_format == "json":
        return False
    elif output_format == "toon":
        return True
    else:  # "auto"
        return result_count >= config["threshold"]
