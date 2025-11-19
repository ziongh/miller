"""
Pytest configuration and fixtures for Miller tests.
"""

import pytest
from pathlib import Path


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
    from miller import server
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
    # Keep same embeddings manager (model loading is expensive)

    yield

    # Cleanup: close connections
    if hasattr(server.storage, 'conn'):
        server.storage.conn.close()
    if hasattr(server.vector_store, 'close'):
        try:
            server.vector_store.close()
        except:
            pass
