"""
Workspace scanning and automatic indexing.

Adapts Julie's workspace indexing pattern for Miller:
- Automatic indexing on startup (if needed)
- Incremental indexing (hash-based change detection)
- .gitignore support via pathspec library
"""

import hashlib
import logging
from pathlib import Path

from .embeddings import EmbeddingManager, VectorStore
from .ignore_patterns import load_gitignore
from .storage import StorageManager

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
        self.errors = 0  # Files that failed to index

    def to_dict(self) -> dict[str, int]:
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

    def _walk_directory(self) -> list[Path]:
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

    def _needs_indexing(self, file_path: Path, db_files_map: dict[str, dict]) -> bool:
        """
        Check if file needs to be indexed.

        Args:
            file_path: Path to file (absolute)
            db_files_map: Dict mapping relative paths to file info (performance optimization)

        Returns:
            True if file should be indexed (new or changed), False if unchanged
        """
        # Convert to relative Unix-style path
        relative_path = str(file_path.relative_to(self.workspace_root)).replace("\\", "/")

        # Compute current hash
        current_hash = self._compute_file_hash(file_path)
        if not current_hash:
            return False  # Can't read file, skip

        # Check if file exists in DB (O(1) lookup with map)
        if relative_path in db_files_map:
            # File exists in DB, check if hash changed
            return db_files_map[relative_path]["hash"] != current_hash

        # File not in DB, needs indexing
        return True

    async def _index_file_timed(self, file_path: Path):
        """
        Index a single file with timing instrumentation.

        Args:
            file_path: Path to file (absolute)

        Returns:
            Tuple of (success, extraction_time, embedding_time, db_time)
        """
        import time

        if miller_core is None:
            return (False, 0.0, 0.0, 0.0)

        try:
            # Convert to relative Unix-style path (like Julie does)
            relative_path = str(file_path.relative_to(self.workspace_root)).replace("\\", "/")

            # Read file
            content = file_path.read_text(encoding="utf-8")

            # Detect language
            language = miller_core.detect_language(str(file_path))
            if not language:
                return (False, 0.0, 0.0, 0.0)

            # Phase 1: Tree-sitter extraction
            extraction_start = time.time()
            result = miller_core.extract_file(
                content=content, language=language, file_path=relative_path
            )
            extraction_time = time.time() - extraction_start

            # Compute file hash
            file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            # Phase 2: Database writes (symbols, identifiers, relationships)
            db_start = time.time()

            # Store file metadata
            self.storage.add_file(
                file_path=relative_path,
                language=language,
                content=content,
                hash=file_hash,
                size=len(content),
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

            db_time = time.time() - db_start

            # Phase 3: Generate embeddings
            embedding_time = 0.0
            if result.symbols:
                embedding_start = time.time()
                vectors = self.embeddings.embed_batch(result.symbols)

                # Store in LanceDB (using relative path)
                self.vector_store.update_file_symbols(relative_path, result.symbols, vectors)
                embedding_time = time.time() - embedding_start

            return (True, extraction_time, embedding_time, db_time)

        except Exception as e:
            # Log error but continue with other files
            logger.warning(f"Failed to index {file_path}: {e}")
            return (False, 0.0, 0.0, 0.0)

    async def _index_file(self, file_path: Path) -> bool:
        """
        Index a single file (without timing instrumentation).

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
                size=len(content),
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
                vectors = self.embeddings.embed_batch(result.symbols)

                # Store in LanceDB (using relative path)
                self.vector_store.update_file_symbols(relative_path, result.symbols, vectors)

            return True

        except Exception as e:
            # Log error but continue with other files
            logger.warning(f"Failed to index {file_path}: {e}")
            return False

    def _get_database_mtime(self) -> float:
        """
        Get modification time of symbols.db file.

        Returns:
            Timestamp of database file, or 0 if doesn't exist (or in-memory)

        Note: Following Julie's staleness check pattern for performance
        """
        # Handle in-memory databases (used in tests)
        if self.storage.db_path == ":memory:":
            # For in-memory DB, use current time (always considered fresh)
            # This prevents false positives in staleness check during testing
            import time

            return time.time()

        db_path = Path(self.storage.db_path)
        if not db_path.exists():
            return 0  # DB doesn't exist, very old

        try:
            return db_path.stat().st_mtime
        except Exception:
            return 0

    def _get_max_file_mtime(self, disk_files: list[Path]) -> float:
        """
        Get the newest file modification time in workspace.

        Args:
            disk_files: List of file paths to check

        Returns:
            Maximum mtime found, or 0 if no files

        Note: Following Julie's staleness check pattern for performance
        """
        max_mtime = 0.0
        for file_path in disk_files:
            try:
                mtime = file_path.stat().st_mtime
                if mtime > max_mtime:
                    max_mtime = mtime
            except Exception:
                continue  # Skip files we can't stat
        return max_mtime

    async def check_if_indexing_needed(self) -> bool:
        """
        Check if workspace needs indexing (O(1) fast check).

        Julie's ACTUAL pattern (not what we thought):
        1. Check if DB is empty (O(1)) → needs indexing
        2. Otherwise assume file watcher keeps it current → skip expensive walk

        The expensive directory walk (O(n)) only happens during actual indexing,
        not during the startup check. This makes startup instant.

        For explicit re-indexing: use manage_workspace(operation="index", force=True)

        Returns:
            True if indexing needed (DB empty only), False otherwise
        """
        # ONLY check if DB is empty - this is O(1) and fast
        db_files = self.storage.get_all_files()

        if not db_files:
            logger.info("📊 Database is empty - initial indexing needed")
            return True

        # DB has files - assume index is current
        # File watcher will handle incremental updates after startup
        logger.info("✅ Index exists - assuming current (file watcher will track changes)")
        return False

    async def index_workspace(self) -> dict[str, int]:
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
        import asyncio
        import time

        start_time = time.time()

        stats = IndexStats()

        # Track cumulative timings
        total_extraction_time = 0.0
        total_embedding_time = 0.0
        total_db_time = 0.0
        total_vector_time = 0.0  # LanceDB vector store writes

        # Phase 1: File discovery
        discovery_start = time.time()
        disk_files = self._walk_directory()
        db_files = self.storage.get_all_files()
        discovery_time = time.time() - discovery_start

        logger.info(f"📁 File discovery: {len(disk_files)} files found in {discovery_time:.2f}s")

        # Build lookup for DB files (uses relative paths)
        db_files_map = {f["path"]: f for f in db_files}
        # Convert disk files to relative Unix-style paths to match DB
        disk_files_set = {
            str(f.relative_to(self.workspace_root)).replace("\\", "/") for f in disk_files
        }

        # Phase 2: Index new/changed files
        files_to_process = []
        for file_path in disk_files:
            # Convert to relative path for DB lookup
            relative_path = str(file_path.relative_to(self.workspace_root)).replace("\\", "/")

            if relative_path in db_files_map:
                # File exists in DB, check if changed
                if self._needs_indexing(file_path, db_files_map):
                    files_to_process.append((file_path, "updated"))
                else:
                    # File unchanged, skip
                    stats.skipped += 1
            else:
                # New file, index
                files_to_process.append((file_path, "indexed"))

        if files_to_process:
            logger.info(
                f"🔄 Processing {len(files_to_process)} files (new/changed), skipping {stats.skipped} unchanged"
            )

        # Process files in batches for optimal GPU utilization
        BATCH_SIZE = 50  # Process 50 files at a time for better GPU batching

        for batch_idx in range(0, len(files_to_process), BATCH_SIZE):
            batch = files_to_process[batch_idx : batch_idx + BATCH_SIZE]

            # Phase 2a: Prepare batch for parallel extraction
            extraction_batch = []
            action_map = {}  # Map relative_path -> action for O(1) lookup

            for file_path, action in batch:
                try:
                    relative_path = str(file_path.relative_to(self.workspace_root)).replace("\\", "/")
                    content = file_path.read_text(encoding="utf-8")
                    language = miller_core.detect_language(str(file_path))

                    if language:
                        extraction_batch.append((content, language, relative_path))
                        action_map[relative_path] = action  # Store action for later lookup
                    else:
                        # Should not happen due to discovery filter, but safe fallback
                        stats.skipped += 1
                except Exception as e:
                    logger.warning(f"Failed to read {file_path}: {e}")
                    stats.errors += 1

            if not extraction_batch:
                continue

            # Phase 2b: Parallel extraction in Rust (releases GIL)
            # This runs on multiple threads in Rust, not blocking Python
            extraction_start = time.time()
            try:
                # Run in thread pool to avoid blocking event loop during FFI call
                # Pass workspace_root for proper symbol path resolution
                results = await asyncio.to_thread(
                    miller_core.extract_files_batch,
                    extraction_batch,
                    str(self.workspace_root)
                )
            except Exception as e:
                logger.error(f"Batch extraction failed: {e}")
                stats.errors += len(extraction_batch)
                continue

            total_extraction_time += time.time() - extraction_start

            # Phase 2c: Process results
            batch_data = []
            for i, result in enumerate(results):
                content, language, relative_path = extraction_batch[i]
                file_path = self.workspace_root / relative_path

                # O(1) action lookup using pre-built map
                action = action_map.get(relative_path, "indexed")

                file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                batch_data.append(
                    (file_path, action, result, relative_path, content, language, file_hash)
                )

            # Phase 2d: Batch embed ALL symbols from this batch of files at once
            all_symbols = []
            symbol_file_map = []  # Track which file each symbol belongs to
            for _, _, result, relative_path, _, _, _ in batch_data:
                if result.symbols:
                    for sym in result.symbols:
                        all_symbols.append(sym)
                        symbol_file_map.append(relative_path)

            # Single embedding call for entire batch of files
            all_vectors = None
            if all_symbols:
                embedding_start = time.time()
                all_vectors = self.embeddings.embed_batch(all_symbols)
                total_embedding_time += time.time() - embedding_start

            # Phase 2c: Write to SQLite database (per-file metadata)
            for (
                file_path,
                action,
                result,
                relative_path,
                content,
                language,
                file_hash,
            ) in batch_data:
                try:
                    db_start = time.time()

                    # Add file metadata
                    self.storage.add_file(
                        file_path=relative_path,
                        language=language,
                        content=content,
                        hash=file_hash,
                        size=len(content),
                    )

                    # Add symbols, identifiers, relationships
                    if result.symbols:
                        self.storage.add_symbols_batch(result.symbols)
                    if result.identifiers:
                        self.storage.add_identifiers_batch(result.identifiers)
                    if result.relationships:
                        self.storage.add_relationships_batch(result.relationships)

                    total_db_time += time.time() - db_start

                    # Update stats
                    if action == "updated":
                        stats.updated += 1
                    else:
                        stats.indexed += 1

                except Exception as e:
                    logger.warning(f"Failed to index {file_path}: {e}")
                    stats.errors += 1

            # Phase 2d: Single bulk write to LanceDB for entire batch (50 files at once!)
            # This is MUCH faster than 50 individual writes (was 73% of time, now <10%)
            if all_symbols and all_vectors is not None:
                vector_start = time.time()
                # Bulk add all symbols+vectors for this batch in one operation
                self.vector_store.add_symbols(all_symbols, all_vectors)
                total_vector_time += time.time() - vector_start

            # Log progress after each batch
            processed = min(batch_idx + BATCH_SIZE, len(files_to_process))
            logger.info(f"   📊 Progress: {processed}/{len(files_to_process)} files processed")

        # Rebuild FTS index once after all files processed
        # (Much faster than rebuilding 298 times - was O(N²), now O(N))
        if files_to_process:
            logger.info("🔨 Rebuilding FTS index (one-time operation)...")
            rebuild_start = time.time()
            self.vector_store.rebuild_fts_index()
            rebuild_time = time.time() - rebuild_start
            logger.info(f"✅ FTS index rebuilt in {rebuild_time:.2f}s")
            total_vector_time += rebuild_time

        # Phase 3: Clean up deleted files
        cleanup_start = time.time()
        for db_file_path in db_files_map:
            if db_file_path not in disk_files_set:
                # File deleted from disk, remove from DB
                self.storage.delete_file(db_file_path)
                stats.deleted += 1
        cleanup_time = time.time() - cleanup_start

        # Final timing summary
        total_time = time.time() - start_time

        logger.info("=" * 60)
        logger.info("📊 Indexing Performance Summary")
        logger.info("=" * 60)
        logger.info(f"⏱️  Total time: {total_time:.2f}s")
        logger.info(
            f"📁 File discovery: {discovery_time:.2f}s ({discovery_time / total_time * 100:.1f}%)"
        )
        if stats.indexed + stats.updated > 0:
            logger.info(
                f"🔍 Tree-sitter extraction: {total_extraction_time:.2f}s ({total_extraction_time / total_time * 100:.1f}%)"
            )
            logger.info(
                f"🧠 Embedding generation: {total_embedding_time:.2f}s ({total_embedding_time / total_time * 100:.1f}%)"
            )
            logger.info(
                f"💾 SQLite writes: {total_db_time:.2f}s ({total_db_time / total_time * 100:.1f}%)"
            )
            logger.info(
                f"🗂️  LanceDB writes: {total_vector_time:.2f}s ({total_vector_time / total_time * 100:.1f}%)"
            )
            logger.info(f"🗑️  Cleanup: {cleanup_time:.2f}s ({cleanup_time / total_time * 100:.1f}%)")
            logger.info(
                f"📈 Throughput: {(stats.indexed + stats.updated) / total_time:.1f} files/sec"
            )
        logger.info("=" * 60)

        return stats.to_dict()
