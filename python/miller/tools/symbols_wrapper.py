"""
Get symbols tool - Retrieve file structure and code.

Provides get_symbols for exploring file structure with minimal token overhead.
"""

from typing import Any, Literal, Optional, Union


def _format_symbols_as_text(file_path: str, symbols: list[dict[str, Any]]) -> str:
    """Format symbols as lean text output - grep-style for quick scanning.

    Output format:
    ```
    src/user.py: 5 symbols

    Class UserService (lines 10-50)
      def __init__(self, db: Database)
      def get_user(self, id: int) -> User
      def save_user(self, user: User) -> bool

    Function validate_email (lines 52-60)
      def validate_email(email: str) -> bool
    ```
    """
    from pathlib import Path

    if not symbols:
        return f"{file_path}: No symbols found"

    # Group by top-level symbols
    top_level = [s for s in symbols if not s.get("parent_id")]
    nested = {s.get("parent_id"): [] for s in symbols if s.get("parent_id")}
    for s in symbols:
        if s.get("parent_id"):
            nested[s["parent_id"]].append(s)

    count = len(symbols)
    output = [f"{Path(file_path).name}: {count} symbol{'s' if count != 1 else ''}", ""]

    for sym in sorted(top_level, key=lambda s: s.get("start_line", 0)):
        name = sym.get("name", "?")
        kind = sym.get("kind", "symbol")
        start = sym.get("start_line", 0)
        end = sym.get("end_line", start)
        signature = sym.get("signature", "")

        # Header: Kind Name (lines X-Y)
        line_info = f"line {start}" if start == end else f"lines {start}-{end}"
        output.append(f"{kind} {name} ({line_info})")

        # Signature (truncated)
        if signature:
            sig = signature.split("\n")[0]
            if len(sig) > 80:
                sig = sig[:77] + "..."
            output.append(f"  {sig}")

        # Nested symbols (methods, etc.)
        sym_id = sym.get("id")
        if sym_id and sym_id in nested:
            for child in sorted(nested[sym_id], key=lambda s: s.get("start_line", 0)):
                child_sig = child.get("signature", child.get("name", "?"))
                child_sig = child_sig.split("\n")[0]
                if len(child_sig) > 76:
                    child_sig = child_sig[:73] + "..."
                output.append(f"    {child_sig}")

        output.append("")

    # Trim trailing blank lines
    while output and output[-1] == "":
        output.pop()

    return "\n".join(output)


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
    output_format: Literal["text", "json", "toon", "auto", "code"] = "text"
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
        output_format: Output format - "text" (default), "json", "toon", "auto", or "code"
                      - "text": Lean grep-style list (DEFAULT - most token-efficient)
                      - "json": Standard list format (for programmatic use)
                      - "toon": TOON-encoded string (30-40% token reduction)
                      - "auto": TOON if ≥20 symbols, else JSON
                      - "code": Raw source code without metadata (optimal for AI reading)

    Returns:
        - Text mode: Lean grep-style list with signatures (DEFAULT)
        - JSON mode: List of symbol dictionaries
        - TOON mode: TOON-encoded string (compact table format)
        - Auto mode: TOON if ≥20 symbols, else JSON
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

    # Handle special output formats
    if output_format == "code":
        return _format_code_output(file_path, result)

    if output_format == "text":
        return _format_symbols_as_text(file_path, result)

    # Apply TOON encoding if requested (for json/toon/auto)
    if should_use_toon(output_format, len(result)):
        return encode_toon(result)
    else:
        return result
