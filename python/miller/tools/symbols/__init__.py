"""Symbol tools - enhanced get_symbols implementation with ML features."""

from .core import get_symbols_enhanced
from .naming import generate_naming_variants
from .hierarchy import apply_max_depth_filter
from .filters import apply_target_filter, apply_semantic_filtering
from .formatters import (
    extract_code_bodies,
    symbol_to_dict,
    calculate_usage_frequency,
    calculate_doc_quality,
    calculate_importance_tier,
)
from .analysis import (
    find_related_symbols,
    find_cross_language_variants,
    calculate_importance_scores,
    get_reference_counts,
)

__all__ = [
    # Main function
    "get_symbols_enhanced",
    # Naming
    "generate_naming_variants",
    # Hierarchy
    "apply_max_depth_filter",
    # Filters
    "apply_target_filter",
    "apply_semantic_filtering",
    # Formatters
    "extract_code_bodies",
    "symbol_to_dict",
    "calculate_usage_frequency",
    "calculate_doc_quality",
    "calculate_importance_tier",
    # Analysis
    "find_related_symbols",
    "find_cross_language_variants",
    "calculate_importance_scores",
    "get_reference_counts",
]
