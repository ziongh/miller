"""
Naming variant generation for cross-language symbol matching.

Converts symbol names between different naming conventions to enable
tracing across language boundaries (TypeScript → Python → SQL, etc.).
"""

from .core import generate_variants
from .parsers import parse_symbol_words, strip_common_prefixes, strip_common_suffixes
from .inflection import pluralize, singularize
from .constants import (
    MATCH_STRATEGIES,
    MIN_SYMBOL_LENGTH,
    MAX_SYMBOL_LENGTH,
    PLURAL_EXCEPTIONS,
    SINGULAR_EXCEPTIONS,
    LANGUAGE_PREFIXES,
    LANGUAGE_SUFFIXES,
    SQL_TABLE_CONVENTIONS,
)

__all__ = [
    "generate_variants",
    "parse_symbol_words",
    "strip_common_prefixes",
    "strip_common_suffixes",
    "pluralize",
    "singularize",
    "MATCH_STRATEGIES",
    "MIN_SYMBOL_LENGTH",
    "MAX_SYMBOL_LENGTH",
    "PLURAL_EXCEPTIONS",
    "SINGULAR_EXCEPTIONS",
    "LANGUAGE_PREFIXES",
    "LANGUAGE_SUFFIXES",
    "SQL_TABLE_CONVENTIONS",
]
