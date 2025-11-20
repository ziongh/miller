"""
Miller Embeddings Layer - LanceDB + sentence-transformers

Provides vector embeddings and semantic search capabilities.
Uses sentence-transformers for encoding and LanceDB for vector storage.

CRITICAL: Heavy imports (torch, sentence-transformers) happen in the submodules,
not here. This __init__.py has NO imports of heavy libraries, ensuring fast module loading
for MCP handshake. Heavy imports are deferred to background task in server.py.
"""

# Public API exports (lazy imports - only when actually used)
__all__ = ["EmbeddingManager", "VectorStore", "SearchMethod", "detect_search_method"]


def __getattr__(name: str):
    """Lazy import of heavy ML libraries on first access.

    This ensures fast MCP handshake - modules are only imported when actually used,
    not when the package is imported.
    """
    if name == "EmbeddingManager":
        from miller.embeddings.manager import EmbeddingManager

        return EmbeddingManager
    elif name == "VectorStore":
        from miller.embeddings.vector_store import VectorStore

        return VectorStore
    elif name == "SearchMethod":
        from miller.embeddings.search import SearchMethod

        return SearchMethod
    elif name == "detect_search_method":
        from miller.embeddings.search import detect_search_method

        return detect_search_method
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
