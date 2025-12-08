"""
Miller server lifecycle - startup, initialization, and shutdown.

Handles:
1. Background initialization of Miller components (storage, embeddings, scanner)
2. Workspace indexing with progress reporting
3. File watcher for real-time updates
4. Graceful shutdown

This module is intentionally separated from server.py to keep server.py under 500 lines
while maintaining the Julie-style fast-startup pattern: instant MCP handshake, then
background initialization and indexing.
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from miller import server_state
from miller.logging_config import setup_logging
from miller.watcher import FileEvent, MultiWorkspaceWatcher

logger = setup_logging()


async def _on_files_changed(events: list[tuple[FileEvent, Path, str | None]]):
    """
    Callback for file watcher - re-indexes changed files in real-time.

    Optimized for batch processing:
    - Deduplicates events by file path (keeps latest event per file)
    - Batches deletions for efficiency
    - Processes independent files concurrently
    - Updates Rust watcher's hash cache after successful indexing

    Args:
        events: List of (event_type, file_path, new_hash) tuples from watcher
                new_hash is the Blake3 hash of new content (None for deletions)
    """
    if not events:
        return

    # Phase 1: Deduplicate events by file path (keep latest event per file)
    # Store (event_type, new_hash) tuple for each path
    # DELETED events take priority - if a file is deleted, ignore earlier CREATED/MODIFIED
    file_events: dict[Path, tuple[FileEvent, str | None]] = {}
    for event_type, file_path, new_hash in events:
        if file_path in file_events:
            # If already seen and this is DELETED, override
            if event_type == FileEvent.DELETED:
                file_events[file_path] = (event_type, new_hash)
            # If previous was DELETED, keep it (don't resurrect deleted files)
            elif file_events[file_path][0] == FileEvent.DELETED:
                pass
            # Otherwise, keep the later event (MODIFIED over CREATED)
            else:
                file_events[file_path] = (event_type, new_hash)
        else:
            file_events[file_path] = (event_type, new_hash)

    # Phase 2: Separate deletions from indexing operations
    deleted_files: list[str] = []
    files_to_index: list[tuple[FileEvent, Path, str | None]] = []

    for file_path, (event_type, new_hash) in file_events.items():
        if event_type == FileEvent.DELETED:
            rel_path = str(file_path.relative_to(server_state.workspace_root)).replace("\\", "/")
            deleted_files.append(rel_path)
        else:
            files_to_index.append((event_type, file_path, new_hash))

    # Phase 3: Batch process deletions (efficient single operation)
    if deleted_files:
        try:
            for rel_path in deleted_files:
                server_state.storage.delete_file(rel_path)
                # Remove hash from Rust watcher's cache
                if server_state.file_watcher:
                    server_state.file_watcher.remove_hash(rel_path)
            server_state.vector_store.delete_files_batch(deleted_files)
            logger.info(f"🗑️  Deleted {len(deleted_files)} file(s) from index")
        except Exception as e:
            logger.error(f"❌ Error batch deleting files: {e}", exc_info=True)

    # Phase 4: Process indexing operations concurrently
    if files_to_index:
        async def index_one(
            event_type: FileEvent, file_path: Path, new_hash: str | None
        ) -> tuple[bool, FileEvent, Path, str | None]:
            """Index a single file and return result with hash."""
            try:
                success = await server_state.scanner._index_file(file_path)
                return (success, event_type, file_path, new_hash)
            except Exception as e:
                logger.error(f"❌ Error indexing {file_path}: {e}", exc_info=True)
                return (False, event_type, file_path, new_hash)

        # Index all files concurrently
        results = await asyncio.gather(
            *[index_one(et, fp, nh) for et, fp, nh in files_to_index]
        )

        # Log results, track success, and update watcher hash cache
        any_success = False
        for success, event_type, file_path, new_hash in results:
            rel_path = str(file_path.relative_to(server_state.workspace_root)).replace("\\", "/")
            if success:
                any_success = True
                action = "Indexed" if event_type == FileEvent.CREATED else "Updated"
                logger.info(f"✏️  {action}: {rel_path}")
                # Update Rust watcher's hash cache to prevent redundant re-indexing
                # on subsequent saves without content changes
                if new_hash and server_state.file_watcher:
                    server_state.file_watcher.update_hash(rel_path, new_hash)
            else:
                logger.warning(f"⚠️  Failed to index: {rel_path}")

        # Phase 5: Refresh reachability if files changed (relationships may have changed)
        if any_success or deleted_files:
            from miller.closure import is_reachability_stale, refresh_reachability

            if await asyncio.to_thread(is_reachability_stale, server_state.storage):
                logger.info("🔗 Refreshing reachability (relationships changed)...")
                count = await asyncio.to_thread(
                    refresh_reachability, server_state.storage, 10
                )
                logger.info(f"✅ Reachability refreshed: {count} entries")


async def _embedding_auto_unload_task():
    """
    Auto-unload embedding model after 5 minutes of inactivity to free GPU memory.

    Following Julie's proven pattern:
    - Check every 60 seconds
    - Unload after 300 seconds (5 minutes) of idle time
    - Lazy reload on next use (handled by EmbeddingManager._ensure_loaded())

    This frees 5GB of VRAM when the model isn't being used, while keeping
    it loaded during active coding sessions.
    """
    CHECK_INTERVAL_SECS = 60  # Check every minute
    IDLE_TIMEOUT_SECS = 300  # Unload after 5 minutes of inactivity

    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL_SECS)

            # Skip if embeddings not initialized yet
            if server_state.embeddings is None:
                continue

            # Check if model should be unloaded
            last_use_time = server_state.embeddings._last_use_time

            if last_use_time is None:
                # Never used yet, don't unload
                continue

            import time
            idle_duration = time.time() - last_use_time

            if idle_duration > IDLE_TIMEOUT_SECS:
                # Model has been idle for >5 minutes
                if server_state.embeddings.is_loaded_on_gpu():
                    # Unload to free GPU memory
                    server_state.embeddings.unload()
                    logger.info(
                        f"🧹 Embedding model auto-unloaded after {idle_duration:.0f}s of inactivity "
                        "(will reload on next use)"
                    )

        except Exception as e:
            # Log errors but keep the task running
            logger.error(f"❌ Error in embedding auto-unload task: {e}", exc_info=True)


async def _background_initialization_and_indexing():
    """
    Background task that initializes components, indexes workspace, and starts file watcher.

    Runs completely in background so MCP handshake completes immediately.
    """
    try:
        import time
        import threading

        init_start = time.time()
        init_phase = "starting"

        # Watchdog thread logs every 15s if initialization is still running
        # This helps diagnose hangs - if you see repeated watchdog messages,
        # something is stuck at the logged phase
        def watchdog():
            while init_phase != "complete":
                time.sleep(15)
                if init_phase != "complete":
                    elapsed = time.time() - init_start
                    logger.warning(f"⏳ Initialization still running after {elapsed:.0f}s (phase: {init_phase})")

        watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        watchdog_thread.start()

        logger.info("🔧 Initializing Miller components in background...")

        # ╔══════════════════════════════════════════════════════════════════════════════╗
        # ║  CRITICAL: IMPORTS MUST RUN IN THREAD POOL - NOT IN EVENT LOOP!              ║
        # ║                                                                               ║
        # ║  Python imports are SYNCHRONOUS and BLOCK THE EVENT LOOP even inside async   ║
        # ║  functions! This causes the MCP handshake to hang for 5-15 seconds.          ║
        # ║                                                                               ║
        # ║  The imports below load heavy ML libraries (torch, sentence-transformers)    ║
        # ║  which take ~5s. If we import them directly, the event loop blocks and       ║
        # ║  Claude Code can't complete the MCP handshake until imports finish.          ║
        # ║                                                                               ║
        # ║  SOLUTION: Run imports in asyncio.to_thread() so they execute in the         ║
        # ║  thread pool, allowing the event loop to continue processing MCP messages.   ║
        # ║                                                                               ║
        # ║  DO NOT REMOVE THIS! This fix has been reverted multiple times causing       ║
        # ║  15-second startup delays. The "lazy import" pattern is NOT enough -         ║
        # ║  imports block even inside async functions!                                   ║
        # ║                                                                               ║
        # ║  UPDATE 2024-11: On Windows, asyncio.to_thread() deadlocks when running as   ║
        # ║  a subprocess with stdin/stdout pipes (how MCP servers run). The thread      ║
        # ║  pool executor interacts badly with Windows pipe I/O. As a workaround, we    ║
        # ║  run imports synchronously - this blocks the event loop for ~6s but works.   ║
        # ║  The MCP handshake still completes immediately because this runs in a        ║
        # ║  background task spawned AFTER the lifespan yields.                          ║
        # ╚══════════════════════════════════════════════════════════════════════════════╝
        init_phase = "imports"
        t0 = time.time()

        def _sync_heavy_imports():
            """Import heavy ML libraries (torch, sentence-transformers ~6s on first load)."""
            from miller.storage import StorageManager
            from miller.workspace import WorkspaceScanner
            from miller.workspace_registry import WorkspaceRegistry
            from miller.workspace_paths import (
                get_workspace_db_path,
                get_workspace_vector_path,
                ensure_miller_directories,
            )
            from miller.embeddings import EmbeddingManager, VectorStore
            return (
                StorageManager,
                WorkspaceScanner,
                WorkspaceRegistry,
                get_workspace_db_path,
                get_workspace_vector_path,
                ensure_miller_directories,
                EmbeddingManager,
                VectorStore,
            )

        if sys.platform == "win32":
            # Windows: asyncio.to_thread deadlocks with MCP's pipe-based stdin/stdout.
            # The thread pool executor interacts badly with Windows pipe I/O.
            # Run synchronously - blocks event loop ~6s but avoids deadlock.
            # This is okay because MCP handshake completed before this task started.
            (
                StorageManager,
                WorkspaceScanner,
                WorkspaceRegistry,
                get_workspace_db_path,
                get_workspace_vector_path,
                ensure_miller_directories,
                EmbeddingManager,
                VectorStore,
            ) = _sync_heavy_imports()
        else:
            # Unix/macOS: Run in thread pool to keep event loop responsive
            (
                StorageManager,
                WorkspaceScanner,
                WorkspaceRegistry,
                get_workspace_db_path,
                get_workspace_vector_path,
                ensure_miller_directories,
                EmbeddingManager,
                VectorStore,
            ) = await asyncio.to_thread(_sync_heavy_imports)

        logger.info(f"✅ Imports complete ({time.time()-t0:.1f}s)")

        init_phase = "workspace_setup"
        # Check for env var override (from MADS CLI)
        env_workspace = os.environ.get("MILLER_WORKSPACE")
        if env_workspace:
            server_state.workspace_root = Path(env_workspace).resolve()
        else:
            server_state.workspace_root = Path.cwd()
            
        logger.info(f"📁 Workspace root: {server_state.workspace_root}")

        # Register primary workspace first to get workspace_id
        registry = WorkspaceRegistry()
        workspace_id = registry.add_workspace(
            path=str(server_state.workspace_root),
            name=server_state.workspace_root.name,
            workspace_type="primary",
        )
        logger.info(f"📋 Workspace ID: {workspace_id}")
        server_state.primary_workspace_id = workspace_id

        # Ensure .miller directory exists (unified database goes here)
        ensure_miller_directories()

        # Use unified paths for database and vectors (single DB for all workspaces)
        db_path = get_workspace_db_path(workspace_id)
        vector_path = get_workspace_vector_path(workspace_id)

        # Initialize embedding model (uses Jina-0.5B by default, or MILLER_EMBEDDING_MODEL env var)
        server_state.embeddings = EmbeddingManager(device="auto")
        server_state.storage = StorageManager(db_path=str(db_path))

        # Initialize vector store with expected dimension from embedding model
        # Pass storage so VectorStore can clear SQLite files table on reset
        # (prevents "migration death spiral" bug - see _invalidate_sqlite_cache)
        server_state.vector_store = VectorStore(
            db_path=str(vector_path),
            embeddings=server_state.embeddings,
            expected_dim=server_state.embeddings.dimensions,
            storage=server_state.storage,
        )

        # ╔══════════════════════════════════════════════════════════════════════════════╗
        # ║  SIGNAL CORE COMPONENTS READY                                                 ║
        # ║                                                                               ║
        # ║  At this point: storage, embeddings, and vector_store are initialized.        ║
        # ║  Tools can now work (even while indexing runs in background).                 ║
        # ║                                                                               ║
        # ║  This is CRITICAL for the Windows pipe deadlock workaround:                   ║
        # ║  - On Windows, imports run synchronously (5-15s)                              ║
        # ║  - Tools await this event instead of returning error strings                  ║
        # ║  - Once set, tools proceed normally                                           ║
        # ╚══════════════════════════════════════════════════════════════════════════════╝
        init_event = server_state.get_initialization_event()
        init_event.set()
        logger.info("✅ Core components ready - tools can now accept requests")

        server_state.scanner = WorkspaceScanner(
            workspace_root=server_state.workspace_root,
            storage=server_state.storage,
            embeddings=server_state.embeddings,
            vector_store=server_state.vector_store,
            workspace_id=workspace_id,
        )
        logger.info("✅ Miller components initialized and ready")

        # PHASE 2: Check if indexing needed and run if stale (uses hashes + mtime)
        # Wrap in global indexing lock to prevent conflicts with file watcher callbacks
        # that may trigger during startup. This implements the "Single-Lane Bridge" pattern
        # ensuring GPU and LanceDB get exclusive access.
        init_phase = "indexing"
        indexing_lock = server_state.get_indexing_lock()

        async with indexing_lock:
            logger.info("🔍 Checking if workspace indexing needed...")
            if await server_state.scanner.check_if_indexing_needed():
                logger.info("📚 Workspace needs indexing - starting background indexing")
                stats = await server_state.scanner.index_workspace()
                logger.info(
                    f"✅ Indexing complete: {stats['indexed']} indexed, "
                    f"{stats['updated']} updated, {stats['skipped']} skipped, "
                    f"{stats['deleted']} deleted, {stats['errors']} errors"
                )

                # Run DB maintenance after heavy writes
                # - PRAGMA optimize: Updates query planner statistics
                # - wal_checkpoint(TRUNCATE): Clears WAL file for clean state
                logger.info("🔧 Running DB optimization after indexing...")
                server_state.storage.optimize()
                logger.info("✅ DB optimized (query stats updated, WAL checkpointed)")

                # Compute transitive closure for fast impact analysis
                # Run in thread pool to avoid blocking the event loop (O(V·E) BFS)
                from miller.closure import compute_transitive_closure

                logger.info("🔗 Computing transitive closure for impact analysis...")
                closure_start = time.time()
                closure_count = await asyncio.to_thread(
                    compute_transitive_closure, server_state.storage, max_depth=10
                )
                closure_time = (time.time() - closure_start) * 1000
                logger.info(f"✅ Transitive closure: {closure_count} reachability entries ({closure_time:.0f}ms)")
            else:
                logger.info("✅ Workspace already indexed - ready for search")

                # Check if reachability needs to be computed (may be empty from older versions)
                from miller.closure import should_compute_closure, compute_transitive_closure

                if await asyncio.to_thread(should_compute_closure, server_state.storage):
                    logger.info("🔗 Reachability table empty - computing transitive closure...")
                    closure_start = time.time()
                    closure_count = await asyncio.to_thread(
                        compute_transitive_closure, server_state.storage, max_depth=10
                    )
                    closure_time = (time.time() - closure_start) * 1000
                    logger.info(f"✅ Transitive closure: {closure_count} reachability entries ({closure_time:.0f}ms)")

        # Always update registry stats (ensures consistency after manual DB changes)
        cursor = server_state.storage.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM symbols")
        final_symbol_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT file_path) FROM symbols")
        final_file_count = cursor.fetchone()[0]
        registry.update_workspace_stats(workspace_id, final_symbol_count, final_file_count)

        # PHASE 3: Start multi-workspace file watcher for real-time updates
        init_phase = "file_watcher"
        logger.info("👁️  Starting multi-workspace file watcher for real-time indexing...")
        from miller.ignore_patterns import load_all_ignores

        ignore_spec = load_all_ignores(server_state.workspace_root)
        pattern_strings = {p.pattern for p in ignore_spec.patterns}

        # Build initial hash map from existing indexed files
        # This allows the Rust watcher to detect if content actually changed
        # (prevents re-indexing when file is saved without changes)
        indexed_files = server_state.storage.get_all_files()
        initial_hashes = {f["path"]: f["hash"] for f in indexed_files if f.get("hash")}
        logger.info(f"📊 Loaded {len(initial_hashes)} file hashes for change detection")

        # Create multi-workspace watcher (manages watchers for all workspaces)
        server_state.file_watcher = MultiWorkspaceWatcher()

        # Store primary scanner in workspace_scanners map
        server_state.workspace_scanners[workspace_id] = server_state.scanner

        # Add primary workspace to the multi-workspace watcher
        await server_state.file_watcher.add_workspace(
            workspace_id=workspace_id,
            workspace_path=server_state.workspace_root,
            scanner=server_state.scanner,
            storage=server_state.storage,
            vector_store=server_state.vector_store,
            ignore_patterns=pattern_strings,
            initial_hashes=initial_hashes,
        )
        logger.info("✅ File watcher active - workspace changes will be indexed automatically")

        # PHASE 4: Start auto-unload task for GPU memory management (Julie-style)
        # This task monitors embedding usage and unloads the model after 5min of inactivity
        init_phase = "auto_unload"
        asyncio.create_task(_embedding_auto_unload_task())
        logger.info("🕐 Started embedding auto-unload task (checks every 60s, unloads after 5min idle)")

        init_phase = "complete"  # Stop watchdog thread

    except Exception as e:
        logger.error(f"❌ Background initialization/indexing failed: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(_app):
    """
    FastMCP lifespan handler - startup and shutdown hooks.

    ╔══════════════════════════════════════════════════════════════════════════════╗
    ║  CRITICAL: THIS FUNCTION MUST YIELD IMMEDIATELY!                             ║
    ║                                                                               ║
    ║  The MCP protocol requires the server to respond to handshake within ~100ms. ║
    ║  If we do ANY heavy work before yielding, Claude Code will timeout or show   ║
    ║  "connecting..." for 15+ seconds.                                            ║
    ║                                                                               ║
    ║  Pattern:                                                                     ║
    ║    1. Spawn background task (asyncio.create_task - non-blocking)             ║
    ║    2. IMMEDIATELY yield (server becomes ready for MCP handshake)             ║
    ║    3. Background task runs heavy init AFTER handshake completes              ║
    ║                                                                               ║
    ║  The background task must also avoid blocking the event loop - see the       ║
    ║  asyncio.to_thread() usage in _background_initialization_and_indexing().     ║
    ╚══════════════════════════════════════════════════════════════════════════════╝

    Startup:
      1. Server becomes ready instantly (MCP handshake completes in <100ms)
      2. Background task initializes components (non-blocking via thread pool)
      3. Background task checks if indexing needed and runs if stale
      4. File watcher starts for real-time updates

    Shutdown: Stop file watcher and cleanup
    """
    # ═══════════════════════════════════════════════════════════════════════════════
    # SPAWN BACKGROUND TASK - DO NOT ADD ANY CODE BEFORE yield!
    # The yield MUST happen within milliseconds of this function being called.
    # Any delay here = delay in MCP handshake = angry users waiting 15 seconds.
    # ═══════════════════════════════════════════════════════════════════════════════
    logger.info("🚀 Spawning background initialization task...")
    init_task = asyncio.create_task(_background_initialization_and_indexing())
    logger.info("✅ Server ready for MCP handshake (initialization running in background)")

    yield  # ← SERVER IS NOW READY! Client sees "Connected" immediately after this.

    # SHUTDOWN: Stop file watchers and wait for background task
    logger.info("🛑 Miller server shutting down...")

    if server_state.file_watcher:
        logger.info("⏹️  Stopping all file watchers...")
        server_state.file_watcher.stop_all()
        logger.info("✅ All file watchers stopped")

    if not init_task.done():
        logger.info("⏳ Waiting for background initialization to complete...")
        await init_task

    logger.info("👋 Miller server shutdown complete")
