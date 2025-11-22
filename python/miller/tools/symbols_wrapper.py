"""
Get symbols tool - Retrieve file structure and code.

Provides get_symbols for exploring file structure with minimal token overhead.
"""

from typing import Any, Literal, Optional, Union


def _format_code_output(file_path: str, symbols: list[dict[str, Any]]) -> str:
    """Format symbols as raw code output - optimal for AI reading.

    Returns code bodies separated by blank lines with a minimal file header.
    Only includes meaningful code definitions (functions, classes, methods, etc.).
    """
    from pathlib import Path

    CODE_DEFINITION_KINDS = {
        "Function", "Method", "Class", "Struct", "Interface", "Trait",
        "Enum", "Constructor", "Module", "Namespace", "Type",
        "function", "method", "class", "struct", "interface", "trait",
        "enum", "constructor", "module", "namespace", "type",
    }

    output = f"// === {Path(file_path).name} ===\n\n"
    code_symbols = []
    for symbol in symbols:
        if symbol.get("kind", "") in CODE_DEFINITION_KINDS:
            code_symbols.append({
                "start_line": symbol.get("start_line", 0),
                "end_line": symbol.get("end_line", 0),
                "code_body": symbol.get("code_body"),
                "parent_id": symbol.get("parent_id"),
            })

    code_symbols.sort(key=lambda s: s["start_line"])
    seen_bodies = set()
    code_bodies = []
    covered_ranges = []

    for symbol in code_symbols:
        if symbol["parent_id"]:
            continue
        is_nested = any(
            start < symbol["start_line"] and symbol["end_line"] < end
            for start, end in covered_ranges
        )
        if is_nested:
            continue
        body = symbol["code_body"]
        if body and body not in seen_bodies:
            seen_bodies.add(body)
            code_bodies.append(body)
            covered_ranges.append((symbol["start_line"], symbol["end_line"]))

    output += "\n\n".join(code_bodies)
    return output.rstrip() + "\n"


async def get_symbols(
    file_path: str,
    mode: str = "structure",
    max_depth: int = 1,
    target: Optional[str] = None,
    limit: Optional[int] = None,
    workspace: str = "primary",
    output_format: Literal["json", "toon", "auto", "code"] = "json"
) -> Union[list[dict[str, Any]], str]:
    """
    Get file structure with enhanced filtering and modes.

    This should be your FIRST tool when exploring a new file! Use it to understand
    the structure before diving into implementation details.

    IMPORTANT: Use mode="structure" (default) to get an overview WITHOUT reading code bodies.
    This is extremely token-efficient - you see all classes, functions, and methods without
    dumping the entire file into context.

    I WILL BE UPSET IF YOU READ AN ENTIRE FILE WHEN get_symbols WOULD SHOW YOU THE STRUCTURE!

    Args:
        file_path: Path to file (relative or absolute)
        mode: Reading mode - "structure" (default), "minimal", or "full"
              - "structure": Names, signatures, no code bodies (fast, token-efficient)
              - "minimal": Code bodies for top-level symbols only
              - "full": Complete code bodies for all symbols (use sparingly!)
        max_depth: Maximum nesting depth (0=top-level only, 1=include methods, 2+=deeper)
        target: Filter to symbols matching this name (case-insensitive partial match)
        limit: Maximum number of symbols to return
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "json" (default), "toon", "auto", or "code"
                      - "json": Standard list format
                      - "toon": TOON-encoded string (30-40% token reduction)
                      - "auto": TOON if ≥20 symbols, else JSON
                      - "code": Raw source code without metadata (optimal for AI reading)

    Returns:
        - JSON mode: List of symbol dictionaries
        - TOON mode: TOON-encoded string (compact table format)
        - Auto mode: Switches based on result count
        - Code mode: Raw source code string with minimal file header

    Examples:
        # Quick structure overview (no code) - USE THIS FIRST!
        await get_symbols("src/user.py", mode="structure", max_depth=1)

        # Find specific class with its methods
        await get_symbols("src/user.py", target="UserService", max_depth=2)

        # Get complete implementation (only when you really need the code)
        await get_symbols("src/utils.py", mode="full", max_depth=2)

        # Get raw code for AI consumption (minimal tokens, maximum readability)
        await get_symbols("src/utils.py", mode="minimal", output_format="code")

    Workflow: get_symbols(mode="structure") → identify what you need → get_symbols(target="X", mode="full")
    This two-step approach reads ONLY the code you need. Much better than reading entire files!
    """
    from miller.tools.symbols import get_symbols_enhanced
    from miller.toon_types import encode_toon, should_use_toon

    result = await get_symbols_enhanced(
        file_path=file_path,
        mode=mode,
        max_depth=max_depth,
        target=target,
        limit=limit,
        workspace=workspace
    )

    # Handle "code" output format - raw source code without metadata
    if output_format == "code":
        return _format_code_output(file_path, result)

    # Apply TOON encoding if requested
    if should_use_toon(output_format, len(result)):
        return encode_toon(result)
    else:
        return result
