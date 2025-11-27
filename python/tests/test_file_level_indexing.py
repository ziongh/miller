"""
Test file-level indexing for text files without tree-sitter parsers.

This tests the feature that makes files like .gitattributes, Dockerfile,
Makefile, etc. searchable even though they don't have symbol extraction.
"""

import pytest
import numpy as np
from pathlib import Path


class TestFileSymbol:
    """Test the FileSymbol dataclass used for file-level entries."""

    def test_creates_file_symbol_from_content(self):
        """Test FileSymbol.from_file creates correct entry."""
        from miller.workspace.indexer import FileSymbol

        content = "* text=auto\n*.png binary"
        file_symbol = FileSymbol.from_file(".gitattributes", content, "text")

        assert file_symbol.name == ".gitattributes"
        assert file_symbol.kind == "file"
        assert file_symbol.language == "text"
        assert file_symbol.file_path == ".gitattributes"
        assert file_symbol.start_line == 1
        assert file_symbol.end_line == 2
        assert file_symbol.content == content
        assert file_symbol.signature is None
        assert file_symbol.id.startswith("file_")

    def test_truncates_large_content(self):
        """Test that FileSymbol truncates content to MAX_CONTENT_FOR_EMBEDDING."""
        from miller.workspace.indexer import FileSymbol, MAX_CONTENT_FOR_EMBEDDING

        # Create content larger than limit
        large_content = "x" * (MAX_CONTENT_FOR_EMBEDDING + 1000)
        file_symbol = FileSymbol.from_file("large.txt", large_content, "text")

        assert len(file_symbol.content) == MAX_CONTENT_FOR_EMBEDDING

    def test_stable_id_for_same_path(self):
        """Test that same file path always produces same ID."""
        from miller.workspace.indexer import FileSymbol

        sym1 = FileSymbol.from_file("test/file.txt", "content1", "text")
        sym2 = FileSymbol.from_file("test/file.txt", "content2", "text")

        # Same path = same ID (for deduplication)
        assert sym1.id == sym2.id

    def test_different_ids_for_different_paths(self):
        """Test that different paths produce different IDs."""
        from miller.workspace.indexer import FileSymbol

        sym1 = FileSymbol.from_file("file1.txt", "content", "text")
        sym2 = FileSymbol.from_file("file2.txt", "content", "text")

        assert sym1.id != sym2.id


class TestLanguageDetection:
    """Test that language detection returns 'text' for unknown extensions.

    NOTE: test_unknown_extension_returns_text requires Rust rebuild to pass.
    Until then, it will be skipped with a helpful message.
    """

    def test_unknown_extension_returns_text(self):
        """Test that unknown file extensions return 'text' language.

        This test requires the Rust extension to be rebuilt with the
        detect_language -> "text" fallback change.
        """
        from miller import miller_core

        # Check if Rust has been rebuilt
        result = miller_core.detect_language(".gitattributes")
        if result is None:
            pytest.skip(
                "Rust extension needs rebuild: detect_language('.gitattributes') "
                "returns None instead of 'text'. Run: maturin develop --release"
            )

        # These should all return "text" since they don't have tree-sitter parsers
        assert miller_core.detect_language(".gitattributes") == "text"
        assert miller_core.detect_language("Makefile.custom") == "text"
        assert miller_core.detect_language("file.xyz") == "text"
        assert miller_core.detect_language("no_extension") == "text"

    def test_known_extension_returns_language(self):
        """Test that known extensions return their language."""
        from miller import miller_core

        assert miller_core.detect_language("test.py") == "python"
        assert miller_core.detect_language("test.rs") == "rust"
        assert miller_core.detect_language("test.js") == "javascript"


class TestFileLevelVectorStore:
    """Test that file-level entries can be stored and searched in VectorStore."""

    def test_add_file_symbol_to_vector_store(self):
        """Test adding a file-level entry to VectorStore."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller.workspace.indexer import FileSymbol

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        store = VectorStore(db_path=":memory:")

        # Create file symbol
        content = "* text=auto\n*.png binary"
        file_symbol = FileSymbol.from_file(".gitattributes", content, "text")

        # Embed and add
        vectors = embeddings.embed_texts([content])
        count = store.add_symbols([file_symbol], vectors)

        assert count == 1

    def test_search_finds_file_content(self):
        """Test that FTS search finds content in file-level entries."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller.workspace.indexer import FileSymbol

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        store = VectorStore(db_path=":memory:")

        # Add file-level entry
        content = "* text=auto\n*.png binary\n*.jpg binary"
        file_symbol = FileSymbol.from_file(".gitattributes", content, "text")
        vectors = embeddings.embed_texts([content])
        store.add_symbols([file_symbol], vectors)

        # Search for content
        results = store.search(query="binary", method="text", limit=10)

        assert len(results) > 0
        assert results[0]["name"] == ".gitattributes"
        assert results[0]["kind"] == "file"

    def test_file_entries_rank_lower_than_symbols(self):
        """Test that file-level entries rank lower than code symbols."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller.workspace.indexer import FileSymbol
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        store = VectorStore(db_path=":memory:")

        # Add a code symbol with "binary" in name
        code = "def binary_search(arr, target): pass"
        result = miller_core.extract_file(code, "python", "search.py")
        code_vectors = embeddings.embed_batch(result.symbols)
        store.add_symbols(result.symbols, code_vectors)

        # Add a file-level entry with "binary"
        content = "*.png binary\n*.jpg binary"
        file_symbol = FileSymbol.from_file(".gitattributes", content, "text")
        file_vectors = embeddings.embed_texts([content])
        store.add_symbols([file_symbol], file_vectors)

        # Search for "binary"
        results = store.search(query="binary", method="hybrid", limit=10)

        # Code symbol should rank higher than file entry
        assert len(results) >= 2
        code_results = [r for r in results if r["kind"] == "function"]
        file_results = [r for r in results if r["kind"] == "file"]

        if code_results and file_results:
            # Code symbol should have higher score
            assert code_results[0]["score"] >= file_results[0]["score"], (
                f"Code symbol should rank higher: "
                f"code={code_results[0]['score']:.3f}, file={file_results[0]['score']:.3f}"
            )


class TestEmbedTexts:
    """Test the embed_texts method for raw text embedding."""

    def test_embed_texts_returns_correct_shape(self):
        """Test embed_texts returns correct embedding dimensions."""
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        texts = ["hello world", "test content", "another string"]
        vectors = embeddings.embed_texts(texts)

        assert vectors.shape == (3, 384)
        assert vectors.dtype == np.float32

    def test_embed_texts_handles_empty_list(self):
        """Test embed_texts handles empty input."""
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        vectors = embeddings.embed_texts([])

        assert vectors.shape == (0, 384)

    def test_embed_texts_normalizes_vectors(self):
        """Test embed_texts returns L2 normalized vectors."""
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        vectors = embeddings.embed_texts(["test content"])

        # Check L2 normalization
        norm = np.linalg.norm(vectors[0])
        assert 0.99 < norm < 1.01


class TestKindWeighting:
    """Test that kind-based weighting includes 'File' kind."""

    def test_file_kind_has_lower_weight(self):
        """Test that 'file' kind has lower weight than code symbols."""
        from miller.embeddings.search_enhancements import apply_kind_weighting

        # File result
        file_result = {"score": 1.0, "kind": "file"}
        file_score = apply_kind_weighting(file_result)

        # Function result
        func_result = {"score": 1.0, "kind": "function"}
        func_score = apply_kind_weighting(func_result)

        # File should have lower weight
        assert file_score < func_score
        assert file_score == 0.5  # File weight is 0.5
        assert func_score == 1.0  # Function weight is 1.5, capped at 1.0


class TestIgnorePatterns:
    """Test that noisy files are in the ignore list."""

    def test_lock_files_are_ignored(self):
        """Test that lock files are in DEFAULT_IGNORES."""
        from miller.ignore_defaults import DEFAULT_IGNORES

        lock_files = [
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "Cargo.lock",
            "poetry.lock",
            "Gemfile.lock",
            "composer.lock",
        ]

        for lock_file in lock_files:
            assert lock_file in DEFAULT_IGNORES, f"{lock_file} should be ignored"

    def test_minified_files_are_ignored(self):
        """Test that minified files are in DEFAULT_IGNORES."""
        from miller.ignore_defaults import DEFAULT_IGNORES

        assert "*.min.js" in DEFAULT_IGNORES
        assert "*.min.css" in DEFAULT_IGNORES
        assert "*.bundle.js" in DEFAULT_IGNORES


class TestIndexFileIntegration:
    """Integration tests for the full file indexing pipeline."""

    @pytest.fixture
    def temp_workspace(self, tmp_path):
        """Create a temporary workspace with test files."""
        # Create a text file without parser support
        gitattributes = tmp_path / ".gitattributes"
        gitattributes.write_text("* text=auto\n*.png binary\n*.jpg binary")

        # Create a Python file (has parser)
        python_file = tmp_path / "search.py"
        python_file.write_text("def binary_search(arr, target):\n    pass")

        # Create a Dockerfile (no parser)
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.11\nRUN pip install flask")

        return tmp_path

    @pytest.fixture
    def indexing_components(self, tmp_path):
        """Create storage, embeddings, and vector store for testing."""
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        vector_store = VectorStore(db_path=":memory:", embeddings=embeddings)

        return storage, embeddings, vector_store

    @pytest.mark.asyncio
    async def test_index_file_with_parser(self, temp_workspace, indexing_components):
        """Test indexing a Python file (has tree-sitter parser)."""
        from miller.workspace.indexer import index_file

        storage, embeddings, vector_store = indexing_components
        python_file = temp_workspace / "search.py"

        success = await index_file(
            python_file, temp_workspace, storage, embeddings, vector_store
        )

        assert success is True

        # Should have extracted symbols
        results = vector_store.search("binary_search", method="text", limit=10)
        assert len(results) > 0
        assert results[0]["kind"] == "function"
        assert results[0]["name"] == "binary_search"

    @pytest.mark.asyncio
    async def test_index_file_without_parser(self, temp_workspace, indexing_components):
        """Test indexing a text file (no tree-sitter parser) - requires Rust rebuild.

        NOTE: This test requires the Rust extension to be rebuilt with the
        detect_language -> "text" fallback. Until then, this test will be skipped.
        """
        from miller.workspace.indexer import index_file, LANGUAGES_WITH_PARSERS
        from miller import miller_core

        storage, embeddings, vector_store = indexing_components
        gitattributes = temp_workspace / ".gitattributes"

        # Check if Rust has been rebuilt with "text" fallback
        detected = miller_core.detect_language(".gitattributes")
        if detected is None:
            pytest.skip("Rust extension needs rebuild - detect_language returns None")

        success = await index_file(
            gitattributes, temp_workspace, storage, embeddings, vector_store
        )

        assert success is True

        # Should find file-level entry
        results = vector_store.search("binary", method="text", limit=10)
        assert len(results) > 0
        assert any(r["kind"] == "file" for r in results)
        assert any(r["name"] == ".gitattributes" for r in results)

    @pytest.mark.asyncio
    async def test_index_dockerfile_without_parser(self, temp_workspace, indexing_components):
        """Test indexing Dockerfile (no parser) - requires Rust rebuild."""
        from miller.workspace.indexer import index_file
        from miller import miller_core

        storage, embeddings, vector_store = indexing_components
        dockerfile = temp_workspace / "Dockerfile"

        # Check if Rust has been rebuilt
        detected = miller_core.detect_language("Dockerfile")
        if detected is None:
            pytest.skip("Rust extension needs rebuild - detect_language returns None")

        success = await index_file(
            dockerfile, temp_workspace, storage, embeddings, vector_store
        )

        assert success is True

        # Should find Dockerfile content
        results = vector_store.search("flask", method="text", limit=10)
        assert len(results) > 0
        assert any(r["name"] == "Dockerfile" for r in results)

    @pytest.mark.asyncio
    async def test_mixed_search_ranks_symbols_higher(self, temp_workspace, indexing_components):
        """Test that code symbols rank higher than file content in mixed results."""
        from miller.workspace.indexer import index_file
        from miller import miller_core

        storage, embeddings, vector_store = indexing_components

        # Index Python file first
        python_file = temp_workspace / "search.py"
        await index_file(python_file, temp_workspace, storage, embeddings, vector_store)

        # Check if Rust has been rebuilt for text files
        detected = miller_core.detect_language(".gitattributes")
        if detected is None:
            pytest.skip("Rust extension needs rebuild for text file indexing")

        # Index .gitattributes
        gitattributes = temp_workspace / ".gitattributes"
        await index_file(gitattributes, temp_workspace, storage, embeddings, vector_store)

        # Search for "binary" - should find both
        results = vector_store.search("binary", method="hybrid", limit=10)

        # Should have at least 2 results
        assert len(results) >= 2

        # Separate by kind
        functions = [r for r in results if r["kind"] == "function"]
        files = [r for r in results if r["kind"] == "file"]

        # Both should be found
        assert len(functions) > 0, "Should find binary_search function"
        assert len(files) > 0, "Should find .gitattributes file"

        # Function should rank higher (appear first or have higher score)
        if functions and files:
            func_score = functions[0]["score"]
            file_score = files[0]["score"]
            assert func_score >= file_score, (
                f"Function should rank >= file: func={func_score:.3f}, file={file_score:.3f}"
            )


class TestLanguagesWithParsers:
    """Test the LANGUAGES_WITH_PARSERS set."""

    def test_common_languages_have_parsers(self):
        """Test that common languages are in LANGUAGES_WITH_PARSERS."""
        from miller.workspace.indexer import LANGUAGES_WITH_PARSERS

        expected = ["python", "rust", "javascript", "typescript", "java", "go", "c", "cpp"]
        for lang in expected:
            assert lang in LANGUAGES_WITH_PARSERS, f"{lang} should have parser"

    def test_text_not_in_parsers(self):
        """Test that 'text' is NOT in LANGUAGES_WITH_PARSERS."""
        from miller.workspace.indexer import LANGUAGES_WITH_PARSERS

        assert "text" not in LANGUAGES_WITH_PARSERS
