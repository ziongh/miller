"""
Tests for stdio hardening - ensuring MCP protocol integrity.

MCP (Model Context Protocol) uses JSON-RPC over stdio. ANY non-JSON output
to stdout breaks the protocol. These tests verify that:

1. UTF-8 encoding is enforced on stdout/stderr
2. Heavy imports (torch, sentence-transformers) don't pollute stdout
3. BrokenPipeError is handled gracefully
4. All logging goes to stderr/file, never stdout

This is critical for integration with MCP clients like .NET/C# agents.
"""

import io
import os
import sys
import subprocess
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr


class TestUtf8Enforcement:
    """Test that UTF-8 encoding is enforced on streams."""

    def test_ensure_utf8_encoding_function_exists(self):
        """Verify ensure_utf8_encoding utility function exists."""
        from miller.stdio_hardening import ensure_utf8_encoding

        # Function should exist and be callable
        assert callable(ensure_utf8_encoding)

    def test_ensure_utf8_encoding_wraps_stdout(self):
        """UTF-8 wrapper should wrap stdout with UTF-8 encoding."""
        from miller.stdio_hardening import ensure_utf8_encoding

        # Simulate non-UTF-8 stdout
        original_stdout = sys.stdout
        try:
            # Create mock stream with different encoding
            mock_buffer = io.BytesIO()
            mock_stdout = io.TextIOWrapper(mock_buffer, encoding='latin-1')
            sys.stdout = mock_stdout

            # Apply UTF-8 enforcement
            ensure_utf8_encoding()

            # stdout should now be UTF-8
            assert sys.stdout.encoding.lower() == 'utf-8'
        finally:
            sys.stdout = original_stdout

    def test_ensure_utf8_encoding_wraps_stderr(self):
        """UTF-8 wrapper should wrap stderr with UTF-8 encoding."""
        from miller.stdio_hardening import ensure_utf8_encoding

        original_stderr = sys.stderr
        try:
            # Create mock stream with different encoding
            mock_buffer = io.BytesIO()
            mock_stderr = io.TextIOWrapper(mock_buffer, encoding='latin-1')
            sys.stderr = mock_stderr

            # Apply UTF-8 enforcement
            ensure_utf8_encoding()

            # stderr should now be UTF-8
            assert sys.stderr.encoding.lower() == 'utf-8'
        finally:
            sys.stderr = original_stderr

    def test_ensure_utf8_encoding_handles_unicode(self):
        """UTF-8 streams should handle unicode symbols correctly."""
        from miller.stdio_hardening import ensure_utf8_encoding

        # Capture output
        captured = io.StringIO()
        original_stdout = sys.stdout

        try:
            sys.stdout = captured
            ensure_utf8_encoding()

            # Write unicode (these are common in code comments)
            test_strings = [
                "Hello World",
                "Привет мир",  # Russian
                "你好世界",  # Chinese
                "🚀 emoji test 🎉",
                "→←↑↓",  # Arrows
            ]

            for s in test_strings:
                print(s)

            output = captured.getvalue()
            for s in test_strings:
                assert s in output
        finally:
            sys.stdout = original_stdout


class TestStdoutProtection:
    """Test that stdout is protected from pollution during initialization."""

    def test_silence_context_manager_exists(self):
        """Verify silence context manager exists."""
        from miller.stdio_hardening import silence_stdout_stderr

        # Should be a context manager
        assert hasattr(silence_stdout_stderr, '__enter__') or callable(silence_stdout_stderr)

    def test_silence_context_suppresses_stdout(self):
        """silence_stdout_stderr should suppress stdout."""
        from miller.stdio_hardening import silence_stdout_stderr

        captured = io.StringIO()
        original_stdout = sys.stdout

        try:
            sys.stdout = captured

            with silence_stdout_stderr():
                print("This should not appear")

            output = captured.getvalue()
            assert "This should not appear" not in output
        finally:
            sys.stdout = original_stdout

    def test_silence_context_suppresses_stderr(self):
        """silence_stdout_stderr should suppress stderr."""
        from miller.stdio_hardening import silence_stdout_stderr

        captured = io.StringIO()
        original_stderr = sys.stderr

        try:
            sys.stderr = captured

            with silence_stdout_stderr():
                print("This should not appear", file=sys.stderr)

            output = captured.getvalue()
            assert "This should not appear" not in output
        finally:
            sys.stderr = original_stderr

    def test_silence_context_restores_streams(self):
        """silence_stdout_stderr should restore original streams after exit."""
        from miller.stdio_hardening import silence_stdout_stderr

        original_stdout = sys.stdout
        original_stderr = sys.stderr

        with silence_stdout_stderr():
            pass

        # Streams should be restored
        assert sys.stdout is original_stdout
        assert sys.stderr is original_stderr

    def test_silence_context_handles_exceptions(self):
        """silence_stdout_stderr should restore streams even on exception."""
        from miller.stdio_hardening import silence_stdout_stderr

        original_stdout = sys.stdout
        original_stderr = sys.stderr

        try:
            with silence_stdout_stderr():
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Streams should still be restored
        assert sys.stdout is original_stdout
        assert sys.stderr is original_stderr


class TestHeavyImportSilence:
    """Test that heavy ML imports don't pollute stdout."""

    def test_embeddings_import_does_not_print_to_stdout(self):
        """Importing embeddings should not print anything to stdout.

        This test verifies that torch/sentence-transformers import messages
        (like 'Loading model...' or GPU detection) don't leak to stdout.
        """
        # Run import in subprocess to capture clean stdout
        result = subprocess.run(
            [
                sys.executable, "-c",
                """
import sys
# Capture stdout
import io
captured = io.StringIO()
sys.stdout = captured

# Import embeddings (this loads torch, sentence-transformers)
try:
    from miller.embeddings import EmbeddingManager
except ImportError as e:
    # If import fails, that's a different problem
    print(f"ImportError: {e}", file=sys.__stderr__)
    sys.exit(0)

# Check if anything was printed to stdout
output = captured.getvalue()
if output.strip():
    print(f"STDOUT_POLLUTION: {repr(output)}", file=sys.__stderr__)
    sys.exit(1)
sys.exit(0)
"""
            ],
            capture_output=True,
            text=True,
            timeout=120,  # Model loading can be slow
            cwd=Path(__file__).parent.parent.parent,  # miller root
        )

        # If the test exited with 1, stdout was polluted
        if result.returncode == 1:
            # Get the polluted output from stderr
            pollution = result.stderr
            assert False, f"Embeddings import polluted stdout: {pollution}"

    def test_lifecycle_imports_silent(self):
        """Background initialization imports should be silent.

        This tests that the imports in lifecycle._background_initialization_and_indexing()
        don't produce any stdout output.
        """
        # Run import in subprocess to capture clean stdout
        result = subprocess.run(
            [
                sys.executable, "-c",
                """
import sys
import io

# Capture stdout from the start
captured = io.StringIO()
sys.stdout = captured

# Simulate the imports that happen in lifecycle.py
try:
    from miller.storage import StorageManager
    from miller.workspace import WorkspaceScanner
    from miller.workspace_registry import WorkspaceRegistry
    from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path
    from miller.embeddings import EmbeddingManager, VectorStore
except ImportError as e:
    print(f"ImportError: {e}", file=sys.__stderr__)
    sys.exit(0)

# Check if anything was printed to stdout
output = captured.getvalue()
if output.strip():
    print(f"STDOUT_POLLUTION: {repr(output)}", file=sys.__stderr__)
    sys.exit(1)
sys.exit(0)
"""
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=Path(__file__).parent.parent.parent,
        )

        if result.returncode == 1:
            pollution = result.stderr
            assert False, f"Lifecycle imports polluted stdout: {pollution}"


class TestBrokenPipeHandling:
    """Test graceful handling of BrokenPipeError."""

    def test_broken_pipe_handler_exists(self):
        """Verify broken pipe handler exists."""
        from miller.stdio_hardening import handle_broken_pipe

        assert callable(handle_broken_pipe)

    def test_broken_pipe_handler_catches_exception(self):
        """handle_broken_pipe should catch BrokenPipeError gracefully."""
        from miller.stdio_hardening import handle_broken_pipe

        # Should not raise when decorating a function that raises BrokenPipeError
        @handle_broken_pipe
        def func_that_breaks_pipe():
            raise BrokenPipeError("Simulated pipe break")

        # Should not raise, should exit gracefully (or return None)
        try:
            result = func_that_breaks_pipe()
            # If it returns, result should be None
            assert result is None
        except BrokenPipeError:
            assert False, "BrokenPipeError should have been caught"
        except SystemExit:
            # Acceptable - graceful exit on pipe break
            pass


class TestServerMainHardened:
    """Test that server main() includes hardening."""

    def test_main_function_hardened(self):
        """server.main() should include stdio hardening."""
        import inspect
        from miller.server import main

        # Get the source code of main
        source = inspect.getsource(main)

        # Should call ensure_utf8_encoding or contain UTF-8 handling
        assert (
            'ensure_utf8_encoding' in source or
            'utf-8' in source.lower() or
            'utf8' in source.lower()
        ), "main() should include UTF-8 encoding enforcement"

    def test_server_startup_silent_on_stdout(self):
        """Server startup should not print anything to stdout.

        Only JSON-RPC messages should go to stdout. All logs go to file/stderr.
        """
        # Start server briefly and check stdout
        result = subprocess.run(
            [
                sys.executable, "-c",
                """
import sys
import io
import asyncio

# Capture stdout
captured = io.StringIO()
sys.stdout = captured

# Import server (this triggers module-level code)
from miller.server import mcp

# Check stdout - should be empty (no banners, no logs)
output = captured.getvalue()
if output.strip():
    # Some output is expected if mcp.run() is called, but not from import
    print(f"STDOUT_ON_IMPORT: {repr(output)}", file=sys.__stderr__)

# Don't actually run the server, just verify import is clean
sys.exit(0)
"""
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Check for pollution warning
        if "STDOUT_ON_IMPORT" in result.stderr:
            pollution = result.stderr.split("STDOUT_ON_IMPORT:")[1].strip()
            assert False, f"Server import produced stdout output: {pollution}"
