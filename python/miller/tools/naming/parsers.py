"""
Symbol name parsing and prefix/suffix stripping.
"""

import re
from .constants import LANGUAGE_PREFIXES, LANGUAGE_SUFFIXES


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
                # EXCEPT: if we'll hit a digit soon (OAuth2 should be one word, not O + Auth)
                elif i + 1 < len(symbol_name) and symbol_name[i+1].islower():
                    # Look ahead: if there's a digit coming after lowercase letters, keep together
                    digit_ahead = False
                    for j in range(i+1, len(symbol_name)):
                        if symbol_name[j].isdigit():
                            digit_ahead = True
                            break
                        elif symbol_name[j].isupper():
                            break  # Hit another uppercase, stop looking

                    if digit_ahead and len(current_word) == 1 and current_word[0].isupper():
                        # Single uppercase + lowercase + digit ahead = keep together (OAuth2)
                        current_word.append(char)
                    else:
                        # Normal split (HTTPServer → HTTP + Server)
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


