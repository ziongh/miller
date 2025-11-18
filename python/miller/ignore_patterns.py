"""
.gitignore pattern matching and file filtering.

Uses pathspec library for GitIgnore-compliant pattern matching.
"""

from pathlib import Path
from typing import List
from pathspec import PathSpec
import logging

# Get logger instance
logger = logging.getLogger("miller.ignore_patterns")


# Default ignore patterns (always applied)
DEFAULT_IGNORES = [
    ".git/",
    "node_modules/",
    ".venv/",
    "venv/",
    "__pycache__/",
    "*.pyc",
    ".pytest_cache/",
    "build/",
    "dist/",
    ".eggs/",
    "*.egg-info/",
    ".tox/",
    ".coverage",
    "htmlcov/",
    ".mypy_cache/",
    ".ruff_cache/",
    "target/",  # Rust
    ".idea/",   # JetBrains IDEs
    ".vscode/", # VS Code (except settings)
    "*.swp",    # Vim
    ".DS_Store", # macOS
]


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
                line for line in gitignore_lines if line.strip() and not line.strip().startswith("#")
            ]
            patterns.extend(gitignore_patterns)
        except Exception as e:
            # If .gitignore is unreadable, just use defaults
            logger.warning(f"Could not read .gitignore: {e}")

    return PathSpec.from_lines("gitwildmatch", patterns)


def should_ignore(file_path: Path, workspace_root: Path) -> bool:
    """
    Check if a file should be ignored based on .gitignore patterns.

    Args:
        file_path: Absolute path to file
        workspace_root: Absolute path to workspace root

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

    # PathSpec.match_file expects string path
    return spec.match_file(str(relative_path))


def filter_files(files: List[Path], workspace_root: Path) -> List[Path]:
    """
    Filter a list of files, removing ignored paths.

    Args:
        files: List of file paths to filter
        workspace_root: Workspace root directory

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

        # Check if should be ignored
        if not spec.match_file(str(relative_path)):
            filtered.append(file_path)

    return filtered
