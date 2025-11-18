"""
Test Miller's storage layer (SQLite).

Following TDD: These tests are written BEFORE implementing StorageManager.
They define the expected behavior and API.

Note: Search is handled by LanceDB, not SQLite FTS5.
"""

import pytest
import sqlite3
from pathlib import Path


@pytest.fixture
def storage():
    """Create in-memory storage and ensure cleanup."""
    from miller.storage import StorageManager
    s = StorageManager(":memory:")
    yield s
    s.close()


class TestDatabaseInitialization:
    """Test database connection and initialization."""

    def test_database_creates_in_memory(self):
        """Test that we can create an in-memory database."""
        from miller.storage import StorageManager

        storage = StorageManager(":memory:")
        assert storage is not None
        assert storage.conn is not None

    def test_database_enables_wal_mode(self):
        """Test that WAL mode is enabled (for concurrent access)."""
        from miller.storage import StorageManager

        storage = StorageManager(":memory:")

        # Verify WAL mode
        cursor = storage.conn.cursor()
        mode = cursor.execute("PRAGMA journal_mode").fetchone()[0]
        # SQLite returns "memory" for in-memory databases, "wal" for file-based
        # For in-memory, we just verify it doesn't error
        assert mode in ("memory", "wal", "WAL")

    def test_database_enables_foreign_keys(self):
        """Test that foreign key constraints are enabled."""
        from miller.storage import StorageManager

        storage = StorageManager(":memory:")

        cursor = storage.conn.cursor()
        fk_enabled = cursor.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk_enabled == 1


class TestSchemaCreation:
    """Test that all required tables are created."""

    def test_creates_files_table(self):
        """Test that files table is created."""
        from miller.storage import StorageManager

        storage = StorageManager(":memory:")

        cursor = storage.conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='files'"
        )
        assert cursor.fetchone() is not None

    def test_creates_symbols_table(self):
        """Test that symbols table is created."""
        from miller.storage import StorageManager

        storage = StorageManager(":memory:")

        cursor = storage.conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='symbols'"
        )
        assert cursor.fetchone() is not None

    def test_creates_identifiers_table(self):
        """Test that identifiers table is created."""
        from miller.storage import StorageManager

        storage = StorageManager(":memory:")

        cursor = storage.conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='identifiers'"
        )
        assert cursor.fetchone() is not None

    def test_creates_relationships_table(self):
        """Test that relationships table is created."""
        from miller.storage import StorageManager

        storage = StorageManager(":memory:")

        cursor = storage.conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='relationships'"
        )
        assert cursor.fetchone() is not None


class TestFileStorage:
    """Test storing and retrieving file records."""

    def test_add_file_stores_metadata(self):
        """Test that add_file stores file metadata."""
        from miller.storage import StorageManager

        storage = StorageManager(":memory:")

        storage.add_file(
            file_path="test.py",
            language="python",
            content="def hello(): pass",
            hash="abc123",
            size=18
        )

        # Verify file was stored
        cursor = storage.conn.cursor()
        row = cursor.execute(
            "SELECT path, language, hash, size FROM files WHERE path = ?",
            ("test.py",)
        ).fetchone()

        assert row is not None
        assert row[0] == "test.py"
        assert row[1] == "python"
        assert row[2] == "abc123"
        assert row[3] == 18

    def test_add_file_updates_existing(self):
        """Test that add_file updates if file already exists (INSERT OR REPLACE)."""
        from miller.storage import StorageManager

        storage = StorageManager(":memory:")

        # Add file first time
        storage.add_file("test.py", "python", "def hello(): pass", "hash1", 100)

        # Update with new hash
        storage.add_file("test.py", "python", "def hello(): return 42", "hash2", 200)

        # Verify updated
        cursor = storage.conn.cursor()
        row = cursor.execute(
            "SELECT hash, size FROM files WHERE path = ?", ("test.py",)
        ).fetchone()

        assert row[0] == "hash2"
        assert row[1] == 200


class TestSymbolStorage:
    """Test storing and retrieving symbols."""

    def test_add_symbols_from_extraction_result(self):
        """Test storing symbols extracted from Miller core."""
        from miller.storage import StorageManager
        from miller import miller_core

        storage = StorageManager(":memory:")

        # Extract symbols
        code = "def hello(): pass"
        result = miller_core.extract_file(code, "python", "test.py")

        # Add file first (foreign key requirement)
        storage.add_file("test.py", "python", code, "hash123", len(code))

        # Add symbols
        count = storage.add_symbols_batch(result.symbols)

        assert count == 1

        # Verify symbol stored
        sym = storage.get_symbol_by_name("hello")
        assert sym is not None
        assert sym['name'] == 'hello'
        assert sym['kind'] == 'function'
        assert sym['file_path'] == 'test.py'

    def test_add_symbols_with_all_fields(self):
        """Test that all symbol fields are stored correctly."""
        from miller.storage import StorageManager
        from miller import miller_core

        storage = StorageManager(":memory:")

        code = '''def greet(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"'''

        result = miller_core.extract_file(code, "python", "test.py")
        storage.add_file("test.py", "python", code, "hash123", len(code))
        storage.add_symbols_batch(result.symbols)

        sym = storage.get_symbol_by_name("greet")

        # Verify all fields
        assert sym['id'] is not None
        assert sym['name'] == 'greet'
        assert sym['kind'] == 'function'
        assert sym['language'] == 'python'
        assert sym['file_path'] == 'test.py'
        assert sym['signature'] is not None
        assert 'name' in sym['signature']  # Has parameter
        assert sym['start_line'] >= 1
        assert sym['end_line'] >= sym['start_line']


class TestCascadeDeletes:
    """Test that foreign key CASCADE deletes work."""

    def test_delete_file_cascades_to_symbols(self):
        """Test that deleting a file automatically deletes its symbols."""
        from miller.storage import StorageManager
        from miller import miller_core

        storage = StorageManager(":memory:")

        # Add file with symbols
        code = "def hello(): pass"
        result = miller_core.extract_file(code, "python", "test.py")
        storage.add_file("test.py", "python", code, "hash123", len(code))
        storage.add_symbols_batch(result.symbols)

        # Verify symbol exists
        sym = storage.get_symbol_by_name("hello")
        assert sym is not None

        # Delete file
        storage.delete_file("test.py")

        # Symbol should be gone (CASCADE)
        sym_after = storage.get_symbol_by_name("hello")
        assert sym_after is None


class TestIdentifierStorage:
    """Test storing and retrieving identifiers (usage references)."""

    def test_add_identifiers_from_extraction(self):
        """Test storing identifiers."""
        from miller.storage import StorageManager
        from miller import miller_core

        storage = StorageManager(":memory:")

        code = '''def greet():
    print("hello")'''
        result = miller_core.extract_file(code, "python", "test.py")
        storage.add_file("test.py", "python", code, "hash123", len(code))
        storage.add_symbols_batch(result.symbols)
        count = storage.add_identifiers_batch(result.identifiers)

        # Should have at least the print call
        assert count > 0

        # Query identifiers
        identifiers = storage.get_identifiers_by_file("test.py")
        assert len(identifiers) > 0
        assert any(i['name'] == 'print' for i in identifiers)


class TestRelationshipStorage:
    """Test storing and retrieving symbol relationships."""

    def test_add_relationships_for_inheritance(self):
        """Test storing relationships (e.g., class inheritance)."""
        from miller.storage import StorageManager
        from miller import miller_core

        storage = StorageManager(":memory:")

        code = """class Base:
    pass

class Derived(Base):
    pass"""
        result = miller_core.extract_file(code, "python", "test.py")
        storage.add_file("test.py", "python", code, "hash123", len(code))
        storage.add_symbols_batch(result.symbols)
        count = storage.add_relationships_batch(result.relationships)

        # Should have at least one "extends" relationship
        assert count > 0

        # Query relationships
        rels = storage.get_relationships_by_file("test.py")
        assert len(rels) > 0
        assert any(r['kind'] == 'extends' for r in rels)


class TestBulkOperations:
    """Test bulk insert performance."""

    def test_bulk_insert_100_symbols(self):
        """Test that bulk insert handles many symbols efficiently."""
        from miller.storage import StorageManager
        from miller import miller_core

        storage = StorageManager(":memory:")

        # Generate code with 100 functions
        code = "\n".join([f"def func_{i}(): pass" for i in range(100)])
        result = miller_core.extract_file(code, "python", "test.py")

        storage.add_file("test.py", "python", code, "hash123", len(code))
        count = storage.add_symbols_batch(result.symbols)

        assert count == 100

        # Verify all stored
        cursor = storage.conn.cursor()
        total = cursor.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        assert total == 100
