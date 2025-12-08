"""
IndexingBuffer for streaming workspace indexing.

Accumulates parsed results and triggers flushing based on symbol count
rather than file count. This keeps memory usage stable regardless of
how many symbols individual files contain.

The "Bucket Brigade" pattern:
1. Rust processes files in small groups (Extraction Layer)
2. IndexingBuffer accumulates symbols (Buffering Layer)
3. Buffer signals when GPU batch is ready (Flush Trigger)
4. GPU processes embedding batch (GPU Layer)
5. Data written to DB and memory cleared (Write Layer)
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

logger = logging.getLogger("miller.workspace")

# Common language keywords that provide no search value
# These are filtered out to reduce I/O by ~30-40%
NOISE_KEYWORDS = frozenset({
    # --- Control Flow & Logic (Common) ---
    "if", "else", "return", "true", "false", "try", "catch", "finally",
    "break", "continue", "for", "while", "do", "switch", "case", "default",
    "throw", "new", "this", "super", "class", "void", "null", "none", "self",

    # --- C# Specifics ---
    # Access Modifiers
    "public", "private", "protected", "internal", "static", "readonly",
    "virtual", "override", "abstract", "sealed", "const", "volatile",
    # Types & Keywords
    "namespace", "using", "interface", "struct", "enum", "delegate", "event",
    "int", "string", "bool", "double", "float", "decimal", "char", "object",
    "byte", "long", "short", "dynamic", "var",
    "get", "set", "value", "add", "remove", # Properties/Events
    "async", "await", "task",
    "is", "as", "in", "out", "ref", "params", "lock", "unchecked",
    "typeof", "sizeof", "stackalloc",
    # LINQ (Very common, usually noise)
    "from", "where", "select", "group", "into", "orderby", "join", "let",

    # --- JavaScript / TypeScript Specifics ---
    "function", "export", "import", "default", "extends", "implements",
    "undefined", "nan", "infinity",
    "let", "const", "var", # Variable declarations
    "debugger", "delete", "instanceof",
    "console", "window", "document", "navigator", "map", "filter", "reduce",
    "promise", "resolve", "reject",

    # --- Razor / CSHTML / Web ---
    # Razor keywords (often appear without the @ in tokenizers)
    "model", "page", "inherits", "inject", "layout", "section",
    "viewbag", "viewdata", "tempdata", "html", "url",
    # Common HTML tags (very noisy in cshtml)
    "div", "span", "br", "hr", "label", "input", "button", "form",
    "class", "style", "href", "src", "type", "value", "name",

    # --- Common Variable Names & Conventions ---
    # These generate huge index bloat with low search value
    "data", "item", "index", "err", "error",
    "result", "response", "request", "req", "res", "ctx",
    "list", "array", "dict", "dictionary", "obj", "param", "args",
    "log", "todo", "fixme", "config", "options", "settings",
})


@dataclass
class IndexingBuffer:
    """
    Accumulates parsed results and triggers flushing based on symbol count.

    Key insight: A file can contain 1 symbol or 100+ symbols. Batching by
    file count leads to unpredictable memory usage. Batching by symbol count
    ensures the GPU always gets a "full plate" of work while maintaining
    stable memory consumption.

    Attributes:
        max_symbols: Flush when we have this many symbols (should match GPU batch size)
        max_files: Secondary threshold - flush when too many files accumulated

    Usage:
        buffer = IndexingBuffer(max_symbols=512)

        for file_path, result in process_files():
            buffer.add_result(file_path, ...)

            if buffer.should_flush():
                await flush_to_db_and_gpu(buffer)
                buffer.clear()

        # Final flush for remaining data
        if not buffer.is_empty():
            await flush_to_db_and_gpu(buffer)
    """

    # Thresholds
    max_symbols: int = 512  # Flush when we have this many symbols (GPU batch size)
    max_files: int = 50  # Prevent huge metadata lists even with few symbols

    # Accumulators
    files_to_clean: List[str] = field(default_factory=list)
    file_data_list: List[Tuple[str, str, str, str, int]] = field(default_factory=list)
    symbols: List[Any] = field(default_factory=list)
    identifiers: List[Any] = field(default_factory=list)
    relationships: List[Any] = field(default_factory=list)
    code_context_map: dict = field(default_factory=dict)

    # Tracking
    _files_processed_count: int = field(default=0, repr=False)

    def add_result(
        self,
        file_path: Path,
        relative_path: str,
        action: str,
        result: Any,
        content: str,
        language: str,
        file_hash: str,
        code_context_fn: Optional[callable] = None,
    ) -> int:
        """
        Add a single file's extraction result to the buffer.

        Args:
            file_path: Absolute path to the file
            relative_path: Path relative to workspace root (Unix-style)
            action: "indexed" (new file) or "updated" (changed file)
            result: Extraction result from miller_core (with symbols, identifiers, relationships)
            content: File content (for code context computation)
            language: Programming language
            file_hash: Content hash for change detection
            code_context_fn: Optional function to compute code context for symbols

        Returns:
            Number of symbols added from this file
        """
        # Track files being updated for cleanup (need old data deleted first)
        if action == "updated":
            self.files_to_clean.append(relative_path)

        # Track file metadata
        # Format: (path, language, content, hash, size)
        self.file_data_list.append(
            (relative_path, language, content, file_hash, len(content))
        )
        self._files_processed_count += 1

        symbols_added = 0

        # Flatten extracted data into lists
        # Handle None results gracefully (text files have no extraction results)
        if result is not None:
            if result.symbols:
                self.symbols.extend(result.symbols)
                symbols_added = len(result.symbols)

                # Compute code context if function provided
                if code_context_fn is not None:
                    file_context_map = code_context_fn(content, result.symbols)
                    self.code_context_map.update(file_context_map)

            if hasattr(result, "identifiers") and result.identifiers:
                # Filter out noise identifiers to reduce I/O by ~30-40%
                useful_identifiers = [
                    ident for ident in result.identifiers
                    if self._is_useful_identifier(ident.name)
                ]
                self.identifiers.extend(useful_identifiers)

            if hasattr(result, "relationships") and result.relationships:
                self.relationships.extend(result.relationships)

        return symbols_added

    def _is_useful_identifier(self, name: str) -> bool:
        """
        Filter out noise identifiers to reduce DB size by ~30-40%.

        Filtered out:
        - Single character names (i, x, j, _)
        - Pure numeric strings (123, 42)
        - Common language keywords (if, else, return, self, etc.)

        Args:
            name: Identifier name to check

        Returns:
            True if the identifier is worth indexing, False if noise
        """
        # Skip very short names (usually loop vars like i, j, k)
        if len(name) < 2:
            return False

        # Skip pure numeric strings (constants, not identifiers)
        if name.isdigit():
            return False

        # Skip common language keywords (case-insensitive)
        if name.lower() in NOISE_KEYWORDS:
            return False

        return True

    def should_flush(self) -> bool:
        """
        Determine if the buffer is full enough to send to GPU.

        Returns True when either:
        1. Symbol count reaches max_symbols (saturates GPU)
        2. File count reaches max_files (prevents huge metadata lists)

        Returns:
            True if buffer should be flushed, False otherwise
        """
        # Flush if we have enough symbols to saturate the GPU
        if len(self.symbols) >= self.max_symbols:
            return True

        # Flush if we have processed too many files (prevent huge metadata lists)
        if len(self.file_data_list) >= self.max_files:
            return True

        return False

    def is_empty(self) -> bool:
        """
        Check if the buffer has any file data.

        Note: We check file_data_list, not symbols, because a file might
        have zero symbols but still need to be tracked in the database.

        Returns:
            True if no files have been added, False otherwise
        """
        return len(self.file_data_list) == 0

    def clear(self) -> None:
        """
        Reset the buffer after a flush.

        Clears all accumulators to prepare for the next batch.
        Does NOT reset max_symbols/max_files thresholds.
        """
        self.files_to_clean.clear()
        self.file_data_list.clear()
        self.symbols.clear()
        self.identifiers.clear()
        self.relationships.clear()
        self.code_context_map.clear()
        # Note: _files_processed_count is NOT reset - it tracks total files
        # across the entire indexing session, not per-flush

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"IndexingBuffer("
            f"symbols={len(self.symbols)}/{self.max_symbols}, "
            f"files={len(self.file_data_list)}/{self.max_files}, "
            f"should_flush={self.should_flush()}"
            f")"
        )
