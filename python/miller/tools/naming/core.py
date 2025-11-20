"""
Core naming variant generation.
"""

import re
from typing import Optional

from .parsers import parse_symbol_words, strip_common_prefixes, strip_common_suffixes
from .inflection import pluralize, singularize


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
    # Special handling:
    # 1. Mixed-case words (OAuth) split further into parts (O, Auth)
    # 2. Digits attach to previous word without separator (OAuth2 → o_auth2 not o_auth_2)
    snake_parts = []
    for i, w in enumerate(words):
        if w.isdigit() and snake_parts:
            # Attach digit to previous word
            snake_parts[-1] += w
        elif len(w) > 1 and any(c.isupper() for c in w) and any(c.islower() for c in w):
            # Mixed case word like "OAuth" - split into parts (O + Auth)
            # Use parse_symbol_words recursively to split it properly
            sub_words = parse_symbol_words(w)
            for j, sub in enumerate(sub_words):
                if sub.isdigit() and snake_parts:
                    snake_parts[-1] += sub
                else:
                    snake_parts.append(sub.lower())
        else:
            snake_parts.append(w.lower())
    result["snake_case"] = "_".join(snake_parts)

    # camel_case: first word lowercase, rest capitalized
    # Special handling:
    # - ALL CAPS words (USER) → lowercase entirely (user)
    # - Mixed case (OAuth) → lowercase first letter only (oAuth)
    # - Digits attach to previous word
    if len(words) == 1:
        w = words[0]
        if w.isupper():
            # ALL CAPS → lowercase entirely
            result["camel_case"] = w.lower()
        else:
            # Mixed case or lowercase → lowercase first letter only
            result["camel_case"] = w[0].lower() + w[1:] if w else ""
    else:
        # First word
        first_word = words[0]
        if first_word.isupper():
            # ALL CAPS → lowercase entirely
            first = first_word.lower()
        else:
            # Mixed case → lowercase first letter only (OAuth → oAuth)
            first = first_word[0].lower() + first_word[1:] if first_word else ""
        camel_parts = [first]

        for w in words[1:]:
            if w.isdigit() and camel_parts:
                # Attach digit to previous word
                camel_parts[-1] += w
            else:
                camel_parts.append(w.capitalize() if w else "")
        result["camel_case"] = "".join(camel_parts)

    # pascal_case: all words capitalized
    # Special handling:
    # - ALL CAPS words (USER) → capitalize properly (User)
    # - Mixed case (OAuth) → preserve (OAuth)
    # - Digits attach to previous word
    pascal_parts = []
    for w in words:
        if w.isdigit() and pascal_parts:
            # Attach digit to previous word
            pascal_parts[-1] += w
        elif w.isupper():
            # ALL CAPS → capitalize (first upper, rest lower)
            pascal_parts.append(w.capitalize() if w else "")
        elif len(w) > 1 and w[0].isupper() and any(c.islower() for c in w[1:]):
            # Mixed case like OAuth → preserve as-is
            pascal_parts.append(w)
        else:
            pascal_parts.append(w.capitalize() if w else "")
    result["pascal_case"] = "".join(pascal_parts)

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


