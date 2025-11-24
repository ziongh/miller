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
from contextlib import asynccontextmanager
from pathlib import Path

from miller import server_state
from miller.logging_config import setup_logging
from miller.watcher import FileEvent, FileWatcher

logger = setup_logging()


async def _on_files_changed(events: list[tuple[FileEvent, Path]]):
    """
    Callback for file watcher - re-indexes changed files in real-time.

    Optimized for batch processing:
    - Deduplicates events by file path (keeps latest event per file)
    - Batches deletions for efficiency
    - Processes independent files concurrently

    Args:
        events: List of (event_type, file_path) tuples from watcher
    """
    if not events:
        return

    # Phase 1: Deduplicate events by file path (keep latest event per file)
    # DELETED events take priority - if a file is deleted, ignore earlier CREATED/MODIFIED
    file_events: dict[Path, FileEvent] = {}
    for event_type, file_path in events:
        if file_path in file_events:
            # If already seen and this is DELETED, override
            if event_type == FileEvent.DELETED:
                file_events[file_path] = event_type
            # If previous was DELETED, keep it (don't resurrect deleted files)
            elif file_events[file_path] == FileEvent.DELETED:
                pass
            # Otherwise, keep the later event (MODIFIED over CREATED)
            else:
                file_events[file_path] = event_type
        else:
            file_events[file_path] = event_type

    # Phase 2: Separate deletions from indexing operations
    deleted_files: list[str] = []
    files_to_index: list[tuple[FileEvent, Path]] = []

    for file_path, event_type in file_events.items():
        if event_type == FileEvent.DELETED:
            rel_path = str(file_path.relative_to(server_state.workspace_root)).replace("\\", "/")
            deleted_files.append(rel_path)
        else:
            files_to_index.append((event_type, file_path))

    # Phase 3: Batch process deletions (efficient single operation)
    if deleted_files:
        try:
            for rel_path in deleted_files:
                server_state.storage.delete_file(rel_path)
            server_state.vector_store.delete_files_batch(deleted_files)
            logger.info(f"🗑️  Deleted {len(deleted_files)} file(s) from index")
        except Exception as e:
            logger.error(f"❌ Error batch deleting files: {e}", exc_info=True)

    # Phase 4: Process indexing operations concurrently
    if files_to_index:
        async def index_one(event_type: FileEvent, file_path: Path) -> tuple[bool, FileEvent, Path]:
            """Index a single file and return result."""
            try:
                success = await server_state.scanner._index_file(file_path)
                return (success, event_type, file_path)
            except Exception as e:
                logger.error(f"❌ Error indexing {file_path}: {e}", exc_info=True)
                return (False, event_type, file_path)

        # Index all files concurrently
        results = await asyncio.gather(*[index_one(et, fp) for et, fp in files_to_index])

        # Log results
        for success, event_type, file_path in results:
            rel_path = str(file_path.relative_to(server_state.workspace_root)).replace("\\", "/")
            if success:
                action = "Indexed" if event_type == FileEvent.CREATED else "Updated"
                logger.info(f"✏️  {action}: {rel_path}")
            else:
                logger.warning(f"⚠️  Failed to index: {rel_path}")


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

        # Lazy imports - only load heavy ML libraries in background task
        # WorkspaceScanner transitively imports embeddings (torch, sentence-transformers)
        # which takes ~6s on first load. This is expected and doesn't block MCP handshake.
        init_phase = "imports"
        t0 = time.time()
        from miller.storage import StorageManager
        from miller.workspace import WorkspaceScanner
        from miller.workspace_registry import WorkspaceRegistry
        from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path
        from miller.embeddings import EmbeddingManager, VectorStore
        logger.info(f"✅ Imports complete ({time.time()-t0:.1f}s)")

        init_phase = "workspace_setup"
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

        # Use workspace-specific paths for database and vectors
        db_path = get_workspace_db_path(workspace_id)
        vector_path = get_workspace_vector_path(workspace_id)

        server_state.embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="auto")
        server_state.storage = StorageManager(db_path=str(db_path))
        server_state.vector_store = VectorStore(
            db_path=str(vector_path), embeddings=server_state.embeddings
        )

        server_state.scanner = WorkspaceScanner(
            workspace_root=server_state.workspace_root,
            storage=server_state.storage,
            embeddings=server_state.embeddings,
            vector_store=server_state.vector_store,
        )
        logger.info("✅ Miller components initialized and ready")

        # PHASE 2: Check if indexing needed and run if stale (uses hashes + mtime)
        init_phase = "indexing"
        logger.info("🔍 Checking if workspace indexing needed...")
        if await server_state.scanner.check_if_indexing_needed():
            logger.info("📚 Workspace needs indexing - starting background indexing")
            stats = await server_state.scanner.index_workspace()
            logger.info(
                f"✅ Indexing complete: {stats['indexed']} indexed, "
                f"{stats['updated']} updated, {stats['skipped']} skipped, "
                f"{stats['deleted']} deleted, {stats['errors']} errors"
            )

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

        # PHASE 3: Start file watcher for real-time updates
        init_phase = "file_watcher"
        logger.info("👁️  Starting file watcher for real-time indexing...")
        from miller.ignore_patterns import load_all_ignores

        ignore_spec = load_all_ignores(server_state.workspace_root)
        pattern_strings = {p.pattern for p in ignore_spec.patterns}
        file_watcher = FileWatcher(
            workspace_path=server_state.workspace_root,
            indexing_callback=_on_files_changed,
            ignore_patterns=pattern_strings,
            debounce_delay=0.2,
        )
        file_watcher.start()
        logger.info("✅ File watcher active - workspace changes will be indexed automatically")

        init_phase = "complete"  # Stop watchdog thread

    except Exception as e:
        logger.error(f"❌ Background initialization/indexing failed: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(_app):
    """
    FastMCP lifespan handler - startup and shutdown hooks.

    Startup:
      1. Server becomes ready instantly (MCP handshake completes)
      2. Background task initializes components (non-blocking)
      3. Background task checks if indexing needed and runs if stale
      4. File watcher starts for real-time updates

    Shutdown: Stop file watcher and cleanup

    This matches Julie's pattern: instant handshake, background initialization + indexing.
    """
    # File watcher reference (initialized by background task)
    file_watcher = None

    # Spawn background task immediately (server becomes ready without waiting)
    logger.info("🚀 Spawning background initialization task...")
    init_task = asyncio.create_task(_background_initialization_and_indexing())
    logger.info("✅ Server ready for MCP handshake (initialization running in background)")

    yield  # Server runs here - client sees "Connected" immediately

    # SHUTDOWN: Stop file watcher and wait for background task
    logger.info("🛑 Miller server shutting down...")

    if file_watcher and file_watcher.is_running():
        logger.info("⏹️  Stopping file watcher...")
        file_watcher.stop()
        logger.info("✅ File watcher stopped")

    if not init_task.done():
        logger.info("⏳ Waiting for background initialization to complete...")
        await init_task

    logger.info("👋 Miller server shutdown complete")
