#!/usr/bin/env python
"""
Benchmark: Arrow extraction vs object-based extraction.

Compares GC pressure, memory allocation, and throughput between:
1. Old path: extract_files_batch_with_io → Python objects → DB
2. New path: extract_files_to_arrow → Arrow batches → DB

Run: python scripts/benchmark_arrow_gc.py
"""

import gc
import sys
import time
import tracemalloc
from pathlib import Path

# Add miller to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from miller import miller_core


def find_test_files(directory: str, max_files: int = 100) -> list[str]:
    """Find Python files for testing."""
    root = Path(directory)
    files = []
    for f in root.rglob("*.py"):
        if ".venv" not in str(f) and "__pycache__" not in str(f):
            # Return relative paths
            try:
                rel_path = str(f.relative_to(root))
                files.append(rel_path)
            except ValueError:
                pass
        if len(files) >= max_files:
            break
    return files


def benchmark_object_extraction(file_paths: list[str], workspace: str, iterations: int = 3):
    """Benchmark the old object-based extraction path."""
    results = []

    for i in range(iterations):
        gc.collect()
        gc.disable()

        tracemalloc.start()
        start_time = time.perf_counter()

        # Old path: creates Python objects
        batch_results = miller_core.extract_files_batch_with_io(file_paths, workspace)

        # Simulate buffer accumulation (accessing fields creates Python strings)
        symbols_count = 0
        identifiers_count = 0
        for res in batch_results:
            extraction_result = getattr(res, 'results', None)
            if extraction_result is None:
                continue
            symbols = getattr(extraction_result, 'symbols', None) or []
            identifiers = getattr(extraction_result, 'identifiers', None) or []

            for sym in symbols:
                # Each field access creates a Python string
                _ = sym.id
                _ = sym.name
                _ = sym.kind
                _ = sym.language
                _ = sym.file_path
                _ = sym.signature
                _ = sym.doc_comment
                _ = sym.start_line
                _ = sym.end_line
                symbols_count += 1

            for ident in identifiers:
                _ = ident.id
                _ = ident.name
                _ = ident.kind
                _ = ident.file_path
                identifiers_count += 1

        elapsed = time.perf_counter() - start_time
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        gc.enable()
        gc.collect()

        results.append({
            "elapsed_ms": elapsed * 1000,
            "peak_memory_mb": peak / (1024 * 1024),
            "symbols": symbols_count,
            "identifiers": identifiers_count,
        })

    return results


def benchmark_arrow_extraction(file_paths: list[str], workspace: str, iterations: int = 3):
    """Benchmark the new Arrow-based extraction path."""
    results = []

    for i in range(iterations):
        gc.collect()
        gc.disable()

        tracemalloc.start()
        start_time = time.perf_counter()

        # New path: returns Arrow batches (zero-copy)
        batch = miller_core.extract_files_to_arrow(file_paths, workspace)

        # Get tables (still zero-copy)
        symbols_table = batch.symbols
        identifiers_table = batch.identifiers

        # Count rows without creating Python objects
        symbols_count = symbols_table.num_rows
        identifiers_count = identifiers_table.num_rows

        # Only extract what's needed for embeddings (4 columns, not all 12)
        if symbols_count > 0:
            # This is the only place we create Python strings
            doc_comments = symbols_table.column("doc_comment").to_pylist()
            signatures = symbols_table.column("signature").to_pylist()
            kinds = symbols_table.column("kind").to_pylist()
            names = symbols_table.column("name").to_pylist()

            # Build embedding texts (minimal allocation)
            texts = []
            for doc, sig, kind, name in zip(doc_comments, signatures, kinds, names):
                parts = []
                if doc:
                    parts.append(f"/* {doc} */")
                if sig:
                    parts.append(sig)
                else:
                    parts.append(f"{kind.lower()} {name}")
                texts.append("\n".join(parts))

        elapsed = time.perf_counter() - start_time
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        gc.enable()
        gc.collect()

        results.append({
            "elapsed_ms": elapsed * 1000,
            "peak_memory_mb": peak / (1024 * 1024),
            "symbols": symbols_count,
            "identifiers": identifiers_count,
        })

    return results


def main():
    # Use Miller's own codebase as test data
    workspace = str(Path(__file__).parent.parent.absolute())
    file_paths = find_test_files(workspace, max_files=50)

    print(f"Benchmarking with {len(file_paths)} Python files from Miller codebase")
    print(f"Workspace: {workspace}\n")

    print("=" * 60)
    print("OBJECT-BASED EXTRACTION (old path)")
    print("=" * 60)
    object_results = benchmark_object_extraction(file_paths, workspace, iterations=3)
    for i, r in enumerate(object_results):
        print(f"  Run {i+1}: {r['elapsed_ms']:.1f}ms, "
              f"{r['peak_memory_mb']:.2f}MB peak, "
              f"{r['symbols']} symbols, {r['identifiers']} identifiers")

    print()
    print("=" * 60)
    print("ARROW-BASED EXTRACTION (new path)")
    print("=" * 60)
    arrow_results = benchmark_arrow_extraction(file_paths, workspace, iterations=3)
    for i, r in enumerate(arrow_results):
        print(f"  Run {i+1}: {r['elapsed_ms']:.1f}ms, "
              f"{r['peak_memory_mb']:.2f}MB peak, "
              f"{r['symbols']} symbols, {r['identifiers']} identifiers")

    # Calculate averages
    avg_object = {
        "elapsed_ms": sum(r["elapsed_ms"] for r in object_results) / len(object_results),
        "peak_memory_mb": sum(r["peak_memory_mb"] for r in object_results) / len(object_results),
    }
    avg_arrow = {
        "elapsed_ms": sum(r["elapsed_ms"] for r in arrow_results) / len(arrow_results),
        "peak_memory_mb": sum(r["peak_memory_mb"] for r in arrow_results) / len(arrow_results),
    }

    print()
    print("=" * 60)
    print("COMPARISON")
    print("=" * 60)
    print(f"  Object path avg: {avg_object['elapsed_ms']:.1f}ms, {avg_object['peak_memory_mb']:.2f}MB")
    print(f"  Arrow path avg:  {avg_arrow['elapsed_ms']:.1f}ms, {avg_arrow['peak_memory_mb']:.2f}MB")

    speedup = avg_object["elapsed_ms"] / avg_arrow["elapsed_ms"] if avg_arrow["elapsed_ms"] > 0 else 0
    memory_reduction = (1 - avg_arrow["peak_memory_mb"] / avg_object["peak_memory_mb"]) * 100 if avg_object["peak_memory_mb"] > 0 else 0

    print()
    print(f"  ⚡ Speed improvement: {speedup:.2f}x")
    print(f"  📉 Memory reduction: {memory_reduction:.1f}%")

    # Count estimated Python objects avoided
    total_symbols = arrow_results[0]["symbols"]
    total_identifiers = arrow_results[0]["identifiers"]
    # Old path: ~11 fields per symbol, ~15 fields per identifier
    estimated_objects_avoided = (total_symbols * 11) + (total_identifiers * 15)
    print(f"  🗑️  Python objects avoided: ~{estimated_objects_avoided:,}")


if __name__ == "__main__":
    main()
