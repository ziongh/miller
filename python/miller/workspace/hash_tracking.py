"""
Hash-based file change detection for incremental indexing.

Provides:
- SHA-256 hash computation for files
- Change detection via hash comparison
- Database staleness checks
"""

import hashlib
import logging
import time
from pathlib import Path

# Get logger instance
logger = logging.getLogger("miller.workspace")


def compute_file_hash(file_path: Path) -> str:
    """
    Compute SHA-256 hash of file content.

    Args:
        file_path: Path to file

    Returns:
        Hex digest of SHA-256 hash (empty string if file can't be read)
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    except Exception:
        # If file can't be read, return empty hash
        return ""


def needs_indexing(file_path: Path, workspace_root: Path, db_files_map: dict[str, dict]) -> bool:
    """
    Check if file needs to be indexed.

    Args:
        file_path: Path to file (absolute)
        workspace_root: Root path of workspace
        db_files_map: Dict mapping relative paths to file info (performance optimization)

    Returns:
        True if file should be indexed (new or changed), False if unchanged
    """
    # Convert to relative Unix-style path
    relative_path = str(file_path.relative_to(workspace_root)).replace("\\", "/")

    # Compute current hash
    current_hash = compute_file_hash(file_path)
    if not current_hash:
        return False  # Can't read file, skip

    # Check if file exists in DB (O(1) lookup with map)
    if relative_path in db_files_map:
        # File exists in DB, check if hash changed
        return db_files_map[relative_path]["hash"] != current_hash

    # File not in DB, needs indexing
    return True


def get_database_mtime(db_path: str) -> float:
    """
    Get modification time of database file.

    Args:
        db_path: Path to database file (from StorageManager)

    Returns:
        Timestamp of database file, or 0 if doesn't exist (or in-memory)

    Note: Following Julie's staleness check pattern for performance
    """
    # Handle in-memory databases (used in tests)
    if db_path == ":memory:":
        # For in-memory DB, use current time (always considered fresh)
        # This prevents false positives in staleness check during testing
        return time.time()

    db_file_path = Path(db_path)
    if not db_file_path.exists():
        return 0  # DB doesn't exist, very old

    try:
        return db_file_path.stat().st_mtime
    except Exception:
        return 0


def get_max_file_mtime(disk_files: list[Path]) -> float:
    """
    Get the newest file modification time in workspace.

    Args:
        disk_files: List of file paths to check

    Returns:
        Maximum mtime found, or 0 if no files

    Note: Following Julie's staleness check pattern for performance
    """
    max_mtime = 0.0
    for file_path in disk_files:
        try:
            mtime = file_path.stat().st_mtime
            if mtime > max_mtime:
                max_mtime = mtime
        except Exception:
            continue  # Skip files we can't stat
    return max_mtime
