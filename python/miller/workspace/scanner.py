"""
WorkspaceScanner for automatic workspace indexing.

Handles:
- File discovery (respecting .gitignore)
- Change detection (hash-based)
- Incremental indexing
- Cleanup of deleted files
"""

import asyncio
import logging
import time
from pathlib import Path

from ..embeddings import EmbeddingManager, VectorStore
from ..ignore_patterns import (
    load_all_ignores,
    load_millerignore,
    analyze_vendor_patterns,
    generate_millerignore,
)
from ..storage import StorageManager
from . import hash_tracking
from .index_stats import IndexStats

# Get logger instance
logger = logging.getLogger("miller.workspace")

# Import Rust core
try:
    from .. import miller_core
except ImportError:
    # For testing without building Rust extension
    miller_core = None


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

        # Load all ignore patterns (.gitignore + .millerignore)
        # Smart vendor detection happens on first index if no .millerignore exists
        self.ignore_spec = load_all_ignores(self.workspace_root)
        self._millerignore_checked = False  # Track if we've done vendor detection

    async def _index_file(self, file_path: Path) -> bool:
        """
        Index a single file (for real-time re-indexing via file watcher).

        Delegates to indexer.index_file which properly handles:
        - Symbol extraction via tree-sitter
        - SQLite storage (file, symbols, identifiers, relationships)
        - Vector store updates (deletes old embeddings, adds new ones)

        Args:
            file_path: Absolute path to file to index

        Returns:
            True if successful, False if error or file doesn't exist
        """
        from .indexer import index_file

        return await index_file(
            file_path=file_path,
            workspace_root=self.workspace_root,
            storage=self.storage,
            embeddings=self.embeddings,
            vector_store=self.vector_store,
        )

    def _walk_directory(self) -> list[Path]:
        """
        Walk workspace directory and find indexable files.

        On first run (no .millerignore exists), performs smart vendor detection
        to auto-generate exclusion patterns for vendor/third-party directories.

        Returns:
            List of file paths to index (filtered by .gitignore, .millerignore, and language support)
        """
        if miller_core is None:
            return []  # Can't detect languages without Rust core

        # Check if we need to do smart vendor detection
        millerignore_path = self.workspace_root / ".millerignore"
        needs_vendor_detection = (
            not self._millerignore_checked
            and not millerignore_path.exists()
        )

        if needs_vendor_detection:
            logger.info("🤖 No .millerignore found - scanning for vendor patterns...")

        indexable_files = []
        all_files_for_analysis = []  # For vendor detection

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
                continue  # Ignored by .gitignore or .millerignore

            # Check if language is supported
            language = miller_core.detect_language(str(file_path))
            if language:
                indexable_files.append(file_path)
                if needs_vendor_detection:
                    all_files_for_analysis.append(file_path)

        # Smart vendor detection on first run
        if needs_vendor_detection:
            self._millerignore_checked = True
            detected_patterns = analyze_vendor_patterns(
                all_files_for_analysis, self.workspace_root
            )

            if detected_patterns:
                generate_millerignore(self.workspace_root, detected_patterns)
                logger.info(
                    f"✅ Generated .millerignore with {len(detected_patterns)} patterns"
                )

                # Reload ignore spec and re-filter files
                self.ignore_spec = load_all_ignores(self.workspace_root)
                indexable_files = [
                    f for f in indexable_files
                    if not self.ignore_spec.match_file(
                        str(f.relative_to(self.workspace_root))
                    )
                ]
                logger.info(
                    f"📊 After vendor filtering: {len(indexable_files)} files to index"
                )
            else:
                logger.info("✨ No vendor patterns detected - project looks clean!")

        return indexable_files

    def _needs_indexing(self, file_path: Path, db_files_map: dict[str, dict]) -> bool:
        """
        Check if file needs to be indexed.

        Args:
            file_path: Path to file (absolute)
            db_files_map: Dict mapping relative paths to file info (performance optimization)

        Returns:
            True if file should be indexed (new or changed), False if unchanged
        """
        return hash_tracking.needs_indexing(file_path, self.workspace_root, db_files_map)

    async def check_if_indexing_needed(self) -> bool:
        """
        Check if workspace needs indexing.

        Performs these checks (in order of cost):
        1. DB empty? (O(1)) → needs full indexing
        2. DB corrupted? (O(1)) → needs re-indexing
        3. DB stale? (O(n) but fast) → compare file mtimes to DB timestamp
        4. New files? (O(n)) → files on disk not in DB

        Returns:
            True if indexing needed, False if index is up-to-date
        """
        # Check 1: DB empty (O(1))
        db_files = self.storage.get_all_files()

        if not db_files:
            logger.info("📊 Database is empty - initial indexing needed")
            return True

        # Check 2: Corrupted state - files but no symbols (O(1))
        cursor = self.storage.conn.execute("SELECT COUNT(*) FROM symbols")
        symbol_count = cursor.fetchone()[0]

        if symbol_count == 0:
            logger.warning("⚠️ Database has files but 0 symbols - re-indexing needed")
            return True

        # Check 3: Staleness - compare file mtimes to last index time
        # Get max last_indexed timestamp from DB
        cursor = self.storage.conn.execute("SELECT MAX(last_indexed) FROM files")
        row = cursor.fetchone()
        db_timestamp = row[0] if row and row[0] else 0

        # Find max file mtime in workspace (fast scan)
        max_file_mtime = self._get_max_file_mtime()

        if max_file_mtime > db_timestamp:
            logger.info(
                f"📊 Database is stale (files modified after last index) - indexing needed"
            )
            logger.debug(f"   max_file_mtime={max_file_mtime}, db_timestamp={db_timestamp}")
            return True

        # Check 4: New files not in database
        db_paths = {f["path"] for f in db_files}
        new_files_found = self._has_new_files(db_paths)

        if new_files_found:
            logger.info("📊 Found new files not in database - indexing needed")
            return True

        # Index is up-to-date
        logger.info("✅ Index is up-to-date - no indexing needed")
        return False

    def _get_max_file_mtime(self) -> int:
        """
        Get the maximum (newest) file modification time in the workspace.

        Returns:
            Unix timestamp of the most recently modified file
        """
        max_mtime = 0

        # Quick scan of just supported code files
        for file_path in self.workspace_root.rglob("*"):
            if file_path.is_dir() or file_path.is_symlink():
                continue

            # Check if ignored
            try:
                relative_path = file_path.relative_to(self.workspace_root)
            except ValueError:
                continue

            if self.ignore_spec.match_file(str(relative_path)):
                continue

            # Check if language is supported (only check code files)
            if miller_core and miller_core.detect_language(str(file_path)):
                try:
                    mtime = int(file_path.stat().st_mtime)
                    if mtime > max_mtime:
                        max_mtime = mtime
                except OSError:
                    continue

        return max_mtime

    def _has_new_files(self, db_paths: set[str]) -> bool:
        """
        Check if there are any new files on disk not in the database.

        Args:
            db_paths: Set of file paths currently in the database

        Returns:
            True if new files found, False otherwise
        """
        for file_path in self.workspace_root.rglob("*"):
            if file_path.is_dir() or file_path.is_symlink():
                continue

            try:
                relative_path = file_path.relative_to(self.workspace_root)
            except ValueError:
                continue

            # Convert to Unix-style path for comparison
            rel_str = str(relative_path).replace("\\", "/")

            if self.ignore_spec.match_file(rel_str):
                continue

            # Check if supported language and not in DB
            if miller_core and miller_core.detect_language(str(file_path)):
                if rel_str not in db_paths:
                    logger.debug(f"   New file detected: {rel_str}")
                    return True

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

                # Use Rust blake3 for 3x faster hashing
                file_hash = miller_core.hash_content(content)
                batch_data.append(
                    (file_path, action, result, relative_path, content, language, file_hash)
                )

            # Phase 2d: Collect all data for atomic batch update
            all_symbols = []
            all_identifiers = []
            all_relationships = []
            files_to_clean = []  # Files being updated (need old data deleted)
            file_data_list = []  # (path, language, content, hash, size)

            for (
                file_path,
                action,
                result,
                relative_path,
                content,
                language,
                file_hash,
            ) in batch_data:
                # Track files being updated for cleanup
                if action == "updated":
                    files_to_clean.append(relative_path)
                    stats.updated += 1
                else:
                    stats.indexed += 1

                # Collect file data
                file_data_list.append((relative_path, language, content, file_hash, len(content)))

                # Collect symbols, identifiers, relationships
                if result.symbols:
                    all_symbols.extend(result.symbols)
                    stats.total_symbols += len(result.symbols)
                if result.identifiers:
                    all_identifiers.extend(result.identifiers)
                if result.relationships:
                    all_relationships.extend(result.relationships)

            # Single embedding call for entire batch of files
            all_vectors = None
            if all_symbols:
                embedding_start = time.time()
                all_vectors = self.embeddings.embed_batch(all_symbols)
                total_embedding_time += time.time() - embedding_start

            # Phase 2e: ATOMIC database write for entire batch
            # All-or-nothing: if any step fails, entire batch is rolled back
            try:
                db_start = time.time()
                self.storage.incremental_update_atomic(
                    files_to_clean=files_to_clean,
                    file_data=file_data_list,
                    symbols=all_symbols,
                    identifiers=all_identifiers,
                    relationships=all_relationships,
                )
                total_db_time += time.time() - db_start
            except Exception as e:
                logger.error(f"❌ Atomic batch update failed: {e}")
                stats.errors += len(batch_data)
                # Continue to next batch rather than failing completely
                continue

            # Phase 2f: Single bulk write to LanceDB for entire batch (50 files at once!)
            # This is MUCH faster than 50 individual writes (was 73% of time, now <10%)
            if all_symbols and all_vectors is not None:
                vector_start = time.time()
                # Delete old vectors for updated files BEFORE adding new ones
                # This prevents stale/duplicate vectors in the search index
                if files_to_clean:
                    self.vector_store.delete_files_batch(files_to_clean)
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
