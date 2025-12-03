"""
Smart symbol lookup with semantic fallback.

Provides fast_lookup - a batch symbol resolution tool that:
- Resolves multiple symbols in one call
- Falls back to fuzzy/semantic matching when exact match fails
- Generates import paths
- Shows symbol structure (methods, properties)
"""

import logging
import re
from typing import Any, Literal, Optional, Union

from .fuzzy import fuzzy_find_symbol

logger = logging.getLogger("miller.navigation")


def get_symbol_structure(storage, sym: dict[str, Any]) -> dict[str, Any]:
    """Get structure info for a symbol (methods, properties, base classes)."""
    structure = {
        "methods": [],
        "properties": [],
        "base_classes": [],
        "interfaces": [],
    }

    symbol_id = sym.get("id")
    if not symbol_id:
        return structure

    # Get child symbols (methods, properties)
    cursor = storage.conn.execute("""
        SELECT name, kind FROM symbols
        WHERE parent_id = ?
        ORDER BY start_line
    """, (symbol_id,))

    for row in cursor.fetchall():
        name, kind = row[0], row[1]
        if kind in ("method", "function"):
            structure["methods"].append(name)
        elif kind in ("property", "variable", "field"):
            structure["properties"].append(name)

    # Get base classes/interfaces from relationships
    cursor = storage.conn.execute("""
        SELECT s.name, r.kind FROM relationships r
        JOIN symbols s ON r.to_symbol_id = s.id
        WHERE r.from_symbol_id = ? AND r.kind IN ('extends', 'implements')
    """, (symbol_id,))

    for row in cursor.fetchall():
        name, rel_kind = row[0], row[1]
        if rel_kind == "extends":
            structure["base_classes"].append(name)
        elif rel_kind == "implements":
            structure["interfaces"].append(name)

    # Also try to extract base class from signature (e.g., "class Foo(Bar):")
    signature = sym.get("signature", "")
    if signature and "(" in signature and sym.get("kind") == "class":
        # Extract class BaseClass from "class Foo(BaseClass):"
        match = re.search(r'\(([^)]+)\)', signature)
        if match:
            bases = [b.strip() for b in match.group(1).split(",")]
            for base in bases:
                if base and base not in structure["base_classes"]:
                    structure["base_classes"].append(base)

    return structure


async def fast_lookup(
    symbols: list[str],
    context_file: Optional[str] = None,
    include_body: bool = False,
    max_depth: int = 1,
    workspace: str = "primary",
    output_format: Literal["text", "json", "toon", "auto"] = "text",
    storage=None,
    vector_store=None,
) -> Union[list[dict[str, Any]], str]:
    """
    Smart batch symbol resolution with semantic fallback.

    Resolves multiple symbols in one call, with:
    - Exact match lookup (fast, from SQLite index)
    - Semantic fallback when exact match fails (from vector store)
    - Import path generation
    - Symbol structure (methods, properties, etc.)

    Args:
        symbols: List of symbol names to look up (1-N symbols)
        context_file: Where you're writing code (for relative import paths)
        include_body: Include source code body
        max_depth: Structure depth - 0=signature only, 1=methods/properties, 2=nested
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "text" (default), "json", "toon", or "auto"
                      - "text": Lean formatted output (DEFAULT - most token-efficient)
                      - "json": Standard list format (for programmatic use)
                      - "toon": TOON-encoded string (30-40% token reduction)
                      - "auto": TOON if ≥5 symbols, else JSON
        storage: StorageManager instance (injected by server)
        vector_store: VectorStore instance for semantic fallback (optional)

    Returns:
        - text mode: Lean scannable format (DEFAULT)
        - json mode: List of symbol dicts with full metadata
        - toon mode: TOON-encoded string (compact format)
        - auto mode: TOON if ≥5 symbols, else JSON

    Examples:
        # Look up multiple symbols at once
        fast_lookup(["AuthService", "User", "hash_password"])

        # With context for relative imports
        fast_lookup(["User"], context_file="src/handlers/auth.py")

        # Get JSON for programmatic use
        fast_lookup(["User"], output_format="json")
    """
    # Get workspace-specific storage if needed
    workspace_storage = None  # Track if we created a new storage that needs cleanup
    if workspace != "primary":
        from miller.workspace_paths import get_workspace_db_path
        from miller.workspace_registry import WorkspaceRegistry
        from miller.storage import StorageManager

        registry = WorkspaceRegistry()
        workspace_entry = registry.get_workspace(workspace)
        if workspace_entry:
            db_path = get_workspace_db_path(workspace)
            workspace_storage = StorageManager(db_path=str(db_path))
            storage = workspace_storage
        else:
            return f"═══ fast_lookup: error ═══\n\nWorkspace '{workspace}' not found."

    try:
        results = []
        for symbol_name in symbols:
            result = await _lookup_single_symbol(
                symbol_name=symbol_name,
                context_file=context_file,
                include_body=include_body,
                max_depth=max_depth,
                storage=storage,
                vector_store=vector_store,
            )
            results.append(result)

        # Use create_toonable_result for consistent output format handling
        from miller.toon_utils import create_toonable_result

        return create_toonable_result(
            json_data=results,
            toon_data=results,
            output_format=output_format,
            auto_threshold=5,  # Use TOON for 5+ symbols
            result_count=len(results),
            tool_name="fast_lookup",
            text_formatter=lambda r: format_lookup_output(symbols, r),
        )
    finally:
        # Clean up workspace-specific storage if we created it
        if workspace_storage is not None:
            workspace_storage.close()


async def _lookup_single_symbol(
    symbol_name: str,
    context_file: Optional[str],
    include_body: bool,
    max_depth: int,
    storage,
    vector_store,
) -> dict[str, Any]:
    """Look up a single symbol with exact match, then semantic fallback."""
    # Try exact match first
    sym = None
    if "." in symbol_name:
        # Qualified name: Parent.Child
        parts = symbol_name.split(".", 1)
        parent_name, child_name = parts[0], parts[1]
        cursor = storage.conn.execute("""
            SELECT s.* FROM symbols s
            JOIN symbols parent ON s.parent_id = parent.id
            WHERE parent.name = ? AND s.name = ?
            ORDER BY CASE s.kind
                WHEN 'import' THEN 2
                WHEN 'reference' THEN 2
                ELSE 1
            END
            LIMIT 1
        """, (parent_name, child_name))
        row = cursor.fetchone()
        if row:
            sym = dict(row)
    else:
        sym = storage.get_symbol_by_name(symbol_name)

    if sym:
        # Exact match found
        return _build_lookup_result(
            sym=sym,
            match_type="exact",
            original_query=symbol_name,
            context_file=context_file,
            include_body=include_body,
            max_depth=max_depth,
            storage=storage,
        )

    # Try fuzzy fallback - first SQL name matching, then semantic if available
    # Only consider "definition" kinds - not variables, imports, or references
    definition_kinds = (
        "class", "function", "method", "type", "interface",
        "struct", "enum", "trait", "module", "constant"
    )

    # Strategy 1: Fuzzy SQL name match (fast, effective for typos)
    try:
        fuzzy_match = fuzzy_find_symbol(storage, symbol_name, definition_kinds)
        if fuzzy_match:
            sym, score = fuzzy_match
            return _build_lookup_result(
                sym=sym,
                match_type="semantic",  # Label as semantic for user clarity
                original_query=symbol_name,
                context_file=context_file,
                include_body=include_body,
                max_depth=max_depth,
                storage=storage,
                semantic_score=score,
            )
    except Exception as e:
        logger.debug(f"Fuzzy lookup failed for '{symbol_name}': {e}")

    # Strategy 2: Vector semantic search (for conceptual matches)
    if vector_store:
        try:
            semantic_results = vector_store.search(
                symbol_name, method="semantic", limit=20
            )

            for match in semantic_results:
                kind = match.get("kind", "").lower()
                if kind not in definition_kinds:
                    continue

                score = match.get("score", 0)
                if score <= 0.80:  # High threshold to avoid false positives
                    continue

                # LanceDB schema uses "id" field, not "symbol_id"
                matched_sym = storage.get_symbol_by_id(match.get("id"))
                if not matched_sym:
                    matched_sym = storage.get_symbol_by_name(match.get("name", ""))
                if matched_sym:
                    return _build_lookup_result(
                        sym=matched_sym,
                        match_type="semantic",
                        original_query=symbol_name,
                        context_file=context_file,
                        include_body=include_body,
                        max_depth=max_depth,
                        storage=storage,
                        semantic_score=score,
                    )
        except Exception as e:
            logger.debug(f"Semantic search failed for '{symbol_name}': {e}")

    # Not found
    return {
        "original_query": symbol_name,
        "match_type": "not_found",
        "name": None,
    }


def _build_lookup_result(
    sym: dict[str, Any],
    match_type: str,
    original_query: str,
    context_file: Optional[str],
    include_body: bool,
    max_depth: int,
    storage,
    semantic_score: Optional[float] = None,
) -> dict[str, Any]:
    """Build a lookup result dict from a symbol."""
    result = {
        "original_query": original_query,
        "match_type": match_type,
        "name": sym["name"],
        "kind": sym["kind"],
        "file_path": sym["file_path"],
        "start_line": sym["start_line"],
        "signature": sym.get("signature", ""),
    }

    if semantic_score is not None:
        result["semantic_score"] = semantic_score

    # Generate import path
    result["import_statement"] = generate_import_path(
        sym["file_path"], sym["name"], context_file
    )

    # Add structure if max_depth > 0
    if max_depth >= 1:
        result["structure"] = get_symbol_structure(storage, sym)

    # Add body if requested
    if include_body:
        result["body"] = sym.get("code_context", "")

    return result


def generate_import_path(
    file_path: str, symbol_name: str, context_file: Optional[str]
) -> str:
    """Generate Python import statement for a symbol.

    Args:
        file_path: Path to file containing the symbol
        symbol_name: Name of the symbol to import
        context_file: Optional file path where import will be used

    Returns:
        Import statement string like "from module.path import Symbol"
    """
    # Convert file path to module path
    # Remove .py extension and convert / to .
    module_path = file_path
    if module_path.endswith(".py"):
        module_path = module_path[:-3]
    module_path = module_path.replace("/", ".").replace("\\", ".")

    # Remove leading src. or similar common prefixes
    for prefix in ["src.", "lib.", "python."]:
        if module_path.startswith(prefix):
            module_path = module_path[len(prefix):]
            break

    # Remove leading dots
    module_path = module_path.lstrip(".")

    if not module_path:
        module_path = symbol_name.lower()

    return f"from {module_path} import {symbol_name}"


def format_lookup_output(queries: list[str], results: list[dict[str, Any]]) -> str:
    """Format lookup results as lean text output."""
    count = len(queries)
    output = [f"═══ fast_lookup: {count} symbol{'s' if count != 1 else ''} ═══", ""]

    for result in results:
        original = result["original_query"]
        match_type = result["match_type"]

        if match_type == "not_found":
            output.append(f"{original} ✗")
            output.append("  No match found")
            output.append("")
            continue

        name = result["name"]
        file_path = result["file_path"]
        line = result["start_line"]
        kind = result["kind"]
        signature = result.get("signature", "")
        import_stmt = result.get("import_statement", "")

        # Header line with match indicator
        if match_type == "semantic":
            score = result.get("semantic_score", 0)
            output.append(f"{original} ✗ → {name} (semantic match, {score:.2f})")
        else:
            output.append(f"{name} ✓")

        # Location
        output.append(f"  {file_path}:{line} ({kind})")

        # Import statement
        if import_stmt:
            output.append(f"  {import_stmt}")

        # Signature
        if signature:
            sig = signature.split("\n")[0]
            if len(sig) > 70:
                sig = sig[:67] + "..."
            output.append(f"  {sig}")

        # Structure (methods/properties)
        structure = result.get("structure")
        if structure:
            methods = structure.get("methods", [])
            properties = structure.get("properties", [])

            if methods:
                if len(methods) > 5:
                    method_str = ", ".join(methods[:5]) + f", ... ({len(methods)} total)"
                else:
                    method_str = ", ".join(methods)
                output.append(f"    Methods: {method_str}")

            if properties:
                if len(properties) > 5:
                    prop_str = ", ".join(properties[:5]) + f", ... ({len(properties)} total)"
                else:
                    prop_str = ", ".join(properties)
                output.append(f"    Properties: {prop_str}")

        # Body if present
        body = result.get("body")
        if body:
            output.append("")
            output.append("  Body:")
            for line_text in body.split("\n")[:15]:
                output.append(f"    {line_text}")
            if body.count("\n") > 15:
                output.append("    ... (truncated)")

        output.append("")

    return "\n".join(output)
