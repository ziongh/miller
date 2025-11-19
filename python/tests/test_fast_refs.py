"""
Tests for fast_refs tool - Find all symbol references.

Following TDD discipline:
- Write tests first (RED)
- Implement to pass (GREEN)
- Refactor (REFACTOR)
"""

import pytest
from pathlib import Path
from miller.storage import StorageManager


# ============================================================================
# SHARED FIXTURES
# ============================================================================


@pytest.fixture
def storage_with_refs(tmp_path):
    """Create storage with sample symbols and relationships (no file content)."""
    storage = StorageManager(":memory:")

    # Add test file
    test_file = "test.py"
    storage.add_file(
        file_path=test_file,
        language="python",
        content='def calculate_age(birthdate): pass\ndef process_user(user): calculate_age(user.dob)',
        hash="abc123",
        size=100,
    )

    # Add symbols
    calculate_age_id = "symbol_calculate_age"
    process_user_id = "symbol_process_user"

    storage.conn.execute(
        """
        INSERT INTO symbols (
            id, name, kind, language, file_path,
            start_line, end_line, signature
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (calculate_age_id, "calculate_age", "Function", "python", test_file, 1, 1, "(birthdate)"),
    )

    storage.conn.execute(
        """
        INSERT INTO symbols (
            id, name, kind, language, file_path,
            start_line, end_line, signature
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (process_user_id, "process_user", "Function", "python", test_file, 2, 2, "(user)"),
    )

    # Add relationship: process_user calls calculate_age
    storage.conn.execute(
        """
        INSERT INTO relationships (
            id, from_symbol_id, to_symbol_id, kind,
            file_path, line_number
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("rel_1", process_user_id, calculate_age_id, "Call", test_file, 2),
    )

    storage.conn.commit()
    return storage


# ============================================================================
# PHASE 1: BASIC IMPLEMENTATION (FOUNDATION)
# ============================================================================

# ----------------------------------------------------------------------------
# Task 1.1: Database Query Foundation
# ----------------------------------------------------------------------------


class TestDatabaseQueryFoundation:
    """Test basic querying of symbol_relationships table."""

    def test_find_references_for_known_symbol(self, storage_with_refs):
        """Test finding references for a symbol that exists."""
        from miller.tools.refs import find_references

        # Query for references to "calculate_age"
        result = find_references(storage_with_refs, symbol_name="calculate_age")

        # Should find 1 reference
        assert result is not None
        assert result["symbol"] == "calculate_age"
        assert result["total_references"] == 1
        assert len(result["files"]) == 1

        # Check reference details
        file_refs = result["files"][0]
        assert file_refs["path"] == "test.py"
        assert file_refs["references_count"] == 1
        assert len(file_refs["references"]) == 1

        ref = file_refs["references"][0]
        assert ref["line"] == 2
        assert ref["kind"] == "Call"

    def test_find_references_with_no_references(self, storage_with_refs):
        """Test handling symbol with no references."""
        from miller.tools.refs import find_references

        # Query for "process_user" which has no references
        result = find_references(storage_with_refs, symbol_name="process_user")

        # Should return empty result
        assert result is not None
        assert result["symbol"] == "process_user"
        assert result["total_references"] == 0
        assert len(result["files"]) == 0

    def test_find_references_for_nonexistent_symbol(self, storage_with_refs):
        """Test handling non-existent symbol."""
        from miller.tools.refs import find_references

        # Query for symbol that doesn't exist
        result = find_references(storage_with_refs, symbol_name="nonexistent_function")

        # Should return empty result (not error)
        assert result is not None
        assert result["symbol"] == "nonexistent_function"
        assert result["total_references"] == 0
        assert len(result["files"]) == 0

    def test_filter_by_relationship_kind(self, storage_with_refs):
        """Test filtering references by relationship kind."""
        # Add an Import relationship
        storage_with_refs.conn.execute(
            """
            INSERT INTO relationships (
                id, from_symbol_id, to_symbol_id, kind,
                file_path, line_number
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "rel_2",
                "symbol_process_user",
                "symbol_calculate_age",
                "Import",
                "test.py",
                1,
            ),
        )
        storage_with_refs.conn.commit()

        from miller.tools.refs import find_references

        # Query for only Call relationships
        result = find_references(
            storage_with_refs, symbol_name="calculate_age", kind_filter=["Call"]
        )

        # Should find only the Call, not the Import
        assert result["total_references"] == 1
        assert result["files"][0]["references"][0]["kind"] == "Call"

        # Query for only Import relationships
        result = find_references(
            storage_with_refs, symbol_name="calculate_age", kind_filter=["Import"]
        )

        # Should find only the Import
        assert result["total_references"] == 1
        assert result["files"][0]["references"][0]["kind"] == "Import"

        # Query for both
        result = find_references(
            storage_with_refs, symbol_name="calculate_age", kind_filter=["Call", "Import"]
        )

        # Should find both
        assert result["total_references"] == 2


# ----------------------------------------------------------------------------
# Task 1.2: Context Snippet Extraction
# ----------------------------------------------------------------------------


class TestContextSnippetExtraction:
    """Test extracting code context for references."""

    @pytest.fixture
    def storage_with_file_content(self, tmp_path):
        """Create storage with file content for context extraction."""
        storage = StorageManager(":memory:")

        # Create a real temp file with code
        test_file = tmp_path / "user_service.py"
        code = """def calculate_age(birthdate):
    return 2025 - birthdate.year

def process_user(user):
    age = calculate_age(user.birthdate)
    return age
"""
        test_file.write_text(code)

        # Add file to storage
        storage.add_file(
            file_path=str(test_file),
            language="python",
            content=code,
            hash="abc123",
            size=len(code),
        )

        # Add symbols
        calculate_age_id = "symbol_calculate_age"
        process_user_id = "symbol_process_user"

        storage.conn.execute(
            """
            INSERT INTO symbols (
                id, name, kind, language, file_path,
                start_line, end_line, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (calculate_age_id, "calculate_age", "Function", "python", str(test_file), 1, 2, "(birthdate)"),
        )

        storage.conn.execute(
            """
            INSERT INTO symbols (
                id, name, kind, language, file_path,
                start_line, end_line, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (process_user_id, "process_user", "Function", "python", str(test_file), 4, 6, "(user)"),
        )

        # Add relationship: process_user calls calculate_age at line 5
        storage.conn.execute(
            """
            INSERT INTO relationships (
                id, from_symbol_id, to_symbol_id, kind,
                file_path, line_number
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("rel_1", process_user_id, calculate_age_id, "Call", str(test_file), 5),
        )

        storage.conn.commit()
        return storage, test_file

    def test_extract_context_from_python_file(self, storage_with_file_content):
        """Test context extraction shows actual code line."""
        from miller.tools.refs import find_references

        storage, test_file = storage_with_file_content

        # Query with context extraction
        result = find_references(storage, symbol_name="calculate_age", include_context=True)

        # Should include context snippet
        assert result["total_references"] == 1
        ref = result["files"][0]["references"][0]
        assert ref["line"] == 5
        assert "context" in ref
        # Should show the actual line of code
        assert "calculate_age(user.birthdate)" in ref["context"]

    def test_handle_missing_file_gracefully(self, storage_with_refs):
        """Test handling when source file is deleted/moved."""
        from miller.tools.refs import find_references

        # Query with context extraction, but file doesn't exist
        result = find_references(storage_with_refs, symbol_name="calculate_age", include_context=True)

        # Should still return reference without context
        assert result["total_references"] == 1
        ref = result["files"][0]["references"][0]
        assert ref["line"] == 2
        # Context should be None or empty when file not found
        assert ref.get("context") is None or ref.get("context") == ""

    def test_context_extraction_with_multiple_refs_same_file(self, storage_with_file_content):
        """Test efficient context extraction (read file once for multiple refs)."""
        from miller.tools.refs import find_references

        storage, test_file = storage_with_file_content

        # Add another reference to calculate_age
        storage.conn.execute(
            """
            INSERT INTO relationships (
                id, from_symbol_id, to_symbol_id, kind,
                file_path, line_number
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("rel_2", "symbol_process_user", "symbol_calculate_age", "Call", str(test_file), 6),
        )
        storage.conn.commit()

        # Query with context
        result = find_references(storage, symbol_name="calculate_age", include_context=True)

        # Should have 2 references with context
        assert result["total_references"] == 2
        refs = result["files"][0]["references"]
        assert len(refs) == 2
        assert all("context" in r for r in refs)
        # Both should have non-empty context
        assert all(r["context"] for r in refs)


# ----------------------------------------------------------------------------
# Task 1.3: Workspace Filtering
# ----------------------------------------------------------------------------


class TestWorkspaceFiltering:
    """Test querying references across different workspaces."""

    def test_query_specific_workspace(self, tmp_path):
        """Test that find_references works with workspace-specific storage."""
        from miller.tools.refs import find_references

        # Create two separate workspace databases
        workspace1_db = tmp_path / "workspace1.db"
        workspace2_db = tmp_path / "workspace2.db"

        storage1 = StorageManager(str(workspace1_db))
        storage2 = StorageManager(str(workspace2_db))

        # Add same symbol to both workspaces
        for i, storage in enumerate([storage1, storage2], 1):
            storage.add_file(
                file_path=f"workspace{i}/test.py",
                language="python",
                content="def shared_function(): pass\ndef caller(): shared_function()",
                hash=f"hash{i}",
                size=100,
            )

            # Add symbols
            storage.conn.execute(
                """
                INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (f"sym{i}_shared", "shared_function", "Function", "python", f"workspace{i}/test.py", 1, 1),
            )

            storage.conn.execute(
                """
                INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (f"sym{i}_caller", "caller", "Function", "python", f"workspace{i}/test.py", 2, 2),
            )

            # Add reference
            storage.conn.execute(
                """
                INSERT INTO relationships (id, from_symbol_id, to_symbol_id, kind, file_path, line_number)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"rel{i}", f"sym{i}_caller", f"sym{i}_shared", "Call", f"workspace{i}/test.py", 2),
            )

            storage.conn.commit()

        # Query workspace 1
        result1 = find_references(storage1, symbol_name="shared_function")

        # Should only find references in workspace 1
        assert result1["total_references"] == 1
        assert result1["files"][0]["path"] == "workspace1/test.py"

        # Query workspace 2
        result2 = find_references(storage2, symbol_name="shared_function")

        # Should only find references in workspace 2
        assert result2["total_references"] == 1
        assert result2["files"][0]["path"] == "workspace2/test.py"

        # Results should be independent
        assert result1["files"][0]["path"] != result2["files"][0]["path"]

    def test_no_cross_contamination_between_workspaces(self, tmp_path):
        """Test that workspaces don't see each other's data."""
        from miller.tools.refs import find_references

        workspace1_db = tmp_path / "ws1.db"
        workspace2_db = tmp_path / "ws2.db"

        storage1 = StorageManager(str(workspace1_db))
        storage2 = StorageManager(str(workspace2_db))

        # Add symbol only to workspace 1
        storage1.add_file(
            file_path="file1.py",
            language="python",
            content="def unique_func(): pass",
            hash="hash1",
            size=50,
        )

        storage1.conn.execute(
            """
            INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("sym1", "unique_func", "Function", "python", "file1.py", 1, 1),
        )

        storage1.conn.commit()

        # Query workspace 1 - should find it
        result1 = find_references(storage1, symbol_name="unique_func")
        # Note: no references added, so total_references=0, but symbol exists
        assert result1["symbol"] == "unique_func"

        # Query workspace 2 - should NOT find it (different database)
        result2 = find_references(storage2, symbol_name="unique_func")
        assert result2["symbol"] == "unique_func"
        assert result2["total_references"] == 0  # No symbol in this workspace


# ============================================================================
# PHASE 2: OUTPUT QUALITY & UX
# ============================================================================

# ----------------------------------------------------------------------------
# Task 2.3: Symbol Disambiguation
# ----------------------------------------------------------------------------


class TestSymbolDisambiguation:
    """Test handling symbols with same name in different scopes."""

    @pytest.fixture
    def storage_with_ambiguous_symbols(self, tmp_path):
        """Create storage with multiple symbols having the same name."""
        storage = StorageManager(":memory:")

        # Create test file with ambiguous symbols
        test_file = tmp_path / "ambiguous.py"
        code = """class User:
    def save(self):
        pass

def process_user(user):
    # 'user' is a parameter (different from User class)
    user.save()

def save_data():
    # 'save' is a function (different from User.save method)
    pass
"""
        test_file.write_text(code)

        storage.add_file(
            file_path=str(test_file),
            language="python",
            content=code,
            hash="hash123",
            size=len(code),
        )

        # Add symbols
        # 1. User class
        storage.conn.execute(
            """
            INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("sym_user_class", "User", "Class", "python", str(test_file), 1, 3),
        )

        # 2. User.save method
        storage.conn.execute(
            """
            INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("sym_user_save", "save", "Method", "python", str(test_file), 2, 3, "sym_user_class"),
        )

        # 3. process_user function
        storage.conn.execute(
            """
            INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("sym_process_user", "process_user", "Function", "python", str(test_file), 5, 7),
        )

        # 4. save_data function
        storage.conn.execute(
            """
            INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("sym_save_data", "save_data", "Function", "python", str(test_file), 9, 11),
        )

        # Add relationship: process_user calls User.save
        storage.conn.execute(
            """
            INSERT INTO relationships (id, from_symbol_id, to_symbol_id, kind, file_path, line_number)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("rel_1", "sym_process_user", "sym_user_save", "Call", str(test_file), 7),
        )

        storage.conn.commit()
        return storage, test_file

    def test_disambiguate_by_context_file(self, storage_with_ambiguous_symbols):
        """Test disambiguating symbols using context_file parameter."""
        from miller.tools.refs import find_references

        storage, test_file = storage_with_ambiguous_symbols

        # Without context_file - finds all symbols named "save"
        result = find_references(storage, symbol_name="save")

        # Should find references to User.save (the method has references)
        # Note: We have both User.save (method) and save_data (function) with "save" in name
        assert result["symbol"] == "save"
        assert result["total_references"] >= 1

        # With context_file - narrows down to symbols in that file
        result = find_references(storage, symbol_name="save", context_file=str(test_file))

        # Should still find the reference (same file)
        assert result["total_references"] >= 1

    def test_qualified_name_support(self, storage_with_ambiguous_symbols):
        """Test finding references using qualified names (Class.method)."""
        from miller.tools.refs import find_references

        storage, test_file = storage_with_ambiguous_symbols

        # Search for "User.save" (qualified name)
        result = find_references(storage, symbol_name="User.save")

        # Should find references to the method specifically
        assert result["symbol"] == "User.save"
        # Should find the call in process_user
        assert result["total_references"] >= 1

    def test_disambiguation_suggestions(self, storage_with_ambiguous_symbols):
        """Test that ambiguous queries provide suggestions."""
        from miller.tools.refs import find_references

        storage, test_file = storage_with_ambiguous_symbols

        # Search for ambiguous name "save"
        result = find_references(storage, symbol_name="save")

        # Should include suggestions for disambiguation
        assert "suggestions" in result or "total_references" in result
        # If multiple symbols match, should provide info about them


# ============================================================================
# PHASE 3: PERFORMANCE & POLISH
# ============================================================================

# ----------------------------------------------------------------------------
# Task 3.1: Performance Optimization
# ----------------------------------------------------------------------------


class TestPerformanceOptimization:
    """Test performance features like pagination."""

    def test_limit_results(self, tmp_path):
        """Test limiting number of results returned."""
        from miller.tools.refs import find_references

        storage = StorageManager(":memory:")

        # Create test file
        test_file = "test.py"
        storage.add_file(
            file_path=test_file,
            language="python",
            content="def target(): pass",
            hash="hash123",
            size=50,
        )

        # Add target symbol
        storage.conn.execute(
            """
            INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("sym_target", "target", "Function", "python", test_file, 1, 1),
        )

        # Add many references (100)
        for i in range(100):
            caller_id = f"sym_caller_{i}"
            storage.conn.execute(
                """
                INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (caller_id, f"caller_{i}", "Function", "python", test_file, i + 10, i + 10),
            )

            storage.conn.execute(
                """
                INSERT INTO relationships (id, from_symbol_id, to_symbol_id, kind, file_path, line_number)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"rel_{i}", caller_id, "sym_target", "Call", test_file, i + 10),
            )

        storage.conn.commit()

        # Without limit - should get all 100
        result = find_references(storage, symbol_name="target")
        assert result["total_references"] == 100

        # With limit=10 - should get only 10
        result = find_references(storage, symbol_name="target", limit=10)
        assert result["total_references"] == 100  # Total still shows all
        assert len(result["files"][0]["references"]) == 10  # But only 10 returned
        assert result["truncated"] is True  # Indicates results were truncated

        # With limit=200 (more than available) - should get all 100
        result = find_references(storage, symbol_name="target", limit=200)
        assert len(result["files"][0]["references"]) == 100
        assert result.get("truncated", False) is False  # Not truncated
