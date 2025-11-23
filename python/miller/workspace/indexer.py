"""
File indexing operations for workspace scanning.

Provides:
- Single file indexing with and without timing
- Batch file indexing with GPU-optimized parallelization
- Symbol extraction, database storage, and embeddings
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Tuple

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


async def index_file(file_path: Path, workspace_root: Path, storage: StorageManager,
                     embeddings: EmbeddingManager, vector_store: VectorStore) -> bool:
    """
    Index a single file (without timing instrumentation).

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

        # Detect language
        language = miller_core.detect_language(str(file_path))
        if not language:
            return False

        # Extract symbols (pass relative path so symbols have correct file_path)
        result = miller_core.extract_file(content, language, relative_path)

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

        # Store symbols
        if result.symbols:
            storage.add_symbols_batch(result.symbols)

        # Store identifiers
        if result.identifiers:
            storage.add_identifiers_batch(result.identifiers)

        # Store relationships
        if result.relationships:
            storage.add_relationships_batch(result.relationships)

        # Generate embeddings
        if result.symbols:
            vectors = embeddings.embed_batch(result.symbols)

            # Store in LanceDB (using relative path)
            vector_store.update_file_symbols(relative_path, result.symbols, vectors)

        return True

    except Exception as e:
        # Log error but continue with other files
        logger.warning(f"Failed to index {file_path}: {e}")
        return False


async def index_file_timed(file_path: Path, workspace_root: Path, storage: StorageManager,
                          embeddings: EmbeddingManager, vector_store: VectorStore) -> Tuple[bool, float, float, float]:
    """
    Index a single file with timing instrumentation.

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

        # Detect language
        language = miller_core.detect_language(str(file_path))
        if not language:
            return (False, 0.0, 0.0, 0.0)

        # Phase 1: Tree-sitter extraction
        extraction_start = time.time()
        result = miller_core.extract_file(
            content=content, language=language, file_path=relative_path
        )
        extraction_time = time.time() - extraction_start

        # Compute file hash using Rust blake3 (3x faster than SHA-256)
        file_hash = miller_core.hash_content(content)

        # Phase 2: Database writes (symbols, identifiers, relationships)
        db_start = time.time()

        # Store file metadata
        storage.add_file(
            file_path=relative_path,
            language=language,
            content=content,
            hash=file_hash,
            size=len(content),
        )

        # Store symbols
        if result.symbols:
            storage.add_symbols_batch(result.symbols)

        # Store identifiers
        if result.identifiers:
            storage.add_identifiers_batch(result.identifiers)

        # Store relationships
        if result.relationships:
            storage.add_relationships_batch(result.relationships)

        db_time = time.time() - db_start

        # Phase 3: Generate embeddings
        embedding_time = 0.0
        if result.symbols:
            embedding_start = time.time()
            vectors = embeddings.embed_batch(result.symbols)

            # Store in LanceDB (using relative path)
            vector_store.update_file_symbols(relative_path, result.symbols, vectors)
            embedding_time = time.time() - embedding_start

        return (True, extraction_time, embedding_time, db_time)

    except Exception as e:
        # Log error but continue with other files
        logger.warning(f"Failed to index {file_path}: {e}")
        return (False, 0.0, 0.0, 0.0)
