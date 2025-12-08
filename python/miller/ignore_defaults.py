"""
Default ignore patterns and vendor directory constants.

This module contains the static configuration used by ignore_patterns.py.
Separated for cleaner file organization and 500-line compliance.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# File Size Limits
# ═══════════════════════════════════════════════════════════════════════════════
# Files larger than these limits are skipped during indexing.
# This prevents memory/performance issues with huge generated files.

# Default max file size: 1MB (1,048,576 bytes)
# Files without an extension-specific limit use this default.
DEFAULT_MAX_FILE_SIZE = 1_048_576

# Per-extension size overrides (in bytes)
# Some file types legitimately need larger limits:
# - Documentation (markdown, rst) can be large but valuable
# - Data files (json, yaml) might contain important configs
# - Generated types (d.ts) can be large but useful for navigation
EXTENSION_SIZE_LIMITS: dict[str, int] = {
    # ═══════════════════════════════════════════
    # Documentation - Allow larger files (5MB)
    # These are human-written and valuable for search
    # ═══════════════════════════════════════════
    ".md": 5_242_880,       # 5MB - README, docs, changelogs
    ".rst": 5_242_880,      # 5MB - Sphinx documentation
    ".txt": 2_097_152,      # 2MB - Plain text docs
    ".adoc": 5_242_880,     # 5MB - AsciiDoc
    # ═══════════════════════════════════════════
    # Config/Data files - Allow larger (2MB)
    # Often contain important project configuration
    # ═══════════════════════════════════════════
    ".json": 2_097_152,     # 2MB - Config, but not data dumps
    ".yaml": 2_097_152,     # 2MB - Config files
    ".yml": 2_097_152,      # 2MB - Config files
    ".toml": 2_097_152,     # 2MB - Cargo.toml, pyproject.toml
    ".xml": 2_097_152,      # 2MB - Config, project files
    # ═══════════════════════════════════════════
    # Type definitions - Allow larger (3MB)
    # Generated but useful for navigation/completion
    # ═══════════════════════════════════════════
    ".d.ts": 3_145_728,     # 3MB - TypeScript definitions
    ".pyi": 3_145_728,      # 3MB - Python type stubs
    # ═══════════════════════════════════════════
    # Stricter limits - Compiled/minified likely
    # ═══════════════════════════════════════════
    ".js": 512_000,         # 500KB - Often bundled/minified
    ".css": 512_000,        # 500KB - Often bundled/minified
    ".cs": 1_048_576,       # 1MB - C# (default, but explicit)
    ".java": 1_048_576,     # 1MB - Java (default, but explicit)
}

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
    "*.tmp.*",  # Editor temp files: file.tmp.12345
    "*.temp",
    "*.swp",
    "*.lock",
    "*.pid",
    # Editor backup/temp files
    "*~",  # Vim/Emacs backup files
    "*.bak",  # Generic backup files
    "[#]*[#]",  # Emacs auto-save files (#filename#)
    ".#*",  # Emacs lock files
    "*.orig",  # Git merge conflict originals
    "*.rej",  # Patch reject files
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
    # ═══════════════════════════════════════════
    # Noisy/Generated Files (high token, low signal)
    # These files are auto-generated and pollute search results
    # ═══════════════════════════════════════════
    # Lock files (huge, auto-generated, zero search value)
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Gemfile.lock",
    "composer.lock",
    "Pipfile.lock",
    "bun.lockb",
    # Minified/bundled files (unreadable, low signal)
    "*.min.js",
    "*.min.css",
    "*.bundle.js",
    "*.chunk.js",
    "*.map",  # Source maps
    # Generated type definitions
    "*.d.ts.map",
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
