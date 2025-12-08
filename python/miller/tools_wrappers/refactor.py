"""
Refactoring tool wrappers for FastMCP.

Contains wrapper for rename_symbol.
"""

from typing import Any, Literal, Union

from miller import server_state
from miller.tools.refactor import rename_symbol as rename_symbol_impl
from miller.tools_wrappers.common import await_ready


async def rename_symbol(
    old_name: str,
    new_name: str,
    scope: str = "workspace",
    dry_run: bool = True,
    update_imports: bool = True,
    workspace: str = "primary",
    output_format: Literal["text", "json"] = "text",
) -> Union[str, dict[str, Any]]:
    """
    Safely rename a symbol across the codebase with reference checking.

    This is Miller's SAFE REFACTORING tool. It uses fast_refs to find ALL references
    (definition + usages), then applies changes atomically with word-boundary safety.

    IMPORTANT: Default dry_run=True shows a preview WITHOUT modifying files.
    Set dry_run=False only after reviewing the preview.

    Args:
        old_name: Current symbol name to rename (e.g., "getUserData", "User.save")
                  Supports qualified names for method disambiguation
        new_name: New name for the symbol (must be valid identifier)
        scope: Rename scope - "workspace" (default) or "file" (future)
        dry_run: If True (default), show preview only. If False, apply changes.
        update_imports: Whether to update import statements (default True)
        workspace: Workspace to operate on ("primary" or workspace_id)
        output_format: Output format - "text" (default) or "json"

    Returns:
        - dry_run=True: Preview showing all files/lines that would change
        - dry_run=False: Summary of applied changes

    Safety Features:
        - Word-boundary matching prevents renaming substrings
          (renaming "get" won't affect "get_user" or "forget")
        - Name collision detection warns if new_name already exists
        - Identifier validation ensures new_name is syntactically valid
        - Preview mode lets you review before committing

    Examples:
        # Preview a rename (safe, no changes)
        await rename_symbol("getUserData", "fetchUserData")

        # Apply after reviewing preview
        await rename_symbol("getUserData", "fetchUserData", dry_run=False)

        # Rename a method specifically
        await rename_symbol("User.save", "User.persist", dry_run=False)

    Workflow:
        1. rename_symbol("old", "new") → Review preview
        2. rename_symbol("old", "new", dry_run=False) → Apply changes
        3. Run tests to verify no breakage
    """
    if err := await await_ready(require_vectors=False):
        return err
    return await rename_symbol_impl(
        old_name=old_name,
        new_name=new_name,
        scope=scope,
        dry_run=dry_run,
        update_imports=update_imports,
        workspace=workspace,
        output_format=output_format,
        storage=server_state.storage,
        vector_store=server_state.vector_store,
    )
