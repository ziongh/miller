"""
Workspace scanning and automatic indexing.

Adapts Julie's workspace indexing pattern for Miller:
- Automatic indexing on startup (if needed)
- Incremental indexing (hash-based change detection)
- .gitignore support via pathspec library
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import hashlib
import asyncio
import logging

from .storage import StorageManager
from .embeddings import EmbeddingManager, VectorStore
from .ignore_patterns import load_gitignore

# Get logger instance
logger = logging.getLogger("miller.workspace")


# Import Rust core
try:
    from . import miller_core
except ImportError:
    # For testing without building Rust extension
    miller_core = None


class IndexStats:
    """Statistics from workspace indexing operation."""

    def __init__(self):
        self.indexed = 0  # New files indexed
        self.updated = 0  # Existing files re-indexed
        self.skipped = 0  # Unchanged files skipped
        self.deleted = 0  # Files deleted from DB
        self.errors = 0   # Files that failed to index

    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary for JSON serialization."""
        return {
            "indexed": self.indexed,
            "updated": self.updated,
            "skipped": self.skipped,
            "deleted": self.deleted,
            "errors": self.errors,
        }


class WorkspaceScanner:
    """
    Scans workspace for code files and manages indexing.

    Handles:
    - File discovery (respecting .gitignore)
    - Change detection (hash-based)
    - Incremental indexing
    - Cleanup of deleted files
    """

    def __init__(
        self,
        workspace_root: Path,
        storage: StorageManager,
        embeddings: EmbeddingManager,
        vector_store: VectorStore,
    ):
        """
        Initialize workspace scanner.

        Args:
            workspace_root: Path to workspace directory
            storage: SQLite storage manager
            embeddings: Embedding generator
            vector_store: LanceDB vector store
        """
        self.workspace_root = Path(workspace_root)
        self.storage = storage
        self.embeddings = embeddings
        self.vector_store = vector_store

        # Load .gitignore patterns
        self.ignore_spec = load_gitignore(self.workspace_root)

    def _walk_directory(self) -> List[Path]:
        """
        Walk workspace directory and find indexable files.

        Returns:
            List of file paths to index (filtered by .gitignore and language support)
        """
        if miller_core is None:
            return []  # Can't detect languages without Rust core

        indexable_files = []

        for file_path in self.workspace_root.rglob("*"):
            # Skip directories and symlinks
            if file_path.is_dir() or file_path.is_symlink():
                continue

            # Check if ignored
            try:
                relative_path = file_path.relative_to(self.workspace_root)
            except ValueError:
                continue  # Not in workspace

            if self.ignore_spec.match_file(str(relative_path)):
                continue  # Ignored by .gitignore

            # Check if language is supported
            language = miller_core.detect_language(str(file_path))
            if language:
                indexable_files.append(file_path)

        return indexable_files

    def _compute_file_hash(self, file_path: Path) -> str:
        """
        Compute SHA-256 hash of file content.

        Args:
            file_path: Path to file

        Returns:
            Hex digest of SHA-256 hash
        """
        try:
            content = file_path.read_text(encoding="utf-8")
            return hashlib.sha256(content.encode("utf-8")).hexdigest()
        except Exception:
            # If file can't be read, return empty hash
            return ""

    def _needs_indexing(self, file_path: Path) -> bool:
        """
        Check if file needs to be indexed.

        Args:
            file_path: Path to file (absolute)

        Returns:
            True if file should be indexed (new or changed), False if unchanged
        """
        # Convert to relative Unix-style path
        relative_path = str(file_path.relative_to(self.workspace_root)).replace("\\", "/")

        # Compute current hash
        current_hash = self._compute_file_hash(file_path)
        if not current_hash:
            return False  # Can't read file, skip

        # Check if file exists in DB (using relative path)
        db_files = self.storage.get_all_files()

        for db_file in db_files:
            if db_file["path"] == relative_path:
                # File exists in DB, check if hash changed
                return db_file["hash"] != current_hash

        # File not in DB, needs indexing
        return True

    async def _index_file(self, file_path: Path) -> bool:
        """
        Index a single file.

        Args:
            file_path: Path to file (absolute)

        Returns:
            True if successful, False if error
        """
        if miller_core is None:
            return False

        try:
            # Convert to relative Unix-style path (like Julie does)
            # e.g., /Users/murphy/source/miller/src/lib.rs -> src/lib.rs
            relative_path = str(file_path.relative_to(self.workspace_root)).replace("\\", "/")

            # Read file
            content = file_path.read_text(encoding="utf-8")

            # Detect language
            language = miller_core.detect_language(str(file_path))
            if not language:
                return False

            # Extract symbols (pass relative path so symbols have correct file_path)
            result = miller_core.extract_file(content, language, relative_path)

            # Compute hash
            file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            # Store file metadata (using relative path)
            self.storage.add_file(
                file_path=relative_path,
                language=language,
                content=content,
                hash=file_hash,
                size=len(content)
            )

            # Store symbols
            if result.symbols:
                self.storage.add_symbols_batch(result.symbols)

            # Store identifiers
            if result.identifiers:
                self.storage.add_identifiers_batch(result.identifiers)

            # Store relationships
            if result.relationships:
                self.storage.add_relationships_batch(result.relationships)

            # Generate embeddings
            if result.symbols:
                import numpy as np
                vectors = self.embeddings.embed_batch(result.symbols)

                # Store in LanceDB (using relative path)
                self.vector_store.update_file_symbols(relative_path, result.symbols, vectors)

            return True

        except Exception as e:
            # Log error but continue with other files
            logger.warning(f"Failed to index {file_path}: {e}")
            return False

    async def check_if_indexing_needed(self) -> bool:
        """
        Check if workspace needs indexing.

        Returns:
            True if indexing needed (DB empty or files changed), False otherwise
        """
        # Check if DB has any files
        db_files = self.storage.get_all_files()

        if not db_files:
            # Empty DB, needs indexing
            return True

        # Check if any files on disk have changed or are new
        disk_files = self._walk_directory()

        for file_path in disk_files:
            if self._needs_indexing(file_path):
                # At least one file changed/new
                return True

        # All files match DB, no indexing needed
        return False

    async def index_workspace(self) -> Dict[str, int]:
        """
        Index entire workspace with incremental change detection.

        Flow:
        1. Scan for files on disk
        2. For each file:
           - If new or changed: index
           - If unchanged: skip
        3. Clean up deleted files from DB
        4. Return statistics

        Returns:
            Dict with indexing statistics
        """
        stats = IndexStats()

        # Get current state
        disk_files = self._walk_directory()
        db_files = self.storage.get_all_files()

        # Build lookup for DB files (uses relative paths)
        db_files_map = {f["path"]: f for f in db_files}
        # Convert disk files to relative Unix-style paths to match DB
        disk_files_set = {str(f.relative_to(self.workspace_root)).replace("\\", "/") for f in disk_files}

        # Index new/changed files
        for file_path in disk_files:
            # Convert to relative path for DB lookup
            relative_path = str(file_path.relative_to(self.workspace_root)).replace("\\", "/")

            if relative_path in db_files_map:
                # File exists in DB, check if changed
                if self._needs_indexing(file_path):
                    # File changed, re-index
                    success = await self._index_file(file_path)
                    if success:
                        stats.updated += 1
                    else:
                        stats.errors += 1
                else:
                    # File unchanged, skip
                    stats.skipped += 1
            else:
                # New file, index
                success = await self._index_file(file_path)
                if success:
                    stats.indexed += 1
                else:
                    stats.errors += 1

        # Clean up deleted files
        for db_file_path in db_files_map.keys():
            if db_file_path not in disk_files_set:
                # File deleted from disk, remove from DB
                self.storage.delete_file(db_file_path)
                stats.deleted += 1

        return stats.to_dict()
