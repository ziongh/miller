"""
Miller MCP Server - FastMCP implementation

Provides MCP tools for code indexing and semantic search.
Uses Miller's Rust core for parsing and Python ML stack for embeddings.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Literal
import hashlib

from fastmcp import FastMCP

from miller.storage import StorageManager
from miller.embeddings import EmbeddingManager, VectorStore

# Import Rust core
try:
    from . import miller_core
except ImportError:
    # For testing without building Rust extension
    miller_core = None


# Initialize Miller components
mcp = FastMCP("Miller Code Intelligence Server")
storage = StorageManager(db_path=".miller/indexes/symbols.db")
vector_store = VectorStore(db_path=".miller/indexes/vectors.lance")
embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="auto")


# Helper functions

def _normalize_path(path: str) -> str:
    r"""
    Normalize file path to remove Windows UNC prefix.

    Rust's path canonicalization adds \\?\ prefix on Windows for absolute paths.
    We strip this to match the path format used everywhere else.
    """
    if path.startswith('\\\\?\\'):
        return path[4:]  # Strip \\?\
    return path


def _compute_file_hash(content: str) -> str:
    """Compute SHA-256 hash of file content."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _index_file_impl(file_path: str) -> Dict[str, Any]:
    """
    Index a single file (internal implementation).

    Returns dict with stats for reporting.
    """
    path = Path(file_path)

    if not path.exists():
        return {
            "success": False,
            "error": f"File not found: {file_path}",
            "symbols": 0
        }

    # Read file
    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read file: {str(e)}",
            "symbols": 0
        }

    # Detect language
    language = miller_core.detect_language(file_path)
    if not language:
        return {
            "success": False,
            "error": "Could not detect language",
            "symbols": 0
        }

    # Extract symbols
    try:
        result = miller_core.extract_file(content, language, file_path)
    except Exception as e:
        return {
            "success": False,
            "error": f"Extraction failed: {str(e)}",
            "symbols": 0
        }

    # Compute file hash
    file_hash = _compute_file_hash(content)

    # Store in SQLite
    storage.add_file(
        file_path=file_path,
        language=language,
        content=content,
        hash=file_hash,
        size=len(content)
    )

    # Store symbols (path normalization happens in storage layer)
    symbol_count = storage.add_symbols_batch(result.symbols)

    # Store identifiers
    storage.add_identifiers_batch(result.identifiers)

    # Store relationships
    storage.add_relationships_batch(result.relationships)

    # Generate embeddings
    if result.symbols:
        vectors = embeddings.embed_batch(result.symbols)

        # Store in LanceDB
        vector_store.update_file_symbols(file_path, result.symbols, vectors)

    return {
        "success": True,
        "symbols": symbol_count,
        "identifiers": len(result.identifiers),
        "relationships": len(result.relationships),
        "language": language
    }


# MCP Tool implementations (plain functions for testing)

def index_file(file_path: str) -> str:
    """
    Index a source code file.

    Extracts symbols, generates embeddings, and stores in database.

    Args:
        file_path: Path to file to index

    Returns:
        Success message with indexing stats
    """
    result = _index_file_impl(file_path)

    if not result["success"]:
        return f"Error: {result['error']}"

    return (
        f"Success: Indexed {file_path}\n"
        f"  Language: {result['language']}\n"
        f"  Symbols: {result['symbols']}\n"
        f"  Identifiers: {result['identifiers']}\n"
        f"  Relationships: {result['relationships']}"
    )


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
mcp.tool()(index_file)
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
    "index_file",
    "fast_search",
    "fast_goto",
    "get_symbols"
]


# Server entry point
if __name__ == "__main__":
    # Run MCP server
    mcp.run()
