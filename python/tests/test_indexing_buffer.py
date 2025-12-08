"""
Test IndexingBuffer for streaming workspace indexing.

Following TDD: These tests define the IndexingBuffer API BEFORE implementation.
The buffer accumulates symbols and triggers flushing based on symbol count,
not file count - this provides stable memory usage regardless of file sizes.
"""

import pytest
from pathlib import Path
from dataclasses import dataclass
from typing import Any, List


@dataclass
class MockSymbol:
    """Mock symbol for testing buffer without Rust extension."""
    id: str
    name: str
    kind: str
    file_path: str
    start_line: int = 1
    end_line: int = 1
    signature: str = ""
    doc_comment: str = ""


@dataclass
class MockIdentifier:
    """Mock identifier for testing."""
    id: str
    name: str
    file_path: str


@dataclass
class MockRelationship:
    """Mock relationship for testing."""
    source_id: str
    target_id: str
    kind: str


@dataclass
class MockExtractionResult:
    """Mock extraction result to simulate miller_core output."""
    symbols: List[MockSymbol]
    identifiers: List[MockIdentifier]
    relationships: List[MockRelationship]


class TestIndexingBufferCreation:
    """Test IndexingBuffer initialization."""

    def test_buffer_initializes_with_default_thresholds(self):
        """Test that buffer creates with sensible defaults."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer()

        assert buffer.max_symbols == 512  # GPU-friendly batch size
        assert buffer.is_empty()
        assert not buffer.should_flush()

    def test_buffer_accepts_custom_thresholds(self):
        """Test that buffer accepts custom symbol threshold."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=1024)

        assert buffer.max_symbols == 1024


class TestBufferAccumulation:
    """Test adding extraction results to buffer."""

    def test_add_result_accumulates_symbols(self):
        """Test that symbols are accumulated in the buffer."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        # Create mock extraction result with 3 symbols
        symbols = [
            MockSymbol(id="sym1", name="func1", kind="function", file_path="test.py"),
            MockSymbol(id="sym2", name="func2", kind="function", file_path="test.py"),
            MockSymbol(id="sym3", name="Class1", kind="class", file_path="test.py"),
        ]
        result = MockExtractionResult(
            symbols=symbols,
            identifiers=[],
            relationships=[]
        )

        buffer.add_result(
            file_path=Path("/workspace/test.py"),
            relative_path="test.py",
            action="indexed",
            result=result,
            content="def func1(): pass\ndef func2(): pass\nclass Class1: pass",
            language="python",
            file_hash="abc123"
        )

        assert len(buffer.symbols) == 3
        assert not buffer.is_empty()
        assert len(buffer.file_data_list) == 1

    def test_add_result_tracks_files_to_clean_for_updates(self):
        """Test that updated files are tracked for cleanup."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        result = MockExtractionResult(
            symbols=[MockSymbol(id="sym1", name="func1", kind="function", file_path="test.py")],
            identifiers=[],
            relationships=[]
        )

        # Action is "updated" - file needs old data cleaned
        buffer.add_result(
            file_path=Path("/workspace/test.py"),
            relative_path="test.py",
            action="updated",
            result=result,
            content="def func1(): pass",
            language="python",
            file_hash="abc123"
        )

        assert "test.py" in buffer.files_to_clean

    def test_add_result_does_not_track_indexed_files_for_cleanup(self):
        """Test that new (indexed) files are not tracked for cleanup."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        result = MockExtractionResult(
            symbols=[MockSymbol(id="sym1", name="func1", kind="function", file_path="test.py")],
            identifiers=[],
            relationships=[]
        )

        # Action is "indexed" - new file, no cleanup needed
        buffer.add_result(
            file_path=Path("/workspace/test.py"),
            relative_path="test.py",
            action="indexed",
            result=result,
            content="def func1(): pass",
            language="python",
            file_hash="abc123"
        )

        assert "test.py" not in buffer.files_to_clean

    def test_add_result_accumulates_identifiers(self):
        """Test that identifiers are accumulated."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        identifiers = [
            MockIdentifier(id="id1", name="var1", file_path="test.py"),
            MockIdentifier(id="id2", name="var2", file_path="test.py"),
        ]
        result = MockExtractionResult(
            symbols=[],
            identifiers=identifiers,
            relationships=[]
        )

        buffer.add_result(
            file_path=Path("/workspace/test.py"),
            relative_path="test.py",
            action="indexed",
            result=result,
            content="var1 = 1\nvar2 = 2",
            language="python",
            file_hash="abc123"
        )

        assert len(buffer.identifiers) == 2

    def test_add_result_accumulates_relationships(self):
        """Test that relationships are accumulated."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        relationships = [
            MockRelationship(source_id="sym1", target_id="sym2", kind="calls"),
        ]
        result = MockExtractionResult(
            symbols=[],
            identifiers=[],
            relationships=relationships
        )

        buffer.add_result(
            file_path=Path("/workspace/test.py"),
            relative_path="test.py",
            action="indexed",
            result=result,
            content="func1 calls func2",
            language="python",
            file_hash="abc123"
        )

        assert len(buffer.relationships) == 1


class TestFlushTrigger:
    """Test buffer flush threshold detection."""

    def test_should_flush_when_symbol_threshold_reached(self):
        """Test that buffer signals flush when symbol count reaches threshold."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=5)  # Low threshold for testing

        # Add 5 symbols (exactly at threshold)
        symbols = [
            MockSymbol(id=f"sym{i}", name=f"func{i}", kind="function", file_path="test.py")
            for i in range(5)
        ]
        result = MockExtractionResult(symbols=symbols, identifiers=[], relationships=[])

        buffer.add_result(
            file_path=Path("/workspace/test.py"),
            relative_path="test.py",
            action="indexed",
            result=result,
            content="code",
            language="python",
            file_hash="abc123"
        )

        assert buffer.should_flush()

    def test_should_not_flush_before_threshold(self):
        """Test that buffer doesn't signal flush before threshold."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        # Add only 3 symbols (well below threshold)
        symbols = [
            MockSymbol(id=f"sym{i}", name=f"func{i}", kind="function", file_path="test.py")
            for i in range(3)
        ]
        result = MockExtractionResult(symbols=symbols, identifiers=[], relationships=[])

        buffer.add_result(
            file_path=Path("/workspace/test.py"),
            relative_path="test.py",
            action="indexed",
            result=result,
            content="code",
            language="python",
            file_hash="abc123"
        )

        assert not buffer.should_flush()

    def test_should_flush_when_file_count_threshold_reached(self):
        """Test that buffer signals flush when too many files accumulated.

        This prevents metadata lists from growing too large even if
        files have few symbols.
        """
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=1000)  # High symbol threshold

        # Add 50 files with 1 symbol each (reaches file threshold before symbol threshold)
        for i in range(50):
            result = MockExtractionResult(
                symbols=[MockSymbol(id=f"sym{i}", name=f"func{i}", kind="function", file_path=f"file{i}.py")],
                identifiers=[],
                relationships=[]
            )
            buffer.add_result(
                file_path=Path(f"/workspace/file{i}.py"),
                relative_path=f"file{i}.py",
                action="indexed",
                result=result,
                content="code",
                language="python",
                file_hash=f"hash{i}"
            )

        # Should flush due to file count (50 files) even though only 50 symbols
        assert buffer.should_flush()


class TestBufferClear:
    """Test buffer clearing after flush."""

    def test_clear_resets_all_accumulators(self):
        """Test that clear() resets all data structures."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        # Add some data
        symbols = [
            MockSymbol(id="sym1", name="func1", kind="function", file_path="test.py")
        ]
        identifiers = [MockIdentifier(id="id1", name="var1", file_path="test.py")]
        relationships = [MockRelationship(source_id="sym1", target_id="sym2", kind="calls")]

        result = MockExtractionResult(
            symbols=symbols,
            identifiers=identifiers,
            relationships=relationships
        )

        buffer.add_result(
            file_path=Path("/workspace/test.py"),
            relative_path="test.py",
            action="updated",
            result=result,
            content="code",
            language="python",
            file_hash="abc123"
        )

        # Verify data was added
        assert not buffer.is_empty()
        assert len(buffer.symbols) == 1
        assert len(buffer.identifiers) == 1
        assert len(buffer.relationships) == 1
        assert len(buffer.files_to_clean) == 1

        # Clear the buffer
        buffer.clear()

        # Verify all data structures are reset
        assert buffer.is_empty()
        assert len(buffer.symbols) == 0
        assert len(buffer.identifiers) == 0
        assert len(buffer.relationships) == 0
        assert len(buffer.files_to_clean) == 0
        assert len(buffer.file_data_list) == 0
        assert not buffer.should_flush()


class TestMultipleFilesAccumulation:
    """Test buffer behavior with multiple files."""

    def test_accumulates_symbols_from_multiple_files(self):
        """Test that symbols from multiple files are accumulated."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        # Add file 1 with 2 symbols
        result1 = MockExtractionResult(
            symbols=[
                MockSymbol(id="sym1", name="func1", kind="function", file_path="file1.py"),
                MockSymbol(id="sym2", name="func2", kind="function", file_path="file1.py"),
            ],
            identifiers=[],
            relationships=[]
        )
        buffer.add_result(
            file_path=Path("/workspace/file1.py"),
            relative_path="file1.py",
            action="indexed",
            result=result1,
            content="code1",
            language="python",
            file_hash="hash1"
        )

        # Add file 2 with 3 symbols
        result2 = MockExtractionResult(
            symbols=[
                MockSymbol(id="sym3", name="func3", kind="function", file_path="file2.py"),
                MockSymbol(id="sym4", name="func4", kind="function", file_path="file2.py"),
                MockSymbol(id="sym5", name="Class1", kind="class", file_path="file2.py"),
            ],
            identifiers=[],
            relationships=[]
        )
        buffer.add_result(
            file_path=Path("/workspace/file2.py"),
            relative_path="file2.py",
            action="indexed",
            result=result2,
            content="code2",
            language="python",
            file_hash="hash2"
        )

        # Should have accumulated 5 symbols total
        assert len(buffer.symbols) == 5
        assert len(buffer.file_data_list) == 2

    def test_flush_threshold_applies_across_files(self):
        """Test that flush threshold works across multiple files."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=5)  # Low threshold

        # Add file 1 with 3 symbols
        result1 = MockExtractionResult(
            symbols=[
                MockSymbol(id=f"sym{i}", name=f"func{i}", kind="function", file_path="file1.py")
                for i in range(3)
            ],
            identifiers=[],
            relationships=[]
        )
        buffer.add_result(
            file_path=Path("/workspace/file1.py"),
            relative_path="file1.py",
            action="indexed",
            result=result1,
            content="code1",
            language="python",
            file_hash="hash1"
        )

        assert not buffer.should_flush()  # 3 < 5

        # Add file 2 with 3 more symbols (total = 6, exceeds threshold)
        result2 = MockExtractionResult(
            symbols=[
                MockSymbol(id=f"sym{i}", name=f"func{i}", kind="function", file_path="file2.py")
                for i in range(3, 6)
            ],
            identifiers=[],
            relationships=[]
        )
        buffer.add_result(
            file_path=Path("/workspace/file2.py"),
            relative_path="file2.py",
            action="indexed",
            result=result2,
            content="code2",
            language="python",
            file_hash="hash2"
        )

        assert buffer.should_flush()  # 6 >= 5


class TestCodeContextComputation:
    """Test code context tracking for grep-style output."""

    def test_stores_code_context_for_symbols(self):
        """Test that buffer can optionally track code context per symbol."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        # Create symbol at specific line
        symbols = [
            MockSymbol(
                id="sym1",
                name="calculate_age",
                kind="function",
                file_path="test.py",
                start_line=5,
                end_line=10
            )
        ]
        result = MockExtractionResult(symbols=symbols, identifiers=[], relationships=[])

        file_content = """# Header comment
import os

# Age calculation
def calculate_age(birthdate):
    '''Calculate user age.'''
    today = date.today()
    age = today.year - birthdate.year
    return age
# End
"""

        # Mock code context function
        def mock_context_fn(content, syms):
            return {s.id: f"context for {s.name}" for s in syms}

        buffer.add_result(
            file_path=Path("/workspace/test.py"),
            relative_path="test.py",
            action="indexed",
            result=result,
            content=file_content,
            language="python",
            file_hash="abc123",
            code_context_fn=mock_context_fn
        )

        # Buffer should have computed code context
        assert len(buffer.symbols) == 1
        assert "sym1" in buffer.code_context_map
        assert buffer.code_context_map["sym1"] == "context for calculate_age"


class TestIdentifierFiltering:
    """Test identifier noise filtering to reduce I/O."""

    def test_filters_single_character_identifiers(self):
        """Single-character names like 'i', 'x', 'j' are filtered out."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        assert buffer._is_useful_identifier("i") is False
        assert buffer._is_useful_identifier("x") is False
        assert buffer._is_useful_identifier("_") is False

    def test_keeps_two_character_identifiers(self):
        """Two-character names are kept (could be meaningful like 'id', 'db')."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        assert buffer._is_useful_identifier("id") is True
        assert buffer._is_useful_identifier("db") is True
        assert buffer._is_useful_identifier("fs") is True

    def test_filters_numeric_strings(self):
        """Pure numeric strings are filtered (constants, not identifiers)."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        assert buffer._is_useful_identifier("123") is False
        assert buffer._is_useful_identifier("0") is False
        assert buffer._is_useful_identifier("42") is False

    def test_filters_common_keywords(self):
        """Language keywords provide no search value."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        # Python keywords
        assert buffer._is_useful_identifier("if") is False
        assert buffer._is_useful_identifier("else") is False
        assert buffer._is_useful_identifier("return") is False
        assert buffer._is_useful_identifier("True") is False  # Case insensitive
        assert buffer._is_useful_identifier("None") is False
        assert buffer._is_useful_identifier("self") is False

        # JavaScript keywords
        assert buffer._is_useful_identifier("const") is False
        assert buffer._is_useful_identifier("let") is False
        assert buffer._is_useful_identifier("var") is False

    def test_keeps_meaningful_identifiers(self):
        """Real identifiers are kept."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        assert buffer._is_useful_identifier("calculate_age") is True
        assert buffer._is_useful_identifier("UserProfile") is True
        assert buffer._is_useful_identifier("getData") is True
        assert buffer._is_useful_identifier("MAX_RETRIES") is True

    def test_add_result_filters_identifiers(self):
        """Verify add_result applies filtering to identifiers."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        # Create mix of useful and noise identifiers
        identifiers = [
            MockIdentifier(id="id1", name="i", file_path="test.py"),  # Noise
            MockIdentifier(id="id2", name="calculate_total", file_path="test.py"),  # Useful
            MockIdentifier(id="id3", name="if", file_path="test.py"),  # Noise (keyword)
            MockIdentifier(id="id4", name="user_name", file_path="test.py"),  # Useful
            MockIdentifier(id="id5", name="123", file_path="test.py"),  # Noise (numeric)
        ]
        result = MockExtractionResult(symbols=[], identifiers=identifiers, relationships=[])

        buffer.add_result(
            file_path=Path("/workspace/test.py"),
            relative_path="test.py",
            action="indexed",
            result=result,
            content="code",
            language="python",
            file_hash="abc123"
        )

        # Should only keep 2 useful identifiers
        assert len(buffer.identifiers) == 2
        names = [ident.name for ident in buffer.identifiers]
        assert "calculate_total" in names
        assert "user_name" in names
        assert "i" not in names
        assert "if" not in names


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_empty_extraction_result(self):
        """Test that buffer handles files with no symbols gracefully."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        # Empty extraction (no symbols, identifiers, or relationships)
        result = MockExtractionResult(symbols=[], identifiers=[], relationships=[])

        buffer.add_result(
            file_path=Path("/workspace/empty.py"),
            relative_path="empty.py",
            action="indexed",
            result=result,
            content="# Empty file",
            language="python",
            file_hash="abc123"
        )

        # File metadata should still be tracked
        assert len(buffer.file_data_list) == 1
        assert len(buffer.symbols) == 0
        # is_empty checks file_data_list, not symbols
        assert not buffer.is_empty()

    def test_handles_none_attributes_gracefully(self):
        """Test that buffer handles None values in extraction results."""
        from miller.workspace.buffer import IndexingBuffer

        buffer = IndexingBuffer(max_symbols=100)

        # Result with None lists (some extractors might return None)
        @dataclass
        class ResultWithNone:
            symbols: Any = None
            identifiers: Any = None
            relationships: Any = None

        result = ResultWithNone()

        # Should not raise, should handle None gracefully
        buffer.add_result(
            file_path=Path("/workspace/test.py"),
            relative_path="test.py",
            action="indexed",
            result=result,
            content="code",
            language="python",
            file_hash="abc123"
        )

        assert len(buffer.symbols) == 0
        assert len(buffer.file_data_list) == 1
