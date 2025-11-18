"""
Test the public extraction API functions.

Tests for:
- extract_file(content, language, file_path)
- detect_language(file_path)
- supported_languages()

CRITICAL: These tests are written BEFORE implementation (TDD).
They will FAIL until we implement the API functions.
"""

import pytest


class TestExtractFileAPI:
    """Test the extract_file() function."""

    def test_extract_file_with_python_code(self):
        """Test basic extraction from Python code."""
        from miller import miller_core

        code = "def hello(): pass"
        result = miller_core.extract_file(
            content=code,
            language="python",
            file_path="test.py"
        )

        assert result is not None
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "hello"

    def test_extract_file_with_javascript_code(self):
        """Test extraction from JavaScript code."""
        from miller import miller_core

        code = "function hello() { }"
        result = miller_core.extract_file(
            content=code,
            language="javascript",
            file_path="test.js"
        )

        # Should extract at least the hello function
        assert len(result.symbols) >= 1
        assert any(s.name == "hello" for s in result.symbols)
        assert result.symbols[0].language == "javascript"

    def test_extract_file_with_rust_code(self):
        """Test extraction from Rust code."""
        from miller import miller_core

        code = "fn hello() {}"
        result = miller_core.extract_file(
            content=code,
            language="rust",
            file_path="test.rs"
        )

        assert len(result.symbols) == 1
        assert result.symbols[0].name == "hello"
        assert result.symbols[0].language == "rust"

    def test_extract_file_with_go_code(self):
        """Test extraction from Go code."""
        from miller import miller_core

        code = "func hello() {}"
        result = miller_core.extract_file(
            content=code,
            language="go",
            file_path="test.go"
        )

        assert len(result.symbols) == 1
        assert result.symbols[0].name == "hello"
        assert result.symbols[0].language == "go"

    def test_extract_file_with_java_code(self):
        """Test extraction from Java code."""
        from miller import miller_core

        code = """class Hello {
    public void greet() {}
}"""
        result = miller_core.extract_file(
            content=code,
            language="java",
            file_path="Hello.java"
        )

        # Should extract class and method
        assert len(result.symbols) >= 2
        assert any(s.name == "Hello" for s in result.symbols)
        assert any(s.name == "greet" for s in result.symbols)

    def test_extract_file_with_empty_code(self):
        """Test extraction from empty file."""
        from miller import miller_core

        result = miller_core.extract_file(
            content="",
            language="python",
            file_path="empty.py"
        )

        # Empty file should return empty results
        assert result is not None
        assert len(result.symbols) == 0

    def test_extract_file_with_comments_only(self):
        """Test extraction from file with only comments."""
        from miller import miller_core

        code = "# This is just a comment"
        result = miller_core.extract_file(
            content=code,
            language="python",
            file_path="comments.py"
        )

        # Comments only should return no symbols
        assert len(result.symbols) == 0

    def test_extract_file_with_invalid_language_raises(self):
        """Test that invalid language raises an error."""
        from miller import miller_core

        with pytest.raises(Exception) as exc_info:
            miller_core.extract_file(
                content="test",
                language="invalid_language_xyz",
                file_path="test.xyz"
            )

        # Should raise ValueError or similar
        assert "unsupported" in str(exc_info.value).lower() or \
               "invalid" in str(exc_info.value).lower()

    def test_extract_file_with_syntax_error_returns_empty(self):
        """Test that code with syntax errors returns empty results gracefully."""
        from miller import miller_core

        # Invalid Python syntax
        code = "def hello( incomplete"
        result = miller_core.extract_file(
            content=code,
            language="python",
            file_path="invalid.py"
        )

        # Should not crash, might return empty or partial results
        assert result is not None


class TestDetectLanguageAPI:
    """Test the detect_language() function."""

    def test_detect_python_from_py_extension(self):
        """Test detection of Python from .py extension."""
        from miller import miller_core

        lang = miller_core.detect_language("test.py")
        assert lang == "python"

    def test_detect_javascript_from_js_extension(self):
        """Test detection of JavaScript from .js extension."""
        from miller import miller_core

        lang = miller_core.detect_language("test.js")
        assert lang == "javascript"

    def test_detect_typescript_from_ts_extension(self):
        """Test detection of TypeScript from .ts extension."""
        from miller import miller_core

        lang = miller_core.detect_language("test.ts")
        assert lang == "typescript"

    def test_detect_rust_from_rs_extension(self):
        """Test detection of Rust from .rs extension."""
        from miller import miller_core

        lang = miller_core.detect_language("main.rs")
        assert lang == "rust"

    def test_detect_go_from_go_extension(self):
        """Test detection of Go from .go extension."""
        from miller import miller_core

        lang = miller_core.detect_language("main.go")
        assert lang == "go"

    def test_detect_java_from_java_extension(self):
        """Test detection of Java from .java extension."""
        from miller import miller_core

        lang = miller_core.detect_language("Main.java")
        assert lang == "java"

    def test_detect_cpp_from_cpp_extension(self):
        """Test detection of C++ from .cpp extension."""
        from miller import miller_core

        lang = miller_core.detect_language("main.cpp")
        assert lang == "cpp"

    def test_detect_c_from_c_extension(self):
        """Test detection of C from .c extension."""
        from miller import miller_core

        lang = miller_core.detect_language("main.c")
        assert lang == "c"

    def test_detect_language_with_path(self):
        """Test detection works with full path."""
        from miller import miller_core

        lang = miller_core.detect_language("src/components/App.tsx")
        assert lang == "tsx"

    def test_detect_language_unknown_extension_returns_none(self):
        """Test that unknown extension returns None."""
        from miller import miller_core

        lang = miller_core.detect_language("test.xyz")
        assert lang is None

    def test_detect_language_no_extension_returns_none(self):
        """Test that file with no extension returns None."""
        from miller import miller_core

        lang = miller_core.detect_language("Makefile")
        assert lang is None


class TestSupportedLanguagesAPI:
    """Test the supported_languages() function."""

    def test_supported_languages_returns_list(self):
        """Test that supported_languages() returns a list."""
        from miller import miller_core

        langs = miller_core.supported_languages()
        assert isinstance(langs, list)
        assert len(langs) > 0

    def test_supported_languages_includes_common_languages(self):
        """Test that common languages are in the list."""
        from miller import miller_core

        langs = miller_core.supported_languages()

        # Should include these common languages
        expected = ["python", "javascript", "typescript", "rust", "go", "java"]
        for lang in expected:
            assert lang in langs, f"{lang} should be in supported languages"

    def test_supported_languages_count(self):
        """Test that we support many languages (Julie's architecture)."""
        from miller import miller_core

        langs = miller_core.supported_languages()

        # Should support many languages (Julie has 31 total including variants)
        assert len(langs) >= 25, "Should support at least 25 languages"


class TestExtractMultipleLanguages:
    """Integration tests for extracting from multiple languages."""

    def test_extract_from_5_different_languages(self):
        """Test that we can extract from 5 different languages."""
        from miller import miller_core

        test_cases = [
            ("def hello(): pass", "python", "test.py"),
            ("function hello() {}", "javascript", "test.js"),
            ("fn hello() {}", "rust", "test.rs"),
            ("func hello() {}", "go", "test.go"),
            ("void hello() {}", "java", "test.java"),
        ]

        for code, language, file_path in test_cases:
            result = miller_core.extract_file(code, language, file_path)
            assert len(result.symbols) >= 1, f"Failed to extract from {language}"
            # Find the hello symbol (might be multiple symbols)
            hello_sym = next((s for s in result.symbols if s.name == "hello"), None)
            assert hello_sym is not None, f"Didn't find 'hello' symbol in {language}"
            assert hello_sym.language == language


class TestExtractionWithUnicode:
    """Test extraction with Unicode characters."""

    def test_extract_function_with_unicode_name(self):
        """Test extraction of function with Unicode characters in name."""
        from miller import miller_core

        # Python allows Unicode identifiers
        code = "def café(): pass"
        result = miller_core.extract_file(code, "python", "test.py")

        # Should successfully extract (or gracefully handle)
        assert result is not None
        # Depending on tree-sitter support, might extract or skip
        if len(result.symbols) > 0:
            assert "caf" in result.symbols[0].name  # Might be normalized

    def test_extract_with_unicode_in_string(self):
        """Test extraction with Unicode in string literals."""
        from miller import miller_core

        code = 'def greet(): return "Hello 世界"'
        result = miller_core.extract_file(code, "python", "test.py")

        assert len(result.symbols) == 1
        assert result.symbols[0].name == "greet"

    def test_extract_with_unicode_in_comment(self):
        """Test extraction with Unicode in comments."""
        from miller import miller_core

        code = """def hello():
    '''Prints 你好'''
    pass"""
        result = miller_core.extract_file(code, "python", "test.py")

        assert len(result.symbols) == 1
        # Doc comment might contain Unicode
        if result.symbols[0].doc_comment:
            assert "你好" in result.symbols[0].doc_comment or \
                   "Prints" in result.symbols[0].doc_comment
