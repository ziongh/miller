"""
Test PyO3 type conversions between Rust and Python.

This test file verifies that Julie's Rust types (Symbol, Identifier, Relationship)
are correctly exposed to Python via PyO3 bindings.

CRITICAL: These tests are written BEFORE implementation (TDD).
They will FAIL until we implement the PyO3 bindings.
"""

import pytest


class TestSymbolTypeConversion:
    """Test that Rust Symbol struct is accessible from Python."""

    def test_symbol_can_be_created_from_rust(self):
        """Test that we can create a Symbol via Rust extraction."""
        from miller import miller_core

        # Simple Python function
        code = "def hello(): pass"

        # This will fail until we implement extract_file()
        result = miller_core.extract_file(
            content=code,
            language="python",
            file_path="test.py"
        )

        # Should have extracted the function
        assert len(result.symbols) == 1
        symbol = result.symbols[0]

        # Verify it's a Symbol type
        assert symbol is not None

    def test_symbol_name_field_accessible(self):
        """Test that Symbol.name is readable from Python."""
        from miller import miller_core

        code = "def hello(): pass"
        result = miller_core.extract_file(code, "python", "test.py")
        symbol = result.symbols[0]

        # Test name field
        assert symbol.name == "hello"
        assert isinstance(symbol.name, str)

    def test_symbol_kind_field_accessible(self):
        """Test that Symbol.kind is readable from Python."""
        from miller import miller_core

        code = "def hello(): pass"
        result = miller_core.extract_file(code, "python", "test.py")
        symbol = result.symbols[0]

        # Test kind field (Rust enum → Python string)
        assert symbol.kind == "function"
        assert isinstance(symbol.kind, str)

    def test_symbol_all_required_fields_accessible(self):
        """Test that all required Symbol fields are accessible."""
        from miller import miller_core

        code = """def hello():
    '''Say hello.'''
    pass"""
        result = miller_core.extract_file(code, "python", "test.py")
        symbol = result.symbols[0]

        # Required fields (must always exist)
        assert isinstance(symbol.id, str)
        assert len(symbol.id) > 0  # MD5 hash should be non-empty

        assert symbol.name == "hello"
        assert symbol.kind == "function"
        assert symbol.language == "python"
        assert symbol.file_path == "test.py"

        # Line numbers (1-based)
        assert symbol.start_line >= 1
        assert symbol.end_line >= symbol.start_line

        # Column numbers (0-based)
        assert symbol.start_column >= 0
        assert symbol.end_column >= 0

        # Byte offsets
        assert symbol.start_byte >= 0
        assert symbol.end_byte >= symbol.start_byte

    def test_symbol_optional_fields_accessible(self):
        """Test that optional Symbol fields work (can be None)."""
        from miller import miller_core

        code = """def hello(name: str) -> str:
    '''Say hello.'''
    return f"Hello, {name}" """
        result = miller_core.extract_file(code, "python", "test.py")
        symbol = result.symbols[0]

        # Optional fields (can be None or have values)
        # signature: Should exist for this function
        assert symbol.signature is not None
        assert "name" in symbol.signature  # Parameter should be in signature

        # doc_comment: Should exist (we have a docstring)
        assert symbol.doc_comment is not None
        assert "Say hello" in symbol.doc_comment

        # visibility: Might be None for Python (no explicit visibility)
        # Just verify the field exists and is accessible
        _ = symbol.visibility

        # parent_id: Should be None (top-level function)
        assert symbol.parent_id is None

        # metadata: Might be None
        _ = symbol.metadata

        # semantic_group: Might be None
        _ = symbol.semantic_group

        # confidence: Might be None
        _ = symbol.confidence

        # code_context: Might be None
        _ = symbol.code_context

        # content_type: Might be None
        _ = symbol.content_type

    def test_symbol_with_parent_id(self):
        """Test that Symbol.parent_id works for methods in classes."""
        from miller import miller_core

        code = """class Greeter:
    def hello(self):
        pass"""
        result = miller_core.extract_file(code, "python", "test.py")

        # Should have both class and method
        assert len(result.symbols) == 2

        # Find the class and method
        class_sym = next(s for s in result.symbols if s.kind == "class")
        method_sym = next(s for s in result.symbols if s.kind == "method")

        # Method should have parent_id pointing to class
        assert method_sym.parent_id == class_sym.id
        assert method_sym.name == "hello"

    def test_symbol_repr_works(self):
        """Test that Symbol has a useful string representation."""
        from miller import miller_core

        code = "def hello(): pass"
        result = miller_core.extract_file(code, "python", "test.py")
        symbol = result.symbols[0]

        # Should have a repr
        repr_str = repr(symbol)
        assert "Symbol" in repr_str or "hello" in repr_str


class TestIdentifierTypeConversion:
    """Test that Rust Identifier struct is accessible from Python."""

    def test_identifier_extracted_for_function_call(self):
        """Test that identifiers (usage references) are extracted."""
        from miller import miller_core

        code = """def greet():
    print("hello")  # print is a function call"""
        result = miller_core.extract_file(code, "python", "test.py")

        # Should have at least one identifier (the print call)
        assert len(result.identifiers) > 0

        # Find the print identifier
        print_id = next((i for i in result.identifiers if i.name == "print"), None)
        assert print_id is not None

    def test_identifier_all_fields_accessible(self):
        """Test that all Identifier fields are accessible."""
        from miller import miller_core

        code = """def greet():
    print("hello")"""
        result = miller_core.extract_file(code, "python", "test.py")

        identifier = result.identifiers[0]

        # Required fields
        assert isinstance(identifier.id, str)
        assert isinstance(identifier.name, str)
        assert isinstance(identifier.kind, str)  # Enum → string
        assert identifier.language == "python"
        assert identifier.file_path == "test.py"

        # Position fields
        assert identifier.start_line >= 1
        assert identifier.end_line >= identifier.start_line
        assert identifier.start_column >= 0
        assert identifier.end_column >= 0
        assert identifier.start_byte >= 0
        assert identifier.end_byte >= identifier.start_byte

        # Optional fields
        _ = identifier.containing_symbol_id
        _ = identifier.target_symbol_id  # None until resolved

        # Confidence (should be float)
        assert isinstance(identifier.confidence, float)
        assert 0.0 <= identifier.confidence <= 1.0

        # Code context
        _ = identifier.code_context


class TestRelationshipTypeConversion:
    """Test that Rust Relationship struct is accessible from Python."""

    def test_relationship_extracted_for_inheritance(self):
        """Test that relationships are extracted for class inheritance."""
        from miller import miller_core

        code = """class Base:
    pass

class Derived(Base):
    pass"""
        result = miller_core.extract_file(code, "python", "test.py")

        # Should have an "extends" relationship (Derived extends Base)
        assert len(result.relationships) > 0

        rel = result.relationships[0]
        assert rel.kind == "extends"

    def test_relationship_all_fields_accessible(self):
        """Test that all Relationship fields are accessible."""
        from miller import miller_core

        code = """class Base:
    pass

class Derived(Base):
    pass"""
        result = miller_core.extract_file(code, "python", "test.py")

        rel = result.relationships[0]

        # Required fields
        assert isinstance(rel.id, str)
        assert isinstance(rel.from_symbol_id, str)
        assert isinstance(rel.to_symbol_id, str)
        assert isinstance(rel.kind, str)  # Enum → string
        assert rel.file_path == "test.py"
        assert rel.line_number >= 1

        # Confidence
        assert isinstance(rel.confidence, float)
        assert 0.0 <= rel.confidence <= 1.0

        # Optional metadata
        _ = rel.metadata


class TestExtractionResultsContainer:
    """Test that ExtractionResults container works."""

    def test_extraction_results_has_all_fields(self):
        """Test that ExtractionResults exposes symbols, identifiers, relationships."""
        from miller import miller_core

        code = """class Base:
    pass

class Derived(Base):
    def hello(self):
        print("hi")"""
        result = miller_core.extract_file(code, "python", "test.py")

        # Should have all three collections
        assert hasattr(result, "symbols")
        assert hasattr(result, "identifiers")
        assert hasattr(result, "relationships")

        # Should be iterable
        assert len(result.symbols) > 0
        assert len(result.identifiers) > 0
        assert len(result.relationships) > 0


class TestEnumConversions:
    """Test that Rust enums are correctly converted to Python strings."""

    def test_symbol_kind_enum_values(self):
        """Test all SymbolKind enum values are converted correctly."""
        from miller import miller_core

        # Test various symbol kinds
        test_cases = [
            ("def foo(): pass", "function"),
            ("class Foo: pass", "class"),
            ("x = 42", "variable"),
        ]

        for code, expected_kind in test_cases:
            result = miller_core.extract_file(code, "python", "test.py")
            assert len(result.symbols) > 0
            # Find the symbol with expected kind
            symbol = next((s for s in result.symbols if s.kind == expected_kind), None)
            assert symbol is not None, f"Expected to find {expected_kind} in {code}"

    def test_identifier_kind_enum_values(self):
        """Test IdentifierKind enum values."""
        from miller import miller_core

        code = """def greet():
    print("hello")"""
        result = miller_core.extract_file(code, "python", "test.py")

        # Should have a "call" identifier for print()
        assert any(i.kind == "call" for i in result.identifiers)

    def test_relationship_kind_enum_values(self):
        """Test RelationshipKind enum values."""
        from miller import miller_core

        code = """class Base:
    pass

class Derived(Base):
    pass"""
        result = miller_core.extract_file(code, "python", "test.py")

        # Should have an "extends" relationship
        assert any(r.kind == "extends" for r in result.relationships)
