"""
Hierarchical TOON Encoding (Phase 5)

Flattens recursive tree structures into single flat tables with parent_id references
for maximum token efficiency. Eliminates repeated keys in nested output.

Key Design Principles:
1. Token Efficiency: Minimize output size through flat tabular format
2. Parseability: Structured, unambiguous data for AI agents
3. Lossless: All information preserved via parent_id pointers
4. Reconstruction: Tree can be rebuilt from flat format if needed

Target Savings:
- 63% reduction for trace_call_path (28,800 chars → 10,680 chars)
- 77% combined with Phase 4 data optimizations

Example:

Instead of nested YAML-ish with repeated keys:
```yaml
- symbol_name: root
  file_path: foo.rs
  children:
    - symbol_name: child1
      file_path: foo.rs
    - symbol_name: child2
      file_path: foo.rs
```

Output flat table:
```
nodes[3]{id,parent_id,level,symbol_name,file_path}:
  0,null,0,root,foo.rs
  1,0,1,child1,foo.rs
  2,0,1,child2,foo.rs
```
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class FlatNode:
    """
    Flattened node for hierarchical TOON encoding.

    Represents a single node from a recursive tree structure, flattened
    into a tabular format with parent_id references for reconstruction.

    Attributes:
        id: Unique identifier within this result set
        parent_id: Reference to parent node (None for root nodes)
        group: Group ID (e.g., which call path this belongs to)
        level: Depth level in tree (0 = root)
        data: The actual node data (will be flattened at top level)

    Example serialization:
        {
          "id": 1,
          "parent_id": 0,
          "group": 0,
          "level": 1,
          "name": "child",
          "value": 42
        }

    Note: In JSON output, fields from 'data' appear at top level, not nested.
    """

    id: int
    parent_id: Optional[int]
    group: int
    level: int
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to flat dictionary with data fields at top level.

        CRITICAL: ALL dicts must have identical keys in identical order for TOON
        to recognize this as a uniform table. We:
        1. ALWAYS include parent_id (even if None) for structural consistency
        2. Sort data keys alphabetically for deterministic field ordering

        Returns:
            Flat dictionary with all fields at top level in consistent order
        """
        result = {
            "id": self.id,
            "parent_id": self.parent_id,  # ALWAYS include, even if None
            "group": self.group,
            "level": self.level,
        }

        # Add data fields in sorted order for consistent schema across all nodes
        # This ensures TOON can recognize the uniform table structure
        for key in sorted(self.data.keys()):
            result[key] = self.data[key]

        return result


class HierarchicalToonable(Protocol):
    """
    Protocol for hierarchical data that can be flattened to TOON format.

    Implement this protocol on any recursive tree structure to enable efficient
    flat-table TOON encoding with parent_id references.

    Example:
        class MyTreeType:
            def flatten(self) -> list[FlatNode]:
                # Depth-first traversal, assign IDs, track parent_id
                ...
    """

    def flatten(self) -> list[FlatNode]:
        """
        Flatten recursive tree into single flat table with parent_id references.

        Each node gets:
        - id: Unique identifier within this result set
        - parent_id: Reference to parent node (None for roots)
        - group: Which tree/path this node belongs to (for multiple trees)
        - level: Depth in tree (0 = root)
        - data: The actual node data (dict with all fields)

        Returns:
            List of flattened nodes ready for TOON encoding
        """
        ...


def flatten_tree_recursive(
    node: dict[str, Any],
    result: list[FlatNode],
    id_counter: list[int],  # Use list for mutable reference
    parent_id: Optional[int],
    group: int,
    level: int,
    children_key: str = "children",
) -> None:
    """
    Recursive helper to flatten a tree node and its children.

    Performs depth-first traversal, assigning unique IDs and tracking parent_id references.

    Args:
        node: Current node dict to flatten
        result: Accumulator for flattened nodes (mutated in place)
        id_counter: Counter for assigning unique IDs (mutated in place)
        parent_id: ID of parent node (None for roots)
        group: Group ID (which tree this node belongs to)
        level: Current depth in tree (0 = root)
        children_key: Key in node dict that holds children list

    Side effects:
        - Appends FlatNode to result list
        - Increments id_counter[0]
    """
    current_id = id_counter[0]
    id_counter[0] += 1

    # Extract children before creating data dict
    children = node.get(children_key, [])

    # Create data dict without children (all other fields)
    data = {k: v for k, v in node.items() if k != children_key}

    # Create flattened node
    result.append(
        FlatNode(
            id=current_id,
            parent_id=parent_id,
            group=group,
            level=level,
            data=data,
        )
    )

    # Recursively flatten children
    for child in children:
        flatten_tree_recursive(
            child,
            result,
            id_counter,
            parent_id=current_id,  # This node becomes parent
            group=group,
            level=level + 1,
            children_key=children_key,
        )
