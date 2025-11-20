"""
Advanced trace workspace fixtures for test_trace_advanced.py tests.
Includes semantic matching and cyclic reference scenarios.
"""
import pytest
from pathlib import Path


@pytest.fixture
def semantic_workspace(tmp_path):
    """
    Create workspace for testing semantic matching.

    Structure:
        - calculate_user_age: Calculate age from birth date
        - get_age_for_user: Get age for a specific user (semantically similar)
        - fetch_data: Retrieve data from database
        - retrieve_information: Get information from database (semantically similar)
        - delete_user_account: Remove user (semantically different)
    """
    from miller.storage import StorageManager

    # Create temporary database
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

    # Mock relationship class
    class MockRelationship:
        def __init__(self, id, from_symbol_id, to_symbol_id, kind, file_path, line_number, confidence=1.0):
            self.id = id
            self.from_symbol_id = from_symbol_id
            self.to_symbol_id = to_symbol_id
            self.kind = kind
            self.file_path = file_path
            self.line_number = line_number
            self.confidence = confidence

    # Python symbols for semantic matching
    calculate_user_age = MockSymbol(
        id="py_calc_age",
        name="calculate_user_age",
        kind="Function",
        language="python",
        file_path="utils/age.py",
        signature="def calculate_user_age(birth_date):",
        doc_comment="Calculate age from birth date",
        start_line=5,
        end_line=15
    )

    get_age_for_user = MockSymbol(
        id="py_get_age",
        name="get_age_for_user",
        kind="Function",
        language="python",
        file_path="api/user_info.py",
        signature="def get_age_for_user(user_id):",
        doc_comment="Get age for a specific user",
        start_line=20,
        end_line=30
    )

    fetch_data = MockSymbol(
        id="py_fetch_data",
        name="fetch_data",
        kind="Function",
        language="python",
        file_path="db/queries.py",
        signature="def fetch_data(query):",
        doc_comment="Retrieve data from database",
        start_line=1,
        end_line=10
    )

    retrieve_information = MockSymbol(
        id="py_retrieve_info",
        name="retrieve_information",
        kind="Function",
        language="python",
        file_path="db/loader.py",
        signature="def retrieve_information(filters):",
        doc_comment="Get information from database",
        start_line=10,
        end_line=20
    )

    delete_user_account = MockSymbol(
        id="py_delete_user",
        name="delete_user_account",
        kind="Function",
        language="python",
        file_path="auth/account.py",
        signature="def delete_user_account(user_id):",
        doc_comment="Remove user account from system",
        start_line=40,
        end_line=55
    )

    # Add files
    storage.add_file("utils/age.py", "python", "hash_age", 300, 0)
    storage.add_file("api/user_info.py", "python", "hash_user_info", 350, 0)
    storage.add_file("db/queries.py", "python", "hash_queries", 200, 0)
    storage.add_file("db/loader.py", "python", "hash_loader", 250, 0)
    storage.add_file("auth/account.py", "python", "hash_account", 400, 0)

    # Add symbols
    symbols = [
        calculate_user_age,
        get_age_for_user,
        fetch_data,
        retrieve_information,
        delete_user_account
    ]
    storage.add_symbols_batch(symbols)

    # Add relationships for semantic matching
    relationships = [
        # calculate_user_age calls get_age_for_user (semantically similar)
        MockRelationship(
            id="rel_sem_1",
            from_symbol_id="py_calc_age",
            to_symbol_id="py_get_age",
            kind="Call",
            file_path="utils/age.py",
            line_number=10
        ),
        # fetch_data calls retrieve_information (semantically similar)
        MockRelationship(
            id="rel_sem_2",
            from_symbol_id="py_fetch_data",
            to_symbol_id="py_retrieve_info",
            kind="Call",
            file_path="db/queries.py",
            line_number=5
        ),
        # calculate_user_age does NOT call delete_user_account (different semantic meaning)
        # No relationship created intentionally for testing threshold filtering
    ]
    storage.add_relationships_batch(relationships)

    yield storage
    storage.close()


@pytest.fixture
def cyclic_workspace(tmp_path):
    """
    Create workspace with circular references.

    Structure:
        Direct cycle: function_a ↔ function_b
        Indirect cycle: a → b → c → a
    """
    from miller.storage import StorageManager

    # Create temporary database
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

    # Mock relationship class
    class MockRelationship:
        def __init__(self, id, from_symbol_id, to_symbol_id, kind, file_path, line_number, confidence=1.0):
            self.id = id
            self.from_symbol_id = from_symbol_id
            self.to_symbol_id = to_symbol_id
            self.kind = kind
            self.file_path = file_path
            self.line_number = line_number
            self.confidence = confidence

    # Symbols for cyclic testing
    function_a = MockSymbol(
        id="py_func_a",
        name="function_a",
        kind="Function",
        language="python",
        file_path="cycles.py",
        signature="def function_a():",
        start_line=1,
        end_line=5
    )

    function_b = MockSymbol(
        id="py_func_b",
        name="function_b",
        kind="Function",
        language="python",
        file_path="cycles.py",
        signature="def function_b():",
        start_line=7,
        end_line=11
    )

    function_c = MockSymbol(
        id="py_func_c",
        name="function_c",
        kind="Function",
        language="python",
        file_path="cycles.py",
        signature="def function_c():",
        start_line=13,
        end_line=17
    )

    # Additional symbols for more complex cycles
    a = MockSymbol(
        id="py_a",
        name="a",
        kind="Function",
        language="python",
        file_path="indirect.py",
        signature="def a():",
        start_line=1,
        end_line=5
    )

    b = MockSymbol(
        id="py_b",
        name="b",
        kind="Function",
        language="python",
        file_path="indirect.py",
        signature="def b():",
        start_line=7,
        end_line=11
    )

    c = MockSymbol(
        id="py_c",
        name="c",
        kind="Function",
        language="python",
        file_path="indirect.py",
        signature="def c():",
        start_line=13,
        end_line=17
    )

    # Add files
    storage.add_file("cycles.py", "python", "hash_cycles", 500, 0)
    storage.add_file("indirect.py", "python", "hash_indirect", 400, 0)

    # Add symbols
    symbols = [function_a, function_b, function_c, a, b, c]
    storage.add_symbols_batch(symbols)

    # Add relationships creating cycles
    relationships = [
        # Direct cycle: function_a ↔ function_b
        MockRelationship(
            id="rel_cycle_1",
            from_symbol_id="py_func_a",
            to_symbol_id="py_func_b",
            kind="Call",
            file_path="cycles.py",
            line_number=3
        ),
        MockRelationship(
            id="rel_cycle_2",
            from_symbol_id="py_func_b",
            to_symbol_id="py_func_a",
            kind="Call",
            file_path="cycles.py",
            line_number=9
        ),

        # Indirect cycle: a → b → c → a
        MockRelationship(
            id="rel_indirect_1",
            from_symbol_id="py_a",
            to_symbol_id="py_b",
            kind="Call",
            file_path="indirect.py",
            line_number=2
        ),
        MockRelationship(
            id="rel_indirect_2",
            from_symbol_id="py_b",
            to_symbol_id="py_c",
            kind="Call",
            file_path="indirect.py",
            line_number=8
        ),
        MockRelationship(
            id="rel_indirect_3",
            from_symbol_id="py_c",
            to_symbol_id="py_a",
            kind="Call",
            file_path="indirect.py",
            line_number=14
        ),
    ]
    storage.add_relationships_batch(relationships)

    yield storage
    storage.close()


