"""
Tests for fast_explore dead_code mode.

TDD: These tests define the expected behavior for finding unused/dead code.
Dead code = symbols not referenced by any other symbol (excluding tests/private).
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


class MockRelationship:
    """Mock relationship for testing."""

    def __init__(self, from_id: str, to_id: str, kind: str = "calls"):
        self.id = f"rel_{from_id}_{to_id}"
        self.from_symbol_id = from_id
        self.to_symbol_id = to_id
        self.kind = kind
        self.file_path = "src/main.py"
        self.line_number = 1
        self.confidence = 1.0
        self.metadata = None


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


class TestDeadCodeModeBasic:
    """Basic tests for dead_code mode."""

    @pytest.mark.asyncio
    async def test_dead_code_mode_accepted(self):
        """Test that mode='dead_code' is a valid mode."""
        from miller.tools.explore import fast_explore

        # Should not raise ValueError("Unknown exploration mode")
        # May return empty result or error about missing storage, but mode is valid
        result = await fast_explore(mode="dead_code")

        # Should return a dict (even if error or empty)
        assert isinstance(result, (dict, str))

    @pytest.mark.asyncio
    async def test_dead_code_returns_expected_structure(self, tmp_path):
        """Test that dead_code mode returns expected dict structure."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Add file first, then symbols
        _add_file(storage, "src/main.py")
        storage.add_symbols_batch([
            MockSymbol("orphan_func", "function"),
            MockSymbol("OrphanClass", "class"),
        ])

        result = await fast_explore(mode="dead_code", storage=storage, limit=10)

        assert isinstance(result, dict)
        assert "dead_code" in result or "symbols" in result
        assert "total_found" in result

        storage.close()

    @pytest.mark.asyncio
    async def test_dead_code_finds_unreferenced_symbols(self, tmp_path):
        """Test that dead_code mode finds symbols with no references."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Add file first
        _add_file(storage, "src/main.py")

        # Add symbols
        storage.add_symbols_batch([
            MockSymbol("used_func", "function"),
            MockSymbol("unused_func", "function"),
            MockSymbol("main", "function"),  # calls used_func
        ])

        # main calls used_func, but nobody calls unused_func
        storage.add_relationships_batch([
            MockRelationship("main", "used_func", "calls"),
        ])

        result = await fast_explore(mode="dead_code", storage=storage, limit=10)

        # Should find unused_func as dead code
        dead_names = [s.get("name") for s in result.get("dead_code", result.get("symbols", []))]
        assert "unused_func" in dead_names
        assert "used_func" not in dead_names

        storage.close()


class TestDeadCodeFiltering:
    """Tests for dead_code filtering logic."""

    @pytest.mark.asyncio
    async def test_dead_code_excludes_test_files(self, tmp_path):
        """Test that symbols in test files are excluded from dead code detection."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Add files first
        _add_file(storage, "tests/test_main.py")
        _add_file(storage, "src/main.py")

        # Add symbols - one in test file, one in production
        storage.add_symbols_batch([
            MockSymbol("test_helper", "function", "tests/test_main.py"),
            MockSymbol("prod_unused", "function", "src/main.py"),
        ])

        result = await fast_explore(mode="dead_code", storage=storage, limit=10)

        dead_names = [s.get("name") for s in result.get("dead_code", result.get("symbols", []))]

        # test_helper should NOT be flagged (it's in test file)
        assert "test_helper" not in dead_names
        # prod_unused SHOULD be flagged
        assert "prod_unused" in dead_names

        storage.close()

    @pytest.mark.asyncio
    async def test_dead_code_excludes_private_symbols(self, tmp_path):
        """Test that private symbols (starting with _) are excluded."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "src/main.py")

        storage.add_symbols_batch([
            MockSymbol("_private_helper", "function"),
            MockSymbol("__dunder_method", "method"),
            MockSymbol("public_unused", "function"),
        ])

        result = await fast_explore(mode="dead_code", storage=storage, limit=10)

        dead_names = [s.get("name") for s in result.get("dead_code", result.get("symbols", []))]

        # Private symbols should NOT be flagged
        assert "_private_helper" not in dead_names
        assert "__dunder_method" not in dead_names
        # Public unused SHOULD be flagged
        assert "public_unused" in dead_names

        storage.close()

    @pytest.mark.asyncio
    async def test_dead_code_excludes_test_prefixed_names(self, tmp_path):
        """Test that symbols starting with 'test_' or 'Test' are excluded."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "src/utils.py")

        storage.add_symbols_batch([
            MockSymbol("test_something", "function", "src/utils.py"),
            MockSymbol("TestCase", "class", "src/utils.py"),
            MockSymbol("regular_unused", "function", "src/utils.py"),
        ])

        result = await fast_explore(mode="dead_code", storage=storage, limit=10)

        dead_names = [s.get("name") for s in result.get("dead_code", result.get("symbols", []))]

        assert "test_something" not in dead_names
        assert "TestCase" not in dead_names
        assert "regular_unused" in dead_names

        storage.close()

    @pytest.mark.asyncio
    async def test_dead_code_only_functions_and_classes(self, tmp_path):
        """Test that only functions and classes are considered for dead code."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "src/main.py")

        storage.add_symbols_batch([
            MockSymbol("unused_func", "function"),
            MockSymbol("UnusedClass", "class"),
            MockSymbol("some_variable", "variable"),
            MockSymbol("CONSTANT", "constant"),
        ])

        result = await fast_explore(mode="dead_code", storage=storage, limit=10)

        dead_names = [s.get("name") for s in result.get("dead_code", result.get("symbols", []))]

        # Functions and classes should be included
        assert "unused_func" in dead_names
        assert "UnusedClass" in dead_names
        # Variables and constants should NOT be included
        assert "some_variable" not in dead_names
        assert "CONSTANT" not in dead_names

        storage.close()


class TestDeadCodeWithIdentifiers:
    """Tests for dead_code considering identifier references."""

    @pytest.mark.asyncio
    async def test_dead_code_considers_identifier_references(self, tmp_path):
        """Test that symbols referenced via identifiers are not dead."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "src/utils.py")
        _add_file(storage, "src/main.py")

        storage.add_symbols_batch([
            MockSymbol("referenced_func", "function", "src/utils.py"),
            MockSymbol("truly_unused", "function", "src/utils.py"),
        ])

        # referenced_func is mentioned in another file (identifier reference)
        storage.add_identifiers_batch([
            MockIdentifier("referenced_func", "src/main.py", 10),
        ])

        result = await fast_explore(mode="dead_code", storage=storage, limit=10)

        dead_names = [s.get("name") for s in result.get("dead_code", result.get("symbols", []))]

        # referenced_func has identifier reference - not dead
        assert "referenced_func" not in dead_names
        # truly_unused has no references - dead
        assert "truly_unused" in dead_names

        storage.close()

    @pytest.mark.asyncio
    async def test_dead_code_ignores_self_references(self, tmp_path):
        """Test that self-references (same file) don't prevent dead code detection."""
        from miller.tools.explore import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "src/lonely.py")

        storage.add_symbols_batch([
            MockSymbol("self_ref_only", "function", "src/lonely.py"),
        ])

        # Only referenced in the same file where it's defined
        storage.add_identifiers_batch([
            MockIdentifier("self_ref_only", "src/lonely.py", 10),
        ])

        result = await fast_explore(mode="dead_code", storage=storage, limit=10)

        dead_names = [s.get("name") for s in result.get("dead_code", result.get("symbols", []))]

        # Self-reference doesn't count - still dead
        assert "self_ref_only" in dead_names

        storage.close()


class TestDeadCodeTextFormat:
    """Tests for dead_code text output formatting."""

    @pytest.mark.asyncio
    async def test_dead_code_text_format(self, tmp_path):
        """Test that dead_code mode produces readable text output."""
        from miller.tools.explore_wrapper import fast_explore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_file(storage, "src/orphan.py")

        storage.add_symbols_batch([
            MockSymbol("orphan_function", "function", "src/orphan.py"),
        ])

        result = await fast_explore(
            mode="dead_code",
            storage=storage,
            limit=10,
            output_format="text"
        )

        # Text format should be a string
        assert isinstance(result, str)
        # Should mention dead code
        assert "dead" in result.lower() or "unused" in result.lower() or "orphan" in result.lower()
        # Should include the function name
        assert "orphan_function" in result

        storage.close()
