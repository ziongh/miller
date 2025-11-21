"""
Script to measure token reduction from TOON format vs JSON for TracePath.

Tests with varying tree depths and widths to validate the 40-50% reduction target.
"""

import json
from typing import Any

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False
    print("⚠️  tiktoken not installed - using character count approximation")

from miller.toon_types import encode_trace_path_toon


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken (GPT-4 encoding)."""
    if HAS_TIKTOKEN:
        enc = tiktoken.encoding_for_model("gpt-4")
        return len(enc.encode(text))
    else:
        # Rough approximation: ~4 characters per token
        return len(text) // 4


def generate_mock_trace(depth: int, width: int) -> dict[str, Any]:
    """
    Generate a mock TracePath with specified depth and width.

    Args:
        depth: Maximum depth of tree (how many levels)
        width: Number of children per node (branching factor)

    Returns:
        TracePath dict with nested TraceNode structure
    """
    def create_node(name: str, current_depth: int, max_depth: int, width: int) -> dict[str, Any]:
        """Recursively create a TraceNode."""
        node = {
            "name": f"{name}_depth{current_depth}",
            "kind": "Function",
            "file_path": f"src/level{current_depth}/{name}.py",
            "line": 10 + (current_depth * 10),
            "language": "python",
            "depth": current_depth,
            "symbol_id": f"sym_{name}_{current_depth}",
            "relationship_kind": "Call" if current_depth > 0 else "Definition",
            "match_type": "exact",
            "signature": f"def {name}_depth{current_depth}(x: int) -> str",
            "doc_comment": f"Function at depth {current_depth} in call tree",
        }

        # Recursively add children
        if current_depth < max_depth:
            node["children"] = [
                create_node(f"child{i}", current_depth + 1, max_depth, width)
                for i in range(width)
            ]
        else:
            node["children"] = []

        return node

    # Calculate total nodes
    total_nodes = sum(width ** d for d in range(depth + 1))

    trace_path = {
        "query_symbol": "root_function",
        "direction": "downstream",
        "max_depth": depth,
        "total_nodes": total_nodes,
        "max_depth_reached": depth,
        "truncated": False,
        "root": create_node("root", 0, depth, width),
        "languages_found": ["python"],
        "match_types": {"exact": total_nodes},
        "relationship_kinds": {"Call": total_nodes - 1, "Definition": 1},
        "execution_time_ms": 12.34,
        "nodes_visited": total_nodes,
    }

    return trace_path


def measure_reduction(depth: int, width: int):
    """Measure token reduction for a specific tree configuration."""
    print(f"\n{'='*70}")
    print(f"Testing tree: depth={depth}, width={width}")
    print(f"{'='*70}")

    # Generate trace
    trace_path = generate_mock_trace(depth, width)
    total_nodes = trace_path["total_nodes"]

    # Format as JSON
    json_output = json.dumps(trace_path, indent=2)
    json_tokens = count_tokens(json_output)
    json_size = len(json_output)

    # Format as TOON
    toon_output = encode_trace_path_toon(trace_path)
    toon_tokens = count_tokens(toon_output) if isinstance(toon_output, str) else count_tokens(json.dumps(toon_output))
    toon_size = len(toon_output) if isinstance(toon_output, str) else len(json.dumps(toon_output))

    # Calculate reduction
    token_reduction = ((json_tokens - toon_tokens) / json_tokens * 100) if json_tokens > 0 else 0
    size_reduction = ((json_size - toon_size) / json_size * 100) if json_size > 0 else 0

    # Display results
    print(f"\n📊 Configuration:")
    print(f"   Depth: {depth} levels")
    print(f"   Width: {width} children per node")
    print(f"   Total nodes: {total_nodes}")

    print(f"\n📊 JSON Format:")
    print(f"   Tokens: {json_tokens:,}")
    print(f"   Size:   {json_size:,} bytes")

    print(f"\n📦 TOON Format:")
    print(f"   Tokens: {toon_tokens:,}")
    print(f"   Size:   {toon_size:,} bytes")

    print(f"\n💰 Savings:")
    print(f"   Token reduction: {token_reduction:.1f}%")
    print(f"   Size reduction:  {size_reduction:.1f}%")

    # Show sample output
    print(f"\n📝 Sample JSON (first 200 chars):")
    print(f"   {json_output[:200]}...")

    print(f"\n📝 Sample TOON (first 200 chars):")
    if isinstance(toon_output, str):
        print(f"   {toon_output[:200]}...")
    else:
        print(f"   (Fallback to JSON)")

    return {
        "depth": depth,
        "width": width,
        "total_nodes": total_nodes,
        "json_tokens": json_tokens,
        "toon_tokens": toon_tokens,
        "token_reduction": token_reduction,
        "size_reduction": size_reduction,
    }


def main():
    """Run token reduction measurements for various trace configurations."""
    print("🎯 TracePath TOON Format Token Reduction Measurement")
    print("=" * 70)

    if not HAS_TIKTOKEN:
        print("\n⚠️  Using approximation - install tiktoken for accurate counts")

    # Test configurations: (depth, width)
    # - Shallow wide: Many children, few levels
    # - Deep narrow: Few children, many levels
    # - Balanced: Moderate both
    test_cases = [
        (1, 5),   # Shallow wide: 6 nodes (1 + 5)
        (2, 3),   # Balanced: 13 nodes (1 + 3 + 9)
        (3, 2),   # Deep narrow: 15 nodes (1 + 2 + 4 + 8)
        (2, 5),   # Wide tree: 31 nodes (1 + 5 + 25)
        (4, 2),   # Very deep: 31 nodes (1 + 2 + 4 + 8 + 16)
    ]

    measurements = []

    for depth, width in test_cases:
        result = measure_reduction(depth, width)
        measurements.append(result)

    # Summary
    print(f"\n{'='*70}")
    print("📈 SUMMARY")
    print(f"{'='*70}\n")
    print(f"{'Config':<15} {'Nodes':<8} {'JSON Tokens':<15} {'TOON Tokens':<15} {'Reduction':<12}")
    print("-" * 70)

    for m in measurements:
        config = f"D{m['depth']}×W{m['width']}"
        print(f"{config:<15} {m['total_nodes']:<8} {m['json_tokens']:<15,} {m['toon_tokens']:<15,} {m['token_reduction']:>10.1f}%")

    # Calculate average reduction
    avg_reduction = sum(m['token_reduction'] for m in measurements) / len(measurements)
    print("-" * 70)
    print(f"{'AVERAGE':<15} {'':<8} {'':<15} {'':<15} {avg_reduction:>10.1f}%")

    # Verdict
    print(f"\n{'='*70}")
    print("🎉 VERDICT")
    print(f"{'='*70}")

    if avg_reduction >= 40:
        print(f"✅ EXCELLENT! Average reduction: {avg_reduction:.1f}%")
        print(f"   Target: 40-50% ✓")
        print(f"   TOON format excels with nested trees!")
    elif avg_reduction >= 30:
        print(f"✅ GOOD! Average reduction: {avg_reduction:.1f}%")
        print(f"   Target: 40-50%")
        print(f"   Still significant savings for nested structures")
    elif avg_reduction >= 20:
        print(f"⚠️  PARTIAL SUCCESS: Average reduction: {avg_reduction:.1f}%")
        print(f"   Target: 40-50%")
        print(f"   Below target but better than flat lists")
    else:
        print(f"❌ BELOW TARGET: Average reduction: {avg_reduction:.1f}%")
        print(f"   Target: 40-50%")
        print(f"   May need custom formatter")

    # Cost impact
    print(f"\n💵 COST IMPACT (example with 1M tokens/month):")
    tokens_saved = 1_000_000 * (avg_reduction / 100)
    print(f"   Tokens saved: {tokens_saved:,.0f}")
    print(f"   @ $10/1M tokens: ${tokens_saved * 10 / 1_000_000:.2f}/month saved")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
