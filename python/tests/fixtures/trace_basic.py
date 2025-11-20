"""
Basic trace workspace fixtures for test_trace_basic.py tests.
"""
import pytest
from pathlib import Path


@pytest.fixture
def sample_indexed_workspace(tmp_path):
    """
    Create a sample indexed workspace with simple call relationships.

    Structure:
        function_a calls function_b
        function_a calls function_c
        function_c calls function_b
        isolated_function (no relationships)
    """
    from miller.storage import StorageManager
    from miller import miller_core

    # Create temporary database
    db_path = tmp_path / "test.db"
    storage = StorageManager(db_path=str(db_path))

    # Index sample code
    code = """
def function_a():
    function_b()
    function_c()

def function_b():
    pass

def function_c():
    function_b()

def isolated_function():
    pass
"""

    # Extract and store
    result = miller_core.extract_file(code, "python", "test.py")
    storage.add_file("test.py", "python", "hash123", len(code), 0)
    storage.add_symbols_batch(result.symbols)
    storage.add_relationships_batch(result.relationships)

    return storage


@pytest.fixture
def cross_language_workspace(tmp_path):
    """
    Create workspace with cross-language relationships.

    Structure:
        TypeScript: UserService → Python: user_service
        TypeScript: IUser → Python: User
        Python: User → SQL: users
        C#: UserDto → Python: User
    """
    from miller.storage import StorageManager

    # Create temporary database
    db_path = tmp_path / "test.db"
    storage = StorageManager(db_path=str(db_path))

    # Mock symbol class for creating test data
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

    # TypeScript symbols
    typescript_user_service = MockSymbol(
        id="ts_user_service",
        name="UserService",
        kind="Class",
        language="typescript",
        file_path="src/services/UserService.ts",
        signature="class UserService",
        doc_comment="Service for user operations",
        start_line=10,
        end_line=50
    )

    typescript_iuser = MockSymbol(
        id="ts_iuser",
        name="IUser",
        kind="Interface",
        language="typescript",
        file_path="src/types/IUser.ts",
        signature="interface IUser",
        start_line=1,
        end_line=15
    )

    # Python symbols
    python_user_service = MockSymbol(
        id="py_user_service",
        name="user_service",
        kind="Function",
        language="python",
        file_path="api/users.py",
        signature="def user_service():",
        start_line=5,
        end_line=20
    )

    python_user = MockSymbol(
        id="py_user",
        name="User",
        kind="Class",
        language="python",
        file_path="models/user.py",
        signature="class User:",
        doc_comment="ORM model for users",
        start_line=1,
        end_line=30
    )

    # C# symbols
    csharp_user_dto = MockSymbol(
        id="cs_user_dto",
        name="UserDto",
        kind="Class",
        language="csharp",
        file_path="src/DTOs/UserDto.cs",
        signature="public class UserDto",
        start_line=10,
        end_line=25
    )

    # SQL symbols (tables)
    sql_users = MockSymbol(
        id="sql_users",
        name="users",
        kind="Table",
        language="sql",
        file_path="schema/schema.sql",
        signature="CREATE TABLE users",
        start_line=45,
        end_line=55
    )

    # Add files
    storage.add_file("src/services/UserService.ts", "typescript", "hash_ts_service", 500, 0)
    storage.add_file("src/types/IUser.ts", "typescript", "hash_ts_iuser", 200, 0)
    storage.add_file("api/users.py", "python", "hash_py_service", 300, 0)
    storage.add_file("models/user.py", "python", "hash_py_user", 400, 0)
    storage.add_file("src/DTOs/UserDto.cs", "csharp", "hash_cs_dto", 250, 0)
    storage.add_file("schema/schema.sql", "sql", "hash_sql_schema", 1000, 0)

    # Add symbols
    symbols = [
        typescript_user_service,
        typescript_iuser,
        python_user_service,
        python_user,
        csharp_user_dto,
        sql_users
    ]
    storage.add_symbols_batch(symbols)

    # Create relationships: Cross-language connections
    relationships = [
        # TypeScript UserService → Python user_service (via naming variant)
        MockRelationship(
            id="rel_1",
            from_symbol_id="ts_user_service",
            to_symbol_id="py_user_service",
            kind="Call",
            file_path="src/services/UserService.ts",
            line_number=25
        ),
        # TypeScript IUser → Python User (via prefix stripping)
        MockRelationship(
            id="rel_2",
            from_symbol_id="ts_iuser",
            to_symbol_id="py_user",
            kind="Reference",
            file_path="src/types/IUser.ts",
            line_number=5
        ),
        # Python User → SQL users (via pluralization)
        MockRelationship(
            id="rel_3",
            from_symbol_id="py_user",
            to_symbol_id="sql_users",
            kind="Reference",
            file_path="models/user.py",
            line_number=15
        ),
        # C# UserDto → Python User (via suffix stripping)
        MockRelationship(
            id="rel_4",
            from_symbol_id="cs_user_dto",
            to_symbol_id="py_user",
            kind="Reference",
            file_path="src/DTOs/UserDto.cs",
            line_number=12
        )
    ]
    storage.add_relationships_batch(relationships)

    yield storage
    storage.close()


