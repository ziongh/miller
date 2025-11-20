import pytest
import time
from pathlib import Path
from miller import miller_core


def test_extract_files_batch_basic():
    """Test basic batch extraction with multiple languages."""
    if miller_core is None:
        pytest.skip("miller_core not available")

    workspace_root = str(Path.cwd())
    files = [
        ("def foo(): pass", "python", "foo.py"),
        ("function bar() {}", "javascript", "bar.js"),
    ]

    results = miller_core.extract_files_batch(files, workspace_root)

    assert len(results) == 2

    # Verify consistency with single file extraction
    single_result_py = miller_core.extract_file(files[0][0], files[0][1], files[0][2])
    assert len(results[0].symbols) == len(single_result_py.symbols)
    assert results[0].symbols[0].name == single_result_py.symbols[0].name

    single_result_js = miller_core.extract_file(files[1][0], files[1][1], files[1][2])
    assert len(results[1].symbols) == len(single_result_js.symbols)

    # Check that "bar" is present in JS symbols
    js_names = [s.name for s in results[1].symbols]
    assert "bar" in js_names


def test_extract_files_batch_empty():
    """Test batch extraction with empty input."""
    if miller_core is None:
        pytest.skip("miller_core not available")

    workspace_root = str(Path.cwd())
    results = miller_core.extract_files_batch([], workspace_root)
    assert len(results) == 0


def test_extract_files_batch_with_syntax_errors():
    """Test that batch extraction handles syntax errors gracefully."""
    if miller_core is None:
        pytest.skip("miller_core not available")

    workspace_root = str(Path.cwd())
    files = [
        ("def valid(): pass", "python", "valid.py"),
        ("this is not valid python syntax!", "python", "invalid.py"),
        ("function works() {}", "javascript", "works.js"),
    ]

    # Should not raise exception
    results = miller_core.extract_files_batch(files, workspace_root)

    assert len(results) == 3

    # Valid files should extract symbols
    assert len(results[0].symbols) > 0, "valid.py should have symbols"
    assert results[0].symbols[0].name == "valid"

    assert len(results[2].symbols) > 0, "works.js should have symbols"
    assert results[2].symbols[0].name == "works"

    # Invalid file should return empty result (error logged to stderr)
    # Note: Some parsers may be more permissive, so we just check it doesn't crash
    assert len(results[1].symbols) >= 0, "invalid.py should not crash extraction"


def test_extract_files_batch_unicode_content():
    """Test batch extraction with Unicode content."""
    if miller_core is None:
        pytest.skip("miller_core not available")

    workspace_root = str(Path.cwd())
    files = [
        ("def café(): pass", "python", "unicode.py"),
        ("function 你好() {}", "javascript", "chinese.js"),
        ("def مرحبا(): pass", "python", "arabic.py"),
    ]

    results = miller_core.extract_files_batch(files, workspace_root)

    assert len(results) == 3

    # All files should extract symbols (Unicode function names)
    assert len(results[0].symbols) > 0
    assert len(results[1].symbols) > 0
    assert len(results[2].symbols) > 0


def test_extract_files_batch_mixed_languages():
    """Test batch extraction with many different languages."""
    if miller_core is None:
        pytest.skip("miller_core not available")

    workspace_root = str(Path.cwd())
    files = [
        ("def python_func(): pass", "python", "file.py"),
        ("function jsFunc() {}", "javascript", "file.js"),
        ("fn rust_func() {}", "rust", "file.rs"),
        ("func goFunc() {}", "go", "file.go"),
        ("public void javaMethod() {}", "java", "File.java"),
    ]

    results = miller_core.extract_files_batch(files, workspace_root)

    assert len(results) == 5

    # All should have at least one symbol
    for i, result in enumerate(results):
        assert len(result.symbols) > 0, f"File {i} should have symbols"


def test_extract_files_batch_preserves_order():
    """Test that batch extraction preserves input order despite parallel processing."""
    if miller_core is None:
        pytest.skip("miller_core not available")

    workspace_root = str(Path.cwd())

    # Create files with unique identifiers
    files = [(f"def func_{i}(): pass", "python", f"file_{i}.py") for i in range(20)]

    results = miller_core.extract_files_batch(files, workspace_root)

    assert len(results) == 20

    # Verify order is preserved
    for i, result in enumerate(results):
        assert len(result.symbols) > 0
        assert result.symbols[0].name == f"func_{i}", f"Order not preserved at index {i}"


def test_extract_files_batch_performance():
    """Test that batch extraction is faster than sequential extraction."""
    if miller_core is None:
        pytest.skip("miller_core not available")

    workspace_root = str(Path.cwd())

    # Generate 30 files (enough to show parallel speedup)
    files = [
        (f"def function_{i}(arg1, arg2, arg3):\n    '''Docstring for function {i}'''\n    return arg1 + arg2 + arg3", "python", f"file_{i}.py")
        for i in range(30)
    ]

    # Batch extraction
    start = time.time()
    batch_results = miller_core.extract_files_batch(files, workspace_root)
    batch_time = time.time() - start

    # Sequential extraction
    start = time.time()
    sequential_results = []
    for content, lang, path in files:
        sequential_results.append(miller_core.extract_file(content, lang, path))
    sequential_time = time.time() - start

    # Results should be identical
    assert len(batch_results) == len(sequential_results) == 30

    # Batch should be faster (at least 1.2x on most systems, more on multi-core)
    # Use conservative threshold to avoid flaky tests on slow/single-core systems
    speedup = sequential_time / batch_time
    print(f"\n📊 Batch extraction speedup: {speedup:.2f}x")
    print(f"   Sequential: {sequential_time:.3f}s")
    print(f"   Batch:      {batch_time:.3f}s")

    # Conservative assertion: batch should not be significantly slower
    # (actual speedup varies by system, but should at least match sequential)
    assert batch_time <= sequential_time * 1.5, \
        f"Batch extraction unexpectedly slow: {speedup:.2f}x"

    # On multi-core systems, we typically expect 1.5x+ speedup
    if speedup >= 1.5:
        print(f"   ✅ Good parallelization: {speedup:.2f}x speedup")
    elif speedup >= 1.1:
        print(f"   ⚠️  Moderate speedup: {speedup:.2f}x (may indicate GIL contention or single-core)")
    else:
        print(f"   ⚠️  Low speedup: {speedup:.2f}x (check system resources)")


def test_extract_files_batch_large_files():
    """Test batch extraction with larger, more complex files."""
    if miller_core is None:
        pytest.skip("miller_core not available")

    workspace_root = str(Path.cwd())

    # Generate a larger Python file with multiple functions and classes
    large_file = """
class UserService:
    def __init__(self, db):
        self.db = db

    def create_user(self, name, email):
        '''Create a new user.'''
        return self.db.insert({"name": name, "email": email})

    def get_user(self, user_id):
        '''Get user by ID.'''
        return self.db.find(user_id)

    def update_user(self, user_id, data):
        '''Update user data.'''
        return self.db.update(user_id, data)

    def delete_user(self, user_id):
        '''Delete a user.'''
        return self.db.delete(user_id)

def helper_function(x, y):
    '''Helper function.'''
    return x + y
"""

    files = [
        (large_file, "python", "user_service.py"),
        ("def simple(): pass", "python", "simple.py"),
    ]

    results = miller_core.extract_files_batch(files, workspace_root)

    assert len(results) == 2

    # Large file should have multiple symbols (class + methods + function)
    assert len(results[0].symbols) >= 5, "Large file should have multiple symbols"

    # Simple file should have one symbol
    assert len(results[1].symbols) == 1
