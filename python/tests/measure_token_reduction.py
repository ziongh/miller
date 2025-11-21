"""
Script to measure token reduction from TOON format vs JSON.

Generates realistic search results and compares token counts between formats.
"""

import json

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False
    print("⚠️  tiktoken not installed - using character count approximation")
    print("   Install with: pip install tiktoken")

from miller.toon_types import encode_toon


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken (GPT-4 encoding)."""
    if HAS_TIKTOKEN:
        enc = tiktoken.encoding_for_model("gpt-4")
        return len(enc.encode(text))
    else:
        # Rough approximation: ~4 characters per token
        return len(text) // 4


def generate_mock_results(count: int) -> list[dict]:
    """Generate realistic mock search results."""
    results = []
    for i in range(count):
        results.append({
            "name": f"calculate_user_score_{i}",
            "kind": "Function",
            "file_path": f"src/services/user_service_{i % 10}.py",
            "start_line": 42 + (i * 10),
            "signature": "(user_id: str, options: Dict[str, Any]) -> float",
            "doc_comment": f"Calculate relevance score for user {i} based on activity and preferences",
            "score": 0.95 - (i * 0.01),
        })
    return results


def measure_reduction(result_count: int):
    """Measure token reduction for a given result count."""
    print(f"\n{'='*70}")
    print(f"Testing with {result_count} results:")
    print(f"{'='*70}")

    # Generate results
    results = generate_mock_results(result_count)

    # Format as JSON
    json_output = json.dumps(results, indent=2)
    json_tokens = count_tokens(json_output)
    json_size = len(json_output)

    # Format as TOON
    toon_output = encode_toon(results)
    toon_tokens = count_tokens(toon_output) if isinstance(toon_output, str) else count_tokens(json.dumps(toon_output))
    toon_size = len(toon_output) if isinstance(toon_output, str) else len(json.dumps(toon_output))

    # Calculate reduction
    token_reduction = ((json_tokens - toon_tokens) / json_tokens * 100) if json_tokens > 0 else 0
    size_reduction = ((json_size - toon_size) / json_size * 100) if json_size > 0 else 0

    # Display results
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
        "count": result_count,
        "json_tokens": json_tokens,
        "toon_tokens": toon_tokens,
        "token_reduction": token_reduction,
        "size_reduction": size_reduction,
    }


def main():
    """Run token reduction measurements for various result counts."""
    print("🎯 TOON Format Token Reduction Measurement")
    print("=" * 70)

    if not HAS_TIKTOKEN:
        print("\n⚠️  Using approximation - install tiktoken for accurate counts")

    # Test with different result counts
    test_cases = [5, 10, 20, 50, 100]
    measurements = []

    for count in test_cases:
        result = measure_reduction(count)
        measurements.append(result)

    # Summary
    print(f"\n{'='*70}")
    print("📈 SUMMARY")
    print(f"{'='*70}\n")
    print(f"{'Results':<10} {'JSON Tokens':<15} {'TOON Tokens':<15} {'Reduction':<12}")
    print("-" * 70)

    for m in measurements:
        print(f"{m['count']:<10} {m['json_tokens']:<15,} {m['toon_tokens']:<15,} {m['token_reduction']:>10.1f}%")

    # Calculate average reduction
    avg_reduction = sum(m['token_reduction'] for m in measurements) / len(measurements)
    print("-" * 70)
    print(f"{'AVERAGE':<10} {'':<15} {'':<15} {avg_reduction:>10.1f}%")

    # Verdict
    print(f"\n{'='*70}")
    print("🎉 VERDICT")
    print(f"{'='*70}")

    if avg_reduction >= 30:
        print(f"✅ SUCCESS! Average reduction: {avg_reduction:.1f}%")
        print(f"   Target: 30-60% ✓")
        print(f"   TOON format delivers significant token savings!")
    elif avg_reduction >= 20:
        print(f"⚠️  PARTIAL SUCCESS: Average reduction: {avg_reduction:.1f}%")
        print(f"   Target: 30-60%")
        print(f"   Below target but still beneficial")
    else:
        print(f"❌ BELOW TARGET: Average reduction: {avg_reduction:.1f}%")
        print(f"   Target: 30-60%")
        print(f"   May need optimization")

    # Cost savings example
    print(f"\n💵 COST IMPACT (example with 1M tokens/month):")
    tokens_saved = 1_000_000 * (avg_reduction / 100)
    print(f"   Tokens saved: {tokens_saved:,.0f}")
    print(f"   @ $10/1M tokens: ${tokens_saved * 10 / 1_000_000:.2f}/month saved")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
