"""
Miller server global state - shared between server and lifecycle modules.

This module holds the mutable global state that is initialized during server
startup and used by both the MCP server and the lifespan handler.

CRITICAL: Don't add heavy imports here (torch, sentence-transformers, etc).
These are imported lazily in the background task to avoid blocking MCP handshake.
"""

# Miller components initialized by background task (None until initialized)
# These are populated by lifecycle._background_initialization_and_indexing()
storage = None
vector_store = None
embeddings = None
scanner = None
workspace_root = None

__all__ = ["storage", "vector_store", "embeddings", "scanner", "workspace_root"]
