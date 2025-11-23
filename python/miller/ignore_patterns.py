"""
.gitignore pattern matching and file filtering.

Uses pathspec library for GitIgnore-compliant pattern matching.
"""

import logging
from pathlib import Path

from pathspec import PathSpec

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
    ".vs/",  # Visual Studio
    ".vscode/",  # VS Code
    ".idea/",  # JetBrains
    ".eclipse/",
    "*.swp",  # Vim swap files
    "*.swo",
    # ═══════════════════════════════════════════
    # Build and Output Directories
    # ═══════════════════════════════════════════
    "bin/",
    "obj/",
    "build/",
    "dist/",
    "out/",
    "target/",  # Rust
    "Debug/",  # C#/C++ build configs
    "Release/",
    ".next/",  # Next.js
    ".nuxt/",  # Nuxt.js
    "DerivedData/",  # Xcode
    # ═══════════════════════════════════════════
    # Package Managers and Dependencies
    # ═══════════════════════════════════════════
    "node_modules/",
    "packages/",
    ".npm/",
    "bower_components/",
    "vendor/",
    "Pods/",  # CocoaPods
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
    "*.dll",
    "*.exe",
    "*.pdb",
    "*.so",
    "*.dylib",
    "*.lib",
    "*.a",
    "*.o",
    "*.obj",
    "*.bin",
    # Media files
    "*.jpg",
    "*.jpeg",
    "*.png",
    "*.gif",
    "*.bmp",
    "*.ico",
    "*.svg",
    "*.webp",
    "*.tiff",
    "*.mp3",
    "*.mp4",
    "*.avi",
    "*.mov",
    "*.wmv",
    "*.flv",
    "*.webm",
    "*.mkv",
    "*.wav",
    # Archives
    "*.zip",
    "*.rar",
    "*.7z",
    "*.tar",
    "*.gz",
    "*.bz2",
    "*.xz",
    "*.dmg",
    "*.pkg",
    # Database files
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.mdf",
    "*.ldf",
    "*.bak",
    # Logs and dumps
    "*.log",
    "*.dump",
    "*.core",
    # Font files
    "*.ttf",
    "*.otf",
    "*.woff",
    "*.woff2",
    "*.eot",
    # Documents (binary formats)
    "*.pdf",
    "*.doc",
    "*.docx",
    "*.xls",
    "*.xlsx",
    "*.ppt",
    "*.pptx",
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
                line
                for line in gitignore_lines
                if line.strip() and not line.strip().startswith("#")
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


def filter_files(files: list[Path], workspace_root: Path) -> list[Path]:
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

# Directory names that typically contain vendor/third-party code
VENDOR_DIRECTORY_NAMES = {
    "libs",
    "lib",
    "plugin",
    "plugins",
    "vendor",
    "third-party",
    "third_party",
    "thirdparty",
    "external",
    "externals",
    "deps",
    "dependencies",
    # Build outputs (already in DEFAULT_IGNORES but detect for .millerignore)
    "target",
    "node_modules",
    "build",
    "dist",
    "out",
    "bin",
    "obj",
    "Debug",
    "Release",
    "packages",
    "bower_components",
}


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
# ═══════════════════════════════════════════════════════════════
# What Miller Did Automatically
# ═══════════════════════════════════════════════════════════════
# Miller analyzed your project and detected vendor/third-party code patterns.
# These patterns exclude files from:
# • Symbol extraction (function/class definitions)
# • Semantic search embeddings (AI-powered search)
#
# Files can still be searched as TEXT using fast_search(method="text"),
# but won't clutter symbol navigation or semantic search results.
#
# ═══════════════════════════════════════════════════════════════
# Why Exclude Vendor Code?
# ═══════════════════════════════════════════════════════════════
# 1. Search Quality: Prevents vendor code from polluting search results
# 2. Performance: Skips symbol extraction for thousands of vendor functions
# 3. Relevance: Semantic search focuses on YOUR code, not libraries
#
# ═══════════════════════════════════════════════════════════════
# How to Modify This File
# ═══════════════════════════════════════════════════════════════
# • Add patterns: Just add new lines with glob patterns (gitignore syntax)
# • Remove patterns: Delete lines or comment out with #
# • Check impact: Use manage_workspace(operation="health")
#
# FALSE POSITIVE? If Miller excluded something important:
# 1. Delete or comment out the pattern below
# 2. Run manage_workspace(operation="refresh") to reindex
#
# DISABLE AUTO-GENERATION: Create this file manually before first run
#
# ═══════════════════════════════════════════════════════════════
# Auto-Detected Vendor Directories
# ═══════════════════════════════════════════════════════════════
{pattern_lines}

# ═══════════════════════════════════════════════════════════════
# Common Patterns (Uncomment if needed in your project)
# ═══════════════════════════════════════════════════════════════
# *.min.js
# *.min.css
# jquery*.js
# bootstrap*.js
# angular*.js
# react*.js

# ═══════════════════════════════════════════════════════════════
# Debugging: If Search Isn't Finding Files
# ═══════════════════════════════════════════════════════════════
# Use manage_workspace(operation="health") to see:
# • How many files are excluded by each pattern
# • Whether patterns are too broad
#
# If a pattern excludes files it shouldn't, comment it out or make
# it more specific (e.g., "src/vendor/lib/" vs "lib/")
"""

    millerignore_path = workspace_root / ".millerignore"
    millerignore_path.write_text(content, encoding="utf-8")
    logger.info(f"📝 Created .millerignore with {len(patterns)} patterns")
