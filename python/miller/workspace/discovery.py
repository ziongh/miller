"""
File discovery and change detection utilities for workspace scanning.

Extracted from WorkspaceScanner to reduce class complexity.

Performance: All scanning functions share a single filesystem walk via
scan_workspace() to avoid redundant rglob() calls.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("miller.workspace")

# Import Rust core
try:
    from .. import miller_core
except ImportError:
    miller_core = None


@dataclass
class WorkspaceScanResult:
    """Result of a single-pass workspace scan.

    Collects all information needed for indexing decisions in ONE filesystem walk,
    avoiding the previous pattern of 3 separate rglob() calls.
    """
    indexable_files: list[Path]  # Files with supported languages
    all_paths: set[str]  # Relative paths as strings (for DB comparison)
    max_mtime: int  # Newest file modification time
    vendor_detection_needed: bool  # Whether vendor detection was performed


def scan_workspace(
    workspace_root: Path,
    ignore_spec,
    perform_vendor_detection: bool = False,
) -> WorkspaceScanResult:
    """
    Single-pass workspace scan that collects ALL needed information.

    This replaces the previous pattern of calling walk_directory(),
    get_max_file_mtime(), and has_new_files() separately - each of which
    did its own rglob("*") walk. On a 10K file workspace, this reduces
    ~30,000 stat calls to ~10,000.

    Args:
        workspace_root: Root directory of workspace
        ignore_spec: Pathspec for .gitignore/.millerignore patterns
        perform_vendor_detection: Whether to check for vendor patterns

    Returns:
        WorkspaceScanResult with all scan data
    """
    if miller_core is None:
        return WorkspaceScanResult(
            indexable_files=[],
            all_paths=set(),
            max_mtime=0,
            vendor_detection_needed=False,
        )

    millerignore_path = workspace_root / ".millerignore"
    needs_vendor_detection = (
        perform_vendor_detection
        and not millerignore_path.exists()
    )

    if needs_vendor_detection:
        logger.info("🤖 No .millerignore found - scanning for vendor patterns...")

    indexable_files: list[Path] = []
    all_paths: set[str] = set()
    max_mtime = 0

    # SINGLE filesystem walk - collect everything we need
    for file_path in workspace_root.rglob("*"):
        # Skip directories and symlinks
        if file_path.is_dir() or file_path.is_symlink():
            continue

        # Get relative path
        try:
            relative_path = file_path.relative_to(workspace_root)
        except ValueError:
            continue  # Not in workspace

        # Convert to Unix-style path string for consistency
        rel_str = str(relative_path).replace("\\", "/")

        # Check if ignored
        if ignore_spec.match_file(rel_str):
            continue

        # Check if language is supported
        language = miller_core.detect_language(str(file_path))
        if language:
            indexable_files.append(file_path)
            all_paths.add(rel_str)

            # Track max mtime while we're here
            try:
                mtime = int(file_path.stat().st_mtime)
                if mtime > max_mtime:
                    max_mtime = mtime
            except OSError:
                pass  # Can't stat, skip mtime tracking

    return WorkspaceScanResult(
        indexable_files=indexable_files,
        all_paths=all_paths,
        max_mtime=max_mtime,
        vendor_detection_needed=needs_vendor_detection,
    )


def walk_directory(
    workspace_root: Path,
    ignore_spec,
    perform_vendor_detection: bool = False,
) -> tuple[list[Path], bool]:
    """
    Walk workspace directory and find indexable files.

    On first run (when perform_vendor_detection=True and no .millerignore exists),
    performs smart vendor detection to auto-generate exclusion patterns.

    Args:
        workspace_root: Root directory of workspace
        ignore_spec: Pathspec for .gitignore/.millerignore patterns
        perform_vendor_detection: Whether to perform smart vendor detection

    Returns:
        Tuple of (list of file paths, bool indicating if vendor detection was performed)
    """
    if miller_core is None:
        return [], False

    millerignore_path = workspace_root / ".millerignore"
    needs_vendor_detection = (
        perform_vendor_detection
        and not millerignore_path.exists()
    )

    if needs_vendor_detection:
        logger.info("🤖 No .millerignore found - scanning for vendor patterns...")

    indexable_files = []
    all_files_for_analysis = []  # For vendor detection

    for file_path in workspace_root.rglob("*"):
        # Skip directories and symlinks
        if file_path.is_dir() or file_path.is_symlink():
            continue

        # Check if ignored
        try:
            relative_path = file_path.relative_to(workspace_root)
        except ValueError:
            continue  # Not in workspace

        if ignore_spec.match_file(str(relative_path)):
            continue  # Ignored by .gitignore or .millerignore

        # Check if language is supported
        language = miller_core.detect_language(str(file_path))
        if language:
            indexable_files.append(file_path)
            if needs_vendor_detection:
                all_files_for_analysis.append(file_path)

    return indexable_files, bool(all_files_for_analysis)


def get_max_file_mtime(workspace_root: Path, ignore_spec) -> int:
    """
    Get the maximum (newest) file modification time in the workspace.

    Args:
        workspace_root: Root directory of workspace
        ignore_spec: Pathspec for .gitignore/.millerignore patterns

    Returns:
        Unix timestamp of the most recently modified file
    """
    max_mtime = 0

    # Quick scan of just supported code files
    for file_path in workspace_root.rglob("*"):
        if file_path.is_dir() or file_path.is_symlink():
            continue

        # Check if ignored
        try:
            relative_path = file_path.relative_to(workspace_root)
        except ValueError:
            continue

        if ignore_spec.match_file(str(relative_path)):
            continue

        # Check if language is supported (only check code files)
        if miller_core and miller_core.detect_language(str(file_path)):
            try:
                mtime = int(file_path.stat().st_mtime)
                if mtime > max_mtime:
                    max_mtime = mtime
            except OSError:
                continue

    return max_mtime


def has_new_files(
    workspace_root: Path,
    ignore_spec,
    db_paths: set[str],
) -> bool:
    """
    Check if there are any new files on disk not in the database.

    Args:
        workspace_root: Root directory of workspace
        ignore_spec: Pathspec for .gitignore/.millerignore patterns
        db_paths: Set of file paths currently in the database

    Returns:
        True if new files found, False otherwise
    """
    for file_path in workspace_root.rglob("*"):
        if file_path.is_dir() or file_path.is_symlink():
            continue

        try:
            relative_path = file_path.relative_to(workspace_root)
        except ValueError:
            continue

        # Convert to Unix-style path for comparison
        rel_str = str(relative_path).replace("\\", "/")

        if ignore_spec.match_file(rel_str):
            continue

        # Check if supported language and not in DB
        if miller_core and miller_core.detect_language(str(file_path)):
            if rel_str not in db_paths:
                logger.debug(f"   New file detected: {rel_str}")
                return True

    return False
