"""
Tests for fast_explore text output formatting.

Following TDD: Tests define the expected text format behavior BEFORE implementation.
These tests verify that _format_explore_as_text produces properly formatted,
consistent output with file:line → signature for all sections.
"""

import pytest
from miller.tools.explore import _format_explore_as_text


class TestFastExploreTextFormat:
    """Tests for the lean text output format (default)."""

    def test_text_format_returns_string(self):
        """Test that text format returns a string."""
        result = {
            "type_name": "IService",
            "total_found": 1,
            "implementations": [
                {
                    "name": "ConcreteService",
                    "kind": "class",
                    "file_path": "src/services.py",
                    "start_line": 10,
                    "signature": "class ConcreteService",
                }
            ],
            "hierarchy": {"parents": [], "children": []},
            "returns": [],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        assert isinstance(text, str)
        assert len(text) > 0

    def test_text_format_has_header(self):
        """Test that output includes properly formatted header."""
        result = {
            "type_name": "IUserService",
            "total_found": 1,
            "implementations": [
                {
                    "name": "UserService",
                    "kind": "class",
                    "file_path": "src/services/user.py",
                    "start_line": 5,
                    "signature": "class UserService",
                }
            ],
            "hierarchy": {"parents": [], "children": []},
            "returns": [],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        assert 'Type intelligence for "IUserService"' in text

    def test_text_format_shows_implementations(self):
        """Test that implementations section shows file:line → signature."""
        result = {
            "type_name": "IService",
            "total_found": 2,
            "implementations": [
                {
                    "name": "ServiceA",
                    "kind": "class",
                    "file_path": "src/services/a.py",
                    "start_line": 10,
                    "signature": "class ServiceA(IService)",
                }
            ],
            "hierarchy": {"parents": [], "children": []},
            "returns": [],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        assert "Implementations (1):" in text
        assert "src/services/a.py:10 → class ServiceA(IService)" in text

    def test_text_format_shows_hierarchy_parents(self):
        """Test that hierarchy section shows parents with file:line → signature."""
        result = {
            "type_name": "ChildService",
            "total_found": 1,
            "implementations": [],
            "hierarchy": {
                "parents": [
                    {
                        "name": "BaseService",
                        "kind": "class",
                        "file_path": "src/base.py",
                        "start_line": 5,
                        "signature": "class BaseService",
                    }
                ],
                "children": [],
            },
            "returns": [],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        assert "Hierarchy:" in text
        assert "Parents (1):" in text
        assert "src/base.py:5 → class BaseService" in text

    def test_text_format_shows_hierarchy_children(self):
        """Test that hierarchy section shows children with file:line → signature."""
        result = {
            "type_name": "BaseService",
            "total_found": 1,
            "implementations": [],
            "hierarchy": {
                "parents": [],
                "children": [
                    {
                        "name": "ConcreteService",
                        "kind": "class",
                        "file_path": "src/impl.py",
                        "start_line": 15,
                        "signature": "class ConcreteService(BaseService)",
                    }
                ],
            },
            "returns": [],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        assert "Hierarchy:" in text
        assert "Children (1):" in text
        assert "src/impl.py:15 → class ConcreteService(BaseService)" in text

    def test_text_format_shows_both_hierarchy_parents_and_children(self):
        """Test hierarchy showing both parents and children with counts."""
        result = {
            "type_name": "MiddleService",
            "total_found": 3,
            "implementations": [],
            "hierarchy": {
                "parents": [
                    {
                        "name": "BaseService",
                        "kind": "class",
                        "file_path": "src/base.py",
                        "start_line": 5,
                        "signature": "class BaseService",
                    }
                ],
                "children": [
                    {
                        "name": "ConcreteServiceA",
                        "kind": "class",
                        "file_path": "src/impl_a.py",
                        "start_line": 10,
                        "signature": "class ConcreteServiceA(MiddleService)",
                    },
                    {
                        "name": "ConcreteServiceB",
                        "kind": "class",
                        "file_path": "src/impl_b.py",
                        "start_line": 20,
                        "signature": "class ConcreteServiceB(MiddleService)",
                    },
                ],
            },
            "returns": [],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        assert "Hierarchy:" in text
        assert "Parents (1):" in text
        assert "Children (2):" in text
        assert "src/base.py:5 → class BaseService" in text
        assert "src/impl_a.py:10 → class ConcreteServiceA(MiddleService)" in text
        assert "src/impl_b.py:20 → class ConcreteServiceB(MiddleService)" in text

    def test_text_format_shows_returns(self):
        """Test that returns section shows functions with file:line → signature."""
        result = {
            "type_name": "IUser",
            "total_found": 1,
            "implementations": [],
            "hierarchy": {"parents": [], "children": []},
            "returns": [
                {
                    "name": "get_user",
                    "kind": "function",
                    "file_path": "src/api.py",
                    "start_line": 30,
                    "signature": "def get_user(id: int) -> IUser",
                }
            ],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        assert "Returns this type (1):" in text
        assert "src/api.py:30 → def get_user(id: int) -> IUser" in text

    def test_text_format_shows_parameters(self):
        """Test that parameters section shows functions with file:line → signature."""
        result = {
            "type_name": "IUser",
            "total_found": 1,
            "implementations": [],
            "hierarchy": {"parents": [], "children": []},
            "returns": [],
            "parameters": [
                {
                    "name": "create_user",
                    "kind": "function",
                    "file_path": "src/api.py",
                    "start_line": 45,
                    "signature": "def create_user(user: IUser) -> bool",
                }
            ],
        }

        text = _format_explore_as_text(result)

        assert "Takes as parameter (1):" in text
        assert "src/api.py:45 → def create_user(user: IUser) -> bool" in text

    def test_text_format_empty_sections_omitted(self):
        """Test that sections with no results are not shown."""
        result = {
            "type_name": "IService",
            "total_found": 1,
            "implementations": [
                {
                    "name": "Service",
                    "kind": "class",
                    "file_path": "src/services.py",
                    "start_line": 10,
                    "signature": "class Service",
                }
            ],
            "hierarchy": {"parents": [], "children": []},
            "returns": [],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        # Should have implementations but not returns, parameters, or hierarchy
        assert "Implementations" in text
        assert "Returns this type" not in text
        assert "Takes as parameter" not in text
        assert "Hierarchy:" not in text

    def test_text_format_type_not_found(self):
        """Test that clear message is shown when type not found."""
        result = {
            "type_name": "NonExistentType",
            "total_found": 0,
            "implementations": [],
            "hierarchy": {"parents": [], "children": []},
            "returns": [],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        assert 'No type information found for "NonExistentType"' in text

    def test_text_format_signature_truncation(self):
        """Test that long signatures are truncated at 60 chars."""
        long_sig = "def very_long_function_name(param1: str, param2: int, param3: bool) -> ComplexType"

        result = {
            "type_name": "IService",
            "total_found": 1,
            "implementations": [
                {
                    "name": "Service",
                    "kind": "class",
                    "file_path": "src/services.py",
                    "start_line": 10,
                    "signature": long_sig,
                }
            ],
            "hierarchy": {"parents": [], "children": []},
            "returns": [],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        # Should contain truncated version (57 chars + "...")
        assert "..." in text
        assert len(long_sig) > 60

    def test_text_format_all_sections_together(self):
        """Test complete output with all sections populated."""
        result = {
            "type_name": "IPaymentProcessor",
            "total_found": 6,
            "implementations": [
                {
                    "name": "StripeProcessor",
                    "kind": "class",
                    "file_path": "src/payments/stripe.py",
                    "start_line": 12,
                    "signature": "class StripeProcessor(IPaymentProcessor)",
                }
            ],
            "hierarchy": {
                "parents": [
                    {
                        "name": "BaseProcessor",
                        "kind": "class",
                        "file_path": "src/payments/base.py",
                        "start_line": 5,
                        "signature": "class BaseProcessor",
                    }
                ],
                "children": [
                    {
                        "name": "MockProcessor",
                        "kind": "class",
                        "file_path": "src/payments/mock.py",
                        "start_line": 20,
                        "signature": "class MockProcessor(IPaymentProcessor)",
                    }
                ],
            },
            "returns": [
                {
                    "name": "get_processor",
                    "kind": "function",
                    "file_path": "src/factory.py",
                    "start_line": 8,
                    "signature": "def get_processor() -> IPaymentProcessor",
                }
            ],
            "parameters": [
                {
                    "name": "process_payment",
                    "kind": "function",
                    "file_path": "src/api/checkout.py",
                    "start_line": 25,
                    "signature": "def process_payment(processor: IPaymentProcessor)",
                }
            ],
        }

        text = _format_explore_as_text(result)

        # Check all sections are present
        assert 'Type intelligence for "IPaymentProcessor"' in text
        assert "Implementations (1):" in text
        assert "Parents (1):" in text
        assert "Children (1):" in text
        assert "Returns this type (1):" in text
        assert "Takes as parameter (1):" in text

        # Check file:line → signature format in each section
        assert "src/payments/stripe.py:12 → class StripeProcessor(IPaymentProcessor)" in text
        assert "src/payments/base.py:5 → class BaseProcessor" in text
        assert "src/payments/mock.py:20 → class MockProcessor(IPaymentProcessor)" in text
        assert "src/factory.py:8 → def get_processor() -> IPaymentProcessor" in text
        assert "src/api/checkout.py:25 → def process_payment(processor: IPaymentProcessor)" in text

    def test_text_format_no_trailing_blank_lines(self):
        """Test that output has no trailing blank lines."""
        result = {
            "type_name": "IService",
            "total_found": 1,
            "implementations": [
                {
                    "name": "Service",
                    "kind": "class",
                    "file_path": "src/services.py",
                    "start_line": 10,
                    "signature": "class Service",
                }
            ],
            "hierarchy": {"parents": [], "children": []},
            "returns": [],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        # Should not end with newline or blank lines
        assert not text.endswith("\n\n")
        lines = text.split("\n")
        assert lines[-1].strip() != ""  # Last line is not blank

    def test_text_format_proper_spacing(self):
        """Test that output has proper spacing between sections."""
        result = {
            "type_name": "IService",
            "total_found": 2,
            "implementations": [
                {
                    "name": "ServiceA",
                    "kind": "class",
                    "file_path": "src/a.py",
                    "start_line": 1,
                    "signature": "class ServiceA",
                }
            ],
            "hierarchy": {"parents": [], "children": []},
            "returns": [
                {
                    "name": "get_service",
                    "kind": "function",
                    "file_path": "src/api.py",
                    "start_line": 2,
                    "signature": "def get_service() -> IService",
                }
            ],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        lines = text.split("\n")
        # Should have blank line between sections
        assert "" in lines

    def test_text_format_uses_name_fallback(self):
        """Test that name is used if signature is not available."""
        result = {
            "type_name": "IService",
            "total_found": 1,
            "implementations": [
                {
                    "name": "MyService",
                    "kind": "class",
                    "file_path": "src/services.py",
                    "start_line": 10,
                    # No signature provided
                }
            ],
            "hierarchy": {"parents": [], "children": []},
            "returns": [],
            "parameters": [],
        }

        text = _format_explore_as_text(result)

        # Should use name when signature is missing
        assert "src/services.py:10 → MyService" in text


class TestFastExploreFormatSwitching:
    """Test format switching between text and JSON in fast_explore."""

    @pytest.mark.asyncio
    async def test_text_vs_json_format_switching(self, storage_with_types):
        """Test that output_format parameter controls format."""
        from miller.server import fast_explore

        # Get text format (default)
        text_result = await fast_explore(
            mode="types",
            type_name="IUser",
            output_format="text",
            workspace="primary",
        )

        assert isinstance(text_result, str)
        assert "Type intelligence for" in text_result or "No type information" in text_result

        # Get JSON format
        json_result = await fast_explore(
            mode="types",
            type_name="IUser",
            output_format="json",
            workspace="primary",
        )

        assert isinstance(json_result, dict)
        assert "type_name" in json_result


# Fixture needed for the async test
@pytest.fixture
def storage_with_types():
    """Create storage with type relationship data for testing."""
    from miller.storage import StorageManager

    storage = StorageManager(db_path=":memory:")

    # Add test files
    storage.add_file("src/interfaces.py", "python", "", "hash1", 100)
    storage.add_file("src/implementations.py", "python", "", "hash2", 200)
    storage.add_file("src/services.py", "python", "", "hash3", 300)

    # Add symbols representing types and functions
    symbols = [
        # Interface/base type
        ("sym_iuser", "IUser", "interface", "python", "src/interfaces.py", 1, 0, 10, 0, 0, 100,
         "class IUser(Protocol)", "User interface", "public", None, None, 1.0, None),

        # Implementations
        ("sym_user", "User", "class", "python", "src/implementations.py", 1, 0, 50, 0, 0, 500,
         "class User(IUser)", "User implementation", "public", None, None, 1.0, None),

        # Functions with type parameters/returns
        ("sym_get_user", "get_user", "function", "python", "src/services.py", 1, 0, 10, 0, 0, 100,
         "def get_user(id: int) -> IUser", "Get user by ID", "public", None, None, 1.0, None),
        ("sym_create_user", "create_user", "function", "python", "src/services.py", 15, 0, 30, 0, 150, 300,
         "def create_user(user: IUser) -> bool", "Create a user", "public", None, None, 1.0, None),
    ]

    # Insert symbols
    storage.conn.executemany("""
        INSERT INTO symbols (id, name, kind, language, file_path, start_line, start_col,
                            end_line, end_col, start_byte, end_byte, signature, doc_comment,
                            visibility, parent_id, semantic_group, confidence, content_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, symbols)

    # Add relationships
    relationships = [
        # User implements IUser
        ("rel1", "sym_user", "sym_iuser", "implements", "src/implementations.py", 1, 1.0, None),
        # get_user returns IUser
        ("rel3", "sym_get_user", "sym_iuser", "returns", "src/services.py", 1, 1.0, None),
        # create_user takes IUser parameter
        ("rel4", "sym_create_user", "sym_iuser", "parameter", "src/services.py", 15, 1.0, None),
    ]

    storage.conn.executemany("""
        INSERT INTO relationships (id, from_symbol_id, to_symbol_id, kind, file_path,
                                  line_number, confidence, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, relationships)
    storage.conn.commit()

    yield storage
    storage.close()
