"""
Workspace scanning and automatic indexing.

Adapts Julie's workspace indexing pattern for Miller:
- Automatic indexing on startup (if needed)
- Incremental indexing (hash-based change detection)
- .gitignore support via pathspec library
"""

from .index_stats import IndexStats
from .scanner import WorkspaceScanner

__all__ = ["WorkspaceScanner", "IndexStats"]
