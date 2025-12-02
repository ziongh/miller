"""
Navigation implementation package.

This package contains the implementations for navigation tools.
The main navigation.py module re-exports these for public use.

Modules:
- lookup.py: fast_lookup and symbol resolution
- fuzzy.py: fuzzy matching strategies
"""

from .lookup import (
    fast_lookup,
    get_symbol_structure,
    generate_import_path,
    format_lookup_output,
)
from .fuzzy import (
    fuzzy_find_symbol,
    levenshtein_distance,
)

__all__ = [
    "fast_lookup",
    "get_symbol_structure",
    "generate_import_path",
    "format_lookup_output",
    "fuzzy_find_symbol",
    "levenshtein_distance",
]
