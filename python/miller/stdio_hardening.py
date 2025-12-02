"""
Stdio hardening utilities for MCP protocol integrity.

MCP (Model Context Protocol) uses JSON-RPC over stdio. ANY non-JSON output
to stdout breaks the protocol and causes client deserialization failures.

This module provides:
1. UTF-8 encoding enforcement on stdout/stderr
2. Context manager to silence stdout/stderr during heavy imports
3. BrokenPipeError handler for graceful shutdown

CRITICAL: These utilities are essential for integration with MCP clients
(like custom agents) that rely on clean stdio streams.
"""

import functools
import io
import os
import sys
from contextlib import contextmanager
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)


def ensure_utf8_encoding() -> None:
    """
    Enforce UTF-8 encoding on stdout and stderr.

    This prevents encoding mismatches when transmitting JSON-RPC messages
    containing unicode characters (code symbols, emojis, non-ASCII comments).

    Should be called early in main() before any output is produced.
    """
    # Wrap stdout with UTF-8 if not already
    if hasattr(sys.stdout, "buffer") and (sys.stdout.encoding or "").lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer,
            encoding="utf-8",
            errors="backslashreplace",
            line_buffering=sys.stdout.line_buffering,
        )

    # Wrap stderr with UTF-8 if not already
    if hasattr(sys.stderr, "buffer") and (sys.stderr.encoding or "").lower() != "utf-8":
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer,
            encoding="utf-8",
            errors="backslashreplace",
            line_buffering=sys.stderr.line_buffering,
        )


@contextmanager
def silence_stdout_stderr():
    """
    Context manager to temporarily redirect stdout and stderr to /dev/null.

    Use this to wrap heavy imports that may produce output (torch, transformers).
    Streams are always restored after exit, even if an exception occurs.

    Example:
        with silence_stdout_stderr():
            import torch
            from sentence_transformers import SentenceTransformer
    """
    # Save original streams
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    try:
        # Open devnull and redirect
        devnull = open(os.devnull, "w")
        sys.stdout = devnull
        sys.stderr = devnull
        yield
    finally:
        # Always restore original streams
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        # Close devnull (suppress errors if already closed)
        try:
            devnull.close()
        except Exception:
            # Suppress close errors - file may already be closed or invalid
            pass


def handle_broken_pipe(func: F) -> F:
    """
    Decorator to handle BrokenPipeError gracefully.

    When an MCP client disconnects unexpectedly, writing to stdout
    raises BrokenPipeError. This decorator catches it and exits cleanly
    instead of producing a stack trace.

    Usage:
        @handle_broken_pipe
        def main():
            mcp.run()

    Args:
        func: The function to wrap

    Returns:
        Wrapped function that handles BrokenPipeError
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BrokenPipeError:
            # Client disconnected - exit cleanly
            # Flush stderr to ensure any pending messages are sent
            try:
                sys.stderr.flush()
            except Exception:
                # Ignore flush errors - stderr may be broken too during shutdown
                pass
            # Exit without error (client disconnect is normal)
            sys.exit(0)

    return wrapper  # type: ignore


def harden_stdio() -> None:
    """
    Apply all stdio hardening measures.

    This is a convenience function that applies all hardening:
    1. Ensures UTF-8 encoding on streams
    2. Sets environment variables for Python encoding defaults

    Call this at the very start of main() for maximum protection.
    """
    # Set environment variables for consistent encoding
    # These affect child processes and some libraries
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")

    # Apply UTF-8 encoding to streams
    ensure_utf8_encoding()
