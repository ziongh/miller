"""Tests for graph expansion in search results.

TDD: These tests define the contract for the expand parameter in fast_search.
Run these BEFORE implementing to verify they fail (Red phase).

Graph expansion enriches search results with contextual information:
- callers: Who calls this symbol (direct, distance=1)
- callees: What this symbol calls (direct, distance=1)
- caller_count/callee_count: Total counts (may exceed returned items due to limit)
"""

import pytest
from miller.storage import StorageManager
from miller.closure import compute_transitive_closure


class MockSymbol:
    """Mock symbol matching PyO3 interface for testing."""

    def __init__(
        self,
        id,
        name,
        kind,
        language,
        file_path,
        signature=None,
        doc_comment=None,
        start_line=1,
        start_col=0,
        end_line=1,
        end_col=0,
        start_byte=0,
        end_byte=0,
        visibility=None,
        code_context=None,
        parent_id=None,
        semantic_group=None,
        confidence=1.0,
        content_type=None,
    ):
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


class MockRelationship:
    """Mock relationship matching PyO3 interface for testing."""

    def __init__(
        self, id, from_symbol_id, to_symbol_id, kind, file_path, line_number, confidence=1.0
    ):
        self.id = id
        self.from_symbol_id = from_symbol_id
        self.to_symbol_id = to_symbol_id
        self.kind = kind
        self.file_path = file_path
        self.line_number = line_number
        self.confidence = confidence


class TestGraphExpansionContract:
    """Contract tests for graph expansion feature."""

    @pytest.fixture
    def storage_with_call_graph(self, tmp_path):
        """Create storage with a realistic call graph for testing expansion.

        Call graph:
            main() -> process() -> validate() -> helper()
                   -> log()

            test_process() -> process()
        """
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Add files first (required by storage)
        storage.add_file("src/app.py", "python", "hash1", 100, 0)
        storage.add_file("src/processor.py", "python", "hash2", 150, 0)
        storage.add_file("src/validator.py", "python", "hash3", 80, 0)
        storage.add_file("src/utils.py", "python", "hash4", 50, 0)
        storage.add_file("src/logger.py", "python", "hash5", 30, 0)
        storage.add_file("tests/test_processor.py", "python", "hash6", 100, 0)

        # Add symbols using MockSymbol
        symbols = [
            MockSymbol(
                id="main_1",
                name="main",
                kind="Function",
                language="python",
                file_path="src/app.py",
                start_line=10,
                end_line=20,
                signature="def main()",
            ),
            MockSymbol(
                id="process_1",
                name="process",
                kind="Function",
                language="python",
                file_path="src/processor.py",
                start_line=15,
                end_line=30,
                signature="def process(data)",
            ),
            MockSymbol(
                id="validate_1",
                name="validate",
                kind="Function",
                language="python",
                file_path="src/validator.py",
                start_line=5,
                end_line=15,
                signature="def validate(item)",
            ),
            MockSymbol(
                id="helper_1",
                name="helper",
                kind="Function",
                language="python",
                file_path="src/utils.py",
                start_line=1,
                end_line=5,
                signature="def helper(x)",
            ),
            MockSymbol(
                id="log_1",
                name="log",
                kind="Function",
                language="python",
                file_path="src/logger.py",
                start_line=10,
                end_line=12,
                signature="def log(msg)",
            ),
            MockSymbol(
                id="test_process_1",
                name="test_process",
                kind="Function",
                language="python",
                file_path="tests/test_processor.py",
                start_line=10,
                end_line=20,
                signature="def test_process()",
            ),
        ]
        storage.add_symbols_batch(symbols)

        # Add call relationships using MockRelationship
        # main -> process, main -> log
        # process -> validate
        # validate -> helper
        # test_process -> process
        relationships = [
            MockRelationship("rel1", "main_1", "process_1", "Call", "src/app.py", 12),
            MockRelationship("rel2", "main_1", "log_1", "Call", "src/app.py", 18),
            MockRelationship("rel3", "process_1", "validate_1", "Call", "src/processor.py", 20),
            MockRelationship("rel4", "validate_1", "helper_1", "Call", "src/validator.py", 10),
            MockRelationship(
                "rel5", "test_process_1", "process_1", "Call", "tests/test_processor.py", 15
            ),
        ]
        storage.add_relationships_batch(relationships)

        # Compute transitive closure
        compute_transitive_closure(storage)

        yield storage
        storage.close()

    def test_expand_returns_callers(self, storage_with_call_graph):
        """When expand=True, results include direct callers."""
        from miller.tools.search import _expand_search_results

        # Search result for "process" function
        results = [
            {
                "id": "process_1",
                "name": "process",
                "kind": "Function",
                "file_path": "src/processor.py",
                "start_line": 15,
            }
        ]

        expanded = _expand_search_results(results, storage_with_call_graph)

        assert len(expanded) == 1
        assert "context" in expanded[0]
        assert "callers" in expanded[0]["context"]

        callers = expanded[0]["context"]["callers"]
        caller_names = {c["name"] for c in callers}

        # process() is called by main() and test_process()
        assert "main" in caller_names
        assert "test_process" in caller_names

    def test_expand_returns_callees(self, storage_with_call_graph):
        """When expand=True, results include direct callees."""
        from miller.tools.search import _expand_search_results

        # Search result for "main" function
        results = [
            {
                "id": "main_1",
                "name": "main",
                "kind": "Function",
                "file_path": "src/app.py",
                "start_line": 10,
            }
        ]

        expanded = _expand_search_results(results, storage_with_call_graph)

        assert "context" in expanded[0]
        assert "callees" in expanded[0]["context"]

        callees = expanded[0]["context"]["callees"]
        callee_names = {c["name"] for c in callees}

        # main() calls process() and log()
        assert "process" in callee_names
        assert "log" in callee_names

    def test_expand_includes_counts(self, storage_with_call_graph):
        """Expansion includes total caller/callee counts."""
        from miller.tools.search import _expand_search_results

        results = [
            {
                "id": "process_1",
                "name": "process",
                "kind": "Function",
                "file_path": "src/processor.py",
                "start_line": 15,
            }
        ]

        expanded = _expand_search_results(results, storage_with_call_graph)
        context = expanded[0]["context"]

        assert "caller_count" in context
        assert "callee_count" in context
        assert context["caller_count"] == 2  # main and test_process
        assert context["callee_count"] == 1  # validate

    def test_expand_respects_limit(self, storage_with_call_graph):
        """Expand limit caps returned callers/callees but not counts."""
        from miller.tools.search import _expand_search_results

        results = [
            {
                "id": "process_1",
                "name": "process",
                "kind": "Function",
                "file_path": "src/processor.py",
                "start_line": 15,
            }
        ]

        # Limit to 1 caller/callee
        expanded = _expand_search_results(results, storage_with_call_graph, expand_limit=1)
        context = expanded[0]["context"]

        # Only 1 caller returned, but count shows true total
        assert len(context["callers"]) == 1
        assert context["caller_count"] == 2

    def test_expand_only_direct_calls(self, storage_with_call_graph):
        """Expansion returns only distance=1 relationships (direct calls)."""
        from miller.tools.search import _expand_search_results

        # validate() is called by process(), which is called by main()
        # But only process() should appear as direct caller
        results = [
            {
                "id": "validate_1",
                "name": "validate",
                "kind": "Function",
                "file_path": "src/validator.py",
                "start_line": 5,
            }
        ]

        expanded = _expand_search_results(results, storage_with_call_graph)
        callers = expanded[0]["context"]["callers"]
        caller_names = {c["name"] for c in callers}

        # Only process() directly calls validate(), not main()
        assert "process" in caller_names
        assert "main" not in caller_names  # main is distance=2

    def test_expand_handles_no_relationships(self, storage_with_call_graph):
        """Symbols with no callers/callees get empty lists."""
        from miller.tools.search import _expand_search_results

        # helper() has no callees
        results = [
            {
                "id": "helper_1",
                "name": "helper",
                "kind": "Function",
                "file_path": "src/utils.py",
                "start_line": 1,
            }
        ]

        expanded = _expand_search_results(results, storage_with_call_graph)
        context = expanded[0]["context"]

        assert context["callees"] == []
        assert context["callee_count"] == 0
        # But helper has one caller (validate)
        assert context["caller_count"] == 1

    def test_expand_includes_symbol_metadata(self, storage_with_call_graph):
        """Expanded callers/callees include useful metadata."""
        from miller.tools.search import _expand_search_results

        results = [
            {
                "id": "process_1",
                "name": "process",
                "kind": "Function",
                "file_path": "src/processor.py",
                "start_line": 15,
            }
        ]

        expanded = _expand_search_results(results, storage_with_call_graph)
        callers = expanded[0]["context"]["callers"]

        # Each caller should have id, name, kind, file_path, line
        for caller in callers:
            assert "id" in caller
            assert "name" in caller
            assert "kind" in caller
            assert "file_path" in caller
            assert "line" in caller

    def test_expand_multiple_results(self, storage_with_call_graph):
        """Expansion works correctly for multiple search results."""
        from miller.tools.search import _expand_search_results

        # Search results for two symbols
        results = [
            {
                "id": "main_1",
                "name": "main",
                "kind": "Function",
                "file_path": "src/app.py",
                "start_line": 10,
            },
            {
                "id": "process_1",
                "name": "process",
                "kind": "Function",
                "file_path": "src/processor.py",
                "start_line": 15,
            },
        ]

        expanded = _expand_search_results(results, storage_with_call_graph)

        assert len(expanded) == 2
        # main has 0 callers, 2 callees
        assert expanded[0]["context"]["caller_count"] == 0
        assert expanded[0]["context"]["callee_count"] == 2
        # process has 2 callers, 1 callee
        assert expanded[1]["context"]["caller_count"] == 2
        assert expanded[1]["context"]["callee_count"] == 1


class TestExpandedTextFormatting:
    """Tests for text output format with expansion."""

    def test_text_format_includes_callers_callees(self, tmp_path):
        """Text format displays caller/callee context."""
        from miller.tools.search import _format_search_as_text

        results = [
            {
                "file_path": "src/processor.py",
                "start_line": 15,
                "signature": "def process(data)",
                "context": {
                    "callers": [
                        {"name": "main", "file_path": "src/app.py", "line": 12},
                        {"name": "test_process", "file_path": "tests/test.py", "line": 10},
                    ],
                    "callees": [
                        {"name": "validate", "file_path": "src/validator.py", "line": 5},
                    ],
                    "caller_count": 2,
                    "callee_count": 1,
                },
            }
        ]

        output = _format_search_as_text(results, query="process")

        # Should contain caller info
        assert "← Callers (2):" in output
        assert "main (src/app.py:12)" in output
        assert "test_process (tests/test.py:10)" in output

        # Should contain callee info
        assert "→ Callees (1):" in output
        assert "validate (src/validator.py:5)" in output

    def test_text_format_shows_more_when_limited(self, tmp_path):
        """Text format shows '+N more' when callers exceed limit."""
        from miller.tools.search import _format_search_as_text

        results = [
            {
                "file_path": "src/fn.py",
                "start_line": 10,
                "signature": "def fn()",
                "context": {
                    "callers": [
                        {"name": "a", "file_path": "a.py", "line": 1},
                    ],
                    "callees": [],
                    "caller_count": 5,  # More than returned
                    "callee_count": 0,
                },
            }
        ]

        output = _format_search_as_text(results, query="fn")

        # Should show +4 more
        assert "+4 more" in output

    def test_text_format_no_context_when_absent(self, tmp_path):
        """Text format works without context field."""
        from miller.tools.search import _format_search_as_text

        results = [
            {
                "file_path": "src/fn.py",
                "start_line": 10,
                "signature": "def fn()",
            }
        ]

        output = _format_search_as_text(results, query="fn")

        # Should not crash, should not have caller/callee markers
        assert "← Callers" not in output
        assert "→ Callees" not in output
        assert "src/fn.py:10" in output
