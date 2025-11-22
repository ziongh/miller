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
    tool_name: str,
    text_formatter: Optional[callable] = None,
) -> Union[str, Any]:
    """
    Return text, TOON, or JSON based on output_format.

    This is Julie's direct pattern - simple and effective.
    Extended to support lean text output as the new default.

    Args:
        json_data: Full result with metadata (for JSON mode)
        toon_data: Optimized flat structure (for TOON mode)
        output_format: "text" (default), "json", "toon", or "auto"
        auto_threshold: Minimum result count for auto→TOON
        result_count: Number of results (for auto mode)
        tool_name: Tool name for logging
        text_formatter: Optional function(json_data) -> str for text mode

    Returns:
        - Text mode: Formatted string (lean, grep-style)
        - TOON mode: TOON-encoded string
        - JSON mode: Original data structure
        - Auto mode: TOON if >= threshold, else JSON

    Example:
        >>> result = {"symbol": "foo", "references": [...]}
        >>> return create_toonable_result(
        ...     json_data=result,
        ...     toon_data=result,
        ...     output_format="text",
        ...     auto_threshold=20,
        ...     result_count=len(result["references"]),
        ...     tool_name="fast_refs",
        ...     text_formatter=format_refs_as_text
        ... )
    """
    from toon_format import encode as toon_encode

    logger = setup_logging()

    if output_format == "text":
        # Text mode: lean grep-style output (new default)
        if text_formatter:
            return text_formatter(json_data)
        else:
            # Fallback to JSON if no formatter provided
            logger.warning(f"{tool_name} has no text formatter, falling back to JSON")
            return json_data

    elif output_format == "toon":
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
        # JSON mode (explicit or fallback)
        return json_data
