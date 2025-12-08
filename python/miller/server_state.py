"""
Miller server global state - shared between server and lifecycle modules.

This module holds the mutable global state that is initialized during server
startup and used by both the MCP server and the lifespan handler.

CRITICAL: Don't add heavy imports here (torch, sentence-transformers, etc).
These are imported lazily in the background task to avoid blocking MCP handshake.
"""

import asyncio

# Miller components initialized by background task (None until initialized)
# These are populated by lifecycle._background_initialization_and_indexing()
storage = None
vector_store = None
embeddings = None
scanner = None
workspace_root = None
file_watcher = None  # MultiWorkspaceWatcher instance for real-time indexing (all workspaces)
primary_workspace_id = None  # Workspace ID of the primary (startup) workspace

# Map of workspace_id -> WorkspaceScanner for multi-workspace support
# This allows each workspace to have its own scanner while sharing storage/vector_store
workspace_scanners: dict = {}

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  INDEXING LOCK - PREVENTS MEMORY CORRUPTION                                   ║
# ║                                                                               ║
# ║  When multiple workspaces are being indexed, they share:                      ║
# ║  - EmbeddingManager (GPU model)                                               ║
# ║  - VectorStore (LanceDB table)                                                ║
# ║  - StorageManager (SQLite database)                                           ║
# ║                                                                               ║
# ║  Concurrent access to these shared resources (especially EmbeddingManager     ║
# ║  with CUDA and VectorStore with Arrow) can cause memory corruption:           ║
# ║  - munmap_chunk(): invalid pointer                                            ║
# ║  - double-free errors                                                         ║
# ║  - CUDA out of memory                                                         ║
# ║                                                                               ║
# ║  This lock ensures only one indexing operation happens at a time.             ║
# ║  It's an asyncio.Lock so it integrates properly with async code.              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
indexing_lock: asyncio.Lock = None  # Created on first access (lazy)


def get_indexing_lock() -> asyncio.Lock:
    """
    Get or create the indexing Lock (lazy creation).

    Why lazy? asyncio.Lock() must be created in an async context
    (when an event loop exists). Module-level creation would fail
    when imported outside async code.
    """
    global indexing_lock
    if indexing_lock is None:
        indexing_lock = asyncio.Lock()
    return indexing_lock


# Console mode flag - enables visual progress bars on stderr
# Set to True in HTTP mode (main_http), False in STDIO mode (default)
# When True and stderr is a TTY, progress uses dynamic visual bars
# When False, progress uses periodic log entries (safe for MCP/files)
console_mode = False

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  INITIALIZATION SYNCHRONIZATION                                               ║
# ║                                                                               ║
# ║  On Windows, heavy imports (torch, sentence-transformers) run synchronously   ║
# ║  and take 5-15 seconds. During this time:                                     ║
# ║  - MCP handshake completes (server appears "ready")                           ║
# ║  - BUT tools would fail because storage/embeddings are None                   ║
# ║                                                                               ║
# ║  Instead of returning error strings (which agents misinterpret as failures),  ║
# ║  tools await this Event. This causes them to block until initialization       ║
# ║  completes, then proceed normally. Much more agent-friendly!                  ║
# ║                                                                               ║
# ║  The Event is set by lifecycle._background_initialization_and_indexing()      ║
# ║  after storage, embeddings, and vector_store are all initialized.             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
initialization_complete: asyncio.Event = None  # Created on first access (lazy)

# Default timeout for waiting on initialization (seconds)
# Windows imports can take 15s, so we add buffer
INITIALIZATION_TIMEOUT_SECONDS = 30


def get_initialization_event() -> asyncio.Event:
    """
    Get or create the initialization Event (lazy creation).

    Why lazy? asyncio.Event() must be created in an async context
    (when an event loop exists). Module-level creation would fail
    when imported outside async code.
    """
    global initialization_complete
    if initialization_complete is None:
        initialization_complete = asyncio.Event()
    return initialization_complete


__all__ = [
    "storage",
    "vector_store",
    "embeddings",
    "scanner",
    "workspace_root",
    "file_watcher",
    "primary_workspace_id",
    "workspace_scanners",
    "console_mode",
    "get_initialization_event",
    "get_indexing_lock",
    "INITIALIZATION_TIMEOUT_SECONDS",
]
