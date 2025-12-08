"""
Test WorkspaceScanner for automatic workspace indexing.

Following TDD: These tests define the WorkspaceScanner API BEFORE implementation.
"""

import pytest
from pathlib import Path
import tempfile
import shutil
import hashlib


@pytest.fixture
def test_workspace():
    """Create a temporary workspace with sample code files."""
    temp_dir = tempfile.mkdtemp(prefix="miller_workspace_test_")
    workspace = Path(temp_dir)

    # Create directory structure
    (workspace / "src").mkdir()
    (workspace / "tests").mkdir()
    (workspace / "node_modules").mkdir()  # Should be ignored

    # Create Python files
    (workspace / "src" / "main.py").write_text("""
def hello(name: str) -> str:
    '''Say hello.'''
    return f"Hello, {name}"
""")

    (workspace / "src" / "utils.py").write_text("""
def add(a: int, b: int) -> int:
    return a + b
""")

    (workspace / "tests" / "test_main.py").write_text("""
def test_hello():
    from src.main import hello
    assert hello("World") == "Hello, World"
""")

    # Create .gitignore
    (workspace / ".gitignore").write_text("""
node_modules/
*.pyc
__pycache__/
""")

    # Create ignored file (should not be indexed)
    (workspace / "node_modules" / "lib.js").write_text("// ignored")

    yield workspace

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestWorkspaceScannerInitialization:
    """Test WorkspaceScanner creation and setup."""

    def test_scanner_initializes_with_required_components(self, test_workspace, storage_manager, vector_store):
        """Test that scanner requires storage, embeddings, and vector_store."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(
            workspace_root=test_workspace,
            storage=storage_manager,
            embeddings=embeddings,
            vector_store=vector_store
        )

        assert scanner.workspace_root == test_workspace
        assert scanner.storage == storage_manager


class TestFileDiscovery:
    """Test workspace file discovery and filtering."""

    def test_walk_directory_finds_python_files(self, test_workspace, storage_manager, vector_store):
        """Test that _walk_directory finds all Python source files."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)
        files = scanner._walk_directory()

        # Should find .py files
        py_files = [f for f in files if f.suffix == ".py"]
        assert len(py_files) >= 3  # main.py, utils.py, test_main.py

    def test_walk_directory_respects_gitignore(self, test_workspace, storage_manager, vector_store):
        """Test that ignored directories are excluded."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)
        files = scanner._walk_directory()

        # Should NOT include files from node_modules
        assert not any("node_modules" in str(f) for f in files)

    def test_walk_directory_includes_text_files(self, test_workspace, storage_manager, vector_store):
        """Test that text files (without parsers) ARE included for file-level indexing.

        Since file-level indexing was added, files without tree-sitter parsers
        are still indexed as "text" type for FTS/semantic search.
        """
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        # Add a text file type (no tree-sitter parser)
        (test_workspace / "data.xyz").write_text("some content")

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)
        files = scanner._walk_directory()

        # Text files should be included for file-level indexing
        assert any(f.suffix == ".xyz" for f in files)


class TestChangeDetection:
    """Test file change detection for incremental indexing."""

    def test_needs_indexing_for_new_file(self, test_workspace, storage_manager, vector_store):
        """Test that new files (not in DB) need indexing."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)

        # File not in DB
        file_path = test_workspace / "src" / "main.py"
        db_files_map = {f["path"]: f for f in storage_manager.get_all_files()}
        assert scanner._needs_indexing(file_path, db_files_map) is True

    def test_needs_indexing_for_changed_file(self, test_workspace, storage_manager, vector_store):
        """Test that files with changed content need re-indexing."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        # Index file with original content
        file_path = test_workspace / "src" / "main.py"
        original_content = file_path.read_text()
        original_hash = hashlib.sha256(original_content.encode()).hexdigest()

        # Use relative path to match production behavior
        relative_path = str(file_path.relative_to(test_workspace)).replace("\\", "/")
        storage_manager.add_file(
            relative_path, "python", original_content, original_hash, len(original_content)
        )

        # Modify file
        new_content = "def new_function(): pass"
        file_path.write_text(new_content)

        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)

        # Should need re-indexing (hash changed)
        db_files_map = {f["path"]: f for f in storage_manager.get_all_files()}
        assert scanner._needs_indexing(file_path, db_files_map) is True

    def test_skips_unchanged_file(self, test_workspace, storage_manager, vector_store):
        """Test that unchanged files are skipped."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(device="cpu")

        # Index file
        file_path = test_workspace / "src" / "main.py"
        content = file_path.read_text()
        # Use blake3 hash (same as scanner uses)
        file_hash = miller_core.hash_content(content)

        # Use relative path to match production behavior
        relative_path = str(file_path.relative_to(test_workspace)).replace("\\", "/")
        storage_manager.add_file(relative_path, "python", content, file_hash, len(content))

        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)

        # Should NOT need re-indexing (hash matches)
        db_files_map = {f["path"]: f for f in storage_manager.get_all_files()}
        assert scanner._needs_indexing(file_path, db_files_map) is False


class TestWorkspaceIndexing:
    """Test full workspace indexing workflow."""

    @pytest.mark.asyncio
    async def test_check_if_indexing_needed_empty_db(self, test_workspace, storage_manager, vector_store):
        """Test that empty database triggers indexing."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)

        # Empty DB should need indexing
        assert await scanner.check_if_indexing_needed() is True

    @pytest.mark.asyncio
    async def test_check_if_indexing_needed_fresh_db(self, test_workspace, storage_manager, vector_store):
        """Test that fresh database (all files indexed WITH symbols) skips indexing."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(device="cpu")

        # Index all files manually first (using relative paths like production code)
        # IMPORTANT: Must add BOTH files AND symbols to be truly "indexed"
        for py_file in test_workspace.rglob("*.py"):
            if "node_modules" in str(py_file):
                continue

            content = py_file.read_text()
            file_hash = hashlib.sha256(content.encode()).hexdigest()
            language = miller_core.detect_language(str(py_file))

            if language:
                # Convert to relative Unix-style path (matches production behavior)
                relative_path = str(py_file.relative_to(test_workspace)).replace("\\", "/")
                storage_manager.add_file(relative_path, language, content, file_hash, len(content))

                # Also extract and add symbols (required for "fresh" state)
                result = miller_core.extract_file(content, language, relative_path)
                if result.symbols:
                    storage_manager.add_symbols_batch(result.symbols)

        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)

        # Fresh DB (with files AND symbols) should NOT need indexing
        assert await scanner.check_if_indexing_needed() is False

    @pytest.mark.asyncio
    async def test_check_if_indexing_needed_detects_deleted_files(self, test_workspace, storage_manager, vector_store):
        """Test that files deleted from disk (but still in DB) trigger re-indexing."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager
        from miller import miller_core
        import hashlib

        embeddings = EmbeddingManager(device="cpu")

        # First, index everything (simulate previous successful indexing)
        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)
        await scanner.index_workspace()

        # Verify it's up-to-date
        assert await scanner.check_if_indexing_needed() is False

        # Now delete a file from disk (but leave it in the DB - simulates offline deletion)
        deleted_file = test_workspace / "src" / "utils.py"
        deleted_file.unlink()

        # CRITICAL: check_if_indexing_needed() should detect this mismatch
        # Currently it only checks for NEW files, not DELETED files
        assert await scanner.check_if_indexing_needed() is True, \
            "Should detect files in DB that no longer exist on disk"

    @pytest.mark.asyncio
    async def test_check_indexing_needed_with_files_but_no_symbols(self, test_workspace, storage_manager, vector_store):
        """
        Regression test for Julie Bug #2: "Workspace already indexed: 0 symbols"

        Bug: check_if_indexing_needed() only checked if files existed in DB,
        but didn't verify symbols. This caused corrupted states (files but no
        symbols) to report "already indexed: 0 symbols" - a nonsensical message.

        Root cause: The check_if_indexing_needed() only queried files table,
        not symbols table. If indexing was interrupted after adding files but
        before adding symbols, the workspace would be in a broken state.

        Fix: Added symbol count check - if files exist but symbols == 0,
        return True (needs indexing) to recover from corrupted state.
        """
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager
        import hashlib
        from miller import miller_core

        embeddings = EmbeddingManager(device="cpu")

        # Simulate corrupted state: add files to DB but NO symbols
        for py_file in test_workspace.rglob("*.py"):
            content = py_file.read_text()
            file_hash = hashlib.sha256(content.encode()).hexdigest()
            language = miller_core.detect_language(str(py_file))

            if language:
                relative_path = str(py_file.relative_to(test_workspace)).replace("\\", "/")
                # Add file record but DON'T add symbols (simulating interrupted indexing)
                storage_manager.add_file(relative_path, language, content, file_hash, len(content))

        # Verify we have files but no symbols
        db_files = storage_manager.get_all_files()
        assert len(db_files) > 0, "Setup failed: should have files in DB"

        cursor = storage_manager.conn.execute("SELECT COUNT(*) FROM symbols")
        symbol_count = cursor.fetchone()[0]
        assert symbol_count == 0, "Setup failed: should have 0 symbols"

        # The bug: check_if_indexing_needed would return False here
        # (because files exist), causing "already indexed: 0 symbols"
        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)
        needs_indexing = await scanner.check_if_indexing_needed()

        # FIX: Should return True because symbol_count == 0 despite files existing
        assert needs_indexing is True, (
            "Bug regression: check_if_indexing_needed() should return True when "
            "files exist but symbols == 0 (corrupted state)"
        )

    @pytest.mark.asyncio
    async def test_check_if_indexing_needed_detects_stale_files_with_newer_non_code_indexed(
        self, test_workspace, storage_manager, vector_store
    ):
        """
        Bug: check_if_indexing_needed uses MAX-based heuristic that misses stale code files.

        Scenario:
        1. Index workspace (all files indexed)
        2. Modify a code file (content changes, mtime updates)
        3. A non-code file (.memories/test.json) is indexed with NEWER timestamp
        4. check_if_indexing_needed() should return True (code file is stale)

        Bug: The check compares MAX(last_indexed) to max(code_file_mtime).
        If a non-code file was indexed more recently than any code file was modified,
        the check incorrectly returns False, leaving code files stale.

        Root cause: Comparing global MAX values instead of per-file mtime vs last_indexed.
        """
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager
        import time

        embeddings = EmbeddingManager(device="cpu")

        # Step 1: Index everything
        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)
        await scanner.index_workspace()

        # Verify it's up-to-date
        assert await scanner.check_if_indexing_needed() is False

        # Step 2: Wait to ensure we're in a new second (filesystem timestamps often 1s resolution)
        # Then modify a code file (change content so hash is different)
        time.sleep(1.1)  # Ensure we cross a second boundary

        utils_file = test_workspace / "src" / "utils.py"
        original_content = utils_file.read_text()
        new_content = original_content + "\n# Modified for test\n"
        utils_file.write_text(new_content)

        # Step 3: Simulate watcher indexing a non-code file with NEWER timestamp
        # This simulates the watcher picking up a .memories file after code was modified
        memories_dir = test_workspace / ".memories"
        memories_dir.mkdir(exist_ok=True)
        memory_file = memories_dir / "test_checkpoint.json"
        memory_file.write_text('{"type": "checkpoint", "description": "test"}')

        # Manually add the memory file to DB with current timestamp
        # (simulating what the watcher would do)
        import json
        memory_content = memory_file.read_text()
        memory_hash = hashlib.sha256(memory_content.encode()).hexdigest()
        relative_memory_path = str(memory_file.relative_to(test_workspace)).replace("\\", "/")
        storage_manager.add_file(
            relative_memory_path, "json", memory_content, memory_hash, len(memory_content)
        )

        # Now the bug manifests:
        # - MAX(last_indexed) = timestamp from .memories file (very recent)
        # - max(code_file_mtime) = mtime of utils.py (slightly older)
        # - The check sees: max_file_mtime <= db_timestamp, returns False
        # - But utils.py HAS changed and needs re-indexing!

        # Step 4: check_if_indexing_needed() should detect the stale code file
        needs_indexing = await scanner.check_if_indexing_needed()

        assert needs_indexing is True, (
            "Bug: check_if_indexing_needed() missed stale code file. "
            "The MAX-based heuristic was fooled by a recently-indexed non-code file. "
            "utils.py was modified but not re-indexed because MAX(last_indexed) > max(code_mtime)."
        )

    @pytest.mark.asyncio
    async def test_index_workspace_returns_stats(self, test_workspace, storage_manager, vector_store):
        """Test that index_workspace returns indexing statistics."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)
        stats = await scanner.index_workspace()

        # Should return statistics
        assert "indexed" in stats
        assert "updated" in stats
        assert "skipped" in stats
        assert "deleted" in stats
        assert stats["indexed"] >= 3  # At least 3 .py files

    @pytest.mark.asyncio
    async def test_index_workspace_returns_total_symbols(self, test_workspace, storage_manager, vector_store):
        """
        Regression test: index_workspace must return total_symbols count.

        Bug: IndexStats didn't track symbol count, causing manage_workspace to show
        "0 symbols indexed" even after successful indexing.

        Root cause: IndexStats class only tracked file counts (indexed, updated, skipped)
        but not the total number of symbols extracted.

        Fix: Added total_symbols field to IndexStats, incremented during indexing.
        """
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)
        stats = await scanner.index_workspace()

        # total_symbols must be in stats
        assert "total_symbols" in stats, "IndexStats must include total_symbols"

        # Should have extracted symbols (test workspace has functions)
        assert stats["total_symbols"] > 0, (
            f"Bug regression: total_symbols is {stats['total_symbols']}, "
            "should be > 0 after indexing workspace with code files"
        )

    @pytest.mark.asyncio
    async def test_index_workspace_stores_symbols(self, test_workspace, storage_manager, vector_store):
        """Test that indexing actually stores symbols in database."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)
        await scanner.index_workspace()

        # Check that function symbols were stored (query by kind to avoid import collisions)
        cursor = storage_manager.conn.execute(
            "SELECT * FROM symbols WHERE name = ? AND kind = ?",
            ("hello", "function")
        )
        symbol = cursor.fetchone()
        assert symbol is not None, "Expected to find 'hello' function symbol"
        assert dict(symbol)["kind"] == "function"


class TestIncrementalIndexing:
    """Test incremental indexing behavior."""

    @pytest.mark.asyncio
    async def test_incremental_indexing_detects_new_files(self, test_workspace, storage_manager, vector_store):
        """Test that new files are detected and indexed."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        # Initial indexing
        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)
        stats1 = await scanner.index_workspace()

        # Add new file
        (test_workspace / "src" / "new.py").write_text("def new_func(): pass")

        # Re-index
        stats2 = await scanner.index_workspace()

        # Should detect and index new file
        assert stats2["indexed"] == 1
        assert stats2["skipped"] > 0  # Old files skipped

    @pytest.mark.asyncio
    async def test_incremental_indexing_detects_deleted_files(self, test_workspace, storage_manager, vector_store):
        """Test that deleted files are removed from database."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        # Initial indexing
        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)
        await scanner.index_workspace()

        # Delete a file
        deleted_file = test_workspace / "src" / "utils.py"
        deleted_file.unlink()

        # Re-index
        stats = await scanner.index_workspace()

        # Should detect deletion
        assert stats["deleted"] == 1

        # Verify symbols were removed from SQLite (CASCADE)
        # Paths are now workspace-qualified (e.g., "primary:src/utils.py")
        files = storage_manager.get_all_files()
        qualified_path = "primary:src/utils.py"
        assert not any(f["path"] == qualified_path for f in files)

        # CRITICAL: Verify symbols were also removed from LanceDB vector store
        # This is the bug - deletions only hit SQLite, not LanceDB
        results = vector_store.search(query="utils", method="text", limit=100)
        assert not any(r.get("file_path") == qualified_path for r in results), \
            f"Found stale vector for deleted file {qualified_path} in LanceDB"


class TestSingleFileIndexing:
    """Test single file indexing via _index_file method."""

    @pytest.mark.asyncio
    async def test_index_file_method_exists(self, test_workspace, storage_manager, vector_store):
        """Test that WorkspaceScanner has _index_file method for real-time re-indexing."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")
        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)

        # Method should exist
        assert hasattr(scanner, "_index_file"), "WorkspaceScanner must have _index_file method"
        assert callable(scanner._index_file), "_index_file must be callable"

    @pytest.mark.asyncio
    async def test_index_file_indexes_single_file(self, test_workspace, storage_manager, vector_store):
        """Test that _index_file correctly indexes a single file."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")
        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)

        # Create a new file
        new_file = test_workspace / "src" / "single.py"
        new_file.write_text("def single_function(): pass")

        # Index just this file
        result = await scanner._index_file(new_file)

        # Should succeed
        assert result is True

        # File should be in database (paths are now workspace-qualified)
        files = storage_manager.get_all_files()
        file_paths = [f["path"] for f in files]
        assert "primary:src/single.py" in file_paths

    @pytest.mark.asyncio
    async def test_index_file_updates_existing_file(self, test_workspace, storage_manager, vector_store):
        """Test that _index_file properly updates an already-indexed file."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")
        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)

        # Create and index a file
        test_file = test_workspace / "src" / "updatable.py"
        test_file.write_text("def original(): pass")
        await scanner._index_file(test_file)

        # Get original symbol count (paths are workspace-qualified)
        cursor = storage_manager.conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE file_path = ?", ("primary:src/updatable.py",)
        )
        original_count = cursor.fetchone()[0]

        # Modify file with more functions
        test_file.write_text("def updated(): pass\ndef another(): pass")
        await scanner._index_file(test_file)

        # Should have updated symbols (not duplicated)
        cursor = storage_manager.conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE file_path = ?", ("primary:src/updatable.py",)
        )
        new_count = cursor.fetchone()[0]

        # Should have 2 functions now, not original + 2
        assert new_count == 2

    @pytest.mark.asyncio
    async def test_index_file_returns_false_for_invalid(self, test_workspace, storage_manager, vector_store):
        """Test that _index_file returns False for non-existent or non-indexable files."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")
        scanner = WorkspaceScanner(test_workspace, storage_manager, embeddings, vector_store)

        # Non-existent file
        result = await scanner._index_file(test_workspace / "nonexistent.py")
        assert result is False
