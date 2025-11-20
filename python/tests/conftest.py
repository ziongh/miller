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
            relative_path = file_path.name  # Use filename for test files
            result = server.miller_core.extract_file(content, language, relative_path)

            # Compute hash
            file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            # Store file metadata
            server.storage.add_file(
                file_path=relative_path,
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


