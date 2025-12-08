"""
Tests for agent tooling: architecture, validation, and code similarity.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from miller.tools.architecture import (
    get_architecture_map,
    _extract_directory_at_depth,
    _build_dependency_graph,
    _generate_mermaid,
    _generate_ascii,
)
from miller.tools.validation import (
    validate_imports,
    _parse_python_imports,
    _parse_typescript_imports,
    _parse_rust_imports,
    _parse_go_imports,
    _detect_language,
)
from miller.tools.code_search import find_similar_implementation


class TestDirectoryExtraction:
    """Tests for directory path extraction at various depths."""

    def test_depth_0(self):
        """Depth 0 returns first component."""
        assert _extract_directory_at_depth("src/auth/login.py", 0) == "src"

    def test_depth_1(self):
        """Depth 1 returns first directory."""
        assert _extract_directory_at_depth("src/auth/login.py", 1) == "src"

    def test_depth_2(self):
        """Depth 2 returns two directories."""
        assert _extract_directory_at_depth("src/auth/login.py", 2) == "src/auth"

    def test_depth_exceeds_path(self):
        """Depth greater than path returns full directory."""
        assert _extract_directory_at_depth("src/auth/login.py", 5) == "src/auth"

    def test_no_directories(self):
        """File in root returns filename (no directory structure)."""
        # When there's no directory structure, the function returns the file path
        assert _extract_directory_at_depth("main.py", 2) == "main.py"


class TestDependencyGraph:
    """Tests for building dependency graphs from raw data."""

    def test_builds_graph(self):
        """Graph is built with edge counts."""
        deps = [
            {"source_dir": "src/auth", "target_dir": "src/db", "edge_count": 5, "relationship_kinds": "Call"},
            {"source_dir": "src/auth", "target_dir": "src/db", "edge_count": 3, "relationship_kinds": "Import"},
        ]
        graph = _build_dependency_graph(deps, depth=2)
        assert "src/auth" in graph
        assert "src/db" in graph["src/auth"]
        assert graph["src/auth"]["src/db"]["edge_count"] == 8

    def test_excludes_self_references(self):
        """Same source and target are excluded."""
        deps = [
            {"source_dir": "src/auth", "target_dir": "src/auth", "edge_count": 10, "relationship_kinds": "Call"},
        ]
        graph = _build_dependency_graph(deps, depth=2)
        assert len(graph) == 0


class TestMermaidGeneration:
    """Tests for Mermaid.js output generation."""

    def test_generates_flowchart(self):
        """Mermaid output contains flowchart syntax."""
        graph = {"src/auth": {"src/db": {"edge_count": 50, "kinds": {"Call"}}}}
        output = _generate_mermaid(graph, title="Test")
        assert "flowchart TD" in output
        assert "title: Test" in output
        assert "==>" in output  # Thick arrow for 50+ edges

    def test_arrow_weight_styles(self):
        """Different arrow styles based on edge weight."""
        graph = {
            "src/a": {"src/b": {"edge_count": 60, "kinds": set()}},  # Heavy
            "src/c": {"src/d": {"edge_count": 15, "kinds": set()}},  # Medium
            "src/e": {"src/f": {"edge_count": 5, "kinds": set()}},   # Light
        }
        output = _generate_mermaid(graph)
        assert "==>" in output    # Heavy deps
        assert "-->" in output    # Normal deps
        assert "-.->" in output   # Light deps


class TestAsciiGeneration:
    """Tests for ASCII tree output generation."""

    def test_generates_tree(self):
        """ASCII output contains tree structure."""
        graph = {"src/auth": {"src/db": {"edge_count": 10, "kinds": {"Call"}}}}
        output = _generate_ascii(graph)
        assert "📁 src/auth" in output
        assert "src/db" in output


class TestPythonImportParsing:
    """Tests for Python import statement parsing."""

    def test_simple_import(self):
        """Parse 'import module'."""
        code = "import os"
        imports = _parse_python_imports(code)
        assert "os" in imports

    def test_from_import(self):
        """Parse 'from module import name'."""
        code = "from miller.storage import StorageManager"
        imports = _parse_python_imports(code)
        # Full module path + symbol name
        assert "miller.storage.StorageManager" in imports

    def test_multi_import(self):
        """Parse multiple imports from one module."""
        code = "from os import path, getcwd"
        imports = _parse_python_imports(code)
        assert "os.path" in imports
        assert "os.getcwd" in imports

    def test_import_with_alias(self):
        """Parse 'import module as alias'."""
        code = "from pandas import DataFrame as df"
        imports = _parse_python_imports(code)
        # Should extract the original name, not alias
        assert "pandas.DataFrame" in imports


class TestTypeScriptImportParsing:
    """Tests for TypeScript/JavaScript import parsing."""

    def test_es6_import(self):
        """Parse ES6 destructured imports."""
        code = "import { UserService, AuthService } from './services';"
        imports = _parse_typescript_imports(code)
        assert "UserService" in imports
        assert "AuthService" in imports

    def test_default_import(self):
        """Parse default imports."""
        code = "import React from 'react';"
        imports = _parse_typescript_imports(code)
        assert "React" in imports

    def test_type_import(self):
        """Parse type imports."""
        code = "import type { User } from './models';"
        imports = _parse_typescript_imports(code)
        assert "User" in imports


class TestRustImportParsing:
    """Tests for Rust use statement parsing."""

    def test_simple_use(self):
        """Parse 'use path::Name'."""
        code = "use crate::models::User;"
        imports = _parse_rust_imports(code)
        assert "User" in imports

    def test_multi_use(self):
        """Parse 'use path::{Name1, Name2}'."""
        code = "use std::collections::{HashMap, HashSet};"
        imports = _parse_rust_imports(code)
        assert "HashMap" in imports
        assert "HashSet" in imports


class TestGoImportParsing:
    """Tests for Go import parsing."""

    def test_single_import(self):
        """Parse single import."""
        code = 'import "fmt"'
        imports = _parse_go_imports(code)
        assert "fmt" in imports

    def test_grouped_import(self):
        """Parse grouped imports."""
        code = '''import (
            "fmt"
            "os"
        )'''
        imports = _parse_go_imports(code)
        assert "fmt" in imports
        assert "os" in imports


class TestLanguageDetection:
    """Tests for automatic language detection."""

    def test_detect_python(self):
        """Detect Python from code."""
        code = "def foo():\n    return 42"
        assert _detect_language(code) == "python"

    def test_detect_rust(self):
        """Detect Rust from code."""
        code = "fn main() {\n    println!(\"Hello\");\n}"
        assert _detect_language(code) == "rust"

    def test_detect_typescript(self):
        """Detect TypeScript from code."""
        code = "import { foo } from './bar';"
        assert _detect_language(code) == "typescript"

    def test_detect_go(self):
        """Detect Go from code."""
        code = "func main() {\n    fmt.Println(\"Hello\")\n}"
        assert _detect_language(code) == "go"


class TestArchitectureMapTool:
    """Integration tests for get_architecture_map tool."""

    @pytest.mark.asyncio
    async def test_no_storage(self):
        """Returns error when storage is None."""
        result = await get_architecture_map(storage=None)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_no_dependencies(self):
        """Returns message when no dependencies found."""
        mock_storage = MagicMock()
        mock_storage.get_cross_directory_dependencies.return_value = []
        result = await get_architecture_map(storage=mock_storage)
        assert "No cross-module dependencies" in result

    @pytest.mark.asyncio
    async def test_mermaid_format(self):
        """Returns Mermaid format by default."""
        mock_storage = MagicMock()
        mock_storage.get_cross_directory_dependencies.return_value = [
            {"source_dir": "src/auth", "target_dir": "src/db", "edge_count": 10, "relationship_kinds": "Call"},
        ]
        result = await get_architecture_map(storage=mock_storage)
        assert "flowchart TD" in result

    @pytest.mark.asyncio
    async def test_ascii_format(self):
        """Returns ASCII format when requested."""
        mock_storage = MagicMock()
        mock_storage.get_cross_directory_dependencies.return_value = [
            {"source_dir": "src/auth", "target_dir": "src/db", "edge_count": 10, "relationship_kinds": "Call"},
        ]
        result = await get_architecture_map(output_format="ascii", storage=mock_storage)
        assert "Module Dependencies" in result

    @pytest.mark.asyncio
    async def test_json_format(self):
        """Returns JSON format when requested."""
        mock_storage = MagicMock()
        mock_storage.get_cross_directory_dependencies.return_value = [
            {"source_dir": "src/auth", "target_dir": "src/db", "edge_count": 10, "relationship_kinds": "Call"},
        ]
        result = await get_architecture_map(output_format="json", storage=mock_storage)
        assert '"summary"' in result
        assert '"dependencies"' in result


class TestValidateImportsTool:
    """Integration tests for validate_imports tool."""

    @pytest.mark.asyncio
    async def test_no_storage(self):
        """Returns error when storage is None."""
        result = await validate_imports("import foo", storage=None)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_no_imports(self):
        """Returns message when no imports found."""
        mock_storage = MagicMock()
        result = await validate_imports("x = 1", storage=mock_storage)
        assert "No imports found" in result

    @pytest.mark.asyncio
    async def test_valid_import(self):
        """Validates existing symbol."""
        mock_storage = MagicMock()
        mock_storage.get_exported_symbols.return_value = [
            {"name": "StorageManager", "file_path": "storage.py", "kind": "class", "visibility": "public"}
        ]
        result = await validate_imports(
            "from miller.storage import StorageManager",
            language="python",
            storage=mock_storage,
        )
        assert "✓" in result
        assert "StorageManager" in result

    @pytest.mark.asyncio
    async def test_invalid_import(self):
        """Detects non-existent symbol."""
        mock_storage = MagicMock()
        mock_storage.get_exported_symbols.return_value = []
        mock_storage.find_symbols_by_name_prefix.return_value = []
        result = await validate_imports(
            "from miller.utils import NonExistent",
            language="python",
            storage=mock_storage,
        )
        assert "✗" in result
        assert "NonExistent" in result


class TestFindSimilarImplementation:
    """Integration tests for find_similar_implementation tool."""

    @pytest.mark.asyncio
    async def test_no_embeddings(self):
        """Returns error when embeddings are None."""
        result = await find_similar_implementation("def foo(): pass", embeddings=None)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_no_vector_store(self):
        """Returns error when vector store is None."""
        mock_embeddings = MagicMock()
        result = await find_similar_implementation(
            "def foo(): pass",
            embeddings=mock_embeddings,
            vector_store=None,
        )
        assert "Error" in result
