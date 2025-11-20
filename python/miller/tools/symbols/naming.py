"""Naming convention helpers for cross-language symbol detection."""

import re


def generate_naming_variants(name: str) -> set[str]:
    """
    Generate naming convention variants for cross-language symbol detection.

    Converts between snake_case, camelCase, PascalCase, kebab-case, and lowercase.

    Args:
        name: Symbol name in any convention

    Returns:
        Set of all naming variants

    Examples:
        >>> generate_naming_variants("UserService")
        {'user_service', 'userService', 'UserService', 'user-service', 'userservice'}

        >>> generate_naming_variants("user_service")
        {'user_service', 'userService', 'UserService', 'user-service', 'userservice'}
    """
    if not name:
        return set()

    variants = set()
    variants.add(name)  # Always include original

    # Split into words based on various delimiters and case changes
    # Handle snake_case, kebab-case, PascalCase, camelCase
    words = []

    # First, split by underscores and hyphens
    parts = re.split(r'[_-]', name)

    for part in parts:
        # Split camelCase/PascalCase within each part
        # Insert space before uppercase letters (except at start)
        spaced = re.sub(r'([a-z])([A-Z])', r'\1 \2', part)
        # Split on spaces
        word_parts = spaced.split()
        words.extend(word_parts)

    # Filter out empty strings
    words = [w.lower() for w in words if w]

    if not words:
        # Single word, no delimiters
        words = [name.lower()]

    # Generate all variants
    if words:
        # snake_case
        variants.add('_'.join(words))

        # kebab-case
        variants.add('-'.join(words))

        # camelCase
        if len(words) > 1:
            variants.add(words[0] + ''.join(w.capitalize() for w in words[1:]))
        else:
            variants.add(words[0])

        # PascalCase
        variants.add(''.join(w.capitalize() for w in words))

        # lowercase (no delimiters)
        variants.add(''.join(words))

        # Also add lowercase version of original
        variants.add(name.lower())

    return variants
