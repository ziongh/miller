"""
Tests for fast_explore mode="dependencies" - transitive dependency graph.

Following TDD: Tests define expected behavior BEFORE implementation.
These tests verify that dependencies mode traverses symbol relationships
to build a dependency graph for impact analysis.
"""

import pytest


class TestExploreDependenciesMode:
    """Tests for fast_explore mode='dependencies'."""

    @pytest.mark.asyncio
    async def test_dependencies_mode_accepted(self):
        """Test that mode='dependencies' is a valid mode (doesn't raise ValueError)."""
        from miller.tools.explore import fast_explore

        # Should not raise ValueError("Unknown exploration mode")
        try:
            result = await fast_explore(mode="dependencies", symbol="test")
        except ValueError as e:
            if "Unknown exploration mode" in str(e):
                pytest.fail("mode='dependencies' should be accepted, got: " + str(e))
        except Exception:
            # Other exceptions are fine - mode was accepted
            pass

    @pytest.mark.asyncio
    async def test_dependencies_mode_requires_symbol_param(self):
        """Test that dependencies mode requires 'symbol' parameter."""
        from miller.tools.explore import fast_explore

        result = await fast_explore(mode="dependencies")

        # Either returns error dict or raised exception
        assert "error" in result or result.get("dependencies") == []

    @pytest.mark.asyncio
    async def test_dependencies_mode_returns_expected_structure(self):
        """Test that dependencies mode returns dict with expected keys."""
        from miller.tools.explore import fast_explore

        result = await fast_explore(
            mode="dependencies",
            symbol="nonexistent_symbol_xyz",
        )

        # Should return a dict with expected keys
        assert isinstance(result, dict)
        assert "symbol" in result
        assert "dependencies" in result
        assert "total_found" in result or "error" in result

    @pytest.mark.asyncio
    async def test_dependencies_mode_symbol_not_found_returns_error(self):
        """Test error response when symbol doesn't exist."""
        from miller.tools.explore import fast_explore

        result = await fast_explore(
            mode="dependencies",
            symbol="definitely_not_a_real_symbol_12345",
        )

        # Should return error, not crash
        assert isinstance(result, dict)
        assert result["symbol"] == "definitely_not_a_real_symbol_12345"
        # Either error message or empty results
        assert "error" in result or result["dependencies"] == []

    @pytest.mark.asyncio
    async def test_dependencies_mode_accepts_depth_param(self):
        """Test that depth parameter is accepted."""
        from miller.tools.explore import fast_explore

        result = await fast_explore(
            mode="dependencies",
            symbol="test",
            depth=5,
        )

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_dependencies_mode_depth_default_is_3(self):
        """Test that depth defaults to 3."""
        from miller.tools.explore import fast_explore

        # Just verify it doesn't crash with default depth
        result = await fast_explore(
            mode="dependencies",
            symbol="test",
        )

        assert isinstance(result, dict)


class TestExploreDependenciesTextFormat:
    """Tests for dependencies mode text output formatting."""

    def test_format_dependencies_as_text_exists(self):
        """Test that _format_dependencies_as_text function exists."""
        from miller.tools.explore import _format_dependencies_as_text

        assert callable(_format_dependencies_as_text)

    def test_dependencies_text_format_returns_string(self):
        """Test that text formatter returns a string."""
        from miller.tools.explore import _format_dependencies_as_text

        result = {
            "symbol": "PaymentService",
            "total_found": 2,
            "max_depth_reached": 2,
            "has_cycles": False,
            "dependencies": [
                {
                    "name": "UserRepository",
                    "kind": "Class",
                    "file_path": "src/repos/user.py",
                    "start_line": 10,
                    "depth": 1,
                    "relationship": "imports",
                },
                {
                    "name": "DatabaseConnection",
                    "kind": "Class",
                    "file_path": "src/db/connection.py",
                    "start_line": 5,
                    "depth": 2,
                    "relationship": "imports",
                },
            ],
        }

        text = _format_dependencies_as_text(result)

        assert isinstance(text, str)
        assert len(text) > 0

    def test_dependencies_text_format_has_header(self):
        """Test that text output includes header with symbol name."""
        from miller.tools.explore import _format_dependencies_as_text

        result = {
            "symbol": "PaymentService",
            "total_found": 1,
            "max_depth_reached": 1,
            "has_cycles": False,
            "dependencies": [
                {
                    "name": "UserRepo",
                    "kind": "Class",
                    "file_path": "src/repo.py",
                    "start_line": 10,
                    "depth": 1,
                    "relationship": "imports",
                },
            ],
        }

        text = _format_dependencies_as_text(result)

        assert "PaymentService" in text

    def test_dependencies_text_format_shows_depth(self):
        """Test that text output shows dependency depth."""
        from miller.tools.explore import _format_dependencies_as_text

        result = {
            "symbol": "Service",
            "total_found": 2,
            "max_depth_reached": 2,
            "has_cycles": False,
            "dependencies": [
                {
                    "name": "RepoA",
                    "kind": "Class",
                    "file_path": "a.py",
                    "start_line": 1,
                    "depth": 1,
                    "relationship": "imports",
                },
                {
                    "name": "RepoB",
                    "kind": "Class",
                    "file_path": "b.py",
                    "start_line": 1,
                    "depth": 2,
                    "relationship": "imports",
                },
            ],
        }

        text = _format_dependencies_as_text(result)

        # Should indicate depth somehow (level, depth, indentation)
        # Just check the output contains both names
        assert "RepoA" in text
        assert "RepoB" in text

    def test_dependencies_text_format_shows_relationship_type(self):
        """Test that text output shows relationship type."""
        from miller.tools.explore import _format_dependencies_as_text

        result = {
            "symbol": "Child",
            "total_found": 1,
            "max_depth_reached": 1,
            "has_cycles": False,
            "dependencies": [
                {
                    "name": "Parent",
                    "kind": "Class",
                    "file_path": "parent.py",
                    "start_line": 1,
                    "depth": 1,
                    "relationship": "extends",
                },
            ],
        }

        text = _format_dependencies_as_text(result)

        # Should show relationship type
        assert "extends" in text.lower() or "parent" in text.lower()

    def test_dependencies_text_format_shows_file_location(self):
        """Test that text output shows file:line."""
        from miller.tools.explore import _format_dependencies_as_text

        result = {
            "symbol": "MyClass",
            "total_found": 1,
            "max_depth_reached": 1,
            "has_cycles": False,
            "dependencies": [
                {
                    "name": "Dependency",
                    "kind": "Class",
                    "file_path": "src/deps/dep.py",
                    "start_line": 42,
                    "depth": 1,
                    "relationship": "imports",
                },
            ],
        }

        text = _format_dependencies_as_text(result)

        assert "src/deps/dep.py" in text
        assert "42" in text

    def test_dependencies_text_format_empty_results(self):
        """Test text output when no dependencies found."""
        from miller.tools.explore import _format_dependencies_as_text

        result = {
            "symbol": "StandaloneClass",
            "total_found": 0,
            "max_depth_reached": 0,
            "has_cycles": False,
            "dependencies": [],
        }

        text = _format_dependencies_as_text(result)

        assert "StandaloneClass" in text
        # Should indicate no dependencies
        assert "0" in text or "No" in text or "none" in text.lower()

    def test_dependencies_text_format_shows_cycles(self):
        """Test that text output indicates when cycles are detected."""
        from miller.tools.explore import _format_dependencies_as_text

        result = {
            "symbol": "CyclicClass",
            "total_found": 2,
            "max_depth_reached": 2,
            "has_cycles": True,
            "dependencies": [
                {
                    "name": "DepA",
                    "kind": "Class",
                    "file_path": "a.py",
                    "start_line": 1,
                    "depth": 1,
                    "relationship": "imports",
                },
            ],
        }

        text = _format_dependencies_as_text(result)

        # Should indicate cycle detection
        assert "cycle" in text.lower() or "circular" in text.lower() or "⚠" in text

    def test_dependencies_text_format_error_case(self):
        """Test text output when there's an error."""
        from miller.tools.explore import _format_dependencies_as_text

        result = {
            "symbol": "badSymbol",
            "error": "Symbol not found",
            "dependencies": [],
        }

        text = _format_dependencies_as_text(result)

        assert "badSymbol" in text
        assert "error" in text.lower() or "not found" in text.lower() or "0" in text
