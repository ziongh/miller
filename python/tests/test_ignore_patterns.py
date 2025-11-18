"""
Test .gitignore pattern matching and file filtering.

Following TDD: These tests define the ignore_patterns API BEFORE implementation.
"""

import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.fixture
def test_workspace():
    """Create a temporary workspace with various file types."""
    temp_dir = tempfile.mkdtemp(prefix="miller_test_ignore_")
    workspace = Path(temp_dir)

    # Create directory structure
    (workspace / "src").mkdir()
    (workspace / "node_modules").mkdir()
    (workspace / ".git").mkdir()
    (workspace / ".venv").mkdir()
    (workspace / "__pycache__").mkdir()
    (workspace / "build").mkdir()

    # Create files
    (workspace / "src" / "main.py").write_text("def hello(): pass")
    (workspace / "src" / "utils.py").write_text("def util(): pass")
    (workspace / "node_modules" / "package.js").write_text("// package")
    (workspace / ".git" / "config").write_text("")
    (workspace / ".venv" / "lib.py").write_text("")
    (workspace / "__pycache__" / "main.pyc").write_text("")
    (workspace / "build" / "output.txt").write_text("")
    (workspace / "README.md").write_text("# README")

    yield workspace

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestDefaultIgnores:
    """Test that default ignore patterns work correctly."""

    def test_ignores_git_directory(self, test_workspace):
        """Test that .git directory is ignored."""
        from miller.ignore_patterns import should_ignore

        git_file = test_workspace / ".git" / "config"
        assert should_ignore(git_file, test_workspace) is True

    def test_ignores_node_modules(self, test_workspace):
        """Test that node_modules is ignored."""
        from miller.ignore_patterns import should_ignore

        node_file = test_workspace / "node_modules" / "package.js"
        assert should_ignore(node_file, test_workspace) is True

    def test_ignores_venv(self, test_workspace):
        """Test that .venv is ignored."""
        from miller.ignore_patterns import should_ignore

        venv_file = test_workspace / ".venv" / "lib.py"
        assert should_ignore(venv_file, test_workspace) is True

    def test_ignores_pycache(self, test_workspace):
        """Test that __pycache__ is ignored."""
        from miller.ignore_patterns import should_ignore

        cache_file = test_workspace / "__pycache__" / "main.pyc"
        assert should_ignore(cache_file, test_workspace) is True

    def test_ignores_build_directory(self, test_workspace):
        """Test that build directory is ignored."""
        from miller.ignore_patterns import should_ignore

        build_file = test_workspace / "build" / "output.txt"
        assert should_ignore(build_file, test_workspace) is True

    def test_does_not_ignore_source_files(self, test_workspace):
        """Test that normal source files are NOT ignored."""
        from miller.ignore_patterns import should_ignore

        source_file = test_workspace / "src" / "main.py"
        assert should_ignore(source_file, test_workspace) is False

    def test_does_not_ignore_readme(self, test_workspace):
        """Test that README.md is NOT ignored."""
        from miller.ignore_patterns import should_ignore

        readme = test_workspace / "README.md"
        assert should_ignore(readme, test_workspace) is False


class TestGitignoreFile:
    """Test .gitignore file parsing."""

    def test_respects_gitignore_patterns(self, test_workspace):
        """Test that .gitignore patterns are respected."""
        from miller.ignore_patterns import should_ignore

        # Create .gitignore with custom pattern
        gitignore = test_workspace / ".gitignore"
        gitignore.write_text("*.log\ntemp/\n")

        # Create files matching .gitignore
        (test_workspace / "debug.log").write_text("logs")
        (test_workspace / "temp").mkdir()
        (test_workspace / "temp" / "file.txt").write_text("temp")

        # Test that they're ignored
        assert should_ignore(test_workspace / "debug.log", test_workspace) is True
        assert should_ignore(test_workspace / "temp" / "file.txt", test_workspace) is True

    def test_works_without_gitignore(self, test_workspace):
        """Test that it works even without .gitignore file."""
        from miller.ignore_patterns import should_ignore

        # No .gitignore exists
        source_file = test_workspace / "src" / "main.py"
        assert should_ignore(source_file, test_workspace) is False


class TestLoadGitignore:
    """Test the load_gitignore function."""

    def test_returns_pathspec(self, test_workspace):
        """Test that load_gitignore returns a PathSpec object."""
        from miller.ignore_patterns import load_gitignore
        from pathspec import PathSpec

        spec = load_gitignore(test_workspace)
        assert isinstance(spec, PathSpec)

    def test_includes_default_patterns(self, test_workspace):
        """Test that default patterns are always included."""
        from miller.ignore_patterns import load_gitignore

        spec = load_gitignore(test_workspace)

        # Test default patterns
        assert spec.match_file(".git/config") is True
        assert spec.match_file("node_modules/package.json") is True
        assert spec.match_file(".venv/lib.py") is True

    def test_combines_gitignore_and_defaults(self, test_workspace):
        """Test that .gitignore patterns are added to defaults."""
        from miller.ignore_patterns import load_gitignore

        # Create .gitignore
        (test_workspace / ".gitignore").write_text("*.custom\n")

        spec = load_gitignore(test_workspace)

        # Both default and custom patterns should work
        assert spec.match_file(".git/config") is True  # Default
        assert spec.match_file("file.custom") is True  # From .gitignore


class TestFiltering:
    """Test file filtering for workspace scanning."""

    def test_filter_files_excludes_ignored(self, test_workspace):
        """Test that filter_files excludes ignored paths."""
        from miller.ignore_patterns import filter_files

        all_files = list(test_workspace.rglob("*"))
        filtered = filter_files(all_files, test_workspace)

        # Should not include ignored directories
        assert not any(".git" in str(f) for f in filtered)
        assert not any("node_modules" in str(f) for f in filtered)
        assert not any(".venv" in str(f) for f in filtered)

    def test_filter_files_includes_source(self, test_workspace):
        """Test that filter_files includes source files."""
        from miller.ignore_patterns import filter_files

        all_files = list(test_workspace.rglob("*"))
        filtered = filter_files(all_files, test_workspace)

        # Should include source files
        source_files = [f for f in filtered if f.name == "main.py"]
        assert len(source_files) > 0
