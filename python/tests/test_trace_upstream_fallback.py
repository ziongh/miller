"""
Tests for trace_call_path upstream fallback using identifiers.containing_symbol_id.

This test captures the bug where:
- Relationships table doesn't have upstream call relationships for imported functions
- But identifiers table HAS containing_symbol_id correctly populated
- The trace should use identifiers as fallback for upstream tracing

Bug reproduction:
- trace_call_path("target_func", direction="upstream") returns wrong results
- It shows identifier references as siblings instead of containing functions as callers
"""

import pytest
from miller.storage import StorageManager


@pytest.fixture
def workspace_with_identifiers_only(tmp_path):
    """
    Create a workspace where:
    - Symbols exist for functions
    - Identifiers exist with containing_symbol_id populated
    - But NO relationships exist (simulating the real bug)

    This simulates the real-world scenario where:
    - function_a() and function_b() both call target_func()
    - The identifiers table has `target_func` references with containing_symbol_id
    - But the relationships table is empty for these calls
    """
    db_path = tmp_path / "test.db"
    storage = StorageManager(db_path=str(db_path))

    # Mock symbol class
    class MockSymbol:
        def __init__(self, id, name, kind, language, file_path, signature=None,
                     doc_comment=None, start_line=1, start_col=0, end_line=1,
                     end_col=0, start_byte=0, end_byte=0, visibility=None,
                     code_context=None, parent_id=None, semantic_group=None,
                     confidence=1.0, content_type=None):
            self.id = id
            self.name = name
            self.kind = kind
            self.language = language
            self.file_path = file_path
            self.signature = signature
            self.doc_comment = doc_comment
            self.start_line = start_line
            self.start_column = start_col
            self.end_line = end_line
            self.end_column = end_col
            self.start_byte = start_byte
            self.end_byte = end_byte
            self.visibility = visibility
            self.code_context = code_context
            self.parent_id = parent_id
            self.semantic_group = semantic_group
            self.confidence = confidence
            self.content_type = content_type

    # Mock identifier class
    class MockIdentifier:
        def __init__(self, id, name, kind, language, file_path, start_line,
                     containing_symbol_id, target_symbol_id=None,
                     start_col=0, end_line=None, end_col=0,
                     start_byte=0, end_byte=0, confidence=1.0, code_context=None):
            self.id = id
            self.name = name
            self.kind = kind
            self.language = language
            self.file_path = file_path
            self.start_line = start_line
            self.start_column = start_col
            self.end_line = end_line or start_line
            self.end_column = end_col
            self.start_byte = start_byte
            self.end_byte = end_byte
            self.containing_symbol_id = containing_symbol_id
            self.target_symbol_id = target_symbol_id
            self.confidence = confidence
            self.code_context = code_context

    # Create symbols: target function and two callers
    target_func = MockSymbol(
        id="target_func_id",
        name="target_func",
        kind="Function",
        language="python",
        file_path="module.py",
        signature="def target_func():",
        start_line=10,
        end_line=15
    )

    caller_a = MockSymbol(
        id="caller_a_id",
        name="caller_a",
        kind="Function",
        language="python",
        file_path="callers.py",
        signature="def caller_a():",
        start_line=1,
        end_line=5
    )

    caller_b = MockSymbol(
        id="caller_b_id",
        name="caller_b",
        kind="Function",
        language="python",
        file_path="callers.py",
        signature="def caller_b():",
        start_line=10,
        end_line=15
    )

    # Add files
    storage.add_file("module.py", "python", "hash1", 100, 0)
    storage.add_file("callers.py", "python", "hash2", 200, 0)

    # Add symbols
    storage.add_symbols_batch([target_func, caller_a, caller_b])

    # Add identifiers - these reference target_func FROM caller_a and caller_b
    # This is the KEY: containing_symbol_id shows which function contains the call
    identifier_in_caller_a = MockIdentifier(
        id="ident_1",
        name="target_func",
        kind="Identifier",
        language="python",
        file_path="callers.py",
        start_line=3,
        containing_symbol_id="caller_a_id",  # Inside caller_a
        target_symbol_id="target_func_id"    # References target_func
    )

    identifier_in_caller_b = MockIdentifier(
        id="ident_2",
        name="target_func",
        kind="Identifier",
        language="python",
        file_path="callers.py",
        start_line=12,
        containing_symbol_id="caller_b_id",  # Inside caller_b
        target_symbol_id="target_func_id"    # References target_func
    )

    storage.add_identifiers_batch([identifier_in_caller_a, identifier_in_caller_b])

    # NOTE: We intentionally DO NOT add relationships!
    # This simulates the bug where relationships aren't created for imported function calls

    yield storage
    storage.close()


class TestTraceUpstreamWithIdentifiersFallback:
    """Test that upstream tracing uses identifiers.containing_symbol_id as fallback."""

    @pytest.mark.asyncio
    async def test_upstream_uses_identifiers_when_no_relationships(
        self, workspace_with_identifiers_only
    ):
        """
        Test that upstream trace finds callers via identifiers.containing_symbol_id.

        Setup:
            - target_func is defined in module.py
            - caller_a and caller_b both call target_func (via identifiers, no relationships)
            - identifiers.containing_symbol_id is correctly populated

        Query: trace_call_path("target_func", direction="upstream")

        Expected:
            - Root: target_func
            - Children: [caller_a, caller_b] (the containing functions)
            - NOT: [target_func@line3, target_func@line12] (identifier locations)

        This test FAILS with the current implementation because:
            1. The trace queries relationships table (empty)
            2. Falls back to variant matching (finds symbols named target_func)
            3. Returns wrong results instead of using identifiers.containing_symbol_id
        """
        from miller.tools.trace import trace_call_path

        storage = workspace_with_identifiers_only

        result = await trace_call_path(
            storage=storage,
            symbol_name="target_func",
            direction="upstream",
            max_depth=1
        )

        assert result["query_symbol"] == "target_func"
        assert result["direction"] == "upstream"

        root = result["root"]
        assert root["name"] == "target_func"
        assert root["depth"] == 0

        # THE CRITICAL ASSERTION:
        # Children should be the CONTAINING FUNCTIONS (caller_a, caller_b)
        # NOT other target_func references
        child_names = {child["name"] for child in root["children"]}

        # This should pass after the fix
        assert "caller_a" in child_names, f"Expected caller_a in children, got {child_names}"
        assert "caller_b" in child_names, f"Expected caller_b in children, got {child_names}"

        # Children should NOT be target_func (that would mean we're returning identifier refs)
        assert "target_func" not in child_names, \
            f"Bug: trace returned target_func references instead of containing functions"

        # Should have exactly 2 children
        assert len(root["children"]) == 2, \
            f"Expected 2 callers, got {len(root['children'])}: {child_names}"
