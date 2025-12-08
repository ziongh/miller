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
bun 

class TestFileSizeLimits:
    """Test file size filtering with per-extension overrides."""

    @pytest.fixture
    def size_test_workspace(self):
        """Create workspace with files of various sizes."""
        temp_dir = tempfile.mkdtemp(prefix="miller_test_size_")
        workspace = Path(temp_dir)

        # Create directory structure
        (workspace / "src").mkdir()

        # Create files of different sizes
        # Small files (under 1KB)
        (workspace / "src" / "small.py").write_text("x" * 100)
        (workspace / "src" / "small.md").write_text("y" * 200)
        (workspace / "src" / "small.cs").write_text("z" * 150)

        # Medium files (~500KB)
        (workspace / "src" / "medium.py").write_text("a" * 500_000)
        (workspace / "src" / "medium.md").write_text("b" * 500_000)

        # Large files (~2MB)
        (workspace / "src" / "large.py").write_text("c" * 2_000_000)
        (workspace / "src" / "large.md").write_text("d" * 2_000_000)
        (workspace / "src" / "large.cs").write_text("e" * 2_000_000)

        # Very large files (~5MB)
        (workspace / "src" / "huge.js").write_text("f" * 5_000_000)

        yield workspace

        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_default_size_limits_exist(self):
        """Test that default size limit constants are defined."""
        from miller.ignore_defaults import (
            DEFAULT_MAX_FILE_SIZE,
            EXTENSION_SIZE_LIMITS,
        )

        # Default should be 1MB (1_048_576 bytes)
        assert DEFAULT_MAX_FILE_SIZE == 1_048_576

        # Extension overrides should be a dict
        assert isinstance(EXTENSION_SIZE_LIMITS, dict)

    def test_extension_size_limits_structure(self):
        """Test that extension size limits have expected entries."""
        from miller.ignore_defaults import EXTENSION_SIZE_LIMITS

        # Markdown should allow larger files (documentation)
        assert ".md" in EXTENSION_SIZE_LIMITS
        assert EXTENSION_SIZE_LIMITS[".md"] > 1_048_576  # > 1MB

        # JSON might need larger limit for config files
        assert ".json" in EXTENSION_SIZE_LIMITS

    def test_get_max_file_size_default(self):
        """Test getting max size for extension without override."""
        from miller.ignore_patterns import get_max_file_size

        # Extensions without override should use default
        default_size = get_max_file_size(".py")
        assert default_size == 1_048_576  # 1MB default

    def test_get_max_file_size_with_override(self):
        """Test getting max size for extension with override."""
        from miller.ignore_patterns import get_max_file_size
        from miller.ignore_defaults import EXTENSION_SIZE_LIMITS

        # Markdown has override
        md_size = get_max_file_size(".md")
        assert md_size == EXTENSION_SIZE_LIMITS[".md"]
        assert md_size > 1_048_576  # Should be larger than default

    def test_is_file_too_large_small_file(self, size_test_workspace):
        """Test that small files pass size check."""
        from miller.ignore_patterns import is_file_too_large

        small_py = size_test_workspace / "src" / "small.py"
        assert is_file_too_large(small_py) is False

    def test_is_file_too_large_large_file(self, size_test_workspace):
        """Test that large files fail size check (using default limit)."""
        from miller.ignore_patterns import is_file_too_large

        large_py = size_test_workspace / "src" / "large.py"  # 2MB
        assert is_file_too_large(large_py) is True

    def test_is_file_too_large_respects_extension_override(self, size_test_workspace):
        """Test that extension overrides are respected."""
        from miller.ignore_patterns import is_file_too_large

        # Large markdown (2MB) should pass if markdown limit is > 2MB
        large_md = size_test_workspace / "src" / "large.md"
        # This depends on EXTENSION_SIZE_LIMITS[".md"] being > 2MB
        # If it's set to 5MB, this should pass
        result = is_file_too_large(large_md)
        # We'll configure .md to allow 5MB, so 2MB should pass
        assert result is False

    def test_is_file_too_large_custom_limit(self, size_test_workspace):
        """Test is_file_too_large with custom limit parameter."""
        from miller.ignore_patterns import is_file_too_large

        medium_py = size_test_workspace / "src" / "medium.py"  # 500KB

        # Should pass with 1MB limit
        assert is_file_too_large(medium_py, max_size=1_048_576) is False

        # Should fail with 100KB limit
        assert is_file_too_large(medium_py, max_size=100_000) is True

    def test_should_ignore_includes_size_check(self, size_test_workspace):
        """Test that should_ignore now includes file size checking."""
        from miller.ignore_patterns import should_ignore

        # Small file should not be ignored
        small_py = size_test_workspace / "src" / "small.py"
        assert should_ignore(small_py, size_test_workspace, check_size=True) is False

        # Large file (2MB Python) should be ignored due to size
        large_py = size_test_workspace / "src" / "large.py"
        assert should_ignore(large_py, size_test_workspace, check_size=True) is True

    def test_should_ignore_size_check_disabled_by_default(self, size_test_workspace):
        """Test that size check is opt-in (backwards compatible)."""
        from miller.ignore_patterns import should_ignore

        # Without check_size=True, large files should NOT be ignored by size
        large_py = size_test_workspace / "src" / "large.py"
        # Default behavior (check_size=False) - only pattern matching
        assert should_ignore(large_py, size_test_workspace) is False

    def test_filter_files_with_size_filtering(self, size_test_workspace):
        """Test filter_files with size filtering enabled."""
        from miller.ignore_patterns import filter_files

        all_files = list(size_test_workspace.rglob("*"))
        filtered = filter_files(all_files, size_test_workspace, check_size=True)

        # Small files should be included
        assert any(f.name == "small.py" for f in filtered)
        assert any(f.name == "small.md" for f in filtered)

        # Large Python files should be excluded (2MB > 1MB default)
        assert not any(f.name == "large.py" for f in filtered)

        # Large markdown might be included (if .md limit > 2MB)
        # Depends on EXTENSION_SIZE_LIMITS configuration

    def test_filter_files_without_size_filtering(self, size_test_workspace):
        """Test filter_files without size filtering (backwards compatible)."""
        from miller.ignore_patterns import filter_files

        all_files = list(size_test_workspace.rglob("*"))
        filtered = filter_files(all_files, size_test_workspace, check_size=False)

        # All files should be included (no size filtering)
        assert any(f.name == "large.py" for f in filtered)
        assert any(f.name == "large.md" for f in filtered)
