"""
Unit tests for trace_call_path (no Rust extension required).

Tests the core traversal logic with hand-crafted test data.
"""

import pytest

from miller.storage import StorageManager
from miller.tools.trace import trace_call_path


@pytest.fixture
def simple_trace_db(tmp_path):
    """
    Create a simple database with traced relationships.

    Structure:
        function_a (id:a1) calls function_b (id:b1)
        function_a (id:a1) calls function_c (id:c1)
        function_c (id:c1) calls function_b (id:b1)
    """
    db_path = tmp_path / "test_trace.db"
    storage = StorageManager(db_path=str(db_path))

    # Add file
    storage.conn.execute(
        "INSERT INTO files (path, language, hash, size, last_modified) VALUES (?, ?, ?, ?, ?)",
        ("test.py", "python", "hash123", 100, 0),
    )

    # Add symbols
    storage.conn.execute(
        """
        INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line, signature, doc_comment)
        VALUES
            ('a1', 'function_a', 'Function', 'python', 'test.py', 1, 3, '()', NULL),
            ('b1', 'function_b', 'Function', 'python', 'test.py', 5, 7, '()', NULL),
            ('c1', 'function_c', 'Function', 'python', 'test.py', 9, 11, '()', NULL)
        """
    )

    # Add relationships
    storage.conn.execute(
        """
        INSERT INTO relationships (id, from_symbol_id, to_symbol_id, kind, file_path)
        VALUES
            ('r1', 'a1', 'b1', 'Call', 'test.py'),
            ('r2', 'a1', 'c1', 'Call', 'test.py'),
            ('r3', 'c1', 'b1', 'Call', 'test.py')
        """
    )

    storage.conn.commit()
    return storage


@pytest.mark.asyncio
async def test_symbol_not_found(simple_trace_db):
    """Test error handling when symbol doesn't exist."""
    result = await trace_call_path(
        storage=simple_trace_db,
        symbol_name="nonexistent",
        direction="downstream",
        max_depth=3,
    )

    assert result["query_symbol"] == "nonexistent"
    assert result["total_nodes"] == 0
    assert "error" in result
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_symbol_with_no_relationships(tmp_path):
    """Test symbol that exists but has no relationships."""
    db_path = tmp_path / "isolated.db"
    storage = StorageManager(db_path=str(db_path))

    # Add file and isolated symbol
    storage.conn.execute(
        "INSERT INTO files (path, language, hash, size, last_modified) VALUES (?, ?, ?, ?, ?)",
        ("test.py", "python", "hash123", 100, 0),
    )
    storage.conn.execute(
        """
        INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
        VALUES ('iso1', 'isolated_function', 'Function', 'python', 'test.py', 1, 3)
        """,
    )
    storage.conn.commit()

    result = await trace_call_path(
        storage=storage,
        symbol_name="isolated_function",
        direction="both",
        max_depth=3,
    )

    assert result["total_nodes"] == 1
    assert result["truncated"] is False
    assert result["root"]["name"] == "isolated_function"
    assert len(result["root"]["children"]) == 0


@pytest.mark.asyncio
async def test_downstream_single_level(simple_trace_db):
    """Test downstream tracing for a single level."""
    result = await trace_call_path(
        storage=simple_trace_db,
        symbol_name="function_a",
        direction="downstream",
        max_depth=1,
    )

    assert result["query_symbol"] == "function_a"
    assert result["direction"] == "downstream"
    assert result["max_depth"] == 1

    root = result["root"]
    assert root["name"] == "function_a"
    assert root["depth"] == 0
    assert len(root["children"]) == 2

    # Children should be function_b and function_c
    child_names = {child["name"] for child in root["children"]}
    assert child_names == {"function_b", "function_c"}

    # All children should be at depth 1
    for child in root["children"]:
        assert child["depth"] == 1
        assert child["relationship_kind"] == "Call"


@pytest.mark.asyncio
async def test_upstream_single_level(simple_trace_db):
    """Test upstream tracing for a single level."""
    result = await trace_call_path(
        storage=simple_trace_db,
        symbol_name="function_b",
        direction="upstream",
        max_depth=1,
    )

    assert result["query_symbol"] == "function_b"
    assert result["direction"] == "upstream"

    root = result["root"]
    assert root["name"] == "function_b"
    assert len(root["children"]) == 2

    # Children should be function_a and function_c (callers)
    child_names = {child["name"] for child in root["children"]}
    assert child_names == {"function_a", "function_c"}


@pytest.mark.asyncio
async def test_max_depth_limiting(tmp_path):
    """Test that max_depth correctly limits traversal depth."""
    db_path = tmp_path / "deep.db"
    storage = StorageManager(db_path=str(db_path))

    # Create chain: a → b → c → d → e
    storage.conn.execute(
        "INSERT INTO files (path, language, hash, size, last_modified) VALUES (?, ?, ?, ?, ?)",
        ("test.py", "python", "hash123", 100, 0),
    )
    storage.conn.execute(
        """
        INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
        VALUES
            ('a', 'a', 'Function', 'python', 'test.py', 1, 2),
            ('b', 'b', 'Function', 'python', 'test.py', 3, 4),
            ('c', 'c', 'Function', 'python', 'test.py', 5, 6),
            ('d', 'd', 'Function', 'python', 'test.py', 7, 8),
            ('e', 'e', 'Function', 'python', 'test.py', 9, 10)
        """
    )
    storage.conn.execute(
        """
        INSERT INTO relationships (id, from_symbol_id, to_symbol_id, kind, file_path)
        VALUES
            ('r1', 'a', 'b', 'Call', 'test.py'),
            ('r2', 'b', 'c', 'Call', 'test.py'),
            ('r3', 'c', 'd', 'Call', 'test.py'),
            ('r4', 'd', 'e', 'Call', 'test.py')
        """
    )
    storage.conn.commit()

    result = await trace_call_path(
        storage=storage, symbol_name="a", direction="downstream", max_depth=2
    )

    assert result["max_depth"] == 2
    assert result["max_depth_reached"] == 2
    assert result["truncated"] is True  # More nodes exist beyond max_depth

    # Should have a → b → c, but not d or e
    root = result["root"]
    assert root["name"] == "a"
    assert root["depth"] == 0

    # Level 1: b
    assert len(root["children"]) == 1
    level_1 = root["children"][0]
    assert level_1["name"] == "b"
    assert level_1["depth"] == 1

    # Level 2: c
    assert len(level_1["children"]) == 1
    level_2 = level_1["children"][0]
    assert level_2["name"] == "c"
    assert level_2["depth"] == 2

    # No level 3 (d should not be included)
    assert len(level_2["children"]) == 0


@pytest.mark.asyncio
async def test_both_directions(simple_trace_db):
    """Test bidirectional tracing."""
    result = await trace_call_path(
        storage=simple_trace_db,
        symbol_name="function_b",
        direction="both",
        max_depth=1,
    )

    assert result["direction"] == "both"

    root = result["root"]
    child_names = {child["name"] for child in root["children"]}

    # Should include both callers (function_a, function_c)
    # In "both" direction, we show callers (upstream)
    assert "function_a" in child_names
    assert "function_c" in child_names


@pytest.mark.asyncio
async def test_tree_output_format(simple_trace_db):
    """Test tree output format."""
    result = await trace_call_path(
        storage=simple_trace_db,
        symbol_name="function_a",
        output_format="tree",
        max_depth=1,
    )

    assert isinstance(result, str)
    assert "function_a" in result
    assert "→" in result  # Tree connector
    assert "python" in result  # Language indicator
    assert "test.py" in result  # File path


@pytest.mark.asyncio
async def test_statistics(simple_trace_db):
    """Test that statistics are collected correctly."""
    result = await trace_call_path(
        storage=simple_trace_db,
        symbol_name="function_a",
        direction="downstream",
        max_depth=2,
    )

    # Should include statistics
    assert "languages_found" in result
    assert "python" in result["languages_found"]

    assert "match_types" in result
    assert isinstance(result["match_types"], dict)

    assert "relationship_kinds" in result
    assert isinstance(result["relationship_kinds"], dict)
    assert result["relationship_kinds"].get("Call", 0) > 0

    assert "execution_time_ms" in result
    assert isinstance(result["execution_time_ms"], (int, float))
    assert result["execution_time_ms"] > 0


@pytest.mark.asyncio
async def test_invalid_max_depth():
    """Test validation of max_depth parameter."""
    from miller.storage import StorageManager

    storage = StorageManager(db_path=":memory:")

    with pytest.raises(ValueError, match="max_depth must be between"):
        await trace_call_path(
            storage=storage, symbol_name="test", direction="downstream", max_depth=0
        )

    with pytest.raises(ValueError, match="max_depth must be between"):
        await trace_call_path(
            storage=storage, symbol_name="test", direction="downstream", max_depth=100
        )


@pytest.mark.asyncio
async def test_invalid_direction():
    """Test validation of direction parameter."""
    from miller.storage import StorageManager

    storage = StorageManager(db_path=":memory:")

    with pytest.raises(ValueError, match="direction must be"):
        await trace_call_path(
            storage=storage,
            symbol_name="test",
            direction="sideways",  # type: ignore
            max_depth=3,
        )
