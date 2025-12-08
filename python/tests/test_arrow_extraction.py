"""
Tests for Arrow-based extraction pipeline.

The Arrow pipeline eliminates GC pressure by passing columnar data
directly from Rust to Python without creating millions of Python objects.
"""

import numpy as np
import pyarrow as pa
import pytest

from miller import miller_core
from miller.workspace.arrow_buffer import ArrowIndexingBuffer


@pytest.fixture
def sample_python_file(tmp_path):
    """Create a sample Python file for testing.

    Returns:
        tuple: (relative_path, workspace_root) - relative path is what
               extract_files_to_arrow expects
    """
    code = '''
def greet(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"

class Calculator:
    """A simple calculator."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def multiply(self, a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b

def main():
    calc = Calculator()
    result = calc.add(1, 2)
    print(greet("World"))
'''
    file_path = tmp_path / "sample.py"
    file_path.write_text(code)
    # Return RELATIVE path (function expects relative paths from workspace root)
    return "sample.py", str(tmp_path)


class TestArrowExtraction:
    """Tests for miller_core.extract_files_to_arrow."""

    def test_extract_returns_arrow_batch(self, sample_python_file):
        """Arrow extraction returns ArrowExtractionBatch with all fields."""
        file_path, workspace = sample_python_file

        batch = miller_core.extract_files_to_arrow([file_path], workspace)

        assert hasattr(batch, 'symbols')
        assert hasattr(batch, 'identifiers')
        assert hasattr(batch, 'relationships')
        assert hasattr(batch, 'files')

    def test_symbols_are_pyarrow_recordbatch(self, sample_python_file):
        """Symbols field is a PyArrow RecordBatch."""
        file_path, workspace = sample_python_file

        batch = miller_core.extract_files_to_arrow([file_path], workspace)

        assert isinstance(batch.symbols, pa.RecordBatch)
        assert batch.symbols.num_rows > 0

    def test_symbols_have_expected_schema(self, sample_python_file):
        """Symbols RecordBatch has correct schema."""
        file_path, workspace = sample_python_file

        batch = miller_core.extract_files_to_arrow([file_path], workspace)
        schema = batch.symbols.schema

        # Check required fields exist
        field_names = [f.name for f in schema]
        assert 'id' in field_names
        assert 'name' in field_names
        assert 'kind' in field_names
        assert 'language' in field_names
        assert 'file_path' in field_names
        assert 'start_line' in field_names
        assert 'end_line' in field_names
        assert 'signature' in field_names
        assert 'doc_comment' in field_names

    def test_extracts_functions_and_classes(self, sample_python_file):
        """Extraction finds functions and classes."""
        file_path, workspace = sample_python_file

        batch = miller_core.extract_files_to_arrow([file_path], workspace)
        symbols_df = batch.symbols.to_pandas()

        names = symbols_df['name'].tolist()
        kinds = symbols_df['kind'].tolist()

        assert 'greet' in names
        assert 'Calculator' in names
        assert 'add' in names
        assert 'multiply' in names
        assert 'main' in names

        # Check kinds
        greet_idx = names.index('greet')
        assert kinds[greet_idx].lower() == 'function'

    def test_extracts_identifiers(self, sample_python_file):
        """Extraction includes identifiers."""
        file_path, workspace = sample_python_file

        batch = miller_core.extract_files_to_arrow([file_path], workspace)

        assert isinstance(batch.identifiers, pa.RecordBatch)
        assert batch.identifiers.num_rows > 0

    def test_file_metadata_extracted(self, sample_python_file):
        """File metadata is captured."""
        file_path, workspace = sample_python_file

        batch = miller_core.extract_files_to_arrow([file_path], workspace)
        files_df = batch.files.to_pandas()

        assert files_df.shape[0] == 1
        assert 'sample.py' in files_df['path'].iloc[0]
        assert files_df['language'].iloc[0] == 'python'


class TestArrowIndexingBuffer:
    """Tests for ArrowIndexingBuffer."""

    def test_empty_buffer(self):
        """New buffer is empty."""
        buffer = ArrowIndexingBuffer()

        assert buffer.is_empty()
        assert buffer.symbol_count == 0
        assert buffer.file_count == 0
        assert not buffer.should_flush()

    def test_add_arrow_batch(self, sample_python_file):
        """Adding batch updates counts."""
        file_path, workspace = sample_python_file
        buffer = ArrowIndexingBuffer()

        batch = miller_core.extract_files_to_arrow([file_path], workspace)
        symbols_added = buffer.add_arrow_batch(batch)

        assert symbols_added > 0
        assert buffer.symbol_count == symbols_added
        assert buffer.file_count == 1
        assert not buffer.is_empty()

    def test_should_flush_on_symbol_threshold(self, sample_python_file):
        """Buffer signals flush when symbol threshold reached."""
        file_path, workspace = sample_python_file
        buffer = ArrowIndexingBuffer(max_symbols=1)  # Very low threshold

        batch = miller_core.extract_files_to_arrow([file_path], workspace)
        buffer.add_arrow_batch(batch)

        assert buffer.should_flush()

    def test_should_flush_on_file_threshold(self, sample_python_file):
        """Buffer signals flush when file threshold reached."""
        file_path, workspace = sample_python_file
        buffer = ArrowIndexingBuffer(max_symbols=10000, max_files=1)

        batch = miller_core.extract_files_to_arrow([file_path], workspace)
        buffer.add_arrow_batch(batch)

        assert buffer.should_flush()

    def test_get_symbols_table(self, sample_python_file):
        """get_symbols_table returns concatenated Arrow table."""
        file_path, workspace = sample_python_file
        buffer = ArrowIndexingBuffer()

        batch = miller_core.extract_files_to_arrow([file_path], workspace)
        buffer.add_arrow_batch(batch)

        table = buffer.get_symbols_table()

        assert isinstance(table, pa.Table)
        assert table.num_rows > 0

    def test_get_embedding_texts(self, sample_python_file):
        """get_embedding_texts extracts text for embedding model."""
        file_path, workspace = sample_python_file
        buffer = ArrowIndexingBuffer()

        batch = miller_core.extract_files_to_arrow([file_path], workspace)
        buffer.add_arrow_batch(batch)

        texts = buffer.get_embedding_texts()

        assert len(texts) == buffer.symbol_count
        assert all(isinstance(t, str) for t in texts)
        # Check some text content
        all_text = '\n'.join(texts)
        assert 'greet' in all_text or 'Calculator' in all_text

    def test_clear_resets_buffer(self, sample_python_file):
        """clear() resets all accumulators."""
        file_path, workspace = sample_python_file
        buffer = ArrowIndexingBuffer()

        batch = miller_core.extract_files_to_arrow([file_path], workspace)
        buffer.add_arrow_batch(batch, files_to_update=['test.py'])

        buffer.clear()

        assert buffer.is_empty()
        assert buffer.symbol_count == 0
        assert buffer.file_count == 0
        assert len(buffer.files_to_clean) == 0

    def test_noise_identifier_filtering(self, tmp_path):
        """Noise identifiers are filtered out."""
        code = '''
def foo():
    for i in range(10):
        if True:
            x = data
            return result
'''
        file_path = tmp_path / "noise.py"
        file_path.write_text(code)

        buffer = ArrowIndexingBuffer()
        # Use relative path from workspace root
        batch = miller_core.extract_files_to_arrow(["noise.py"], str(tmp_path))
        buffer.add_arrow_batch(batch)

        idents_table = buffer.get_identifiers_table()
        ident_names = idents_table.column('name').to_pylist()

        # Common noise keywords should be filtered
        assert 'i' not in ident_names  # Single char
        assert 'True' not in ident_names or len([n for n in ident_names if n.lower() == 'true']) == 0
        # Real identifiers should remain
        assert 'foo' in ident_names or 'range' in ident_names


class TestArrowVectorStore:
    """Tests for VectorStore Arrow integration."""

    def test_add_symbols_arrow(self, sample_python_file):
        """add_symbols_arrow inserts data into LanceDB."""
        from miller.embeddings.vector_store import VectorStore

        file_path, workspace = sample_python_file
        buffer = ArrowIndexingBuffer()

        batch = miller_core.extract_files_to_arrow([file_path], workspace)
        buffer.add_arrow_batch(batch)

        symbols_table = buffer.get_symbols_table()
        fake_vectors = np.random.rand(symbols_table.num_rows, 896).astype(np.float32)

        vs = VectorStore(db_path=':memory:', expected_dim=896)
        added = vs.add_symbols_arrow(symbols_table, fake_vectors)

        assert added == symbols_table.num_rows
        assert vs._table.count_rows() == added

    def test_arrow_path_searchable(self, sample_python_file):
        """Data inserted via Arrow path is searchable."""
        from miller.embeddings.vector_store import VectorStore

        file_path, workspace = sample_python_file
        buffer = ArrowIndexingBuffer()

        batch = miller_core.extract_files_to_arrow([file_path], workspace)
        buffer.add_arrow_batch(batch)

        symbols_table = buffer.get_symbols_table()
        fake_vectors = np.random.rand(symbols_table.num_rows, 896).astype(np.float32)

        vs = VectorStore(db_path=':memory:', expected_dim=896)
        vs.add_symbols_arrow(symbols_table, fake_vectors)

        # Text search should work
        results = vs.search('Calculator', method='text', limit=5)

        assert len(results) > 0
        assert any('Calculator' in r.get('name', '') for r in results)


class TestArrowSQLiteStorage:
    """Tests for SQLite Arrow integration."""

    def test_add_files_from_arrow(self, sample_python_file):
        """add_files_from_arrow inserts file records."""
        from miller.storage import StorageManager

        file_path, workspace = sample_python_file
        batch = miller_core.extract_files_to_arrow([file_path], workspace)

        storage = StorageManager(':memory:')
        added = storage.add_files_from_arrow(batch.files)

        assert added == 1

    def test_add_symbols_from_arrow(self, sample_python_file):
        """add_symbols_from_arrow inserts symbols."""
        from miller.storage import StorageManager

        file_path, workspace = sample_python_file
        batch = miller_core.extract_files_to_arrow([file_path], workspace)

        storage = StorageManager(':memory:')
        storage.add_files_from_arrow(batch.files)  # FK constraint
        added = storage.add_symbols_from_arrow(batch.symbols)

        assert added > 0

    def test_symbols_queryable_after_arrow_insert(self, sample_python_file):
        """Symbols inserted via Arrow path are queryable."""
        from miller.storage import StorageManager

        file_path, workspace = sample_python_file
        batch = miller_core.extract_files_to_arrow([file_path], workspace)

        storage = StorageManager(':memory:')
        storage.add_files_from_arrow(batch.files)
        storage.add_symbols_from_arrow(batch.symbols)

        sym = storage.get_symbol_by_name('Calculator')

        assert sym is not None
        assert sym['name'] == 'Calculator'
        assert sym['kind'].lower() == 'class'

    def test_full_arrow_pipeline(self, sample_python_file):
        """Full pipeline: Arrow extraction → buffer → SQLite + LanceDB."""
        from miller.storage import StorageManager
        from miller.embeddings.vector_store import VectorStore

        file_path, workspace = sample_python_file

        # Extract
        batch = miller_core.extract_files_to_arrow([file_path], workspace)

        # Buffer
        buffer = ArrowIndexingBuffer()
        buffer.add_arrow_batch(batch)

        # Get tables
        symbols_table = buffer.get_symbols_table()
        identifiers_table = buffer.get_identifiers_table()
        relationships_table = buffer.get_relationships_table()
        files_table = buffer.get_files_table()

        # SQLite
        storage = StorageManager(':memory:')
        storage.add_files_from_arrow(files_table)
        storage.add_symbols_from_arrow(symbols_table)
        storage.add_identifiers_from_arrow(identifiers_table)
        storage.add_relationships_from_arrow(relationships_table)

        # VectorStore
        fake_vectors = np.random.rand(symbols_table.num_rows, 896).astype(np.float32)
        vs = VectorStore(db_path=':memory:', expected_dim=896)
        vs.add_symbols_arrow(symbols_table, fake_vectors)

        # Verify both stores
        sql_sym = storage.get_symbol_by_name('greet')
        lance_results = vs.search('greet', method='text', limit=1)

        assert sql_sym is not None
        assert len(lance_results) > 0
