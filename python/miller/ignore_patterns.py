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
# Based on Julie's battle-tested blacklist from production use
DEFAULT_IGNORES = [
    # ═══════════════════════════════════════════
    # Version Control
    # ═══════════════════════════════════════════
    ".git/",
    ".svn/",
    ".hg/",
    ".bzr/",

    # ═══════════════════════════════════════════
    # IDE and Editor
    # ═══════════════════════════════════════════
    ".vs/",      # Visual Studio
    ".vscode/",  # VS Code
    ".idea/",    # JetBrains
    ".eclipse/",
    "*.swp",     # Vim swap files
    "*.swo",

    # ═══════════════════════════════════════════
    # Build and Output Directories
    # ═══════════════════════════════════════════
    "bin/",
    "obj/",
    "build/",
    "dist/",
    "out/",
    "target/",   # Rust
    "Debug/",    # C#/C++ build configs
    "Release/",
    ".next/",    # Next.js
    ".nuxt/",    # Nuxt.js
    "DerivedData/", # Xcode

    # ═══════════════════════════════════════════
    # Package Managers and Dependencies
    # ═══════════════════════════════════════════
    "node_modules/",
    "packages/",
    ".npm/",
    "bower_components/",
    "vendor/",
    "Pods/",     # CocoaPods

    # ═══════════════════════════════════════════
    # Python Virtual Environments and Cache
    # ═══════════════════════════════════════════
    ".venv/",
    "venv/",
    "env/",
    ".env/",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".tox/",
    ".eggs/",
    "*.egg-info/",
    ".coverage",
    "htmlcov/",
    ".hypothesis/",

    # ═══════════════════════════════════════════
    # Cache and Temporary Files
    # ═══════════════════════════════════════════
    ".cache/",
    ".temp/",
    ".tmp/",
    "tmp/",
    "temp/",
    ".sass-cache/",
    "*.tmp",
    "*.temp",
    "*.swp",
    "*.lock",
    "*.pid",

    # ═══════════════════════════════════════════
    # Code Intelligence Tools (our own dirs)
    # ═══════════════════════════════════════════
    ".miller/",
    ".julie/",
    ".coa/",
    ".codenav/",
    # NOTE: .memories/ is NOT ignored - we want semantic search over checkpoints/plans!

    # ═══════════════════════════════════════════
    # Binary Files (by extension)
    # ═══════════════════════════════════════════
    # Executables and libraries
    "*.dll", "*.exe", "*.pdb", "*.so", "*.dylib", "*.lib", "*.a", "*.o", "*.obj", "*.bin",

    # Media files
    "*.jpg", "*.jpeg", "*.png", "*.gif", "*.bmp", "*.ico", "*.svg", "*.webp", "*.tiff",
    "*.mp3", "*.mp4", "*.avi", "*.mov", "*.wmv", "*.flv", "*.webm", "*.mkv", "*.wav",

    # Archives
    "*.zip", "*.rar", "*.7z", "*.tar", "*.gz", "*.bz2", "*.xz", "*.dmg", "*.pkg",

    # Database files
    "*.db", "*.sqlite", "*.sqlite3", "*.mdf", "*.ldf", "*.bak",

    # Logs and dumps
    "*.log", "*.dump", "*.core",

    # Font files
    "*.ttf", "*.otf", "*.woff", "*.woff2", "*.eot",

    # Documents (binary formats)
    "*.pdf", "*.doc", "*.docx", "*.xls", "*.xlsx", "*.ppt", "*.pptx",

    # ═══════════════════════════════════════════
    # macOS and Windows System Files
    # ═══════════════════════════════════════════
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
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
