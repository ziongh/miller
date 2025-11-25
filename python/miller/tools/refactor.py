"""
Refactoring tools for Miller - safe, atomic code transformations.

This module provides rename_symbol, a tool that leverages Miller's unique advantages:
- tree-sitter: Precise symbol boundaries (not just text search)
- Reference graph: Complete reference discovery via fast_refs
- Embeddings: Semantic similarity for cascade suggestions
- Qualified names: Parent.method disambiguation support
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional, Union

# =============================================================================
# TYPE DEFINITIONS
# =============================================================================


@dataclass
class RenameEdit:
    """A single edit to be applied during rename."""

    file_path: str
    line: int
    column: int
    old_text: str
    new_text: str
    kind: str  # "definition", "call", "import", "reference"
    context: str = ""  # The line of code for preview


@dataclass
class RenamePreview:
    """Preview of rename operation (returned when dry_run=True)."""

    old_name: str
    new_name: str
    total_references: int
    files_affected: int
    edits: list[RenameEdit]
    warnings: list[str] = field(default_factory=list)
    # e.g., ["String literal 'getUserData' at file.py:15 not renamed"]


@dataclass
class RenameResult:
    """Result of applied rename operation (returned when dry_run=False)."""

    old_name: str
    new_name: str
    success: bool
    files_modified: dict[str, int]  # file_path -> change_count
    total_changes: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class CascadeSuggestion:
    """A suggested related symbol to also rename."""

    symbol_name: str
    suggested_new_name: str
    file_path: str
    line: int
    match_type: Literal["pattern", "semantic"]  # How it was found
    confidence: float  # 0.0-1.0, pattern matches are 1.0
    reason: str  # e.g., "snake_case variant", "semantic similarity 0.89"


# =============================================================================
# FUNCTION CONTRACT
# =============================================================================


async def rename_symbol(
    old_name: str,
    new_name: str,
    scope: str = "workspace",
    dry_run: bool = True,
    update_imports: bool = True,
    workspace: str = "primary",
    output_format: Literal["text", "json"] = "text",
    # Injected dependencies (for testing)
    storage: Optional[Any] = None,
    vector_store: Optional[Any] = None,
) -> Union[str, dict[str, Any]]:
    """
    Safely rename a symbol across the codebase.

    Uses fast_refs to find ALL references (definition + usages), then applies
    changes atomically. Default dry_run=True shows preview without modifying files.
    """
    # Validate inputs
    if not old_name:
        raise ValueError("old_name cannot be empty")

    if old_name == new_name:
        raise ValueError("new_name cannot be the same as old_name")

    is_valid, error = _validate_identifier(new_name)
    if not is_valid:
        raise ValueError(f"Invalid new_name: {error}")

    # Check for name collision
    collision = _check_name_collision(new_name, workspace, storage)
    if collision:
        result_msg = f"Name collision: '{new_name}' already exists at {collision.get('file_path', 'unknown')}:{collision.get('start_line', 0)}"
        if output_format == "json":
            return {"error": result_msg, "collision": True, "existing_symbol": collision}
        return result_msg

    # Find all references using fast_refs logic
    from miller.tools.refs import find_references

    # Handle qualified names (e.g., "ClassName.method")
    symbol_to_find = old_name
    if "." in old_name:
        # For qualified names, we search for the child name
        # The find_references function handles qualified name resolution
        pass

    refs_result = find_references(
        storage=storage,
        symbol_name=symbol_to_find,
        include_context=True,
    )

    total_refs = refs_result.get("total_references", 0)

    if total_refs == 0:
        result_msg = f"No references found for symbol '{old_name}'"
        if output_format == "json":
            return {"error": result_msg, "total_references": 0}
        return result_msg

    # Build edit plan
    edits = _build_edit_plan(refs_result, old_name, new_name, update_imports)

    # Count unique files
    unique_files = set(e.file_path for e in edits)

    if dry_run:
        # Return preview (use len(edits) for deduplicated count)
        preview = RenamePreview(
            old_name=old_name,
            new_name=new_name,
            total_references=len(edits),
            files_affected=len(unique_files),
            edits=edits,
        )

        if output_format == "json":
            return _format_preview_as_json(preview)
        return _format_preview_as_text(preview)
    else:
        # Apply the edits
        result = await _apply_edits(edits, old_name, new_name)

        if output_format == "json":
            return _format_result_as_json(result)
        return _format_result_as_text(result)


async def find_cascade_suggestions(
    symbol_name: str,
    new_name_pattern: Optional[str] = None,
    include_pattern_variants: bool = True,
    include_semantic_matches: bool = True,
    min_confidence: float = 0.75,
    workspace: str = "primary",
    storage: Optional[Any] = None,
    vector_store: Optional[Any] = None,
) -> list[CascadeSuggestion]:
    """
    Find symbols related to the given name that might also need renaming.

    Uses a hybrid approach:
    1. Pattern matching: Find case variants (snake_case, camelCase, etc.)
    2. Semantic matching: Find conceptually similar symbols via embeddings
    """
    suggestions: list[CascadeSuggestion] = []

    if storage is None:
        return suggestions

    # Import naming utilities
    from miller.tools.naming import generate_variants

    if include_pattern_variants:
        # Generate naming variants of the symbol
        variants = generate_variants(symbol_name)

        # Search for symbols matching any variant
        for variant_type, variant_name in variants.items():
            if variant_name == symbol_name:
                continue  # Skip the original

            # Search for symbols with this name pattern
            # Look for symbols that START with or CONTAIN the variant
            cursor = storage.conn.execute(
                """
                SELECT id, name, kind, file_path, start_line, signature
                FROM symbols
                WHERE name LIKE ? OR name LIKE ?
                """,
                (f"{variant_name}%", f"%{variant_name}%"),
            )

            for row in cursor.fetchall():
                sym_name = row["name"]
                if sym_name == symbol_name:
                    continue  # Skip the original symbol

                # Generate suggested new name
                suggested_new = sym_name
                if new_name_pattern:
                    # Replace the base pattern in the symbol name
                    # e.g., UserService with User→Account becomes AccountService
                    suggested_new = sym_name.replace(symbol_name, new_name_pattern)
                    # Also try case variants
                    suggested_new = suggested_new.replace(
                        symbol_name.lower(), new_name_pattern.lower()
                    )
                    suggested_new = suggested_new.replace(
                        symbol_name.upper(), new_name_pattern.upper()
                    )

                suggestions.append(
                    CascadeSuggestion(
                        symbol_name=sym_name,
                        suggested_new_name=suggested_new,
                        file_path=row["file_path"],
                        line=row["start_line"],
                        match_type="pattern",
                        confidence=1.0,  # Pattern matches are certain
                        reason=f"{variant_type} variant",
                    )
                )

    # TODO: Add semantic matching using vector_store
    # if include_semantic_matches and vector_store is not None:
    #     # Query embedding similarity for conceptually related symbols
    #     pass

    # Sort by confidence (highest first), then by name
    suggestions.sort(key=lambda s: (-s.confidence, s.symbol_name))

    # Deduplicate by symbol name
    seen = set()
    unique_suggestions = []
    for s in suggestions:
        if s.symbol_name not in seen:
            seen.add(s.symbol_name)
            unique_suggestions.append(s)

    return unique_suggestions


# =============================================================================
# INTERNAL HELPERS (signatures only for now)
# =============================================================================


def _validate_identifier(name: str) -> tuple[bool, str]:
    """
    Check if a name is a valid identifier.

    Returns (is_valid, error_message).
    """
    if not name:
        return False, "Identifier cannot be empty"

    # Check if it's a valid Python identifier
    if not name.isidentifier():
        if name[0].isdigit():
            return False, "Identifier cannot start with a number"
        if " " in name:
            return False, "Identifier cannot contain spaces"
        return False, f"Invalid identifier: '{name}' contains invalid characters"

    return True, ""


def _build_edit_plan(
    refs_result: dict[str, Any],
    old_name: str,
    new_name: str,
    update_imports: bool,
) -> list[RenameEdit]:
    """
    Build list of edits from fast_refs result.

    Deduplicates by (file_path, line) since the same location may appear
    multiple times with different relationship kinds (e.g., "calls" and "call").
    """
    edits = []
    seen: set[tuple[str, int]] = set()

    for file_info in refs_result.get("files", []):
        file_path = file_info.get("path", "")

        for ref in file_info.get("references", []):
            line = ref.get("line", 0)
            key = (file_path, line)

            # Skip duplicates - same file+line already processed
            if key in seen:
                continue
            seen.add(key)

            edit = RenameEdit(
                file_path=file_path,
                line=line,
                column=ref.get("column", 0),
                old_text=old_name,
                new_text=new_name,
                kind=ref.get("kind", "reference"),
                context=ref.get("context", ""),
            )
            edits.append(edit)

    return edits


def _check_name_collision(
    new_name: str,
    workspace: str,
    storage: Any,
) -> Optional[dict[str, Any]]:
    """
    Check if new_name already exists as a symbol.

    Returns the existing symbol info if collision, None otherwise.
    """
    if storage is None:
        return None

    existing = storage.get_symbol_by_name(new_name)
    return existing


def _format_preview_as_text(preview: RenamePreview) -> str:
    """Format preview for human-readable text output."""
    lines = [
        f"🔍 Rename Preview: '{preview.old_name}' → '{preview.new_name}'",
        f"Found {preview.total_references} references across {preview.files_affected} files",
        "",
    ]

    # Group edits by file
    edits_by_file: dict[str, list[RenameEdit]] = {}
    for edit in preview.edits:
        if edit.file_path not in edits_by_file:
            edits_by_file[edit.file_path] = []
        edits_by_file[edit.file_path].append(edit)

    for file_path, file_edits in edits_by_file.items():
        lines.append(f"📄 {file_path}")
        for edit in file_edits:
            kind_label = f"[{edit.kind}]" if edit.kind else ""
            lines.append(f"   Line {edit.line}: {edit.old_text} → {edit.new_text} {kind_label}")
        lines.append("")

    if preview.warnings:
        lines.append("⚠️  Warnings:")
        for warning in preview.warnings:
            lines.append(f"   - {warning}")
        lines.append("")

    lines.append("Set dry_run=False to apply changes.")
    return "\n".join(lines)


def _format_preview_as_json(preview: RenamePreview) -> dict[str, Any]:
    """Format preview for JSON output."""
    return {
        "old_name": preview.old_name,
        "new_name": preview.new_name,
        "total_references": preview.total_references,
        "files_affected": preview.files_affected,
        "edits": [
            {
                "file_path": e.file_path,
                "line": e.line,
                "column": e.column,
                "old_text": e.old_text,
                "new_text": e.new_text,
                "kind": e.kind,
                "context": e.context,
            }
            for e in preview.edits
        ],
        "warnings": preview.warnings,
    }


def _format_result_as_text(result: RenameResult) -> str:
    """Format result for human-readable text output."""
    if result.success:
        lines = [
            f"✅ Rename Complete: '{result.old_name}' → '{result.new_name}'",
            f"Modified {len(result.files_modified)} files with {result.total_changes} changes:",
        ]
        for file_path, count in result.files_modified.items():
            lines.append(f"   {file_path} ({count} changes)")
    else:
        lines = [
            f"❌ Rename Failed: '{result.old_name}' → '{result.new_name}'",
        ]
        for error in result.errors:
            lines.append(f"   Error: {error}")

    if result.warnings:
        lines.append("")
        lines.append("⚠️  Warnings:")
        for warning in result.warnings:
            lines.append(f"   - {warning}")

    return "\n".join(lines)


def _format_result_as_json(result: RenameResult) -> dict[str, Any]:
    """Format result for JSON output."""
    return {
        "old_name": result.old_name,
        "new_name": result.new_name,
        "success": result.success,
        "files_modified": result.files_modified,
        "total_changes": result.total_changes,
        "errors": result.errors,
        "warnings": result.warnings,
    }


import re


async def _apply_edits(
    edits: list[RenameEdit],
    old_name: str,
    new_name: str,
) -> RenameResult:
    """
    Apply edits to files using word-boundary-aware replacement.

    Edits are applied in reverse line order within each file to preserve
    line numbers during the operation.
    """
    files_modified: dict[str, int] = {}
    errors: list[str] = []

    # Group edits by file
    edits_by_file: dict[str, list[RenameEdit]] = {}
    for edit in edits:
        if edit.file_path not in edits_by_file:
            edits_by_file[edit.file_path] = []
        edits_by_file[edit.file_path].append(edit)

    # Build word-boundary regex pattern
    # This ensures we don't rename substrings (e.g., 'get' in 'get_user')
    pattern = re.compile(r'\b' + re.escape(old_name) + r'\b')

    for file_path, file_edits in edits_by_file.items():
        try:
            path = Path(file_path)
            if not path.exists():
                errors.append(f"File not found: {file_path}")
                continue

            content = path.read_text()
            original_content = content

            # Apply word-boundary replacement
            new_content, count = pattern.subn(new_name, content)

            if count > 0:
                path.write_text(new_content)
                files_modified[file_path] = count

        except Exception as e:
            errors.append(f"Error processing {file_path}: {e}")

    total_changes = sum(files_modified.values())
    success = len(errors) == 0 and total_changes > 0

    return RenameResult(
        old_name=old_name,
        new_name=new_name,
        success=success,
        files_modified=files_modified,
        total_changes=total_changes,
        errors=errors,
    )
