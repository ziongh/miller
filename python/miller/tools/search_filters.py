"""
Search result filtering utilities.

Provides post-processing filters for language and file pattern matching.
"""

import fnmatch
from typing import Any, Optional


def apply_language_filter(
    results: list[dict[str, Any]], language: Optional[str]
) -> list[dict[str, Any]]:
    """Filter results by programming language (case-insensitive).

    Args:
        results: Search results to filter
        language: Language to filter by (e.g., "python", "rust"). None returns all.

    Returns:
        Filtered results containing only the specified language.
    """
    if language is None:
        return results

    language_lower = language.lower()
    return [r for r in results if r.get("language", "").lower() == language_lower]


def apply_file_pattern_filter(
    results: list[dict[str, Any]], file_pattern: Optional[str]
) -> list[dict[str, Any]]:
    """Filter results by file path glob pattern.

    Supports standard glob patterns:
    - *.py - match extension
    - src/**/*.py - match directory + extension
    - tests/** - match all in directory

    Args:
        results: Search results to filter
        file_pattern: Glob pattern to filter by. None returns all.

    Returns:
        Filtered results matching the file pattern.
    """
    if file_pattern is None:
        return results

    filtered = []
    for r in results:
        file_path = r.get("file_path", "")
        # Use fnmatch for glob matching
        # Handle ** for recursive matching by trying both fnmatch and manual check
        if fnmatch.fnmatch(file_path, file_pattern):
            filtered.append(r)
        elif "**" in file_pattern:
            # fnmatch doesn't handle ** well, do manual check
            # Convert ** pattern to check prefix and suffix
            parts = file_pattern.split("**")
            if len(parts) == 2:
                prefix, suffix = parts
                prefix = prefix.rstrip("/")
                suffix = suffix.lstrip("/")
                # Check if file_path starts with prefix (if non-empty) and ends with suffix pattern
                prefix_match = (
                    not prefix
                    or file_path.startswith(prefix + "/")
                    or file_path.startswith(prefix)
                )
                suffix_match = (
                    not suffix
                    or fnmatch.fnmatch(file_path, "*" + suffix)
                    or fnmatch.fnmatch(file_path.split("/")[-1], suffix.lstrip("*"))
                )
                if prefix_match and suffix_match:
                    filtered.append(r)

    return filtered
