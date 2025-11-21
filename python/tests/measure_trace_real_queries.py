#!/usr/bin/env python3
"""
Measure token reduction for trace_call_path using real queries.

Tests:
1. encode_toon upstream (32 nodes)
2. fast_search downstream (1170 nodes)
"""
import asyncio
import json
from pathlib import Path

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from miller.server import trace_call_path


def count_tokens_rough(text: str) -> int:
    """
    Rough token counting (approximation).
    1 token ≈ 4 characters for English text.
    JSON/code is slightly more efficient, so we use 3.5 chars/token.
    """
    return len(text) // 3.5


async def measure_query(symbol: str, direction: str, max_depth: int = 3):
    """Measure token reduction for a single query."""
    print(f"\n{'='*70}")
    print(f"Query: {symbol} ({direction}, depth={max_depth})")
    print(f"{'='*70}\n")

    # Get JSON output
    json_result = await trace_call_path(
        symbol_name=symbol,
        direction=direction,
        max_depth=max_depth,
        output_format="json"
    )
    json_str = json.dumps(json_result, indent=2)
    json_tokens = count_tokens_rough(json_str)
    json_nodes = json_result.get("total_nodes", 0)

    # Get TOON output
    toon_result = await trace_call_path(
        symbol_name=symbol,
        direction=direction,
        max_depth=max_depth,
        output_format="toon"
    )
    toon_tokens = count_tokens_rough(toon_result)

    # Calculate reduction
    reduction_pct = ((json_tokens - toon_tokens) / json_tokens * 100) if json_tokens > 0 else 0

    print(f"Total nodes: {json_nodes}")
    print(f"\nJSON format:")
    print(f"  - Characters: {len(json_str):,}")
    print(f"  - Tokens (rough): {json_tokens:,}")
    print(f"\nTOON format:")
    print(f"  - Characters: {len(toon_result):,}")
    print(f"  - Tokens (rough): {toon_tokens:,}")
    print(f"\nReduction:")
    print(f"  - Absolute: {json_tokens - toon_tokens:,} tokens")
    print(f"  - Percentage: {reduction_pct:.1f}%")

    return {
        "symbol": symbol,
        "direction": direction,
        "nodes": json_nodes,
        "json_tokens": json_tokens,
        "toon_tokens": toon_tokens,
        "reduction_pct": reduction_pct
    }


async def main():
    """Run all measurements."""
    print("="*70)
    print("REAL QUERY TOKEN REDUCTION MEASUREMENT")
    print("="*70)

    results = []

    # Test 1: encode_toon upstream (32 nodes)
    results.append(await measure_query("encode_toon", "upstream", max_depth=3))

    # Test 2: fast_search downstream (1170 nodes - big tree!)
    results.append(await measure_query("fast_search", "downstream", max_depth=3))

    # Summary
    print(f"\n\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}\n")

    total_json = sum(r["json_tokens"] for r in results)
    total_toon = sum(r["toon_tokens"] for r in results)
    avg_reduction = sum(r["reduction_pct"] for r in results) / len(results)

    print(f"{'Symbol':<20} {'Nodes':>8} {'JSON':>10} {'TOON':>10} {'Reduction':>10}")
    print("-" * 70)
    for r in results:
        print(f"{r['symbol']:<20} {r['nodes']:>8,} {r['json_tokens']:>10,} "
              f"{r['toon_tokens']:>10,} {r['reduction_pct']:>9.1f}%")
    print("-" * 70)
    print(f"{'TOTAL':<20} {' '*8} {total_json:>10,} {total_toon:>10,} "
          f"{((total_json - total_toon) / total_json * 100):>9.1f}%")
    print(f"\nAverage reduction: {avg_reduction:.1f}%")

    print(f"\n✅ Real query validation complete!")
    print(f"   TOON reduces tokens by {avg_reduction:.1f}% on average")


if __name__ == "__main__":
    asyncio.run(main())
