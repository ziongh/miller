#!/usr/bin/env python3
"""
Benchmark script for get_symbols performance profiling.

Measures time spent in different phases:
- Parsing (Rust extraction)
- Filtering (depth, target)
- Database queries (relationships, variants)
- Embeddings (semantic search, related symbols)
- PageRank (importance scoring)
"""

import asyncio
import time
from pathlib import Path


async def benchmark_get_symbols():
    """Benchmark get_symbols on a typical Python file."""
    from miller.server import get_symbols

    # Use symbols.py itself as a test case (it's a typical large file)
    test_file = Path(__file__).parent / "python/miller/tools/symbols.py"

    print(f"Benchmarking get_symbols on: {test_file.name}")
    print(f"File size: {test_file.stat().st_size / 1024:.1f} KB")
    print(f"Lines: {len(test_file.read_text().splitlines())}")
    print()

    # Warm up (load models, etc.)
    print("Warming up...")
    await get_symbols(file_path=str(test_file), mode="structure", max_depth=1)
    print("Warm-up complete.\n")

    # Test different modes
    modes = [
        ("structure", 1, None),  # Basic structure
        ("structure", 2, None),  # With nested symbols
        ("structure", 1, "calculate"),  # With target filter
        ("full", 1, None),  # With code bodies
    ]

    results = []

    for mode, depth, target in modes:
        desc = f"mode={mode}, depth={depth}"
        if target:
            desc += f", target={target}"

        print(f"Testing: {desc}")

        start = time.perf_counter()
        result = await get_symbols(
            file_path=str(test_file),
            mode=mode,
            max_depth=depth,
            target=target
        )
        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms

        print(f"  Time: {elapsed:.2f} ms")
        print(f"  Symbols returned: {len(result)}")
        if result:
            # Show fields in first symbol
            print(f"  Fields: {', '.join(result[0].keys())}")
        print()

        results.append({
            "mode": mode,
            "depth": depth,
            "target": target,
            "time_ms": elapsed,
            "symbols_count": len(result)
        })

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        desc = f"{r['mode']}, depth={r['depth']}"
        if r['target']:
            desc += f", target={r['target']}"
        print(f"{desc:40} {r['time_ms']:>8.2f} ms ({r['symbols_count']} symbols)")

    # Performance targets
    print("\n" + "=" * 60)
    print("PERFORMANCE TARGETS")
    print("=" * 60)
    print("Typical file (structure mode): <50 ms")
    print("Large file (full mode):        <200 ms")
    print()

    typical_time = results[0]['time_ms']  # structure, depth=1
    if typical_time < 50:
        print(f"✓ Typical file target MET: {typical_time:.2f} ms")
    else:
        print(f"✗ Typical file target MISSED: {typical_time:.2f} ms (target: <50 ms)")


if __name__ == "__main__":
    asyncio.run(benchmark_get_symbols())
