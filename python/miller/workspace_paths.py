"""
Workspace path utilities.

Provides consistent path generation for databases and vector indexes.

ARCHITECTURE NOTE (Unified Database):
Miller uses a SINGLE database and vector store for ALL workspaces.
This enables cross-workspace relationships (e.g., tracing calls from repo A to repo B).
Each record includes a workspace_id column for filtering.

Path structure:
    .miller/
    ├── workspace_registry.json   # Maps workspace IDs to paths
    ├── symbols.db                # Single SQLite DB (all workspaces)
    └── vectors.lance/            # Single LanceDB store (all workspaces)
"""

from pathlib import Path


# Unified database paths (single DB for all workspaces)
MILLER_DIR = Path(".miller")
UNIFIED_DB_PATH = MILLER_DIR / "symbols.db"
UNIFIED_VECTOR_PATH = MILLER_DIR / "vectors.lance"


def get_unified_db_path() -> Path:
    """
    Get the unified SQLite database path (shared by all workspaces).

    Returns:
        Path to unified SQLite database (.miller/symbols.db)
    """
    return UNIFIED_DB_PATH


def get_unified_vector_path() -> Path:
    """
    Get the unified LanceDB vector index path (shared by all workspaces).

    Returns:
        Path to unified LanceDB vector index (.miller/vectors.lance)
    """
    return UNIFIED_VECTOR_PATH


def ensure_miller_directories() -> None:
    """
    Create the .miller directory if it doesn't exist.

    Should be called during server initialization.
    """
    MILLER_DIR.mkdir(parents=True, exist_ok=True)


# Legacy functions for backward compatibility during migration
# TODO: Remove these after full migration to unified database

def get_workspace_db_path(workspace_id: str) -> Path:
    """
    DEPRECATED: Get SQLite database path for workspace.

    In the unified database architecture, all workspaces share a single DB.
    This function is kept for backward compatibility during migration.

    Args:
        workspace_id: Workspace ID (ignored in unified architecture)

    Returns:
        Path to unified SQLite database
    """
    # Return unified path (workspace_id is now a column, not a path segment)
    return get_unified_db_path()


def get_workspace_vector_path(workspace_id: str) -> Path:
    """
    DEPRECATED: Get LanceDB vector index path for workspace.

    In the unified database architecture, all workspaces share a single vector store.
    This function is kept for backward compatibility during migration.

    Args:
        workspace_id: Workspace ID (ignored in unified architecture)

    Returns:
        Path to unified LanceDB vector index
    """
    # Return unified path (workspace_id is now a column/field, not a path segment)
    return get_unified_vector_path()


def ensure_workspace_directories(workspace_id: str) -> None:
    """
    DEPRECATED: Create workspace directories.

    In the unified architecture, we just need the .miller directory.

    Args:
        workspace_id: Workspace ID (ignored in unified architecture)
    """
    ensure_miller_directories()


def make_qualified_path(workspace_id: str, relative_path: str) -> str:
    """
    Create a workspace-qualified path for database storage.

    Format: "{workspace_id}:{relative_path}"

    This makes paths globally unique across workspaces in the unified database.

    Args:
        workspace_id: Workspace identifier
        relative_path: Path relative to workspace root (Unix-style)

    Returns:
        Qualified path string, e.g., "miller_abc123:src/main.py"
    """
    return f"{workspace_id}:{relative_path}"


def parse_qualified_path(qualified_path: str) -> tuple[str, str]:
    """
    Parse a workspace-qualified path into components.

    Args:
        qualified_path: Qualified path, e.g., "miller_abc123:src/main.py"

    Returns:
        Tuple of (workspace_id, relative_path)

    Raises:
        ValueError: If path is not properly qualified
    """
    if ":" not in qualified_path:
        # Legacy path without workspace qualifier - assume primary
        return ("primary", qualified_path)

    parts = qualified_path.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid qualified path: {qualified_path}")

    return (parts[0], parts[1])
