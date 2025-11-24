"""
Default ignore patterns and vendor directory constants.

This module contains the static configuration used by ignore_patterns.py.
Separated for cleaner file organization and 500-line compliance.
"""

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
