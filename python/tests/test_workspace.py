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

    def test_scanner_initializes_with_required_components(self, test_workspace):
        """Test that scanner requires storage, embeddings, and vector_store."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(
            workspace_root=test_workspace,
            storage=storage,
            embeddings=embeddings,
            vector_store=vector_store
        )

        assert scanner.workspace_root == test_workspace
        assert scanner.storage == storage


class TestFileDiscovery:
    """Test workspace file discovery and filtering."""

    def test_walk_directory_finds_python_files(self, test_workspace):
        """Test that _walk_directory finds all Python source files."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)
        files = scanner._walk_directory()

        # Should find .py files
        py_files = [f for f in files if f.suffix == ".py"]
        assert len(py_files) >= 3  # main.py, utils.py, test_main.py

    def test_walk_directory_respects_gitignore(self, test_workspace):
        """Test that ignored directories are excluded."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)
        files = scanner._walk_directory()

        # Should NOT include files from node_modules
        assert not any("node_modules" in str(f) for f in files)

    def test_walk_directory_filters_by_supported_languages(self, test_workspace):
        """Test that only supported file types are returned."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        # Add an unsupported file type
        (test_workspace / "data.xyz").write_text("unsupported")

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)
        files = scanner._walk_directory()

        # Should not include unsupported file
        assert not any(f.suffix == ".xyz" for f in files)


class TestChangeDetection:
    """Test file change detection for incremental indexing."""

    def test_needs_indexing_for_new_file(self, test_workspace):
        """Test that new files (not in DB) need indexing."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)

        # File not in DB
        file_path = test_workspace / "src" / "main.py"
        db_files_map = {f["path"]: f for f in storage.get_all_files()}
        assert scanner._needs_indexing(file_path, db_files_map) is True

    def test_needs_indexing_for_changed_file(self, test_workspace):
        """Test that files with changed content need re-indexing."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        # Index file with original content
        file_path = test_workspace / "src" / "main.py"
        original_content = file_path.read_text()
        original_hash = hashlib.sha256(original_content.encode()).hexdigest()

        # Use relative path to match production behavior
        relative_path = str(file_path.relative_to(test_workspace)).replace("\\", "/")
        storage.add_file(
            relative_path, "python", original_content, original_hash, len(original_content)
        )

        # Modify file
        new_content = "def new_function(): pass"
        file_path.write_text(new_content)

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)

        # Should need re-indexing (hash changed)
        db_files_map = {f["path"]: f for f in storage.get_all_files()}
        assert scanner._needs_indexing(file_path, db_files_map) is True

    def test_skips_unchanged_file(self, test_workspace):
        """Test that unchanged files are skipped."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        # Index file
        file_path = test_workspace / "src" / "main.py"
        content = file_path.read_text()
        file_hash = hashlib.sha256(content.encode()).hexdigest()

        # Use relative path to match production behavior
        relative_path = str(file_path.relative_to(test_workspace)).replace("\\", "/")
        storage.add_file(relative_path, "python", content, file_hash, len(content))

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)

        # Should NOT need re-indexing (hash matches)
        db_files_map = {f["path"]: f for f in storage.get_all_files()}
        assert scanner._needs_indexing(file_path, db_files_map) is False


class TestWorkspaceIndexing:
    """Test full workspace indexing workflow."""

    @pytest.mark.asyncio
    async def test_check_if_indexing_needed_empty_db(self, test_workspace):
        """Test that empty database triggers indexing."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)

        # Empty DB should need indexing
        assert await scanner.check_if_indexing_needed() is True

    @pytest.mark.asyncio
    async def test_check_if_indexing_needed_fresh_db(self, test_workspace):
        """Test that fresh database (all files indexed) skips indexing."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore
        from miller import miller_core

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        # Index all files manually first (using relative paths like production code)
        for py_file in test_workspace.rglob("*.py"):
            if "node_modules" in str(py_file):
                continue

            content = py_file.read_text()
            file_hash = hashlib.sha256(content.encode()).hexdigest()
            language = miller_core.detect_language(str(py_file))

            if language:
                # Convert to relative Unix-style path (matches production behavior)
                relative_path = str(py_file.relative_to(test_workspace)).replace("\\", "/")
                storage.add_file(relative_path, language, content, file_hash, len(content))

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)

        # Fresh DB should NOT need indexing
        assert await scanner.check_if_indexing_needed() is False

    @pytest.mark.asyncio
    async def test_index_workspace_returns_stats(self, test_workspace):
        """Test that index_workspace returns indexing statistics."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)
        stats = await scanner.index_workspace()

        # Should return statistics
        assert "indexed" in stats
        assert "updated" in stats
        assert "skipped" in stats
        assert "deleted" in stats
        assert stats["indexed"] >= 3  # At least 3 .py files

    @pytest.mark.asyncio
    async def test_index_workspace_stores_symbols(self, test_workspace):
        """Test that indexing actually stores symbols in database."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)
        await scanner.index_workspace()

        # Check that symbols were stored
        symbol = storage.get_symbol_by_name("hello")
        assert symbol is not None
        assert symbol["kind"] == "function"


class TestIncrementalIndexing:
    """Test incremental indexing behavior."""

    @pytest.mark.asyncio
    async def test_incremental_indexing_detects_new_files(self, test_workspace):
        """Test that new files are detected and indexed."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        # Initial indexing
        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)
        stats1 = await scanner.index_workspace()

        # Add new file
        (test_workspace / "src" / "new.py").write_text("def new_func(): pass")

        # Re-index
        stats2 = await scanner.index_workspace()

        # Should detect and index new file
        assert stats2["indexed"] == 1
        assert stats2["skipped"] > 0  # Old files skipped

    @pytest.mark.asyncio
    async def test_incremental_indexing_detects_deleted_files(self, test_workspace):
        """Test that deleted files are removed from database."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        # Initial indexing
        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)
        await scanner.index_workspace()

        # Delete a file
        deleted_file = test_workspace / "src" / "utils.py"
        deleted_file.unlink()

        # Re-index
        stats = await scanner.index_workspace()

        # Should detect deletion
        assert stats["deleted"] == 1

        # Verify symbols were removed (CASCADE)
        files = storage.get_all_files()
        assert not any(f["path"] == str(deleted_file) for f in files)
