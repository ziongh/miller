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
