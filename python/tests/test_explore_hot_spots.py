"""
Tests for fast_explore hot_spots mode.

TDD: These tests define the expected behavior for finding high-impact symbols.
Hot spots = symbols most referenced across the codebase (high coupling indicators).
"""

import pytest
from miller.storage import StorageManager


class MockSymbol:
    """Mock symbol for testing."""

    def __init__(self, name: str, kind: str = "function", file_path: str = "src/main.py"):
        self.id = name
        self.name = name
        self.kind = kind
        self.file_path = file_path
        self.start_line = 1
        self.end_line = 10
        self.start_column = 0
        self.end_column = 0
        self.start_byte = 0
        self.end_byte = 100
        self.signature = f"def {name}()" if kind == "function" else f"class {name}"
        self.doc_comment = None
        self.parent_id = None
        self.language = "python"
        self.visibility = "public"
        self.semantic_group = None
        self.confidence = 1.0
        self.content_type = None
        self.code_context = None


class MockIdentifier:
    """Mock identifier for testing."""

    def __init__(self, name: str, file_path: str, line: int = 1, kind: str = "reference"):
        self.id = f"ident_{name}_{file_path}_{line}"
        self.name = name
        self.kind = kind
        self.language = "python"
        self.file_path = file_path
        self.start_line = line
        self.start_column = 0
        self.end_line = line
        self.end_column = len(name)
        self.start_byte = 0
        self.end_byte = len(name)
        self.containing_symbol_id = None
        self.target_symbol_id = None
        self.confidence = 1.0
        self.code_context = None


def _add_file(storage, file_path: str):
    """Helper to add a file to storage."""
    storage.add_file(file_path, "python", "# test", f"hash_{file_path}", 10)


class TestHotSpotsModeBasic:
    """Basic tests for hot_spots mode."""

    @pytest.mark.asyncio
    async def test_hot_spots_mode_accepted(self):
        """Test that mode='hot_spots' is a valid mode."""
        from miller.tools.explore import fast_explore

        # Should not raise ValueError("Unknown exploration mode")
        result = await fast_explore(mode="hot_spots")

        # Should return a dict (even if error or empty)
        assert isinstance(result, (dict, str))

    @pytest.mark.asyncio
    async def test_hot_spots_returns_expected_structure(self, tmp_path):
        """Test that hot_spots mode returns expected dict structure."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "src/main.py")
        _add_file(storage, "src/utils.py")

        storage.add_symbols_batch([
            MockSymbol("popular_func", "function", "src/utils.py"),
        ])

        # Add multiple references
        storage.add_identifiers_batch([
            MockIdentifier("popular_func", "src/main.py", 10),
            MockIdentifier("popular_func", "src/main.py", 20),
        ])

        result = await fast_explore(mode="hot_spots", storage=storage, limit=10)

        assert isinstance(result, dict)
        assert "hot_spots" in result
        assert "total_found" in result

        storage.close()

    @pytest.mark.asyncio
    async def test_hot_spots_ranks_by_reference_count(self, tmp_path):
        """Test that hot_spots returns symbols ranked by reference count."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "src/utils.py")
        _add_file(storage, "src/a.py")
        _add_file(storage, "src/b.py")
        _add_file(storage, "src/c.py")

        storage.add_symbols_batch([
            MockSymbol("very_popular", "function", "src/utils.py"),
            MockSymbol("somewhat_popular", "function", "src/utils.py"),
            MockSymbol("rarely_used", "function", "src/utils.py"),
        ])

        # very_popular: 5 references across 3 files
        storage.add_identifiers_batch([
            MockIdentifier("very_popular", "src/a.py", 1),
            MockIdentifier("very_popular", "src/a.py", 10),
            MockIdentifier("very_popular", "src/b.py", 5),
            MockIdentifier("very_popular", "src/b.py", 15),
            MockIdentifier("very_popular", "src/c.py", 8),
        ])

        # somewhat_popular: 2 references
        storage.add_identifiers_batch([
            MockIdentifier("somewhat_popular", "src/a.py", 20),
            MockIdentifier("somewhat_popular", "src/b.py", 25),
        ])

        # rarely_used: 1 reference
        storage.add_identifiers_batch([
            MockIdentifier("rarely_used", "src/a.py", 30),
        ])

        result = await fast_explore(mode="hot_spots", storage=storage, limit=10)

        hot_spots = result.get("hot_spots", [])
        names = [s.get("name") for s in hot_spots]

        # Should be ranked by popularity
        assert names.index("very_popular") < names.index("somewhat_popular")
        assert names.index("somewhat_popular") < names.index("rarely_used")

        # Should include ref_count
        very_popular_entry = next(s for s in hot_spots if s["name"] == "very_popular")
        assert very_popular_entry.get("ref_count", 0) >= 5

        storage.close()


class TestHotSpotsFiltering:
    """Tests for hot_spots filtering logic."""

    @pytest.mark.asyncio
    async def test_hot_spots_excludes_test_files(self, tmp_path):
        """Test that symbols in test files are excluded."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "tests/test_main.py")
        _add_file(storage, "src/utils.py")
        _add_file(storage, "src/main.py")

        storage.add_symbols_batch([
            MockSymbol("test_fixture", "function", "tests/test_main.py"),
            MockSymbol("prod_util", "function", "src/utils.py"),
        ])

        # Both get referenced
        storage.add_identifiers_batch([
            MockIdentifier("test_fixture", "src/main.py", 1),
            MockIdentifier("prod_util", "src/main.py", 2),
        ])

        result = await fast_explore(mode="hot_spots", storage=storage, limit=10)

        hot_names = [s.get("name") for s in result.get("hot_spots", [])]

        assert "test_fixture" not in hot_names
        assert "prod_util" in hot_names

        storage.close()

    @pytest.mark.asyncio
    async def test_hot_spots_only_project_symbols(self, tmp_path):
        """Test that only project-defined symbols are included (not builtins)."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "src/utils.py")
        _add_file(storage, "src/main.py")

        # Only add project symbol
        storage.add_symbols_batch([
            MockSymbol("my_helper", "function", "src/utils.py"),
        ])

        # Add identifiers including a "builtin" name that doesn't match any symbol
        storage.add_identifiers_batch([
            MockIdentifier("my_helper", "src/main.py", 1),
            MockIdentifier("len", "src/main.py", 2),  # builtin, no matching symbol
            MockIdentifier("print", "src/main.py", 3),  # builtin, no matching symbol
        ])

        result = await fast_explore(mode="hot_spots", storage=storage, limit=10)

        hot_names = [s.get("name") for s in result.get("hot_spots", [])]

        # Only project-defined symbols should appear
        assert "my_helper" in hot_names
        assert "len" not in hot_names
        assert "print" not in hot_names

        storage.close()

    @pytest.mark.asyncio
    async def test_hot_spots_includes_file_count(self, tmp_path):
        """Test that hot_spots includes file_count (coupling indicator)."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "src/utils.py")
        _add_file(storage, "src/a.py")
        _add_file(storage, "src/b.py")
        _add_file(storage, "src/c.py")

        storage.add_symbols_batch([
            MockSymbol("widely_used", "function", "src/utils.py"),
        ])

        # Referenced from 3 different files
        storage.add_identifiers_batch([
            MockIdentifier("widely_used", "src/a.py", 1),
            MockIdentifier("widely_used", "src/b.py", 1),
            MockIdentifier("widely_used", "src/c.py", 1),
        ])

        result = await fast_explore(mode="hot_spots", storage=storage, limit=10)

        hot_spots = result.get("hot_spots", [])
        assert len(hot_spots) > 0

        entry = hot_spots[0]
        assert "file_count" in entry
        assert entry["file_count"] >= 3

        storage.close()


class TestHotSpotsTextFormat:
    """Tests for hot_spots text output formatting."""

    @pytest.mark.asyncio
    async def test_hot_spots_text_format(self, tmp_path):
        """Test that hot_spots mode produces readable text output."""
        from miller.tools.explore_wrapper import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "src/utils.py")
        _add_file(storage, "src/main.py")

        storage.add_symbols_batch([
            MockSymbol("important_func", "function", "src/utils.py"),
        ])

        storage.add_identifiers_batch([
            MockIdentifier("important_func", "src/main.py", 1),
            MockIdentifier("important_func", "src/main.py", 10),
        ])

        result = await fast_explore(
            mode="hot_spots",
            storage=storage,
            limit=10,
            output_format="text"
        )

        # Text format should be a string
        assert isinstance(result, str)
        # Should mention hot spots
        assert "hot" in result.lower() or "impact" in result.lower() or "referenced" in result.lower()
        # Should include the function name
        assert "important_func" in result

        storage.close()
