"""
Miller Storage Layer - SQLite

Provides persistent storage for extracted symbols.
Search functionality is handled by LanceDB (see embeddings.py).

This module re-exports the main StorageManager class and StorageError
exception for backwards compatibility with code that imports:
    from miller.storage import StorageManager, StorageError
"""

from .manager import StorageManager
from .schema import StorageError

__all__ = ["StorageManager", "StorageError"]
