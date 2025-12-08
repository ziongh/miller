"""
File discovery and change detection utilities for workspace scanning.

Extracted from WorkspaceScanner to reduce class complexity.

Performance: Uses os.walk() with directory pruning to skip ignored directories
BEFORE descending into them. This is critical on Windows where walking into
.venv (35K+ files) then filtering is 20x slower than skipping it entirely.
"""

import logging
import os
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


def _optimized_walk(workspace_root: Path, ignore_spec):
    """
    Walk workspace using os.walk() with directory pruning.

    CRITICAL OPTIMIZATION: Prunes ignored directories IN-PLACE before descending.
    This prevents walking into .venv, node_modules, target/, etc.

    On Windows with a .venv containing 35K files:
    - rglob("*") + filter: ~7 seconds (walks everything, then discards)
    - os.walk() + pruning: ~0.3 seconds (skips ignored dirs entirely)

    Yields:
        Tuple of (file_path: Path, rel_str: str) for each non-ignored file
    """
    workspace_str = str(workspace_root)

    for root, dirs, files in os.walk(workspace_root):
        # Calculate relative path for this directory
        if root == workspace_str:
            rel_root = ""
        else:
            rel_root = os.path.relpath(root, workspace_root).replace("\\", "/")

        # CRITICAL: Prune ignored directories IN-PLACE to prevent descent
        # This is what makes os.walk() faster than rglob() - we skip entire subtrees
        dirs_to_keep = []
        for d in dirs:
            # Build the relative path for this directory (with trailing slash for pathspec)
            if rel_root:
                dir_rel = f"{rel_root}/{d}/"
            else:
                dir_rel = f"{d}/"

            # Keep directory only if NOT ignored
            if not ignore_spec.match_file(dir_rel):
                dirs_to_keep.append(d)

        # Modify dirs in-place to prune the walk
        dirs[:] = dirs_to_keep

        # Yield non-ignored files
        for f in files:
            if rel_root:
                rel_str = f"{rel_root}/{f}"
            else:
                rel_str = f

            # Skip ignored files
            if ignore_spec.match_file(rel_str):
                continue

            file_path = Path(root) / f
            yield file_path, rel_str


def scan_workspace(
    workspace_root: Path,
    ignore_spec,
    perform_vendor_detection: bool = False,
) -> WorkspaceScanResult:
    """
    Single-pass workspace scan that collects ALL needed information.

    Uses optimized os.walk() with directory pruning - critical for Windows
    performance where walking into .venv then filtering is 20x slower than
    skipping it entirely.

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

    # Use optimized walk with directory pruning
    for file_path, rel_str in _optimized_walk(workspace_root, ignore_spec):
        # Skip symlinks
        if file_path.is_symlink():
            continue

        # Check if language is supported
        language = miller_core.detect_language(str(file_path))
        if language:
            indexable_files.append(file_path)
            # Only add to all_paths if file will actually be indexed
            # Text files are discovered (for vendor detection) but not indexed,
            # so they shouldn't be tracked for incremental indexing checks
            if language != "text":
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

    # Use optimized walk with directory pruning
    for file_path, rel_str in _optimized_walk(workspace_root, ignore_spec):
        # Skip symlinks
        if file_path.is_symlink():
            continue

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

    # Use optimized walk with directory pruning
    for file_path, rel_str in _optimized_walk(workspace_root, ignore_spec):
        # Skip symlinks
        if file_path.is_symlink():
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
    # Use optimized walk with directory pruning
    for file_path, rel_str in _optimized_walk(workspace_root, ignore_spec):
        # Skip symlinks
        if file_path.is_symlink():
            continue

        # Check if supported language and not in DB
        if miller_core and miller_core.detect_language(str(file_path)):
            if rel_str not in db_paths:
                logger.debug(f"   New file detected: {rel_str}")
                return True

    return False
