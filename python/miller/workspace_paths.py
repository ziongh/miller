"""
Workspace path utilities.

Provides consistent path generation for workspace databases and vector indexes.
"""

from pathlib import Path


def get_workspace_db_path(workspace_id: str) -> Path:
    """
    Get SQLite database path for workspace.

    Args:
        workspace_id: Workspace ID (e.g., "my-project_abc123")

    Returns:
        Path to workspace SQLite database
    """
    return Path(f".miller/indexes/{workspace_id}/symbols.db")


def get_workspace_vector_path(workspace_id: str) -> Path:
    """
    Get LanceDB vector index path for workspace.

    Args:
        workspace_id: Workspace ID (e.g., "my-project_abc123")

    Returns:
        Path to workspace LanceDB vector index
    """
    return Path(f".miller/indexes/{workspace_id}/vectors.lance")


def ensure_workspace_directories(workspace_id: str):
    """
    Create workspace directories if they don't exist.

    Creates the parent directories for both database and vector storage.

    Args:
        workspace_id: Workspace ID (e.g., "my-project_abc123")
    """
    db_path = get_workspace_db_path(workspace_id)
    vector_path = get_workspace_vector_path(workspace_id)

    # Create parent directories (same for both)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    vector_path.parent.mkdir(parents=True, exist_ok=True)
