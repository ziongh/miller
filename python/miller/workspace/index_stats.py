"""
Statistics tracking for workspace indexing operations.

Provides:
- IndexStats class for collecting and reporting indexing metrics
"""


class IndexStats:
    """Statistics from workspace indexing operation."""

    def __init__(self):
        self.indexed = 0  # New files indexed
        self.updated = 0  # Existing files re-indexed
        self.skipped = 0  # Unchanged files skipped
        self.deleted = 0  # Files deleted from DB
        self.errors = 0  # Files that failed to index
        self.total_symbols = 0  # Total symbols extracted across all files

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary for JSON serialization."""
        return {
            "indexed": self.indexed,
            "updated": self.updated,
            "skipped": self.skipped,
            "deleted": self.deleted,
            "errors": self.errors,
            "total_symbols": self.total_symbols,
        }
