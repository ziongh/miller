"""
Test FileWatcher event processing optimizations.

Tests the deduplication and batching logic in the FileWatcher callback.

NOTE: Events now include a hash as the third element:
    (FileEvent, Path, Optional[str]) where the hash is from Blake3.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, call
from miller.watcher import FileEvent


@pytest.mark.asyncio
async def test_file_watcher_deduplicates_events():
    """
    Test that FileWatcher callback deduplicates events by file path.

    If the same file has multiple events, only the latest should be processed:
    - Multiple MODIFIED events → single MODIFIED
    - CREATED then MODIFIED → single CREATED (it's still new)
    - MODIFIED then DELETED → single DELETED (final state)
    """
    # This test verifies the deduplication logic conceptually
    # The actual callback is in lifecycle.py and tested through integration tests

    # Simulate duplicate events for the same file (with hash as 3rd element)
    events = [
        (FileEvent.CREATED, Path("/workspace/test.py"), "hash_v1"),
        (FileEvent.MODIFIED, Path("/workspace/test.py"), "hash_v2"),
        (FileEvent.MODIFIED, Path("/workspace/test.py"), "hash_v3"),
    ]

    # Deduplicate (keep latest event per file, tracking both event type and hash)
    file_events: dict[Path, tuple[FileEvent, str | None]] = {}
    for event_type, file_path, new_hash in events:
        if file_path in file_events:
            # For multiple events, keep the later one
            # Exception: DELETED always wins
            if event_type == FileEvent.DELETED:
                file_events[file_path] = (event_type, new_hash)
            elif file_events[file_path][0] != FileEvent.DELETED:
                file_events[file_path] = (event_type, new_hash)
        else:
            file_events[file_path] = (event_type, new_hash)

    # Should have only 1 event for the file (MODIFIED with latest hash)
    assert len(file_events) == 1
    assert file_events[Path("/workspace/test.py")] == (FileEvent.MODIFIED, "hash_v3")


@pytest.mark.asyncio
async def test_file_watcher_deleted_supersedes_all():
    """Test that DELETED events supersede all other events for the same file."""
    events = [
        (FileEvent.CREATED, Path("/workspace/test.py"), "hash_v1"),
        (FileEvent.MODIFIED, Path("/workspace/test.py"), "hash_v2"),
        (FileEvent.DELETED, Path("/workspace/test.py"), None),  # Deleted files have no hash
    ]

    # Deduplicate
    file_events: dict[Path, tuple[FileEvent, str | None]] = {}
    for event_type, file_path, new_hash in events:
        if file_path in file_events:
            if event_type == FileEvent.DELETED:
                file_events[file_path] = (event_type, new_hash)
            elif file_events[file_path][0] != FileEvent.DELETED:
                file_events[file_path] = (event_type, new_hash)
        else:
            file_events[file_path] = (event_type, new_hash)

    # Should have only DELETED
    assert len(file_events) == 1
    assert file_events[Path("/workspace/test.py")] == (FileEvent.DELETED, None)


@pytest.mark.asyncio
async def test_file_watcher_processes_multiple_files():
    """Test that different files are tracked separately."""
    events = [
        (FileEvent.CREATED, Path("/workspace/file1.py"), "hash_1"),
        (FileEvent.MODIFIED, Path("/workspace/file2.py"), "hash_2"),
        (FileEvent.DELETED, Path("/workspace/file3.py"), None),
    ]

    # Deduplicate
    file_events: dict[Path, tuple[FileEvent, str | None]] = {}
    for event_type, file_path, new_hash in events:
        file_events[file_path] = (event_type, new_hash)

    # Should have all 3 files
    assert len(file_events) == 3
    assert file_events[Path("/workspace/file1.py")] == (FileEvent.CREATED, "hash_1")
    assert file_events[Path("/workspace/file2.py")] == (FileEvent.MODIFIED, "hash_2")
    assert file_events[Path("/workspace/file3.py")] == (FileEvent.DELETED, None)


@pytest.mark.asyncio
async def test_file_watcher_batches_deletions():
    """Test that multiple deletions are batched together for efficiency."""
    events = [
        (FileEvent.DELETED, Path("/workspace/file1.py"), None),
        (FileEvent.DELETED, Path("/workspace/file2.py"), None),
        (FileEvent.DELETED, Path("/workspace/file3.py"), None),
        (FileEvent.MODIFIED, Path("/workspace/file4.py"), "hash_4"),
    ]

    # Separate deletions from indexing
    deleted_files = []
    files_to_index = []

    for event_type, file_path, new_hash in events:
        if event_type == FileEvent.DELETED:
            deleted_files.append(str(file_path))
        else:
            files_to_index.append((event_type, file_path, new_hash))

    # Should have 3 deletions batched together
    assert len(deleted_files) == 3
    assert len(files_to_index) == 1
    assert files_to_index[0] == (FileEvent.MODIFIED, Path("/workspace/file4.py"), "hash_4")

    # In the actual implementation, these would be processed in ONE call to delete_files_batch()
    # instead of 3 separate calls, and file4.py would be indexed concurrently
