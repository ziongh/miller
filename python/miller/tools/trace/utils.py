"""
Utility functions for trace formatting and metrics.
"""

from miller.tools.trace_types import TraceNode


def _count_nodes(node: TraceNode) -> int:
    """Count total nodes in tree."""
    count = 1
    for child in node["children"]:
        count += _count_nodes(child)
    return count


def _get_max_depth(node: TraceNode) -> int:
    """Get maximum depth reached in tree."""
    if not node["children"]:
        return node["depth"]

    return max(_get_max_depth(child) for child in node["children"])


def _format_as_tree(
    node: TraceNode,
    indent: str = "",
    is_last: bool = True,
    max_depth: int = 10,
    max_depth_reached: int = 0,
) -> str:
    """
    Format trace tree as human-readable ASCII tree.

    Example output:
        UserService (typescript) @ src/services/user.ts:10
        ├─[Call]→ user_service (python) @ api/users.py:5
        │  └─[Call]→ User (python) @ models/user.py:12
        └─[Call]→ createUser (typescript) @ src/api/users.ts:22

        ... (max depth 2 reached, tree truncated)

    Args:
        node: Root node of trace tree
        indent: Current indentation string
        is_last: Whether this is the last child
        max_depth: Maximum depth limit
        max_depth_reached: Actual maximum depth reached in tree
    """
    # Build line for current node
    connector = "└─" if is_last else "├─"
    if node["depth"] == 0:
        # Root node - no connector
        line = f"{node['name']} ({node['language']}) @ {node['file_path']}:{node['line']}\n"
    else:
        rel_kind = node.get("relationship_kind", "Call")
        line = f"{indent}{connector}[{rel_kind}]→ {node['name']} ({node['language']}) @ {node['file_path']}:{node['line']}\n"

    # Recursively format children
    for i, child in enumerate(node["children"]):
        is_child_last = i == len(node["children"]) - 1
        if node["depth"] == 0:
            child_indent = ""
        else:
            child_indent = indent + ("   " if is_last else "│  ")
        line += _format_as_tree(child, child_indent, is_child_last, max_depth, max_depth_reached)

    # Add truncation indicator at the bottom
    if node["depth"] == 0 and max_depth_reached >= max_depth:
        line += f"\n... (max depth {max_depth_reached} reached, tree truncated)"

    return line
