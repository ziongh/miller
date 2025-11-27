"""
File indexing operations for workspace scanning.

Provides:
- Single file indexing with and without timing
- Batch file indexing with GPU-optimized parallelization
- Symbol extraction, database storage, and embeddings
- File-level indexing for text files without tree-sitter parsers
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

from ..embeddings import EmbeddingManager, VectorStore
from ..storage import StorageManager

# Get logger instance
logger = logging.getLogger("miller.workspace")

# Import Rust core
try:
    from .. import miller_core
except ImportError:
    # For testing without building Rust extension
    miller_core = None

# Maximum file content size for embedding (10KB)
MAX_CONTENT_FOR_EMBEDDING = 10 * 1024

# Languages that have tree-sitter parsers (symbol extraction available)
# Files with other languages get file-level indexing only
LANGUAGES_WITH_PARSERS = {
    "rust", "python", "javascript", "typescript", "java", "csharp", "go",
    "cpp", "c", "ruby", "php", "swift", "kotlin", "lua", "sql", "html",
    "css", "vue", "razor", "bash", "powershell", "gdscript", "zig", "dart",
    "qml", "r", "markdown", "json", "toml",
}


@dataclass
class FileSymbol:
    """
    Represents a file-level entry for files without tree-sitter parsers.

    Used for .gitattributes, Dockerfile, Makefile, and other text files
    that don't have symbol extraction but should still be searchable.
    """
    id: str
    name: str
    kind: str  # Always "file"
    language: str
    file_path: str
    signature: Optional[str]
    doc_comment: Optional[str]
    start_line: int
    end_line: int
    content: Optional[str]  # File content for FTS (truncated to MAX_CONTENT_FOR_EMBEDDING)

    @classmethod
    def from_file(cls, file_path: str, content: str, language: str = "text") -> "FileSymbol":
        """Create a FileSymbol from file path and content."""
        # Generate stable ID from file path
        file_id = f"file_{hashlib.sha256(file_path.encode()).hexdigest()[:16]}"

        # Get filename for display
        name = Path(file_path).name

        # Count lines
        lines = content.splitlines()
        end_line = len(lines) if lines else 1

        # Truncate content for embedding/FTS (first 10KB)
        truncated_content = content[:MAX_CONTENT_FOR_EMBEDDING] if content else ""

        return cls(
            id=file_id,
            name=name,
            kind="file",
            language=language,
            file_path=file_path,
            signature=None,
            doc_comment=None,
            start_line=1,
            end_line=end_line,
            content=truncated_content,
        )


def compute_code_context(content: str, symbols: list[Any], context_lines: int = 2) -> dict[str, str]:
    """
    Compute grep-style code context for each symbol.

    Extracts a few lines around each symbol's start_line for display
    in search results (like grep -C output).

    Args:
        content: Full file content as string
        symbols: List of PySymbol objects with start_line attributes
        context_lines: Number of lines before/after to include (default: 2)

    Returns:
        Dict mapping symbol_id to code_context string
    """
    if not symbols or not content:
        return {}

    lines = content.splitlines()
    total_lines = len(lines)
    context_map = {}

    for sym in symbols:
        # start_line is 1-indexed, convert to 0-indexed
        line_idx = sym.start_line - 1 if sym.start_line > 0 else 0

        # Calculate context range
        start_idx = max(0, line_idx - context_lines)
        end_idx = min(total_lines, line_idx + context_lines + 1)

        # Extract context lines with line numbers
        context_parts = []
        for i in range(start_idx, end_idx):
            line_num = i + 1  # 1-indexed for display
            line_content = lines[i] if i < total_lines else ""

            # Mark the symbol's line with an arrow, others with colon
            if i == line_idx:
                context_parts.append(f"{line_num:>4}→ {line_content}")
            else:
                context_parts.append(f"{line_num:>4}: {line_content}")

        context_map[sym.id] = "\n".join(context_parts)

    return context_map


async def index_file(file_path: Path, workspace_root: Path, storage: StorageManager,
                     embeddings: EmbeddingManager, vector_store: VectorStore) -> bool:
    """
    Index a single file (without timing instrumentation).

    Handles two cases:
    1. Files with tree-sitter parsers: Full symbol extraction + embeddings
    2. Files without parsers (language="text"): File-level entry for FTS/semantic search

    Args:
        file_path: Path to file (absolute)
        workspace_root: Root path of workspace
        storage: SQLite storage manager
        embeddings: Embedding generator
        vector_store: LanceDB vector store

    Returns:
        True if successful, False if error
    """
    if miller_core is None:
        return False

    try:
        # Convert to relative Unix-style path (like Julie does)
        # e.g., /Users/murphy/source/miller/src/lib.rs -> src/lib.rs
        relative_path = str(file_path.relative_to(workspace_root)).replace("\\", "/")

        # Read file
        content = file_path.read_text(encoding="utf-8")

        # Detect language (now returns "text" for unknown extensions, never None)
        language = miller_core.detect_language(str(file_path))

        # Compute hash using Rust blake3 (3x faster than SHA-256)
        file_hash = miller_core.hash_content(content)

        # Store file metadata (using relative path)
        storage.add_file(
            file_path=relative_path,
            language=language,
            content=content,
            hash=file_hash,
            size=len(content),
        )

        # Check if this language has a tree-sitter parser
        has_parser = language in LANGUAGES_WITH_PARSERS

        if has_parser:
            # Full symbol extraction path
            result = miller_core.extract_file(content, language, relative_path)

            # Compute code context for grep-style search output
            code_context_map = compute_code_context(content, result.symbols) if result.symbols else {}

            # Store symbols (with computed code_context)
            if result.symbols:
                storage.add_symbols_batch(result.symbols, code_context_map)

            # Store identifiers
            if result.identifiers:
                storage.add_identifiers_batch(result.identifiers)

            # Store relationships
            if result.relationships:
                storage.add_relationships_batch(result.relationships)

            # Generate embeddings for symbols
            if result.symbols:
                vectors = embeddings.embed_batch(result.symbols)
                vector_store.update_file_symbols(relative_path, result.symbols, vectors)
        else:
            # File-level indexing path (no tree-sitter parser)
            # Create a synthetic file-level entry for FTS and semantic search
            logger.debug(f"File-level indexing for {relative_path} (language={language})")

            file_symbol = FileSymbol.from_file(relative_path, content, language)

            # Generate embedding from file content (first 2KB for embedding model)
            embed_content = content[:2048] if content else file_symbol.name
            vectors = embeddings.embed_texts([embed_content])

            # Store in LanceDB with content for FTS
            vector_store.update_file_symbols(relative_path, [file_symbol], vectors)

        return True

    except Exception as e:
        # Log error but continue with other files
        logger.warning(f"Failed to index {file_path}: {e}")
        return False


async def index_file_timed(file_path: Path, workspace_root: Path, storage: StorageManager,
                          embeddings: EmbeddingManager, vector_store: VectorStore) -> Tuple[bool, float, float, float]:
    """
    Index a single file with timing instrumentation.

    Handles two cases:
    1. Files with tree-sitter parsers: Full symbol extraction + embeddings
    2. Files without parsers (language="text"): File-level entry for FTS/semantic search

    Args:
        file_path: Path to file (absolute)
        workspace_root: Root path of workspace
        storage: SQLite storage manager
        embeddings: Embedding generator
        vector_store: LanceDB vector store

    Returns:
        Tuple of (success, extraction_time, embedding_time, db_time)
    """
    if miller_core is None:
        return (False, 0.0, 0.0, 0.0)

    try:
        # Convert to relative Unix-style path (like Julie does)
        relative_path = str(file_path.relative_to(workspace_root)).replace("\\", "/")

        # Read file
        content = file_path.read_text(encoding="utf-8")

        # Detect language (now returns "text" for unknown extensions, never None)
        language = miller_core.detect_language(str(file_path))

        # Compute file hash using Rust blake3 (3x faster than SHA-256)
        file_hash = miller_core.hash_content(content)

        # Phase 1: Database writes (file metadata)
        db_start = time.time()

        # Store file metadata
        storage.add_file(
            file_path=relative_path,
            language=language,
            content=content,
            hash=file_hash,
            size=len(content),
        )

        # Check if this language has a tree-sitter parser
        has_parser = language in LANGUAGES_WITH_PARSERS

        extraction_time = 0.0
        embedding_time = 0.0

        if has_parser:
            db_time = time.time() - db_start

            # Phase 1b: Tree-sitter extraction
            extraction_start = time.time()
            result = miller_core.extract_file(
                content=content, language=language, file_path=relative_path
            )
            extraction_time = time.time() - extraction_start

            # Phase 2: More database writes (symbols, identifiers, relationships)
            db_start2 = time.time()

            # Compute code context for grep-style search output
            code_context_map = compute_code_context(content, result.symbols) if result.symbols else {}

            # Store symbols (with computed code_context)
            if result.symbols:
                storage.add_symbols_batch(result.symbols, code_context_map)

            # Store identifiers
            if result.identifiers:
                storage.add_identifiers_batch(result.identifiers)

            # Store relationships
            if result.relationships:
                storage.add_relationships_batch(result.relationships)

            db_time += time.time() - db_start2

            # Phase 3: Generate embeddings for symbols
            if result.symbols:
                embedding_start = time.time()
                vectors = embeddings.embed_batch(result.symbols)
                vector_store.update_file_symbols(relative_path, result.symbols, vectors)
                embedding_time = time.time() - embedding_start
        else:
            # File-level indexing path (no tree-sitter parser)
            db_time = time.time() - db_start

            logger.debug(f"File-level indexing for {relative_path} (language={language})")

            file_symbol = FileSymbol.from_file(relative_path, content, language)

            # Phase 3: Generate embedding from file content
            embedding_start = time.time()
            embed_content = content[:2048] if content else file_symbol.name
            vectors = embeddings.embed_texts([embed_content])
            vector_store.update_file_symbols(relative_path, [file_symbol], vectors)
            embedding_time = time.time() - embedding_start

        return (True, extraction_time, embedding_time, db_time)

    except Exception as e:
        # Log error but continue with other files
        logger.warning(f"Failed to index {file_path}: {e}")
        return (False, 0.0, 0.0, 0.0)
