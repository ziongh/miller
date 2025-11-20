"""
Tests for naming variant generator.

TDD Phase 2: Write tests BEFORE implementation.
These tests define the exact behavior we expect from the naming variant system.
"""

import pytest

from miller.tools.naming import (
    generate_variants,
    parse_symbol_words,
    pluralize,
    singularize,
    strip_common_prefixes,
    strip_common_suffixes,
)


class TestGenerateVariants:
    """Test the main generate_variants function."""

    def test_pascal_case_input(self):
        """PascalCase input should generate all variants correctly."""
        result = generate_variants("UserService")

        assert result["original"] == "UserService"
        assert result["snake_case"] == "user_service"
        assert result["camel_case"] == "userService"
        assert result["pascal_case"] == "UserService"
        assert result["kebab_case"] == "user-service"
        assert result["screaming_snake"] == "USER_SERVICE"
        assert result["screaming_kebab"] == "USER-SERVICE"
        assert result["plural_snake"] == "user_services"
        assert result["plural_pascal"] == "UserServices"

    def test_snake_case_input(self):
        """snake_case input should generate all variants correctly."""
        result = generate_variants("user_service")

        assert result["original"] == "user_service"
        assert result["snake_case"] == "user_service"
        assert result["camel_case"] == "userService"
        assert result["pascal_case"] == "UserService"
        assert result["kebab_case"] == "user-service"
        assert result["screaming_snake"] == "USER_SERVICE"

    def test_camel_case_input(self):
        """camelCase input should generate all variants correctly."""
        result = generate_variants("userService")

        assert result["original"] == "userService"
        assert result["snake_case"] == "user_service"
        assert result["camel_case"] == "userService"
        assert result["pascal_case"] == "UserService"

    def test_kebab_case_input(self):
        """kebab-case input should generate all variants correctly."""
        result = generate_variants("user-service")

        assert result["original"] == "user-service"
        assert result["snake_case"] == "user_service"
        assert result["camel_case"] == "userService"
        assert result["pascal_case"] == "UserService"
        assert result["kebab_case"] == "user-service"

    def test_screaming_snake_input(self):
        """SCREAMING_SNAKE input should generate all variants correctly."""
        result = generate_variants("USER_SERVICE")

        assert result["original"] == "USER_SERVICE"
        assert result["snake_case"] == "user_service"
        assert result["camel_case"] == "userService"
        assert result["pascal_case"] == "UserService"
        assert result["screaming_snake"] == "USER_SERVICE"

    def test_single_word(self):
        """Single word should generate variants correctly."""
        result = generate_variants("user")

        assert result["original"] == "user"
        assert result["snake_case"] == "user"
        assert result["camel_case"] == "user"
        assert result["pascal_case"] == "User"
        assert result["plural_snake"] == "users"
        assert result["plural_pascal"] == "Users"

    def test_interface_prefix(self):
        """Interface prefix (IUser) should generate variants with and without prefix."""
        result = generate_variants("IUser")

        assert result["original"] == "IUser"
        assert result["snake_case"] == "i_user"
        assert result["pascal_case"] == "IUser"
        # Should also have variants without prefix
        assert "without_prefix_snake" in result
        assert result["without_prefix_snake"] == "user"
        assert result["without_prefix_pascal"] == "User"

    def test_dto_suffix(self):
        """DTO suffix should generate variants with and without suffix."""
        result = generate_variants("UserDto")

        assert result["original"] == "UserDto"
        assert result["snake_case"] == "user_dto"
        # Should also have variants without suffix
        assert "without_suffix_snake" in result
        assert result["without_suffix_snake"] == "user"
        assert result["without_suffix_pascal"] == "User"

    def test_numbers_in_name(self):
        """Names with numbers (OAuth2Client) should parse correctly."""
        result = generate_variants("OAuth2Client")

        assert result["original"] == "OAuth2Client"
        assert result["snake_case"] == "o_auth2_client"
        assert result["camel_case"] == "oAuth2Client"
        assert result["pascal_case"] == "OAuth2Client"

    def test_acronyms(self):
        """Acronyms (HTTPServer) should parse correctly."""
        result = generate_variants("HTTPServer")

        assert result["original"] == "HTTPServer"
        # Should recognize HTTP as single word
        assert result["snake_case"] == "http_server"
        assert result["camel_case"] == "httpServer"

    def test_sql_table_plural(self):
        """SQL table names (users) should generate singular variants."""
        result = generate_variants("users")

        assert result["original"] == "users"
        assert result["singular_snake"] == "user"
        assert result["singular_pascal"] == "User"


class TestParseSymbolWords:
    """Test word parsing from different naming conventions."""

    def test_pascal_case(self):
        """Parse PascalCase into words."""
        assert parse_symbol_words("UserService") == ["User", "Service"]
        assert parse_symbol_words("User") == ["User"]

    def test_camel_case(self):
        """Parse camelCase into words."""
        assert parse_symbol_words("userService") == ["user", "Service"]
        assert parse_symbol_words("getUserById") == ["get", "User", "By", "Id"]

    def test_snake_case(self):
        """Parse snake_case into words."""
        assert parse_symbol_words("user_service") == ["user", "service"]
        assert parse_symbol_words("get_user_by_id") == ["get", "user", "by", "id"]

    def test_kebab_case(self):
        """Parse kebab-case into words."""
        assert parse_symbol_words("user-service") == ["user", "service"]

    def test_screaming_snake(self):
        """Parse SCREAMING_SNAKE_CASE into words."""
        assert parse_symbol_words("USER_SERVICE") == ["USER", "SERVICE"]

    def test_acronyms(self):
        """Parse acronyms as single words."""
        assert parse_symbol_words("HTTPServer") == ["HTTP", "Server"]
        assert parse_symbol_words("XMLParser") == ["XML", "Parser"]

    def test_numbers(self):
        """Parse numbers correctly."""
        assert parse_symbol_words("OAuth2Client") == ["OAuth", "2", "Client"]
        assert parse_symbol_words("base64Encode") == ["base", "64", "Encode"]

    def test_mixed_conventions(self):
        """Parse mixed conventions."""
        assert parse_symbol_words("getHTTP2Response") == ["get", "HTTP", "2", "Response"]

    def test_empty_string(self):
        """Empty string returns empty list."""
        assert parse_symbol_words("") == []

    def test_single_char(self):
        """Single character."""
        assert parse_symbol_words("x") == ["x"]
        assert parse_symbol_words("X") == ["X"]


class TestStripPrefixes:
    """Test stripping common type prefixes."""

    def test_interface_prefix(self):
        """Strip I prefix from interfaces."""
        assert strip_common_prefixes("IUser") == ["IUser", "User"]
        assert strip_common_prefixes("IUserService") == ["IUserService", "UserService"]

    def test_type_prefix(self):
        """Strip T prefix from types."""
        assert strip_common_prefixes("TUser") == ["TUser", "User"]
        assert strip_common_prefixes("TUserRole") == ["TUserRole", "UserRole"]

    def test_enum_prefix(self):
        """Strip E prefix from enums."""
        assert strip_common_prefixes("EUserStatus") == ["EUserStatus", "UserStatus"]

    def test_base_prefix(self):
        """Strip Base prefix."""
        assert strip_common_prefixes("BaseService") == ["BaseService", "Service"]
        assert strip_common_prefixes("BaseController") == ["BaseController", "Controller"]

    def test_no_prefix(self):
        """No prefix returns only original."""
        assert strip_common_prefixes("User") == ["User"]
        assert strip_common_prefixes("UserService") == ["UserService"]

    def test_ambiguous_not_prefix(self):
        """Don't strip when it's not actually a prefix."""
        # "If" is a word, not "I" prefix + "f"
        assert strip_common_prefixes("If") == ["If"]
        # "It" is a word, not "I" prefix + "t"
        assert strip_common_prefixes("It") == ["It"]

    def test_multiple_prefixes(self):
        """Multiple prefixes (IBaseUser)."""
        result = strip_common_prefixes("IBaseUser")
        assert "IBaseUser" in result
        assert "BaseUser" in result  # Strip I
        assert "User" in result  # Strip IBase


class TestStripSuffixes:
    """Test stripping common type suffixes."""

    def test_dto_suffix(self):
        """Strip Dto suffix."""
        assert strip_common_suffixes("UserDto") == ["UserDto", "User"]
        assert strip_common_suffixes("UserDTO") == ["UserDTO", "User"]

    def test_model_suffix(self):
        """Strip Model suffix."""
        assert strip_common_suffixes("UserModel") == ["UserModel", "User"]

    def test_entity_suffix(self):
        """Strip Entity suffix."""
        assert strip_common_suffixes("UserEntity") == ["UserEntity", "User"]

    def test_service_suffix(self):
        """Strip Service suffix."""
        assert strip_common_suffixes("UserService") == ["UserService", "User"]

    def test_repository_suffix(self):
        """Strip Repository suffix."""
        assert strip_common_suffixes("UserRepository") == ["UserRepository", "User"]
        assert strip_common_suffixes("UserRepo") == ["UserRepo", "User"]

    def test_controller_suffix(self):
        """Strip Controller suffix."""
        assert strip_common_suffixes("UserController") == ["UserController", "User"]

    def test_no_suffix(self):
        """No suffix returns only original."""
        assert strip_common_suffixes("User") == ["User"]

    def test_whole_word_is_suffix(self):
        """Don't strip if whole word is the suffix."""
        assert strip_common_suffixes("Service") == ["Service"]
        assert strip_common_suffixes("Model") == ["Model"]

    def test_multiple_suffixes(self):
        """Multiple suffixes (UserServiceManager)."""
        result = strip_common_suffixes("UserServiceManager")
        assert "UserServiceManager" in result
        assert "UserService" in result  # Strip Manager
        assert "User" in result  # Strip ServiceManager


class TestPluralize:
    """Test English pluralization rules."""

    def test_regular_plural(self):
        """Regular pluralization (add 's')."""
        assert pluralize("user") == "users"
        assert pluralize("service") == "services"
        assert pluralize("table") == "tables"

    def test_ends_in_s(self):
        """Words ending in 's' add 'es'."""
        assert pluralize("status") == "statuses"
        assert pluralize("class") == "classes"

    def test_ends_in_sh_ch_x(self):
        """Words ending in sh/ch/x add 'es'."""
        assert pluralize("box") == "boxes"
        assert pluralize("match") == "matches"
        assert pluralize("dish") == "dishes"

    def test_ends_in_y(self):
        """Words ending in 'y' change to 'ies'."""
        assert pluralize("category") == "categories"
        assert pluralize("entity") == "entities"
        # But not if preceded by vowel
        assert pluralize("key") == "keys"
        assert pluralize("day") == "days"

    def test_irregular_plurals(self):
        """Irregular plurals."""
        assert pluralize("child") == "children"
        assert pluralize("person") == "people"
        assert pluralize("man") == "men"
        assert pluralize("woman") == "women"
        assert pluralize("tooth") == "teeth"
        assert pluralize("foot") == "feet"
        assert pluralize("mouse") == "mice"

    def test_already_plural(self):
        """Already plural returns unchanged."""
        assert pluralize("users") == "users"
        assert pluralize("children") == "children"


class TestSingularize:
    """Test English singularization rules."""

    def test_regular_singular(self):
        """Regular singularization (remove 's')."""
        assert singularize("users") == "user"
        assert singularize("services") == "service"
        assert singularize("tables") == "table"

    def test_ends_in_es(self):
        """Words ending in 'es'."""
        assert singularize("statuses") == "status"
        assert singularize("classes") == "class"
        assert singularize("boxes") == "box"

    def test_ends_in_ies(self):
        """Words ending in 'ies' change to 'y'."""
        assert singularize("categories") == "category"
        assert singularize("entities") == "entity"

    def test_irregular_singulars(self):
        """Irregular singulars."""
        assert singularize("children") == "child"
        assert singularize("people") == "person"
        assert singularize("men") == "man"
        assert singularize("women") == "woman"
        assert singularize("teeth") == "tooth"
        assert singularize("feet") == "foot"
        assert singularize("mice") == "mouse"

    def test_already_singular(self):
        """Already singular returns unchanged."""
        assert singularize("user") == "user"
        assert singularize("child") == "child"

    def test_false_plural(self):
        """Don't incorrectly singularize words that look plural."""
        # "status" ends in 's' but isn't plural
        assert singularize("status") == "status"


class TestCrossLanguageMatching:
    """Test real-world cross-language matching scenarios."""

    def test_typescript_to_python_interface(self):
        """TypeScript IUser → Python user."""
        ts_variants = generate_variants("IUser")
        py_variants = generate_variants("user")

        # Should match via: IUser → i_user → user
        assert ts_variants["without_prefix_snake"] == py_variants["snake_case"]

    def test_typescript_to_python_service(self):
        """TypeScript UserService → Python user_service."""
        ts_variants = generate_variants("UserService")
        py_variants = generate_variants("user_service")

        assert ts_variants["snake_case"] == py_variants["snake_case"]

    def test_python_model_to_sql_table(self):
        """Python User model → SQL users table."""
        py_variants = generate_variants("User")
        sql_variants = generate_variants("users")

        # Should match via: User → user → users (pluralization)
        assert py_variants["plural_snake"] == sql_variants["snake_case"]

    def test_csharp_dto_to_typescript(self):
        """C# UserDto → TypeScript User."""
        cs_variants = generate_variants("UserDto")
        ts_variants = generate_variants("User")

        # Should match via: UserDto → User (strip suffix)
        assert cs_variants["without_suffix_pascal"] == ts_variants["pascal_case"]

    def test_rust_to_sql(self):
        """Rust user_service → SQL user_services."""
        rust_variants = generate_variants("user_service")
        sql_variants = generate_variants("user_services")

        assert rust_variants["plural_snake"] == sql_variants["snake_case"]

    def test_complex_chain(self):
        """Complex chain: IUserService → user_service → UserDto → users."""
        # TypeScript interface
        ts_interface = generate_variants("IUserService")
        # Python function
        py_function = generate_variants("user_service")
        # C# DTO
        cs_dto = generate_variants("UserDto")
        # SQL table
        sql_table = generate_variants("users")

        # Verify matching chain exists
        # IUserService → UserService (strip prefix)
        assert ts_interface["without_prefix_pascal"] == "UserService"
        # UserService → user_service (snake case)
        assert ts_interface["without_prefix_snake"] == "user_service"
        # user_service matches Python directly
        assert py_function["snake_case"] == "user_service"
        # Can trace to users via pluralization
        assert py_function["plural_snake"] == "user_services"
