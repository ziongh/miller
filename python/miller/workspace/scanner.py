"""
WorkspaceScanner for automatic workspace indexing.

Handles:
- File discovery (respecting .gitignore)
- Change detection (hash-based)
- Incremental indexing
- Cleanup of deleted files

Environment Variables:
- MILLER_USE_ARROW: Set to "1" or "true" to enable Arrow-based extraction (default: true).
                    This eliminates ~75M Python allocations for large codebases.
                    Set to "0" or "false" to use legacy PyO3 object path.
"""

import asyncio
import logging
import os
import time
from pathlib import Path

from ..embeddings import EmbeddingManager, VectorStore
from ..ignore_patterns import (
    load_all_ignores,
    analyze_vendor_patterns,
    generate_millerignore,
)
from ..storage import StorageManager
from ..utils.progress import ProgressTracker
from .. import server_state
from . import hash_tracking
from .index_stats import IndexStats
from . import discovery
from .indexer import compute_code_context
from .buffer import IndexingBuffer
from .arrow_buffer import ArrowIndexingBuffer

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
        workspace_id: str = "primary",
    ):
        """
        Initialize workspace scanner.

        Args:
            workspace_root: Path to workspace directory
            storage: SQLite storage manager
            embeddings: Embedding generator
            vector_store: LanceDB vector store
            workspace_id: Workspace identifier for this scanner
        """
        self.workspace_root = Path(workspace_root)
        self.storage = storage
        self.embeddings = embeddings
        self.vector_store = vector_store
        self.workspace_id = workspace_id

        # Load all ignore patterns (.gitignore + .millerignore)
        # Smart vendor detection happens on first index if no .millerignore exists
        self.ignore_spec = load_all_ignores(self.workspace_root)
        self._millerignore_checked = False  # Track if we've done vendor detection

        # Per-file locks to prevent concurrent indexing of the same file
        self._file_locks: dict[Path, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

    async def _flush_buffer(
        self,
        buffer: IndexingBuffer,
        stats: IndexStats,
        timings: dict,
    ) -> None:
        """
        Flush accumulated buffer to database and vector store.

        This is called when the buffer reaches its symbol threshold (typically 512),
        ensuring the GPU always gets optimally-sized batches.

        Args:
            buffer: IndexingBuffer with accumulated symbols
            stats: IndexStats to update
            timings: Dict to accumulate timing data
        """
        if buffer.is_empty():
            return

        logger.info(
            f"🌊 Flushing buffer: {len(buffer.symbols)} symbols, "
            f"{len(buffer.file_data_list)} files"
        )

        # Embedding (GPU) - run in thread pool to release event loop
        # This prevents file watcher callbacks from being blocked during batch indexing
        all_vectors = None
        if buffer.symbols:
            embedding_start = time.time()
            all_vectors = await asyncio.to_thread(
                self.embeddings.embed_batch, buffer.symbols
            )
            timings["embedding"] += time.time() - embedding_start

        # SQLite write (atomic)
        try:
            db_start = time.time()
            self.storage.incremental_update_atomic(
                files_to_clean=buffer.files_to_clean,
                file_data=buffer.file_data_list,
                symbols=buffer.symbols,
                identifiers=buffer.identifiers,
                relationships=buffer.relationships,
                code_context_map=buffer.code_context_map,
                workspace_id=self.workspace_id,
            )
            timings["db"] += time.time() - db_start
        except Exception as e:
            logger.error(f"❌ Buffer flush failed: {e}")
            stats.errors += len(buffer.file_data_list)
            buffer.clear()
            return

        # LanceDB write
        if buffer.symbols and all_vectors is not None:
            vector_start = time.time()
            if buffer.files_to_clean:
                self.vector_store.delete_files_batch(buffer.files_to_clean)
            self.vector_store.add_symbols(buffer.symbols, all_vectors, workspace_id=self.workspace_id)
            timings["vector"] += time.time() - vector_start

        # Clear buffer (Python list.clear() is sufficient - no gc.collect())
        # IMPORTANT: Do NOT call gc.collect() or torch.cuda.empty_cache() here!
        # These aggressive memory operations can trigger memory corruption bugs in
        # native code (LanceDB/Arrow, PyTorch CUDA) during heavy indexing.
        # Memory cleanup will happen at the end of index_workspace() instead.
        buffer.clear()

    async def _flush_buffer_arrow(
        self,
        buffer: ArrowIndexingBuffer,
        stats: IndexStats,
        timings: dict,
    ) -> None:
        """
        Flush Arrow buffer to database and vector store (zero-copy path).

        This is the Arrow-based version of _flush_buffer that eliminates
        ~75 million Python object allocations for large codebases by:
        1. Keeping data in Arrow columnar format from Rust extraction
        2. Passing Arrow tables directly to LanceDB (native Arrow support)
        3. Extracting columns for SQLite only at the final write step

        Args:
            buffer: ArrowIndexingBuffer with accumulated Arrow RecordBatches
            stats: IndexStats to update
            timings: Dict to accumulate timing data
        """
        if buffer.is_empty():
            return

        logger.info(
            f"🌊 Flushing Arrow buffer: {buffer.symbol_count} symbols, "
            f"{buffer.file_count} files"
        )

        # Get concatenated Arrow tables
        symbols_table = buffer.get_symbols_table()
        identifiers_table = buffer.get_identifiers_table()
        relationships_table = buffer.get_relationships_table()
        files_table = buffer.get_files_table()

        # Filter out "text" files from files_table to match scan_workspace behavior
        # Text files are discovered but not tracked for incremental indexing
        import pyarrow.compute as pc
        if files_table.num_rows > 0:
            language_col = files_table.column("language")
            mask = pc.not_equal(language_col, "text")
            files_table = files_table.filter(mask)

        # Pre-compute qualified paths for files_to_clean (used in both SQLite and LanceDB)
        qualified_files_to_clean = []
        if buffer.files_to_clean:
            from ..workspace_paths import make_qualified_path
            qualified_files_to_clean = [
                make_qualified_path(self.workspace_id, p) for p in buffer.files_to_clean
            ]

        # Embedding (GPU) - extract only the text fields needed
        # IMPORTANT: Run in thread pool to release event loop during GPU operations.
        # This prevents file watcher callbacks from being blocked, which could cause
        # the event loop to freeze if many events queue up during batch indexing.
        all_vectors = None
        if symbols_table.num_rows > 0:
            embedding_start = time.time()
            # Get embedding texts from Arrow buffer (minimal Python strings)
            # This is the ONLY place we create Python strings in the Arrow path
            embedding_texts = buffer.get_embedding_texts()
            # Run embedding in thread pool to free event loop for other tasks
            all_vectors = await asyncio.to_thread(
                self.embeddings.embed_texts, embedding_texts
            )
            timings["embedding"] += time.time() - embedding_start

        # SQLite writes (files, symbols, identifiers, relationships)
        try:
            db_start = time.time()

            # Temporarily disable FK constraints for batch insert
            # Arrow data is internally consistent from Rust extraction, but
            # identifiers/relationships may reference symbols from other files
            # that aren't in this batch (cross-file references are common)
            self.storage.conn.execute("PRAGMA foreign_keys = OFF")
            try:
                # Delete old data for files being updated
                if qualified_files_to_clean:
                    self.storage.delete_files_batch(qualified_files_to_clean)

                # Insert new data from Arrow tables
                self.storage.add_files_from_arrow(files_table, workspace_id=self.workspace_id)
                self.storage.add_symbols_from_arrow(symbols_table, workspace_id=self.workspace_id)
                self.storage.add_identifiers_from_arrow(identifiers_table, workspace_id=self.workspace_id)
                self.storage.add_relationships_from_arrow(relationships_table, workspace_id=self.workspace_id)
            finally:
                # Re-enable FK constraints
                self.storage.conn.execute("PRAGMA foreign_keys = ON")

            timings["db"] += time.time() - db_start
        except Exception as e:
            logger.error(f"❌ Arrow buffer flush failed: {e}")
            stats.errors += buffer.file_count
            buffer.clear()
            return

        # LanceDB write (directly from Arrow table)
        if symbols_table.num_rows > 0 and all_vectors is not None:
            vector_start = time.time()
            if qualified_files_to_clean:
                self.vector_store.delete_files_batch(qualified_files_to_clean)
            self.vector_store.add_symbols_arrow(
                symbols_table, all_vectors, workspace_id=self.workspace_id
            )
            timings["vector"] += time.time() - vector_start

        # Update stats
        stats.total_symbols += symbols_table.num_rows

        # Clear buffer - Arrow tables are dropped, freeing contiguous memory blocks
        buffer.clear()

        # SAFE to gc.collect() here in Arrow path!
        # Unlike the legacy PyO3 path, Arrow memory is managed by Arrow's allocator,
        # not Python's gc. After buffer.clear():
        # 1. Arrow RecordBatches are dropped → memory returned to Arrow pool → OS
        # 2. SQLite writes are committed → no pending native operations
        # 3. LanceDB writes are committed → no pending native operations
        # 4. Only Python intermediates remain (lists from .to_pylist())
        #
        # This reclaims memory from:
        # - Temporary lists created during column extraction
        # - Any Python string intermediates from embedding text generation
        # - PyArrow Table wrapper objects (lightweight, but still gc-tracked)
        import gc
        gc.collect()

        # On Linux/glibc, explicitly return freed memory to OS
        # glibc's malloc keeps freed memory in process heap by default (lazy return)
        # malloc_trim(0) forces return of free memory at top of heap to OS
        # This turns the memory graph from "staircase" to "sawtooth"
        try:
            import ctypes
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except (OSError, AttributeError):
            pass  # Not on Linux/glibc, skip

    async def _index_file(self, file_path: Path) -> bool:
        """
        Index a single file (for real-time re-indexing via file watcher).

        Delegates to indexer.index_file which properly handles:
        - Symbol extraction via tree-sitter
        - SQLite storage (file, symbols, identifiers, relationships)
        - Vector store updates (deletes old embeddings, adds new ones)

        Includes global indexing lock to prevent conflicts with batch indexing,
        plus per-file locking to prevent concurrent indexing of the same file.

        The "Single-Lane Bridge" Pattern:
        PyTorch (GPU) and LanceDB (Native) resources are not safe for concurrent
        access. We serialize all indexing operations (batch and single-file) using
        the global indexing lock.

        Args:
            file_path: Absolute path to file to index

        Returns:
            True if successful, False if error or file doesn't exist
        """
        from .indexer import index_file
        from .. import server_state

        # Acquire global indexing lock to prevent conflict with batch indexing
        # This ensures GPU and LanceDB get exclusive access (no concurrent writes)
        indexing_lock = server_state.get_indexing_lock()

        if indexing_lock.locked():
            logger.debug(f"⏳ _index_file waiting for global indexing lock: {file_path.name}")

        async with indexing_lock:
            # Acquire per-file lock to prevent concurrent indexing of SAME file
            # (e.g. from rapid file watcher events for the same file)
            async with self._locks_lock:
                if file_path not in self._file_locks:
                    self._file_locks[file_path] = asyncio.Lock()
                lock = self._file_locks[file_path]

            async with lock:
                try:
                    return await index_file(
                        file_path=file_path,
                        workspace_root=self.workspace_root,
                        storage=self.storage,
                        embeddings=self.embeddings,
                        vector_store=self.vector_store,
                        workspace_id=self.workspace_id,
                    )
                finally:
                    # Cleanup lock if no longer used?
                    # Hard to know if others are waiting without race condition.
                    # For now, we keep the lock object.
                    # With normal workspace sizes (<50k files), this memory usage is negligible.
                    pass

    def _walk_directory(self) -> list[Path]:
        """
        Walk workspace directory and find indexable files.

        OPTIMIZED: Uses single-pass scan_workspace() internally.

        On first run (no .millerignore exists), performs smart vendor detection
        to auto-generate exclusion patterns for vendor/third-party directories.

        Returns:
            List of file paths to index (filtered by .gitignore, .millerignore, and language support)
        """
        if miller_core is None:
            return []  # Can't detect languages without Rust core

        # Use optimized single-pass scan
        scan_result = discovery.scan_workspace(
            self.workspace_root,
            self.ignore_spec,
            perform_vendor_detection=not self._millerignore_checked,
        )

        indexable_files = scan_result.indexable_files

        # Smart vendor detection on first run
        if scan_result.vendor_detection_needed and not self._millerignore_checked:
            self._millerignore_checked = True
            if not (self.workspace_root / ".millerignore").exists():
                detected_patterns = analyze_vendor_patterns(indexable_files, self.workspace_root)
                if detected_patterns:
                    generate_millerignore(self.workspace_root, detected_patterns)
                    logger.info(f"✅ Generated .millerignore with {len(detected_patterns)} patterns")
                    # Reload and re-filter files
                    self.ignore_spec = load_all_ignores(self.workspace_root)
                    indexable_files = [
                        f for f in indexable_files
                        if not self.ignore_spec.match_file(str(f.relative_to(self.workspace_root)))
                    ]
                    logger.info(f"📊 After vendor filtering: {len(indexable_files)} files to index")
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

        OPTIMIZED: Uses single-pass scan_workspace() instead of multiple rglob() walks.
        Previous implementation did 3 separate filesystem walks; now does 1.

        Performs these checks (in order of cost):
        1. DB empty? (O(1)) → needs full indexing
        2. DB corrupted? (O(1)) → needs re-indexing
        3. Single filesystem scan (O(n)) → collects all file info in one pass
        4. Compare scan results vs DB → detect stale, new, or deleted files

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

        # Build lookup structures from DB
        # Note: DB paths are workspace-qualified ("primary:src/main.py")
        # We need to compare against disk paths which are relative ("src/main.py")
        from ..workspace_paths import parse_qualified_path

        db_paths = set()
        db_files_map = {}
        for f in db_files:
            # Extract relative path from qualified path
            _, rel_path = parse_qualified_path(f["path"])
            db_paths.add(rel_path)
            db_files_map[rel_path] = f

        # SINGLE filesystem scan - replaces 3 separate rglob() walks!
        scan_result = discovery.scan_workspace(
            self.workspace_root,
            self.ignore_spec,
            perform_vendor_detection=False,  # Don't do vendor detection during check
        )

        # Check 3: Staleness - compare each indexed file's mtime to its last_indexed
        # We already have mtime from scan, so we just need to compare with DB's last_indexed
        for rel_path in scan_result.all_paths:
            if rel_path in db_files_map:
                db_file = db_files_map[rel_path]
                file_path = self.workspace_root / rel_path

                try:
                    mtime = int(file_path.stat().st_mtime)
                    last_indexed = db_file.get("last_indexed", 0) or 0

                    if mtime > last_indexed:
                        logger.info(
                            f"📊 File modified since last index: {rel_path} - indexing needed"
                        )
                        logger.debug(f"   mtime={mtime}, last_indexed={last_indexed}")
                        return True
                except OSError:
                    continue  # Can't stat file, skip

        # Check 4: New files not in database (set difference is O(1) per element)
        new_files = scan_result.all_paths - db_paths
        if new_files:
            logger.info(f"📊 Found {len(new_files)} new files not in database - indexing needed")
            logger.debug(f"   New files: {list(new_files)[:5]}")
            return True

        # Check 5: Deleted files still in database
        deleted_files = db_paths - scan_result.all_paths
        if deleted_files:
            logger.info(f"📊 Found {len(deleted_files)} deleted files still in database - indexing needed")
            logger.debug(f"   Deleted files: {list(deleted_files)[:5]}")
            return True

        # Index is up-to-date
        logger.info("✅ Index is up-to-date - no indexing needed")
        return False

    def _has_new_files(self, db_paths: set[str]) -> bool:
        """
        Check if there are any new files on disk not in the database.

        Args:
            db_paths: Set of file paths currently in the database

        Returns:
            True if new files found, False otherwise
        """
        return discovery.has_new_files(self.workspace_root, self.ignore_spec, db_paths)

    async def index_workspace(self) -> dict[str, int]:
        """
        Index entire workspace with streaming buffer architecture.

        "Bucket Brigade" pattern:
        1. Scan for files on disk
        2. Process files in small groups (Rust parallelism)
        3. Accumulate results in buffer
        4. Flush when symbol threshold reached (GPU optimization)
        5. Clean up deleted files from DB
        6. Return statistics

        Returns:
            Dict with indexing statistics
        """
        start_time = time.time()

        stats = IndexStats()

        # Track cumulative timings
        timings = {
            "extraction": 0.0,
            "embedding": 0.0,
            "db": 0.0,
            "vector": 0.0,
        }

        # Phase 1: File discovery
        discovery_start = time.time()
        disk_files = self._walk_directory()
        db_files = self.storage.get_all_files()
        discovery_time = time.time() - discovery_start

        logger.info(f"📁 File discovery: {len(disk_files)} files found in {discovery_time:.2f}s")

        # Build lookup for DB files
        # Note: DB paths are workspace-qualified ("primary:src/main.py")
        # We need to compare against disk paths which are relative ("src/main.py")
        from ..workspace_paths import parse_qualified_path

        db_files_map = {}
        for f in db_files:
            _, rel_path = parse_qualified_path(f["path"])
            db_files_map[rel_path] = f

        disk_files_set = {
            str(f.relative_to(self.workspace_root)).replace("\\", "/") for f in disk_files
        }

        # Phase 2: Identify files to process
        files_to_process = []
        for file_path in disk_files:
            relative_path = str(file_path.relative_to(self.workspace_root)).replace("\\", "/")

            if relative_path in db_files_map:
                if self._needs_indexing(file_path, db_files_map):
                    files_to_process.append((file_path, "updated"))
                else:
                    stats.skipped += 1
            else:
                files_to_process.append((file_path, "indexed"))

        if files_to_process:
            logger.info(
                f"🔄 Processing {len(files_to_process)} files (new/changed), "
                f"skipping {stats.skipped} unchanged"
            )

        # Initialize progress tracker
        # Visual mode (tqdm-style bar) in HTTP mode, log-based in STDIO mode
        progress = ProgressTracker(
            total=len(files_to_process),
            desc="Indexing",
            console_mode=server_state.console_mode,
        )

        # Check if Arrow extraction is enabled (default: True for better memory)
        use_arrow = os.getenv("MILLER_USE_ARROW", "1").lower() not in ("0", "false", "no", "off")

        # Extraction chunk size - small groups for Rust parallelism
        chunk_size = 20

        if use_arrow:
            # ARROW PATH: Zero-copy extraction eliminates ~75M Python allocations
            buffer = ArrowIndexingBuffer(
                max_symbols=512,
                max_files=200,
            )
            logger.info(
                f"📦 Arrow streaming config: symbol_threshold={buffer.max_symbols}, "
                f"chunk_size={chunk_size} (device: {self.embeddings.device_type}) 🚀 ZERO-COPY"
            )
        else:
            # LEGACY PATH: PyO3 object-based extraction (for debugging/fallback)
            buffer = IndexingBuffer(
                max_symbols=512,  # Accumulate more symbols before flushing (was: batch_size=16)
                max_files=200,    # Allow more files before forcing flush (was: 50)
            )
            logger.info(
                f"📦 Legacy streaming config: symbol_threshold={buffer.max_symbols}, "
                f"chunk_size={chunk_size} (device: {self.embeddings.device_type})"
            )

        # Bulk insert optimization: drop indexes for massive scans
        # Re-creating indexes once at the end is faster than maintaining them
        # during each insert (saves ~30-40% I/O for large workspaces)
        is_massive_scan = len(files_to_process) > 1000
        if is_massive_scan:
            logger.info(f"🚀 Massive scan ({len(files_to_process)} files) - dropping identifier indexes")
            self.storage.drop_identifier_indexes()

        total_files_processed = 0
        batches_completed = 0
        total_batches = (len(files_to_process) + chunk_size - 1) // chunk_size if files_to_process else 0

        try:
            for chunk_start in range(0, len(files_to_process), chunk_size):
                chunk = files_to_process[chunk_start:chunk_start + chunk_size]
                current_batch = chunk_start // chunk_size + 1

                # Prepare paths for Rust I/O
                paths_to_extract = []
                action_map = {}
                files_to_update = []  # Track files being updated (for cleanup)

                for file_path, action in chunk:
                    relative_path = str(file_path.relative_to(self.workspace_root)).replace("\\", "/")
                    paths_to_extract.append(relative_path)
                    action_map[relative_path] = (file_path, action)
                    if action == "updated":
                        files_to_update.append(relative_path)

                if not paths_to_extract:
                    continue

                extraction_start = time.time()

                if use_arrow:
                    # ═══════════════════════════════════════════════════════════════
                    # ARROW PATH: Zero-copy extraction
                    # Returns Arrow RecordBatches instead of Python objects
                    # ═══════════════════════════════════════════════════════════════
                    try:
                        arrow_batch = await asyncio.to_thread(
                            miller_core.extract_files_to_arrow,
                            paths_to_extract,
                            str(self.workspace_root)
                        )
                    except Exception as e:
                        logger.error(f"Arrow batch extraction failed: {e}")
                        stats.errors += len(paths_to_extract)
                        continue

                    timings["extraction"] += time.time() - extraction_start

                    # Track stats from Arrow batch
                    # Count non-text files for accurate stats (text files are filtered before DB storage)
                    files_batch = arrow_batch.files
                    non_text_count = 0
                    if files_batch.num_rows > 0:
                        import pyarrow.compute as pc
                        non_text_mask = pc.not_equal(files_batch.column("language"), "text")
                        non_text_count = pc.sum(non_text_mask).as_py()

                    # Distinguish between updated and newly indexed files
                    updated_count = min(len(files_to_update), non_text_count)
                    new_count = non_text_count - updated_count
                    stats.updated += updated_count
                    stats.indexed += max(0, new_count)
                    stats.errors += arrow_batch.files_failed
                    for err in arrow_batch.errors:
                        logger.warning(f"Extraction error: {err}")

                    # Add Arrow batch to buffer (just stores RecordBatch references)
                    buffer.add_arrow_batch(arrow_batch, files_to_update=files_to_update)

                    total_files_processed += arrow_batch.files_processed

                    # Check if buffer should flush
                    if buffer.should_flush():
                        await self._flush_buffer_arrow(buffer, stats, timings)

                else:
                    # ═══════════════════════════════════════════════════════════════
                    # LEGACY PATH: PyO3 object-based extraction
                    # Creates Python objects for each symbol (more memory pressure)
                    # ═══════════════════════════════════════════════════════════════
                    try:
                        batch_results = await asyncio.to_thread(
                            miller_core.extract_files_batch_with_io,
                            paths_to_extract,
                            str(self.workspace_root)
                        )
                    except Exception as e:
                        logger.error(f"Batch extraction failed: {e}")
                        stats.errors += len(paths_to_extract)
                        continue

                    timings["extraction"] += time.time() - extraction_start

                    # Process BatchFileResult objects
                    for res in batch_results:
                        # Check for read/extraction errors
                        if res.error or res.content is None:
                            logger.warning(f"Failed to process {res.path}: {res.error}")
                            stats.errors += 1
                            continue

                        # Skip text files (no symbol extraction)
                        if res.language == "text":
                            stats.skipped += 1
                            continue

                        file_path, action = action_map[res.path]

                        # Get extraction results ONCE (takes ownership via Rust's .take())
                        extraction_result = res.results

                        # Ensure path consistency for FK constraints
                        if extraction_result and extraction_result.symbols:
                            for sym in extraction_result.symbols:
                                sym.file_path = res.path
                            if extraction_result.identifiers:
                                for ident in extraction_result.identifiers:
                                    ident.file_path = res.path
                            if extraction_result.relationships:
                                for rel in extraction_result.relationships:
                                    rel.file_path = res.path

                        # Track stats
                        if action == "updated":
                            stats.updated += 1
                        else:
                            stats.indexed += 1

                        symbols_added = buffer.add_result(
                            file_path=file_path,
                            relative_path=res.path,
                            action=action,
                            result=extraction_result,
                            content=res.content,
                            language=res.language,
                            file_hash=res.hash,
                            code_context_fn=compute_code_context,
                        )
                        stats.total_symbols += symbols_added

                    total_files_processed += len(paths_to_extract)

                    # Check if buffer should flush
                    if buffer.should_flush():
                        await self._flush_buffer(buffer, stats, timings)

                # Update progress tracker (visual bar or log entry)
                progress.update(len(paths_to_extract))
                batches_completed += 1

            # Log successful loop completion (helps debug premature termination)
            logger.info(
                f"✅ Processing loop completed: {batches_completed}/{total_batches} batches, "
                f"{total_files_processed} files processed"
            )

            # Final flush for remaining data
            if not buffer.is_empty():
                if use_arrow:
                    await self._flush_buffer_arrow(buffer, stats, timings)
                else:
                    await self._flush_buffer(buffer, stats, timings)

            # Ensure progress shows 100% at completion
            progress.finish()

            # Rebuild FTS index once after all files processed
            if files_to_process:
                logger.info("🔨 Rebuilding FTS index (one-time operation)...")
                rebuild_start = time.time()
                self.vector_store.rebuild_fts_index()
                rebuild_time = time.time() - rebuild_start
                logger.info(f"✅ FTS index rebuilt in {rebuild_time:.2f}s")
                timings["vector"] += rebuild_time

        except Exception as e:
            # Log critical error with batch context for debugging premature termination
            logger.error(
                f"❌ Critical error during indexing at batch {batches_completed + 1}/{total_batches}: {e}",
                exc_info=True
            )
            raise
        finally:
            # Always restore indexes, even if indexing was interrupted
            if is_massive_scan:
                logger.info(
                    f"🔧 Restoring identifier indexes (completed {batches_completed}/{total_batches} batches)..."
                )
                self.storage.restore_identifier_indexes()
                logger.info("✅ Identifier indexes restored")

        # Phase 3: Clean up deleted files
        cleanup_start = time.time()
        deleted_files_relative = [p for p in db_files_map if p not in disk_files_set]

        if deleted_files_relative:
            # Convert relative paths back to qualified paths for deletion
            from ..workspace_paths import make_qualified_path
            deleted_files_qualified = [
                make_qualified_path(self.workspace_id, p) for p in deleted_files_relative
            ]
            self.storage.delete_files_batch(deleted_files_qualified)
            self.vector_store.delete_files_batch(deleted_files_qualified)
            stats.deleted = len(deleted_files_relative)
            logger.debug(f"🗑️ Cleaned up {len(deleted_files_relative)} deleted files")

        cleanup_time = time.time() - cleanup_start

        # Post-indexing maintenance (only if changes occurred)
        # Deletions are especially important to cleanup because LanceDB keeps deleted rows
        # on disk until cleanup_old_versions is called.
        maintenance_time = 0.0
        if stats.indexed + stats.updated + stats.deleted > 0:
            logger.info("🧹 Performing post-indexing maintenance...")
            maintenance_start = time.time()

            # 1. Optimize SQLite (Analyze + WAL Checkpoint)
            try:
                self.storage.optimize()
                if stats.deleted > 100:  # Aggressive checkpoint after heavy deletes
                    self.storage.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as e:
                logger.warning(f"SQLite maintenance warning: {e}")

            # 2. Update reference counts (for importance weighting in search)
            # Counts incoming relationships to each symbol for search ranking
            try:
                updated_count = self.storage.update_reference_counts()
                if updated_count > 0:
                    logger.debug(f"📊 Updated reference counts for {updated_count} symbols")
            except Exception as e:
                logger.warning(f"Reference count update warning: {e}")

            # 3. Optimize LanceDB (Compaction + GC)
            # This runs on the thread pool to avoid blocking the event loop
            try:
                await asyncio.to_thread(self.vector_store.optimize)
            except Exception as e:
                logger.warning(f"LanceDB optimization warning: {e}")

            maintenance_time = time.time() - maintenance_start

        # Safe GPU memory cleanup (only at end when all native operations are done)
        # This is safe now because:
        # 1. All embeddings have been computed and persisted
        # 2. All LanceDB writes are complete
        # 3. No more interaction with native code
        if self.embeddings.device_type == "cuda":
            import gc
            gc.collect()  # Let Python clean up any numpy arrays first
            import torch
            torch.cuda.empty_cache()
            logger.debug("🧹 GPU cache cleared after indexing completion")

        # Final timing summary
        total_time = time.time() - start_time

        logger.info("=" * 60)
        logger.info("📊 Indexing Performance Summary (Streaming Architecture)")
        logger.info("=" * 60)
        logger.info(f"⏱️  Total time: {total_time:.2f}s")
        logger.info(f"📁 File discovery: {discovery_time:.2f}s ({discovery_time / total_time * 100:.1f}%)")
        if stats.indexed + stats.updated > 0:
            logger.info(f"🔍 Extraction: {timings['extraction']:.2f}s ({timings['extraction'] / total_time * 100:.1f}%)")
            logger.info(f"🧠 Embedding: {timings['embedding']:.2f}s ({timings['embedding'] / total_time * 100:.1f}%)")
            logger.info(f"💾 SQLite: {timings['db']:.2f}s ({timings['db'] / total_time * 100:.1f}%)")
            logger.info(f"🗂️  LanceDB: {timings['vector']:.2f}s ({timings['vector'] / total_time * 100:.1f}%)")
            logger.info(f"🗑️  Cleanup: {cleanup_time:.2f}s ({cleanup_time / total_time * 100:.1f}%)")
            if maintenance_time > 0:
                logger.info(f"🔧 Maintenance: {maintenance_time:.2f}s ({maintenance_time / total_time * 100:.1f}%)")
            logger.info(f"📈 Throughput: {(stats.indexed + stats.updated) / total_time:.1f} files/sec")
        logger.info("=" * 60)

        return stats.to_dict()
