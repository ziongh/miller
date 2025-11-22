"""
Pytest configuration and fixtures for Miller tests.

Specialized fixtures are organized in the fixtures/ directory:
- fixtures.trace_basic: Basic trace workspace fixtures
- fixtures.trace_advanced: Advanced trace scenarios (semantic, cyclic)
- fixtures.trace_edge: Edge cases (ambiguous symbols)
- fixtures.memory: Memory tool fixtures (checkpoint, recall, plan)
- fixtures.watcher: FileWatcher fixtures
"""

import pytest
from pathlib import Path

# Load fixture modules
pytest_plugins = [
    "tests.fixtures.trace_basic",
    "tests.fixtures.trace_advanced",
    "tests.fixtures.trace_edge",
    "tests.fixtures.memory",
    "tests.fixtures.watcher",
]


@pytest.fixture
def sample_python_code():
    """Sample Python code for testing extraction."""
    return """
def hello(name: str) -> str:
    '''Say hello to someone.'''
    return f"Hello, {name}!"

class Greeter:
    def __init__(self):
        self.greeting = "Hello"

    def greet(self, name: str):
        return hello(name)
"""


@pytest.fixture
def sample_javascript_code():
    """Sample JavaScript code for testing extraction."""
    return """
function hello(name) {
    return `Hello, ${name}!`;
}

class Greeter {
    constructor() {
        this.greeting = "Hello";
    }

    greet(name) {
        return hello(name);
    }
}
"""


@pytest.fixture
def temp_file(tmp_path):
    """Create a temporary file for testing."""
    def _create_file(content: str, extension: str = ".py"):
        file_path = tmp_path / f"test{extension}"
        file_path.write_text(content)
        return file_path
    return _create_file


@pytest.fixture
def storage_manager():
    """
    Provide a properly managed StorageManager for tests.

    Automatically closes database connections after test completes
    to prevent resource leaks.
    """
    from miller.storage import StorageManager

    storage = StorageManager(db_path=":memory:")
    yield storage
    storage.close()


@pytest.fixture
def vector_store():
    """
    Provide a properly managed VectorStore for tests.

    Automatically closes connections after test completes.
    """
    from miller.embeddings import VectorStore
    import tempfile
    import shutil
    from pathlib import Path

    # Use temp directory for vector store (LanceDB requires file path)
    temp_dir = Path(tempfile.mkdtemp(prefix="miller_vector_test_"))
    db_path = temp_dir / "vectors.lance"

    store = VectorStore(db_path=str(db_path))
    yield store

    # Cleanup
    try:
        if hasattr(store, 'close'):
            store.close()
    except:
        pass
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_server_storage():
    """
    Clean server storage before each test.

    This fixture runs automatically before each test to ensure
    tests don't interfere with each other by using fresh in-memory databases.
    """
    import miller.server as server
    from miller.storage import StorageManager
    from miller.embeddings import VectorStore

    # Close old connections if they exist
    if hasattr(server.storage, 'conn'):
        server.storage.conn.close()
    if hasattr(server.vector_store, 'close'):
        try:
            server.vector_store.close()
        except:
            pass

    # Replace global instances with fresh in-memory databases
    server.storage = StorageManager(db_path=":memory:")
    server.vector_store = VectorStore(db_path=":memory:")

    # Initialize embeddings manager if not already initialized (expensive operation)
    if server.embeddings is None:
        from miller.embeddings import EmbeddingManager
        server.embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="cpu")

    # Initialize scanner for tests (only if WorkspaceScanner is available)
    try:
        from miller.workspace import WorkspaceScanner
        server.scanner = WorkspaceScanner(
            workspace_root=Path.cwd(),
            storage=server.storage,
            embeddings=server.embeddings,
            vector_store=server.vector_store
        )
    except (ImportError, ModuleNotFoundError):
        # WorkspaceScanner not yet available, skip initialization
        server.scanner = None

    yield

    # Cleanup: close connections
    if hasattr(server.storage, 'conn'):
        server.storage.conn.close()
    if hasattr(server.vector_store, 'close'):
        try:
            server.vector_store.close()
        except:
            pass


@pytest.fixture
def storage_with_test_data():
    """
    Populate global server storage with test data for fast_refs tests.

    Creates symbols with different reference counts:
    - test_function: 15 references (triggers TOON in auto mode)
    - small_symbol: 5 references (uses JSON in auto mode)
    - large_symbol: 25 references (triggers TOON in auto mode)
    """
    import miller.server as server
    from miller import miller_core

    # Index test code with multiple symbols and references
    code = """
def test_function():
    '''A function with many references.'''
    pass

def small_symbol():
    '''A function with few references.'''
    pass

def large_symbol():
    '''A function with many references.'''
    pass

# Create references to test_function (15 calls)
def caller1(): test_function()
def caller2(): test_function()
def caller3(): test_function()
def caller4(): test_function()
def caller5(): test_function()
def caller6(): test_function()
def caller7(): test_function()
def caller8(): test_function()
def caller9(): test_function()
def caller10(): test_function()
def caller11(): test_function()
def caller12(): test_function()
def caller13(): test_function()
def caller14(): test_function()
def caller15(): test_function()

# Create references to small_symbol (5 calls)
def small_caller1(): small_symbol()
def small_caller2(): small_symbol()
def small_caller3(): small_symbol()
def small_caller4(): small_symbol()
def small_caller5(): small_symbol()

# Create references to large_symbol (25 calls)
def large_caller1(): large_symbol()
def large_caller2(): large_symbol()
def large_caller3(): large_symbol()
def large_caller4(): large_symbol()
def large_caller5(): large_symbol()
def large_caller6(): large_symbol()
def large_caller7(): large_symbol()
def large_caller8(): large_symbol()
def large_caller9(): large_symbol()
def large_caller10(): large_symbol()
def large_caller11(): large_symbol()
def large_caller12(): large_symbol()
def large_caller13(): large_symbol()
def large_caller14(): large_symbol()
def large_caller15(): large_symbol()
def large_caller16(): large_symbol()
def large_caller17(): large_symbol()
def large_caller18(): large_symbol()
def large_caller19(): large_symbol()
def large_caller20(): large_symbol()
def large_caller21(): large_symbol()
def large_caller22(): large_symbol()
def large_caller23(): large_symbol()
def large_caller24(): large_symbol()
def large_caller25(): large_symbol()
"""

    # Extract and store symbols
    result = miller_core.extract_file(code, "python", "test_refs.py")

    # Add file to storage
    server.storage.add_file(
        file_path="test_refs.py",
        language="python",
        content=code,
        hash="test_hash",
        size=len(code)
    )

    # Add symbols and relationships using batch methods
    server.storage.add_symbols_batch(result.symbols)
    server.storage.add_relationships_batch(result.relationships)

    return server.storage


@pytest.fixture
def index_file_helper():
    """
    Provide an async helper function for indexing files in tests.

    Returns an async function that directly indexes a file using storage/embeddings,
    bypassing workspace boundaries (useful for test files in temp directories).
    """
    async def _index_file(file_path: str | Path) -> bool:
        """Index a single file for testing."""
        import miller.server as server
        from pathlib import Path
        import hashlib
        import numpy as np

        file_path = Path(file_path)

        if not file_path.exists():
            return False

        # Check if miller_core is available
        if server.miller_core is None:
            return False

        try:
            # Read file content
            content = file_path.read_text(encoding="utf-8")

            # Detect language
            language = server.miller_core.detect_language(str(file_path))
            if not language:
                return False

            # Extract symbols
            # Use absolute path so context extraction can find the file
            stored_path = str(file_path.resolve())
            result = server.miller_core.extract_file(content, language, stored_path)

            # Compute hash
            file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            # Store file metadata
            server.storage.add_file(
                file_path=stored_path,
                language=language,
                content=content,
                hash=file_hash,
                size=len(content)
            )

            # Store symbols and generate embeddings
            if result.symbols:
                server.storage.add_symbols_batch(result.symbols)

                # Generate embeddings
                embeddings_list = []
                for sym in result.symbols:
                    search_text = f"{sym.name} {sym.kind}"
                    if sym.signature:
                        search_text += f" {sym.signature}"
                    if sym.doc_comment:
                        search_text += f" {sym.doc_comment}"

                    vec = server.embeddings.embed_query(search_text)
                    embeddings_list.append(vec)

                # Add to vector store
                vectors_array = np.array(embeddings_list, dtype=np.float32)
                server.vector_store.add_symbols(result.symbols, vectors_array)

            # Store identifiers
            if result.identifiers:
                server.storage.add_identifiers_batch(result.identifiers)

            # Store relationships
            if result.relationships:
                server.storage.add_relationships_batch(result.relationships)

            return True

        except Exception:
            return False

    return _index_file


