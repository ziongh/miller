"""
Test that the miller_core Rust extension module loads correctly.

This is our first test - it will fail until we build the Rust extension.
"""

import pytest


def test_miller_core_imports():
    """Test that miller_core module can be imported."""
    try:
        from miller import miller_core
        assert miller_core is not None
    except ImportError as e:
        pytest.fail(f"Failed to import miller_core: {e}")


def test_miller_core_has_version():
    """Test that miller_core exposes a version."""
    from miller import miller_core
    assert hasattr(miller_core, "__version__")
    assert isinstance(miller_core.__version__, str)
    assert len(miller_core.__version__) > 0


def test_miller_package_imports():
    """Test that the miller Python package imports."""
    import miller
    assert miller.__version__ == "0.1.0"
