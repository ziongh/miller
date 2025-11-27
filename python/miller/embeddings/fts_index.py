"""FTS (Full-Text Search) index management for LanceDB.

Handles Tantivy FTS index creation with retry logic for Windows-specific
file locking issues.
"""

import logging
import sys
import time

logger = logging.getLogger("miller.vector_store")


def create_fts_index(table, max_retries: int = 3):
    """
    Create Tantivy FTS index on code_pattern and content fields.

    Indexes two fields:
    - code_pattern: signature + name + kind (for symbol search)
    - content: raw file content (for file-level entries with kind="file")

    Uses unicode61 tokenizer which:
    - Provides good word segmentation for file content (natural language)
    - Still works for code patterns (tokenizes on punctuation/whitespace)
    - Supports searching across both symbols and file content

    Args:
        table: LanceDB table object to create index on
        max_retries: Number of retry attempts for Windows file locking issues.
                     Tantivy has a known race condition on Windows where file
                     operations can fail with PermissionDenied. Usually succeeds
                     on retry. See: https://github.com/quickwit-oss/tantivy/issues/587

    Returns:
        Tuple of (fts_index_created, pattern_index_created) booleans
    """
    if table is None:
        return False, False

    last_error = None
    for attempt in range(max_retries):
        try:
            # Create FTS index on both code_pattern and content fields
            # This enables searching symbols AND file content in one query
            table.create_fts_index(
                ["code_pattern", "content"],  # Both symbol patterns AND file content
                use_tantivy=True,  # Enable Tantivy FTS
                base_tokenizer="whitespace",  # Preserves code patterns (: < > [ ])
                with_position=True,  # Enable phrase search
                replace=True,  # Replace existing index
            )
            if attempt > 0:
                logger.info(f"FTS index created successfully on retry {attempt + 1}")
            else:
                logger.debug("FTS index created on code_pattern and content fields")
            return True, True  # Both flags set (same index serves both purposes)

        except Exception as e:
            last_error = e
            error_str = str(e)

            # Check if this is a retryable Windows error
            # Tantivy has known race conditions on Windows that cause transient failures:
            # 1. PermissionDenied (code 5) - file locking race condition
            # 2. "index writer was killed" - thread panic, often from I/O race
            # See: https://github.com/quickwit-oss/tantivy/issues/587
            is_windows_transient = (
                "PermissionDenied" in error_str
                or "Access is denied" in error_str
                or "index writer was killed" in error_str
                or "worker thread encountered an error" in error_str
                or (hasattr(e, "errno") and e.errno == 5)
            )

            if is_windows_transient and sys.platform == "win32" and attempt < max_retries - 1:
                # Exponential backoff: 100ms, 200ms, 400ms...
                delay = 0.1 * (2 ** attempt)
                logger.debug(
                    f"FTS index creation hit Windows issue (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay:.1f}s: {error_str[:100]}"
                )
                time.sleep(delay)
                continue

            # Non-retryable error or max retries exceeded
            break

    # All retries failed or non-retryable error
    logger.warning(f"FTS index creation failed: {last_error}", exc_info=True)
    return False, False
