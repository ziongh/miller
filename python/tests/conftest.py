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
