"""
Edge case trace workspace fixtures.
Includes ambiguous symbol scenarios.
"""
import pytest
from pathlib import Path


@pytest.fixture
def ambiguous_workspace(tmp_path):
    """
    Create workspace with ambiguous symbols (same name, different files).

    Structure:
        src/user.py: User class (ORM model)
        src/admin.py: User class (admin user model)
        src/models/user.py: User class (different file path)
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

    # Multiple User symbols with same name in different files
    user_in_main = MockSymbol(
        id="py_user_main",
        name="User",
        kind="Class",
        language="python",
        file_path="src/user.py",
        signature="class User:",
        doc_comment="Main user ORM model",
        start_line=1,
        end_line=30
    )

    user_in_admin = MockSymbol(
        id="py_user_admin",
        name="User",
        kind="Class",
        language="python",
        file_path="src/admin.py",
        signature="class User:",
        doc_comment="Admin user model",
        start_line=50,
        end_line=80
    )

    user_in_models = MockSymbol(
        id="py_user_models",
        name="User",
        kind="Class",
        language="python",
        file_path="src/models/user.py",
        signature="class User:",
        doc_comment="Extended user model",
        start_line=1,
        end_line=40
    )

    # Helper symbols for relationships
    get_user = MockSymbol(
        id="py_get_user",
        name="get_user",
        kind="Function",
        language="python",
        file_path="src/user.py",
        signature="def get_user(user_id):",
        start_line=32,
        end_line=40
    )

    admin_function = MockSymbol(
        id="py_admin_func",
        name="admin_function",
        kind="Function",
        language="python",
        file_path="src/admin.py",
        signature="def admin_function():",
        start_line=82,
        end_line=90
    )

    # Add files
    storage.add_file("src/user.py", "python", "hash_user_main", 500, 0)
    storage.add_file("src/admin.py", "python", "hash_admin", 400, 0)
    storage.add_file("src/models/user.py", "python", "hash_user_models", 600, 0)

    # Add symbols
    symbols = [
        user_in_main,
        user_in_admin,
        user_in_models,
        get_user,
        admin_function
    ]
    storage.add_symbols_batch(symbols)

    # Add relationships for disambiguation testing
    relationships = [
        # get_user (in src/user.py) calls User (in src/user.py)
        MockRelationship(
            id="rel_disambig_1",
            from_symbol_id="py_get_user",
            to_symbol_id="py_user_main",
            kind="Call",
            file_path="src/user.py",
            line_number=35
        ),
        # admin_function (in src/admin.py) calls User (in src/admin.py)
        MockRelationship(
            id="rel_disambig_2",
            from_symbol_id="py_admin_func",
            to_symbol_id="py_user_admin",
            kind="Call",
            file_path="src/admin.py",
            line_number=85
        ),
        # user_in_main imports user_in_models
        MockRelationship(
            id="rel_disambig_3",
            from_symbol_id="py_user_main",
            to_symbol_id="py_user_models",
            kind="Import",
            file_path="src/user.py",
            line_number=1
        ),
    ]
    storage.add_relationships_batch(relationships)

    yield storage
    storage.close()


