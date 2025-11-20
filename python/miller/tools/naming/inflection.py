"""
Pluralization and singularization for naming variants.
"""

from .constants import PLURAL_EXCEPTIONS, SINGULAR_EXCEPTIONS


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
