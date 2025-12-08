"""
.gitignore pattern matching and file filtering.

Uses pathspec library for GitIgnore-compliant pattern matching.
"""

import logging
from pathlib import Path

from pathspec import PathSpec

from miller.ignore_defaults import (
    DEFAULT_IGNORES,
    DEFAULT_MAX_FILE_SIZE,
    EXTENSION_SIZE_LIMITS,
    VENDOR_DIRECTORY_NAMES,
)

# Get logger instance
logger = logging.getLogger("miller.ignore_patterns")


def load_gitignore(workspace_root: Path) -> PathSpec:
    """
    Load .gitignore patterns and combine with defaults.

    Args:
        workspace_root: Path to workspace directory

    Returns:
        PathSpec object for matching files against patterns
    """
    patterns = DEFAULT_IGNORES.copy()

    # Load .gitignore if it exists
    gitignore = workspace_root / ".gitignore"
    if gitignore.exists():
        try:
            gitignore_lines = gitignore.read_text(encoding="utf-8").splitlines()
            # Filter out empty lines and comments
            gitignore_patterns = [
                line
                for line in gitignore_lines
                if line.strip() and not line.strip().startswith("#")
            ]
            patterns.extend(gitignore_patterns)
        except Exception as e:
            # If .gitignore is unreadable, just use defaults
            logger.warning(f"Could not read .gitignore: {e}")

    return PathSpec.from_lines("gitwildmatch", patterns)


# ═══════════════════════════════════════════════════════════════════════════════
# File Size Filtering
# ═══════════════════════════════════════════════════════════════════════════════


def get_max_file_size(extension: str) -> int:
    """
    Get the maximum allowed file size for a given extension.

    Args:
        extension: File extension including dot (e.g., ".py", ".md")

    Returns:
        Maximum file size in bytes (uses DEFAULT_MAX_FILE_SIZE if no override)
    """
    # Normalize extension to lowercase with leading dot
    ext = extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"

    # Check for extension-specific limit
    if ext in EXTENSION_SIZE_LIMITS:
        return EXTENSION_SIZE_LIMITS[ext]

    # Special case: .d.ts files (compound extension)
    if ext == ".ts" and extension.lower().endswith(".d.ts"):
        return EXTENSION_SIZE_LIMITS.get(".d.ts", DEFAULT_MAX_FILE_SIZE)

    return DEFAULT_MAX_FILE_SIZE


def is_file_too_large(file_path: Path, max_size: int | None = None) -> bool:
    """
    Check if a file exceeds its size limit.

    Args:
        file_path: Path to the file to check
        max_size: Optional explicit size limit (overrides extension-based limit)

    Returns:
        True if file is too large, False otherwise
    """
    try:
        file_size = file_path.stat().st_size
    except OSError:
        # Can't stat file - don't filter it out
        return False

    # Use explicit limit if provided, otherwise derive from extension
    if max_size is not None:
        limit = max_size
    else:
        # Get extension (handle compound extensions like .d.ts)
        suffix = file_path.suffix.lower()
        name = file_path.name.lower()

        # Check for .d.ts specifically
        if name.endswith(".d.ts"):
            limit = EXTENSION_SIZE_LIMITS.get(".d.ts", DEFAULT_MAX_FILE_SIZE)
        else:
            limit = get_max_file_size(suffix)

    return file_size > limit


def should_ignore(file_path: Path, workspace_root: Path, check_size: bool = False) -> bool:
    """
    Check if a file should be ignored based on .gitignore patterns and optionally size.

    Args:
        file_path: Absolute path to file
        workspace_root: Absolute path to workspace root
        check_size: If True, also filter files that exceed size limits

    Returns:
        True if file should be ignored, False otherwise
    """
    spec = load_gitignore(workspace_root)

    # Convert to relative path for matching
    try:
        relative_path = file_path.relative_to(workspace_root)
    except ValueError:
        # File is not in workspace, ignore it
        return True

    # Check pattern-based ignore first
    if spec.match_file(str(relative_path)):
        return True

    # Optionally check file size
    if check_size and is_file_too_large(file_path):
        logger.debug(f"📏 Skipping oversized file: {relative_path}")
        return True

    return False


def filter_files(files: list[Path], workspace_root: Path, check_size: bool = False) -> list[Path]:
    """
    Filter a list of files, removing ignored paths.

    Args:
        files: List of file paths to filter
        workspace_root: Workspace root directory
        check_size: If True, also filter files that exceed size limits

    Returns:
        Filtered list of files (non-ignored only)
    """
    spec = load_gitignore(workspace_root)

    filtered = []
    for file_path in files:
        # Skip directories
        if file_path.is_dir():
            continue

        # Get relative path for matching
        try:
            relative_path = file_path.relative_to(workspace_root)
        except ValueError:
            # Not in workspace, skip
            continue

        # Check pattern-based ignore
        if spec.match_file(str(relative_path)):
            continue

        # Optionally check file size
        if check_size and is_file_too_large(file_path):
            logger.debug(f"📏 Filtering oversized file: {relative_path}")
            continue

        filtered.append(file_path)

    return filtered


# ═══════════════════════════════════════════════════════════════════════════════
# .millerignore Support - Custom project-specific ignore patterns
# ═══════════════════════════════════════════════════════════════════════════════


def load_millerignore(workspace_root: Path) -> list[str]:
    """
    Load custom ignore patterns from .millerignore file.

    Args:
        workspace_root: Path to workspace directory

    Returns:
        List of pattern strings (empty if file doesn't exist)
    """
    millerignore = workspace_root / ".millerignore"

    if not millerignore.exists():
        return []

    try:
        content = millerignore.read_text(encoding="utf-8")
        patterns = [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        if patterns:
            logger.info(f"📋 Loaded {len(patterns)} custom patterns from .millerignore")

        return patterns
    except Exception as e:
        logger.warning(f"Could not read .millerignore: {e}")
        return []


def load_all_ignores(workspace_root: Path) -> PathSpec:
    """
    Load all ignore patterns: defaults + .gitignore + .millerignore.

    Args:
        workspace_root: Path to workspace directory

    Returns:
        PathSpec object combining all patterns
    """
    patterns = DEFAULT_IGNORES.copy()

    # Load .gitignore
    gitignore = workspace_root / ".gitignore"
    if gitignore.exists():
        try:
            gitignore_lines = gitignore.read_text(encoding="utf-8").splitlines()
            gitignore_patterns = [
                line
                for line in gitignore_lines
                if line.strip() and not line.strip().startswith("#")
            ]
            patterns.extend(gitignore_patterns)
        except Exception as e:
            logger.warning(f"Could not read .gitignore: {e}")

    # Load .millerignore (project-specific patterns)
    miller_patterns = load_millerignore(workspace_root)
    patterns.extend(miller_patterns)

    return PathSpec.from_lines("gitwildmatch", patterns)


# ═══════════════════════════════════════════════════════════════════════════════
# Smart Vendor Detection - Auto-detect vendor/third-party code directories
# ═══════════════════════════════════════════════════════════════════════════════


class DirectoryStats:
    """Statistics for analyzing vendor code patterns in a directory."""

    def __init__(self):
        self.file_count = 0
        self.minified_count = 0
        self.jquery_count = 0
        self.bootstrap_count = 0
        self.vendor_lib_count = 0  # fontawesome, angular, react, etc.


def is_minified_file(file_path: Path) -> bool:
    """Check if a file is minified (generated code we should skip)."""
    name = file_path.name.lower()
    return (
        ".min." in name
        or name.endswith(".min.js")
        or name.endswith(".min.css")
        or name.endswith(".bundle.js")
        or name.endswith(".bundle.css")
        or name.endswith(".packed.js")
    )


def is_vendor_library_file(file_path: Path) -> bool:
    """Check if file name suggests it's a vendor library."""
    name = file_path.name.lower()
    vendor_prefixes = [
        "jquery",
        "bootstrap",
        "angular",
        "react",
        "vue",
        "ember",
        "backbone",
        "lodash",
        "underscore",
        "moment",
        "axios",
        "d3",
        "three",
        "fontawesome",
        "font-awesome",
        "popper",
        "modernizr",
        "normalize",
        "reset",
    ]
    return any(name.startswith(prefix) for prefix in vendor_prefixes)


def analyze_vendor_patterns(
    files: list[Path], workspace_root: Path
) -> list[str]:
    """
    Analyze files for vendor patterns and return directory paths to exclude.

    This scans the file list to detect:
    1. Directories with vendor-like names (libs/, vendor/, etc.)
    2. Directories with high concentration of minified files
    3. Directories with many jQuery/Bootstrap/etc files

    Args:
        files: List of file paths to analyze
        workspace_root: Workspace root directory

    Returns:
        List of relative directory paths to add to .millerignore
    """
    patterns: list[str] = []
    dir_stats: dict[Path, DirectoryStats] = {}

    # Collect statistics for each directory
    for file_path in files:
        parent = file_path.parent
        if parent not in dir_stats:
            dir_stats[parent] = DirectoryStats()

        stats = dir_stats[parent]
        stats.file_count += 1

        if is_minified_file(file_path):
            stats.minified_count += 1
        if is_vendor_library_file(file_path):
            stats.vendor_lib_count += 1

        # Specific library detection
        name = file_path.name.lower()
        if name.startswith("jquery"):
            stats.jquery_count += 1
        if name.startswith("bootstrap"):
            stats.bootstrap_count += 1

    # Build set of vendor candidate directories
    vendor_candidates: set[Path] = set()

    for dir_path in dir_stats:
        # Check the directory itself
        if dir_path.name.lower() in VENDOR_DIRECTORY_NAMES:
            vendor_candidates.add(dir_path)

        # Check all ancestors
        current = dir_path
        while current != workspace_root and current.parent != current:
            if current.name.lower() in VENDOR_DIRECTORY_NAMES:
                vendor_candidates.add(current)
            current = current.parent

    # Evaluate each vendor candidate
    for vendor_dir in vendor_candidates:
        # Count files recursively in this directory
        recursive_count = sum(
            stats.file_count
            for subdir, stats in dir_stats.items()
            if subdir == vendor_dir or _is_subpath(subdir, vendor_dir)
        )

        # Convert to relative pattern
        try:
            relative = vendor_dir.relative_to(workspace_root)
            pattern = str(relative).replace("\\", "/")
        except ValueError:
            continue

        # Only add if has meaningful number of files
        if recursive_count > 5:
            logger.info(
                f"📦 Detected vendor directory: {pattern}/ ({recursive_count} files)"
            )
            if pattern not in patterns:
                patterns.append(pattern)

    # Check for medium-confidence patterns based on file content
    for dir_path, stats in dir_stats.items():
        try:
            relative = dir_path.relative_to(workspace_root)
            pattern = str(relative).replace("\\", "/")
        except ValueError:
            continue

        # Skip if already covered by a parent pattern
        if any(pattern.startswith(p) for p in patterns):
            continue

        # High concentration of vendor library files
        if stats.jquery_count > 3 or stats.bootstrap_count > 2 or stats.vendor_lib_count > 5:
            logger.info(f"📦 Detected library directory: {pattern}/ (vendor files)")
            patterns.append(pattern)
        # High concentration of minified files (>50% of directory)
        elif stats.minified_count > 10 and stats.minified_count > stats.file_count / 2:
            logger.info(
                f"📦 Detected minified directory: {pattern}/ ({stats.minified_count} minified)"
            )
            patterns.append(pattern)

    return patterns


def _is_subpath(path: Path, parent: Path) -> bool:
    """Check if path is a subpath of parent."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def generate_millerignore(workspace_root: Path, patterns: list[str]) -> None:
    """
    Generate .millerignore file with detected patterns and documentation.

    Args:
        workspace_root: Workspace root directory
        patterns: List of relative directory paths to ignore
    """
    from datetime import datetime

    pattern_lines = "\n".join(f"{p}/" for p in patterns)

    content = f"""# .millerignore - Miller Code Intelligence Exclusion Patterns
# Auto-generated by Miller on {datetime.now().strftime("%Y-%m-%d")}
#
# These patterns exclude files from symbol extraction and semantic search.
# Files can still be searched as TEXT using fast_search(method="text").
#
# To modify: Add/remove patterns (gitignore syntax), then run
# manage_workspace(operation="refresh") to reindex.
#
# Auto-Detected Vendor Directories:
{pattern_lines}

# Common Patterns (uncomment if needed):
# *.min.js
# *.min.css
"""

    millerignore_path = workspace_root / ".millerignore"
    millerignore_path.write_text(content, encoding="utf-8")
    logger.info(f"📝 Created .millerignore with {len(patterns)} patterns")
