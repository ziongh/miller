"""
Tests for fast_refs tool - Basic reference finding (Part 1).

Following TDD discipline:
- Write tests first (RED)
- Implement to pass (GREEN)
- Refactor (REFACTOR)
"""

import pytest
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


# ============================================================================
# Task 1.3: Workspace Filtering
# ============================================================================


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
# BUG FIX: Class Instantiation References (identifiers table)
# ============================================================================


class TestIdentifierBasedReferences:
    """Test finding references from identifiers table (not just relationships).

    Bug: fast_refs only queries relationships table, missing class instantiations
    and other identifier usages that aren't explicit function calls.

    Root cause: relationships table only contains function/method calls detected
    by tree-sitter. Class instantiations like `StorageManager()` are stored in
    identifiers table as "Reference" kind entries.
    """

    @pytest.fixture
    def storage_with_identifiers(self, tmp_path):
        """Create storage with class symbol and identifier usages (no relationships)."""
        storage = StorageManager(":memory:")

        # Add test files
        storage.add_file(
            file_path="models/user.py",
            language="python",
            content="class UserService:\n    pass",
            hash="abc123",
            size=50,
        )
        storage.add_file(
            file_path="handlers/api.py",
            language="python",
            content="from models.user import UserService\n\ndef get_user():\n    svc = UserService()\n    return svc.get()",
            hash="def456",
            size=100,
        )

        # Add the class symbol (definition)
        user_service_id = "symbol_user_service"
        storage.conn.execute(
            """
            INSERT INTO symbols (
                id, name, kind, language, file_path,
                start_line, end_line, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_service_id, "UserService", "Class", "python", "models/user.py", 1, 2, "class UserService"),
        )

        # Add the containing function symbol (needed for FK constraint)
        storage.conn.execute(
            """
            INSERT INTO symbols (
                id, name, kind, language, file_path,
                start_line, end_line, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("symbol_get_user", "get_user", "Function", "python", "handlers/api.py", 3, 5, "def get_user()"),
        )

        # Add identifier entries (usages of UserService in other files)
        # This is what tree-sitter captures for class instantiation
        storage.conn.execute(
            """
            INSERT INTO identifiers (
                id, name, kind, language, file_path,
                start_line, start_col, end_line, end_col,
                containing_symbol_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ident_import",
                "UserService",
                "Reference",  # Import reference
                "python",
                "handlers/api.py",
                1,  # line 1: from models.user import UserService
                0,
                1,
                11,
                None,  # module-level, no containing symbol
            ),
        )

        storage.conn.execute(
            """
            INSERT INTO identifiers (
                id, name, kind, language, file_path,
                start_line, start_col, end_line, end_col,
                containing_symbol_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ident_instantiation",
                "UserService",
                "Reference",  # Class instantiation
                "python",
                "handlers/api.py",
                4,  # line 4: svc = UserService()
                10,
                4,
                21,
                "symbol_get_user",  # inside get_user function
            ),
        )

        # NOTE: We intentionally DO NOT add any relationships entries
        # This simulates the real-world case where class instantiation
        # is not captured as a "Call" relationship

        storage.conn.commit()
        return storage

    def test_find_class_instantiation_references(self, storage_with_identifiers):
        """Test that find_references finds class usages from identifiers table.

        This test should FAIL with current implementation (only queries relationships)
        and PASS after fix (also queries identifiers).
        """
        from miller.tools.refs import find_references

        # Query for references to UserService class
        result = find_references(storage_with_identifiers, symbol_name="UserService")

        # Should find 2 references (import + instantiation) from identifiers table
        assert result is not None
        assert result["symbol"] == "UserService"
        assert result["total_references"] == 2, (
            f"Expected 2 references from identifiers table, got {result['total_references']}. "
            "Bug: find_references only queries relationships table."
        )

        # Both references should be in handlers/api.py
        assert len(result["files"]) == 1
        assert result["files"][0]["path"] == "handlers/api.py"
        assert result["files"][0]["references_count"] == 2

    def test_find_references_combines_relationships_and_identifiers(self, storage_with_identifiers):
        """Test that references from both tables are combined without duplicates."""
        from miller.tools.refs import find_references

        # Add a relationship entry for the same location as an identifier
        # (some extractors might capture both)
        # Note: symbol_get_user already exists from fixture setup

        storage_with_identifiers.conn.execute(
            """
            INSERT INTO relationships (
                id, from_symbol_id, to_symbol_id, kind,
                file_path, line_number
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("rel_1", "symbol_get_user", "symbol_user_service", "Call", "handlers/api.py", 4),
        )
        storage_with_identifiers.conn.commit()

        result = find_references(storage_with_identifiers, symbol_name="UserService")

        # Should find 3 references total:
        # - 2 from identifiers (import line 1 + instantiation line 4)
        # - 1 from relationships (call on line 4)
        # Note: line 4 appears in both tables, but they're different reference types
        # so both should be included (or deduplicated by file:line if we choose)
        assert result["total_references"] >= 2, (
            f"Expected at least 2 references, got {result['total_references']}"
        )

    def test_identifier_references_respect_kind_filter(self, storage_with_identifiers):
        """Test that kind_filter applies to identifier-based references."""
        from miller.tools.refs import find_references

        # Query with kind filter that matches identifier kinds
        result = find_references(
            storage_with_identifiers,
            symbol_name="UserService",
            kind_filter=["Reference"],
        )

        # Should find the 2 Reference-kind identifiers
        assert result["total_references"] == 2

        # Query with kind filter that doesn't match
        result = find_references(
            storage_with_identifiers,
            symbol_name="UserService",
            kind_filter=["Call"],  # No "Call" kind in our identifiers
        )

        # Should find 0 (no relationships, and identifiers are "Reference" not "Call")
        assert result["total_references"] == 0
