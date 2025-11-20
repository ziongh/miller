"""
Naming variant generator for cross-language symbol matching.

Converts symbol names between different naming conventions to enable
tracing across language boundaries (TypeScript → Python → SQL, etc.).

This file defines the specification (TDD Phase 1).
Implementation will follow after tests are written.
"""

import re
from typing import Optional


def generate_variants(symbol_name: str) -> dict[str, str]:
    """
    Generate all naming convention variants for a symbol name.

    This enables cross-language matching:
    - TypeScript: UserService, IUser, userService
    - Python: user_service, UserService
    - SQL: users, user_service
    - C#: UserDto, IUserService
    - Rust: UserService, user_service

    Args:
        symbol_name: Original symbol name (any case convention)

    Returns:
        Dictionary with keys:
        - original: Original input name
        - snake_case: user_service
        - camel_case: userService
        - pascal_case: UserService
        - kebab_case: user-service
        - screaming_snake: USER_SERVICE
        - screaming_kebab: USER-SERVICE
        - plural_snake: user_services (for DB tables)
        - plural_pascal: UserServices
        - singular_snake: user_service (strips trailing 's')
        - singular_pascal: UserService (strips trailing 's')

    Examples:
        >>> generate_variants("UserService")
        {
            "original": "UserService",
            "snake_case": "user_service",
            "camel_case": "userService",
            "pascal_case": "UserService",
            "kebab_case": "user-service",
            "screaming_snake": "USER_SERVICE",
            "screaming_kebab": "USER-SERVICE",
            "plural_snake": "user_services",
            "plural_pascal": "UserServices",
            "singular_snake": "user_service",
            "singular_pascal": "UserService"
        }

        >>> generate_variants("IUser")  # Interface prefix
        {
            "original": "IUser",
            "snake_case": "i_user",
            "camel_case": "iUser",
            "pascal_case": "IUser",
            "without_prefix_snake": "user",  # Strips 'I' prefix
            "without_prefix_pascal": "User",
            ...
        }

        >>> generate_variants("users")  # SQL table
        {
            "original": "users",
            "snake_case": "users",
            "singular_snake": "user",
            "singular_pascal": "User",
            ...
        }

    Edge Cases:
        - Single word: "user" → {"snake_case": "user", "pascal_case": "User", ...}
        - Already snake: "user_service" → preserves as-is, generates others
        - Numbers: "OAuth2Client" → "o_auth2_client", "oAuth2Client"
        - Acronyms: "HTTPServer" → "http_server", "httpServer"
        - Prefixes: "IUser", "TUser", "EUserStatus" → variants with/without prefix
        - Suffixes: "UserDto", "UserModel" → variants with/without suffix
        - Special chars: "user-service" → treats as kebab, generates snake/camel
    """
    result = {"original": symbol_name}

    # Parse into words
    words = parse_symbol_words(symbol_name)

    if not words:
        return result

    # Generate case variants from words
    # snake_case: all lowercase, joined with _
    result["snake_case"] = "_".join(w.lower() for w in words)

    # camel_case: first word lowercase, rest capitalized
    if len(words) == 1:
        result["camel_case"] = words[0].lower()
    else:
        result["camel_case"] = words[0].lower() + "".join(w.capitalize() for w in words[1:])

    # pascal_case: all words capitalized
    result["pascal_case"] = "".join(w.capitalize() for w in words)

    # kebab-case: all lowercase, joined with -
    result["kebab_case"] = "-".join(w.lower() for w in words)

    # SCREAMING_SNAKE_CASE: all uppercase, joined with _
    result["screaming_snake"] = "_".join(w.upper() for w in words)

    # SCREAMING-KEBAB-CASE: all uppercase, joined with -
    result["screaming_kebab"] = "-".join(w.upper() for w in words)

    # Pluralization variants
    # Pluralize last word
    last_word = words[-1]
    plural_last = pluralize(last_word)
    if plural_last != last_word:
        plural_words = words[:-1] + [plural_last]
        result["plural_snake"] = "_".join(w.lower() for w in plural_words)
        result["plural_pascal"] = "".join(w.capitalize() for w in plural_words)

    # Singularize last word
    singular_last = singularize(last_word)
    if singular_last != last_word:
        singular_words = words[:-1] + [singular_last]
        result["singular_snake"] = "_".join(w.lower() for w in singular_words)
        result["singular_pascal"] = "".join(w.capitalize() for w in singular_words)

    # Prefix stripping variants
    prefix_variants = strip_common_prefixes(symbol_name)
    if len(prefix_variants) > 1:
        # Has prefixes
        for i, variant in enumerate(prefix_variants[1:], 1):  # Skip original
            variant_words = parse_symbol_words(variant)
            result[f"without_prefix_snake"] = "_".join(w.lower() for w in variant_words)
            result[f"without_prefix_pascal"] = "".join(w.capitalize() for w in variant_words)
            break  # Just add first variant (most common case)

    # Suffix stripping variants
    suffix_variants = strip_common_suffixes(symbol_name)
    if len(suffix_variants) > 1:
        # Has suffixes
        for i, variant in enumerate(suffix_variants[1:], 1):  # Skip original
            variant_words = parse_symbol_words(variant)
            result[f"without_suffix_snake"] = "_".join(w.lower() for w in variant_words)
            result[f"without_suffix_pascal"] = "".join(w.capitalize() for w in variant_words)
            break  # Just add first variant

    return result


def parse_symbol_words(symbol_name: str) -> list[str]:
    """
    Parse a symbol name into individual words for variant generation.

    Handles multiple input formats:
    - PascalCase: "UserService" → ["User", "Service"]
    - camelCase: "userService" → ["user", "Service"]
    - snake_case: "user_service" → ["user", "service"]
    - kebab-case: "user-service" → ["user", "service"]
    - SCREAMING_SNAKE: "USER_SERVICE" → ["USER", "SERVICE"]
    - Acronyms: "HTTPServer" → ["HTTP", "Server"]
    - Numbers: "OAuth2Client" → ["OAuth", "2", "Client"]

    Args:
        symbol_name: Input symbol name (any convention)

    Returns:
        List of words extracted from symbol name

    Examples:
        >>> parse_symbol_words("UserService")
        ["User", "Service"]

        >>> parse_symbol_words("user_service")
        ["user", "service"]

        >>> parse_symbol_words("HTTPServer")
        ["HTTP", "Server"]

        >>> parse_symbol_words("OAuth2Client")
        ["OAuth", "2", "Client"]

    Edge Cases:
        - Empty string: [] (empty list)
        - Single char: "x" → ["x"]
        - All caps: "HTTP" → ["HTTP"]
        - Numbers only: "123" → ["123"]
        - Mixed: "getHTTP2Response" → ["get", "HTTP", "2", "Response"]
    """
    if not symbol_name:
        return []

    # Handle snake_case and kebab-case (split on _ or -)
    if '_' in symbol_name or '-' in symbol_name:
        # Split on both _ and -
        words = re.split(r'[_-]', symbol_name)
        return [w for w in words if w]  # Filter empty strings

    # Handle camelCase and PascalCase
    # Insert spaces before uppercase letters (but handle acronyms)
    # Pattern: lowercase followed by uppercase, OR multiple uppercase followed by lowercase
    result = []
    current_word = []

    for i, char in enumerate(symbol_name):
        if i == 0:
            current_word.append(char)
        elif char.isdigit():
            # Check if we're in middle of digits (64 in base64)
            if i > 0 and symbol_name[i-1].isdigit():
                # Continue number word
                current_word.append(char)
            else:
                # Start new number word
                if current_word:
                    result.append(''.join(current_word))
                    current_word = []
                current_word.append(char)
        elif char.isupper():
            # Check if this is start of new word
            if current_word:
                # If previous char is digit or lowercase, start new word
                if symbol_name[i-1].isdigit() or symbol_name[i-1].islower():
                    result.append(''.join(current_word))
                    current_word = [char]
                # If next char is lowercase, this starts new word (HTTPServer: S starts "Server")
                elif i + 1 < len(symbol_name) and symbol_name[i+1].islower():
                    result.append(''.join(current_word))
                    current_word = [char]
                else:
                    # Continue acronym (HTTP)
                    current_word.append(char)
            else:
                current_word.append(char)
        else:
            # Lowercase letter
            if current_word and symbol_name[i-1].isdigit():
                # Digit followed by lowercase - start new word
                result.append(''.join(current_word))
                current_word = [char]
            else:
                current_word.append(char)

    if current_word:
        result.append(''.join(current_word))

    return result


def strip_common_prefixes(symbol_name: str) -> list[str]:
    """
    Strip common type prefixes from symbol names.

    Common prefixes in different languages:
    - Interfaces: I, T (TypeScript, C#)
    - Enums: E (C#, TypeScript)
    - Types: T (TypeScript, Rust)
    - Abstract: A (C++, Java)
    - Base: Base (all languages)

    Args:
        symbol_name: Symbol name that may have prefix

    Returns:
        List of variants: [original, without_prefix, ...]

    Examples:
        >>> strip_common_prefixes("IUser")
        ["IUser", "User"]

        >>> strip_common_prefixes("TUserRole")
        ["TUserRole", "UserRole"]

        >>> strip_common_prefixes("EUserStatus")
        ["EUserStatus", "UserStatus"]

        >>> strip_common_prefixes("BaseService")
        ["BaseService", "Service"]

    Edge Cases:
        - No prefix: "User" → ["User"] (only original)
        - Ambiguous: "If" → ["If"] (not a prefix)
        - Multiple: "IBaseUser" → ["IBaseUser", "BaseUser", "User"]
    """
    results = [symbol_name]

    # Single letter prefixes (I, T, E, A)
    if len(symbol_name) > 2 and symbol_name[0] in 'ITEA' and symbol_name[1].isupper():
        # Check it's not a two-letter word like "If" or "It"
        without_prefix = symbol_name[1:]
        results.append(without_prefix)

        # Recursively check for more prefixes (IBaseUser → BaseUser → User)
        more_variants = strip_common_prefixes(without_prefix)
        for variant in more_variants:
            if variant not in results:
                results.append(variant)

    # "Base" prefix
    if symbol_name.startswith("Base") and len(symbol_name) > 4 and symbol_name[4].isupper():
        without_prefix = symbol_name[4:]
        results.append(without_prefix)

        # Recursively check
        more_variants = strip_common_prefixes(without_prefix)
        for variant in more_variants:
            if variant not in results:
                results.append(variant)

    return results


def strip_common_suffixes(symbol_name: str) -> list[str]:
    """
    Strip common type suffixes from symbol names.

    Common suffixes across languages:
    - DTOs: Dto, DTO
    - Models: Model, Entity
    - Services: Service, Manager, Handler
    - Repositories: Repository, Repo
    - Controllers: Controller
    - Factories: Factory
    - Builders: Builder

    Args:
        symbol_name: Symbol name that may have suffix

    Returns:
        List of variants: [original, without_suffix, ...]

    Examples:
        >>> strip_common_suffixes("UserDto")
        ["UserDto", "User"]

        >>> strip_common_suffixes("UserService")
        ["UserService", "User"]

        >>> strip_common_suffixes("UserRepository")
        ["UserRepository", "User"]

    Edge Cases:
        - No suffix: "User" → ["User"]
        - Ambiguous: "Service" → ["Service"] (whole word is suffix)
        - Multiple: "UserServiceManager" → ["UserServiceManager", "UserService", "User"]
    """
    results = [symbol_name]

    common_suffixes = [
        "Controller", "Service", "Manager", "Handler", "Repository", "Repo",
        "Factory", "Builder", "Model", "Entity", "Dto", "DTO"
    ]

    for suffix in common_suffixes:
        if symbol_name.endswith(suffix) and len(symbol_name) > len(suffix):
            # Don't strip if the whole word IS the suffix
            without_suffix = symbol_name[:-len(suffix)]
            if without_suffix:  # Not empty after stripping
                results.append(without_suffix)

                # Recursively check for more suffixes
                more_variants = strip_common_suffixes(without_suffix)
                for variant in more_variants:
                    if variant not in results:
                        results.append(variant)
                break  # Only strip one suffix per call (recursion handles multiple)

    return results


def pluralize(word: str) -> str:
    """
    Convert singular word to plural form (English rules).

    Used for matching:
    - Python model: User → SQL table: users
    - TypeScript: UserService → users_service

    Args:
        word: Singular word

    Returns:
        Plural form of word

    Examples:
        >>> pluralize("user")
        "users"

        >>> pluralize("child")
        "children"

        >>> pluralize("status")
        "statuses"

        >>> pluralize("category")
        "categories"

    Edge Cases:
        - Already plural: "users" → "users" (no change)
        - Irregular: "child" → "children"
        - Ends in 's': "status" → "statuses"
        - Ends in 'y': "category" → "categories"
        - Ends in 'sh/ch/x': "box" → "boxes"
    """
    if not word:
        return word

    lower_word = word.lower()

    # Check irregular plurals
    if lower_word in PLURAL_EXCEPTIONS:
        # Preserve original case
        result = PLURAL_EXCEPTIONS[lower_word]
        if word[0].isupper():
            result = result[0].upper() + result[1:]
        return result

    # Check for irregular plurals that are already plural
    if lower_word in ['children', 'people', 'men', 'women', 'teeth', 'feet', 'mice', 'geese']:
        return word

    # Check if already plural (ends in 's' but not 'ss', 'us', 'is')
    # Common plural endings: -s, -es, -ies
    if lower_word.endswith('s') and not lower_word.endswith(('ss', 'us', 'is')):
        # Likely already plural - return as-is
        return word

    # Ends in 'ss', 'sh', 'ch', 'x', 'z', 'us', 'is' → add 'es'
    if lower_word.endswith(('ss', 'sh', 'ch', 'x', 'z', 'us', 'is')):
        return word + 'es'

    # Ends in consonant + 'y' → change to 'ies'
    if len(word) >= 2 and lower_word.endswith('y'):
        if lower_word[-2] not in 'aeiou':
            return word[:-1] + 'ies'

    # Regular plural: add 's'
    return word + 's'


def singularize(word: str) -> str:
    """
    Convert plural word to singular form (English rules).

    Used for matching:
    - SQL table: users → Python model: User
    - TypeScript: users → user_service

    Args:
        word: Plural word

    Returns:
        Singular form of word

    Examples:
        >>> singularize("users")
        "user"

        >>> singularize("children")
        "child"

        >>> singularize("statuses")
        "status"

        >>> singularize("categories")
        "category"

    Edge Cases:
        - Already singular: "user" → "user"
        - Irregular: "children" → "child"
        - False plural: "status" → "status" (not "statu")
    """
    if not word:
        return word

    lower_word = word.lower()

    # Check irregular singulars
    if lower_word in SINGULAR_EXCEPTIONS:
        result = SINGULAR_EXCEPTIONS[lower_word]
        if word[0].isupper():
            result = result[0].upper() + result[1:]
        return result

    # Ends in 'ies' → change to 'y'
    if lower_word.endswith('ies') and len(word) > 3:
        return word[:-3] + 'y'

    # Check for false plurals (words that end in 's' but aren't plural)
    # Common false plurals: status, basis, crisis, analysis
    if lower_word.endswith(('us', 'is', 'ss')):
        # Not actually plural - return as-is
        return word

    # Ends in 'es' → check if it's from 's', 'sh', 'ch', 'x', 'z'
    if lower_word.endswith('es') and len(word) > 2:
        # Could be: statuses → status, boxes → box
        # Try removing 'es'
        stem = word[:-2]
        if stem.endswith(('s', 'sh', 'ch', 'x', 'z', 'us', 'is')):
            return stem
        # Otherwise just remove 's' (e.g., "tables" → "table")
        return word[:-1]

    # Ends in 's' → remove 's'
    if lower_word.endswith('s') and len(word) > 1:
        return word[:-1]

    # Already singular
    return word


# Variant matching strategies (priority order)
MATCH_STRATEGIES = [
    # 1. Exact match (highest priority)
    "exact",  # Symbol names match exactly

    # 2. Case-insensitive exact
    "exact_case_insensitive",  # UserService == userservice

    # 3. Variant matches (medium priority)
    "snake_to_camel",  # user_service → userService
    "camel_to_snake",  # userService → user_service
    "pascal_to_snake",  # UserService → user_service
    "kebab_to_snake",  # user-service → user_service

    # 4. Prefix/suffix stripping
    "without_interface_prefix",  # IUser → User
    "without_type_prefix",  # TUser → User
    "without_dto_suffix",  # UserDto → User
    "without_service_suffix",  # UserService → User

    # 5. Pluralization
    "singular_to_plural",  # user → users (Python model → SQL table)
    "plural_to_singular",  # users → user (SQL table → Python model)

    # 6. Semantic similarity (lowest priority, fallback)
    "semantic_embedding",  # Cosine similarity > 0.7
]


# Configuration constants
MIN_SYMBOL_LENGTH = 1  # Minimum length for valid symbol name
MAX_SYMBOL_LENGTH = 255  # Maximum length (database limit)
PLURAL_EXCEPTIONS = {
    # Irregular plurals (English)
    "child": "children",
    "person": "people",
    "man": "men",
    "woman": "women",
    "tooth": "teeth",
    "foot": "feet",
    "mouse": "mice",
    "goose": "geese",
}
SINGULAR_EXCEPTIONS = {v: k for k, v in PLURAL_EXCEPTIONS.items()}


# Common prefixes/suffixes by language
LANGUAGE_PREFIXES = {
    "typescript": ["I", "T", "E"],  # Interface, Type, Enum
    "csharp": ["I", "T", "E", "A"],  # Interface, Type, Enum, Abstract
    "java": ["I", "A"],  # Interface, Abstract
    "rust": [],  # Rust doesn't use prefixes
    "python": [],  # Python doesn't use prefixes
    "go": [],  # Go doesn't use prefixes
}

LANGUAGE_SUFFIXES = {
    "typescript": ["Service", "Controller", "Component", "Module"],
    "csharp": ["Dto", "Model", "Entity", "Service", "Repository", "Controller"],
    "java": ["Dto", "Entity", "Service", "Repository", "Controller", "Factory"],
    "python": ["_service", "_model", "_repository", "_handler", "_manager"],
    "rust": ["_service", "_handler", "_manager"],
    "go": ["Service", "Handler", "Manager", "Repository"],
}


# Database-specific conventions
SQL_TABLE_CONVENTIONS = [
    "plural_snake_case",  # users, user_profiles
    "singular_snake_case",  # user, user_profile
]
