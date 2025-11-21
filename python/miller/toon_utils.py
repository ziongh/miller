"""
TOON Output Utilities - Julie's Simple Pattern

This module provides a simple helper for returning TOON or JSON output
based on the output_format parameter. This is Julie's proven pattern -
no traits, no generics, no complexity.

Key principles:
1. Two data structures: one for JSON (full metadata), one for TOON (flat primitives)
2. Simple helper decides which to use
3. Graceful fallback to JSON if TOON encoding fails
4. Auto mode: TOON for large results, JSON for small
"""

from typing import Any, Optional, Union
from miller.logging_config import setup_logging


def create_toonable_result(
    json_data: Any,
    toon_data: Any,
    output_format: Optional[str],
    auto_threshold: int,
    result_count: int,
    tool_name: str
) -> Union[str, Any]:
    """
    Return either TOON or JSON based on output_format.

    This is Julie's direct pattern - simple and effective.

    Args:
        json_data: Full result with metadata (for JSON mode)
        toon_data: Optimized flat structure (for TOON mode)
        output_format: "json", "toon", "auto", or None
        auto_threshold: Minimum result count for auto→TOON
        result_count: Number of results (for auto mode)
        tool_name: Tool name for logging

    Returns:
        - TOON mode: TOON-encoded string
        - JSON mode: Original data structure
        - Auto mode: TOON if >= threshold, else JSON

    Example:
        >>> result = SearchResult(query="foo", results=[...])
        >>> return create_toonable_result(
        ...     json_data=result.to_json(),
        ...     toon_data=result.to_toon_flat(),
        ...     output_format="auto",
        ...     auto_threshold=20,
        ...     result_count=len(result.results),
        ...     tool_name="fast_search"
        ... )
    """
    from toon_format import encode as toon_encode

    logger = setup_logging()

    if output_format == "toon":
        # TOON mode: encode toon_data only
        try:
            return toon_encode(toon_data)
        except Exception as e:
            # Graceful fallback to JSON
            logger.warning(f"{tool_name} TOON encoding failed, falling back to JSON: {e}")
            return json_data

    elif output_format == "auto":
        # Auto: TOON for >= threshold, JSON for < threshold
        if result_count >= auto_threshold:
            try:
                return toon_encode(toon_data)
            except Exception as e:
                # Fall through to JSON
                logger.debug(f"{tool_name} TOON encoding failed in auto mode: {e}")
        return json_data

    else:
        # Default: JSON only (backwards compatible)
        return json_data
