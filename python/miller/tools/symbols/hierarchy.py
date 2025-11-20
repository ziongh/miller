"""Symbol hierarchy traversal and filtering."""


def build_parent_to_children(symbols: list) -> dict[str, list[int]]:
    """Build a parent_id -> children indices map for efficient hierarchy navigation."""
    parent_to_children: dict[str, list[int]] = {}

    for idx, symbol in enumerate(symbols):
        parent_id = getattr(symbol, "parent_id", None)
        if parent_id:
            if parent_id not in parent_to_children:
                parent_to_children[parent_id] = []
            parent_to_children[parent_id].append(idx)

    return parent_to_children


def find_top_level_symbols(symbols: list) -> list[int]:
    """Find all top-level symbols (those with no parent)."""
    top_level = []
    for idx, symbol in enumerate(symbols):
        parent_id = getattr(symbol, "parent_id", None)
        if parent_id is None:
            top_level.append(idx)
    return top_level


def collect_symbols_by_depth(
    indices: list[int],
    depth: int,
    max_depth: int,
    all_symbols: list,
    parent_to_children: dict[str, list[int]],
    result: list[int]
):
    """Recursively collect symbols up to maximum depth."""
    if depth > max_depth:
        return

    for idx in indices:
        result.append(idx)

        if depth < max_depth:
            symbol_id = getattr(all_symbols[idx], "id", None)
            if symbol_id and symbol_id in parent_to_children:
                children_indices = parent_to_children[symbol_id]
                collect_symbols_by_depth(
                    children_indices,
                    depth + 1,
                    max_depth,
                    all_symbols,
                    parent_to_children,
                    result
                )


def apply_max_depth_filter(all_symbols: list, max_depth: int) -> list:
    """Apply max_depth filtering to symbols.

    Returns filtered symbols in original order, keeping only those within
    the maximum depth from top-level symbols.
    """
    parent_to_children = build_parent_to_children(all_symbols)
    top_level_indices = find_top_level_symbols(all_symbols)

    indices_to_include = []
    collect_symbols_by_depth(
        top_level_indices,
        0,
        max_depth,
        all_symbols,
        parent_to_children,
        indices_to_include
    )

    # Preserve original order
    indices_to_include.sort()

    return [all_symbols[idx] for idx in indices_to_include]
