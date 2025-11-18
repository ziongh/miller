"""
Miller MCP Server - FastMCP implementation

Provides MCP tools for code indexing and semantic search.
Uses Miller's Rust core for parsing and Python ML stack for embeddings.

CRITICAL: This is an MCP server - NEVER use print() statements!
stdout/stderr are reserved for JSON-RPC protocol. Use logger instead.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Literal
import hashlib

from fastmcp import FastMCP

from miller.storage import StorageManager
from miller.embeddings import EmbeddingManager, VectorStore
from miller.workspace import WorkspaceScanner
from miller.logging_config import setup_logging, get_logger
import asyncio

# Initialize logging FIRST (before any other operations)
logger = setup_logging()
logger.info("Starting Miller MCP Server initialization...")

# Import Rust core
try:
    from . import miller_core
except ImportError:
    # For testing without building Rust extension
    miller_core = None


# Initialize Miller components
logger.info("Initializing Miller components...")
# Note: FastMCP doesn't have request_timeout parameter
# Timeout handling is managed by the underlying transport layer
mcp = FastMCP("Miller Code Intelligence Server")
storage = StorageManager(db_path=".miller/indexes/symbols.db")
vector_store = VectorStore(db_path=".miller/indexes/vectors.lance")
embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="auto")
logger.info("✓ Core components initialized")

# Initialize workspace scanner for automatic indexing
workspace_root = Path.cwd()
logger.info(f"Workspace root: {workspace_root}")
scanner = WorkspaceScanner(
    workspace_root=workspace_root,
    storage=storage,
    embeddings=embeddings,
    vector_store=vector_store
)
logger.info("✓ WorkspaceScanner initialized")

# Track if lazy indexing has run
_indexing_complete = False


# Background auto-indexing (runs after server starts)
async def startup_indexing():
    """Check if indexing needed and run in background."""
    try:
        logger.info("Checking if workspace indexing needed...")
        if await scanner.check_if_indexing_needed():
            logger.info("Workspace needs indexing - starting background indexing")
            stats = await scanner.index_workspace()
            logger.info(
                f"Indexing complete: {stats['indexed']} indexed, "
                f"{stats['updated']} updated, {stats['skipped']} skipped, "
                f"{stats['deleted']} deleted, {stats['errors']} errors"
            )
        else:
            logger.info("Workspace already indexed - ready for search")
    except Exception as e:
        logger.error(f"Auto-indexing failed: {e}", exc_info=True)


# MCP Tool implementations (plain functions for testing)


def fast_search(
    query: str,
    method: Literal["text", "semantic", "hybrid"] = "hybrid",
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Search indexed code.

    Args:
        query: Search query
        method: Search method (text, semantic, hybrid)
        limit: Maximum results to return

    Returns:
        List of matching symbols with metadata
    """
    global _indexing_complete

    # Lazy indexing: index on first search if needed
    if not _indexing_complete:
        logger.info("First search - running lazy indexing...")
        try:
            asyncio.run(startup_indexing())
            _indexing_complete = True
        except Exception as e:
            logger.error(f"Lazy indexing failed: {e}", exc_info=True)
            # Continue anyway - return whatever results we have

    results = vector_store.search(query, method=method, limit=limit)

    # Format results for MCP
    formatted = []
    for r in results:
        formatted.append({
            "name": r.get("name", ""),
            "kind": r.get("kind", ""),
            "file_path": r.get("file_path", ""),
            "signature": r.get("signature"),
            "doc_comment": r.get("doc_comment"),
            "start_line": r.get("start_line", 0),
            "score": r.get("score", 0.0)
        })

    return formatted


def fast_goto(symbol_name: str) -> Optional[Dict[str, Any]]:
    """
    Find symbol definition location.

    Args:
        symbol_name: Name of symbol to find

    Returns:
        Symbol location info, or None if not found
    """
    # Query SQLite for exact match
    sym = storage.get_symbol_by_name(symbol_name)

    if not sym:
        return None

    return {
        "name": sym["name"],
        "kind": sym["kind"],
        "file_path": sym["file_path"],
        "start_line": sym["start_line"],
        "end_line": sym["end_line"],
        "signature": sym["signature"],
        "doc_comment": sym["doc_comment"]
    }


def get_symbols(file_path: str) -> List[Dict[str, Any]]:
    """
    Get file structure (symbols without full content).

    Args:
        file_path: Path to file

    Returns:
        List of symbols in file
    """
    path = Path(file_path)

    if not path.exists():
        return []

    # Read and extract
    try:
        content = path.read_text(encoding='utf-8')
        language = miller_core.detect_language(file_path)

        if not language:
            return []

        result = miller_core.extract_file(content, language, file_path)

        # Convert to dicts
        symbols = []
        for sym in result.symbols:
            symbols.append({
                "name": sym.name,
                "kind": sym.kind,
                "start_line": sym.start_line,
                "end_line": sym.end_line,
                "signature": sym.signature if hasattr(sym, 'signature') else None,
                "doc_comment": sym.doc_comment if hasattr(sym, 'doc_comment') else None
            })

        return symbols

    except Exception as e:
        return []


# Register tools with FastMCP
mcp.tool()(fast_search)
mcp.tool()(fast_goto)
mcp.tool()(get_symbols)


# Export functions for direct use (testing)
# The @mcp.tool() decorator wraps them, but we also need raw access
__all__ = [
    "mcp",
    "storage",
    "vector_store",
    "embeddings",
    "scanner",
    "fast_search",
    "fast_goto",
    "get_symbols"
]


# Server entry point
def main():
    """Main entry point for Miller MCP server."""
    logger.info("Starting Miller MCP server...")

    # Skip startup indexing - index on-demand when first search is called
    # Running indexing before mcp.run() blocks the server from accepting connections
    # which causes Claude Code CLI connection timeouts
    logger.info("Miller MCP server ready - indexing will run on first search")

    # Suppress FastMCP banner to keep stdout clean for MCP protocol
    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
