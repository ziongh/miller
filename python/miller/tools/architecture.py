"""
Architecture mapping tool for high-level codebase visualization.

Provides a "zoom out" view of module dependencies, allowing agents to
understand system architecture without reading thousands of files.
"""

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from miller.storage import StorageManager

logger = logging.getLogger("miller.architecture")


def _extract_directory_at_depth(path: str, depth: int) -> str:
    """
    Extract directory path at a specific depth.

    Args:
        path: Full file path (e.g., "src/auth/login/handlers.py")
        depth: Number of directory components to include (e.g., 2 → "src/auth")

    Returns:
        Directory path truncated to depth, or full path if shallower
    """
    # Handle both forward and back slashes
    parts = path.replace("\\", "/").split("/")

    # If depth is 0 or path has no directories, return the first part or empty
    if depth <= 0:
        return parts[0] if parts else ""

    # Extract up to 'depth' directory components (excluding filename)
    dir_parts = parts[:-1] if "." in parts[-1] else parts  # Remove filename if present
    return "/".join(dir_parts[:depth]) if dir_parts else parts[0]


def _build_dependency_graph(
    dependencies: list[dict],
    depth: int = 2,
) -> dict[str, dict[str, dict]]:
    """
    Build a graph structure from raw dependencies.

    Args:
        dependencies: List of dicts from get_cross_directory_dependencies
        depth: Directory depth for grouping

    Returns:
        Dict mapping source_dir → {target_dir → {edge_count, kinds}}
    """
    graph = defaultdict(lambda: defaultdict(lambda: {"edge_count": 0, "kinds": set()}))

    for dep in dependencies:
        source = _extract_directory_at_depth(dep["source_dir"], depth)
        target = _extract_directory_at_depth(dep["target_dir"], depth)

        if source != target and source and target:
            graph[source][target]["edge_count"] += dep["edge_count"]
            if dep.get("relationship_kinds"):
                for kind in dep["relationship_kinds"].split(","):
                    graph[source][target]["kinds"].add(kind.strip())

    return graph


def _generate_mermaid(graph: dict, title: str = "Architecture") -> str:
    """
    Generate Mermaid.js flowchart syntax from dependency graph.

    Args:
        graph: Dependency graph from _build_dependency_graph
        title: Chart title

    Returns:
        Mermaid.js diagram string
    """
    lines = [f"---", f"title: {title}", f"---", "flowchart TD"]

    # Collect all unique nodes
    nodes = set()
    for source, targets in graph.items():
        nodes.add(source)
        for target in targets:
            nodes.add(target)

    # Create node definitions with sanitized IDs
    node_ids = {}
    for i, node in enumerate(sorted(nodes)):
        safe_id = f"N{i}"
        node_ids[node] = safe_id
        # Escape special characters in label
        label = node.replace('"', "'")
        lines.append(f'    {safe_id}["{label}"]')

    # Add edges with weight labels
    for source, targets in sorted(graph.items()):
        source_id = node_ids[source]
        for target, data in sorted(targets.items(), key=lambda x: -x[1]["edge_count"]):
            target_id = node_ids[target]
            count = data["edge_count"]
            # Use different arrow styles based on edge weight
            if count >= 50:
                arrow = "==>"  # Thick arrow for heavy dependencies
            elif count >= 10:
                arrow = "-->"  # Normal arrow
            else:
                arrow = "-.->"  # Dotted for light dependencies
            lines.append(f"    {source_id} {arrow}|{count}| {target_id}")

    return "\n".join(lines)


def _generate_ascii(graph: dict) -> str:
    """
    Generate ASCII representation of dependency graph.

    Args:
        graph: Dependency graph from _build_dependency_graph

    Returns:
        ASCII tree-like representation
    """
    lines = ["Module Dependencies", "=" * 40]

    # Sort by total outgoing edge count
    sorted_sources = sorted(
        graph.items(),
        key=lambda x: sum(t["edge_count"] for t in x[1].values()),
        reverse=True,
    )

    for source, targets in sorted_sources:
        total_out = sum(t["edge_count"] for t in targets.values())
        lines.append(f"\n📁 {source} (→ {total_out} refs)")

        # Sort targets by edge count
        sorted_targets = sorted(
            targets.items(), key=lambda x: x[1]["edge_count"], reverse=True
        )

        for i, (target, data) in enumerate(sorted_targets):
            is_last = i == len(sorted_targets) - 1
            prefix = "└──" if is_last else "├──"
            kinds = ", ".join(sorted(data["kinds"])) if data["kinds"] else "mixed"
            lines.append(f"   {prefix} {target} ({data['edge_count']} {kinds})")

    return "\n".join(lines)


def _generate_summary(graph: dict) -> dict:
    """
    Generate summary statistics from dependency graph.

    Args:
        graph: Dependency graph from _build_dependency_graph

    Returns:
        Dict with summary statistics
    """
    total_modules = set()
    total_edges = 0
    edge_counts = []

    for source, targets in graph.items():
        total_modules.add(source)
        for target, data in targets.items():
            total_modules.add(target)
            total_edges += data["edge_count"]
            edge_counts.append(data["edge_count"])

    # Find most connected modules
    outgoing = defaultdict(int)
    incoming = defaultdict(int)

    for source, targets in graph.items():
        for target, data in targets.items():
            outgoing[source] += data["edge_count"]
            incoming[target] += data["edge_count"]

    top_sources = sorted(outgoing.items(), key=lambda x: -x[1])[:5]
    top_targets = sorted(incoming.items(), key=lambda x: -x[1])[:5]

    return {
        "total_modules": len(total_modules),
        "total_edges": total_edges,
        "avg_edge_weight": total_edges / len(edge_counts) if edge_counts else 0,
        "top_dependents": [{"module": m, "outgoing": c} for m, c in top_sources],
        "top_dependencies": [{"module": m, "incoming": c} for m, c in top_targets],
    }


async def get_architecture_map(
    depth: int = 2,
    output_format: Literal["mermaid", "ascii", "json"] = "mermaid",
    min_edge_count: int = 3,
    # Injected dependencies
    storage: Optional["StorageManager"] = None,
) -> str:
    """
    Generate a high-level architecture map of module dependencies.

    This tool provides a "zoom out" view of the codebase, showing how
    directories/modules depend on each other. Use this to:
    - Understand system architecture before making changes
    - Plan cross-module refactors
    - Identify tightly coupled modules
    - Find potential circular dependencies

    Args:
        depth: Directory depth to aggregate at (default: 2).
               Example: depth=2 for "src/auth" from "src/auth/login.py"
        output_format: Output format:
            - "mermaid": Mermaid.js flowchart (paste into docs/diagrams)
            - "ascii": ASCII tree (for quick terminal viewing)
            - "json": Structured data with statistics
        min_edge_count: Minimum relationships to show an edge (default: 3).
                       Higher values show only strong dependencies.

    Returns:
        Architecture diagram/data in the requested format

    Examples:
        >>> # Get Mermaid diagram for documentation
        >>> get_architecture_map(depth=2, output_format="mermaid")

        >>> # Quick ASCII overview
        >>> get_architecture_map(depth=1, output_format="ascii")

        >>> # Detailed stats for analysis
        >>> get_architecture_map(depth=3, output_format="json", min_edge_count=1)
    """
    if storage is None:
        return "Error: Storage not available. Workspace may not be indexed."

    # Get raw dependencies from database
    dependencies = storage.get_cross_directory_dependencies(
        depth=depth, min_edge_count=1  # Get all, filter later for graph building
    )

    if not dependencies:
        return "No cross-module dependencies found. The workspace may not be indexed or has no inter-module relationships."

    # Build the graph with the specified depth
    graph = _build_dependency_graph(dependencies, depth=depth)

    # Filter by min_edge_count
    filtered_graph = {}
    for source, targets in graph.items():
        filtered_targets = {
            t: d for t, d in targets.items() if d["edge_count"] >= min_edge_count
        }
        if filtered_targets:
            filtered_graph[source] = filtered_targets

    if not filtered_graph:
        return f"No dependencies with >= {min_edge_count} relationships. Try lowering min_edge_count."

    # Generate output in requested format
    if output_format == "mermaid":
        return _generate_mermaid(filtered_graph, title=f"Architecture (depth={depth})")
    elif output_format == "ascii":
        return _generate_ascii(filtered_graph)
    else:  # json
        import json

        summary = _generate_summary(filtered_graph)
        return json.dumps(
            {
                "summary": summary,
                "dependencies": [
                    {
                        "source": source,
                        "target": target,
                        "edge_count": data["edge_count"],
                        "kinds": list(data["kinds"]),
                    }
                    for source, targets in filtered_graph.items()
                    for target, data in targets.items()
                ],
            },
            indent=2,
        )
