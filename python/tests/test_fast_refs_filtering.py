"""
Tests for fast_refs tool - Filtering and context extraction (Part 2).

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
def storage_with_file_content(tmp_path):
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
# Task 1.2: Context Snippet Extraction
# ----------------------------------------------------------------------------


class TestContextSnippetExtraction:
    """Test extracting code context for references."""

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
