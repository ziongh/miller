"""
Common utilities for tool wrappers.

Contains the _await_ready function and error messages shared by all wrappers.
"""

import asyncio
from miller import server_state


# Error messages for initialization states
TIMEOUT_MSG = (
    "❌ Miller initialization timed out after {timeout}s. "
    "This may indicate a startup problem - check .miller/miller.log for details."
)
VECTORS_NOT_READY_MSG = (
    "⚠️ Miller core is ready but vector store is still initializing. "
    "This tool requires semantic search. Please retry in a few seconds."
)


async def await_ready(require_vectors: bool = True) -> str | None:
    """
    Wait for server components to be ready, with timeout.

    This is the agent-friendly replacement for the old _check_ready().
    Instead of immediately returning an error string (which agents may
    misinterpret as a permanent failure), this function WAITS for
    initialization to complete.

    Why this matters (Windows pipe deadlock workaround):
    - On Windows, heavy imports run synchronously (5-15 seconds)
    - MCP handshake completes immediately (server appears "ready")
    - But tools would fail because storage/embeddings are None
    - OLD: Return error string → agents give up or spam retries
    - NEW: Await event → tools "just work" after brief pause

    Args:
        require_vectors: Whether vector_store is required (some tools don't need it)

    Returns:
        None if ready, error message string if timeout or still not ready
    """
    event = server_state.get_initialization_event()
    timeout = server_state.INITIALIZATION_TIMEOUT_SECONDS

    # Wait for initialization_complete event with timeout
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        return TIMEOUT_MSG.format(timeout=timeout)

    # Double-check components are actually ready (defensive)
    # This should always pass after the event is set, but safety first
    if server_state.storage is None:
        return TIMEOUT_MSG.format(timeout=timeout)

    # Some tools (get_symbols, fast_refs, etc.) don't need vector store
    if require_vectors and server_state.vector_store is None:
        return VECTORS_NOT_READY_MSG

    return None
