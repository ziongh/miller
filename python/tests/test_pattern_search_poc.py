"""
POC Test: Pattern-Preserving Search with Whitespace Tokenizer

This test validates that we can:
1. Add a code_pattern field to LanceDB
2. Create a whitespace-tokenized FTS index on it
3. Search for code idioms like "ILogger<", ": BaseClass", "[Fact]"

If this POC works, we proceed with full implementation.
"""

import pytest
import numpy as np
from pathlib import Path
import tempfile
import shutil
import pyarrow as pa


class TestPatternSearchPOC:
    """POC: Validate whitespace tokenizer for code pattern search."""

    @pytest.fixture
    def temp_db_path(self):
        """Create temporary directory for test database."""
        temp_dir = tempfile.mkdtemp(prefix="miller_pattern_poc_")
        yield temp_dir
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_poc_whitespace_tokenizer_preserves_patterns(self, temp_db_path):
        """
        POC TEST 1: Verify whitespace tokenizer preserves special characters.

        This is the critical test - if this works, our approach is viable.
        """
        import lancedb

        # Connect to test database
        db = lancedb.connect(temp_db_path)

        # Define schema WITH pattern field
        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("name", pa.string()),
            pa.field("kind", pa.string()),
            pa.field("language", pa.string()),
            pa.field("signature", pa.string()),
            pa.field("code_pattern", pa.string()),  # NEW: Pattern-preserving field
            pa.field("vector", pa.list_(pa.float32(), 384)),
        ])

        # Create test data simulating C# code
        test_data = [
            {
                "id": "sym_1",
                "name": "UserService",
                "kind": "Class",
                "language": "csharp",
                "signature": "public class UserService : BaseService",
                "code_pattern": "public class UserService : BaseService UserService",  # Pattern field
                "vector": np.random.rand(384).astype(np.float32).tolist(),
            },
            {
                "id": "sym_2",
                "name": "OrderService",
                "kind": "Class",
                "language": "csharp",
                "signature": "public class OrderService : BaseService",
                "code_pattern": "public class OrderService : BaseService OrderService",
                "vector": np.random.rand(384).astype(np.float32).tolist(),
            },
            {
                "id": "sym_3",
                "name": "_logger",
                "kind": "Field",
                "language": "csharp",
                "signature": "private readonly ILogger<UserService> _logger",
                "code_pattern": "private readonly ILogger<UserService> _logger _logger",
                "vector": np.random.rand(384).astype(np.float32).tolist(),
            },
            {
                "id": "sym_4",
                "name": "_repoLogger",
                "kind": "Field",
                "language": "csharp",
                "signature": "private readonly ILogger<IUserRepository> _repoLogger",
                "code_pattern": "private readonly ILogger<IUserRepository> _repoLogger _repoLogger",
                "vector": np.random.rand(384).astype(np.float32).tolist(),
            },
            {
                "id": "sym_5",
                "name": "TestMethod",
                "kind": "Method",
                "language": "csharp",
                "signature": "[Fact] public void TestMethod()",
                "code_pattern": "[Fact] public void TestMethod() TestMethod",
                "vector": np.random.rand(384).astype(np.float32).tolist(),
            },
        ]

        # Create table
        table_data = pa.Table.from_pylist(test_data, schema=schema)
        table = db.create_table("poc_symbols", table_data, mode="overwrite")

        # 🔑 KEY TEST: Create FTS index with WHITESPACE tokenizer
        print("\n🔬 Creating FTS index with whitespace tokenizer...")
        table.create_fts_index(
            ["code_pattern"],  # Only index pattern field
            use_tantivy=True,
            base_tokenizer="whitespace",  # KEY: Preserves : < > [ ] ( )
            with_position=True,
            replace=True
        )
        print("✅ FTS index created successfully")

        # TEST 1: Search for inheritance pattern ": BaseService"
        # Note: Need to use phrase search (quotes) to handle special chars
        print("\n🔍 TEST 1: Searching for ': BaseService' (using phrase search)...")
        results_1 = table.search('": BaseService"', query_type="fts").limit(10).to_list()

        print(f"Found {len(results_1)} results:")
        for r in results_1:
            print(f"  - {r['name']} ({r['kind']}): {r['code_pattern']}")

        # Assertions
        assert len(results_1) == 2, f"Expected 2 results, got {len(results_1)}"
        result_names = {r['name'] for r in results_1}
        assert "UserService" in result_names, "Should find UserService"
        assert "OrderService" in result_names, "Should find OrderService"
        assert all(": BaseService" in r['code_pattern'] for r in results_1), \
            "All results should contain ': BaseService' pattern"

        print("✅ TEST 1 PASSED: Inheritance pattern search works!")

        # TEST 2: Search for generic type pattern "ILogger<"
        # Note: Escape < or use phrase search
        print("\n🔍 TEST 2: Searching for 'ILogger<' (using phrase search)...")
        results_2 = table.search('"ILogger<"', query_type="fts").limit(10).to_list()

        print(f"Found {len(results_2)} results:")
        for r in results_2:
            print(f"  - {r['name']} ({r['kind']}): {r['code_pattern']}")

        # Assertions
        assert len(results_2) == 2, f"Expected 2 results, got {len(results_2)}"
        result_names_2 = {r['name'] for r in results_2}
        assert "_logger" in result_names_2, "Should find _logger field"
        assert "_repoLogger" in result_names_2, "Should find _repoLogger field"
        assert all("ILogger<" in r['code_pattern'] for r in results_2), \
            "All results should contain 'ILogger<' pattern"

        print("✅ TEST 2 PASSED: Generic type pattern search works!")

        # TEST 3: Search for attribute pattern "[Fact]"
        # Note: Brackets are range syntax in Lucene, need phrase search
        print("\n🔍 TEST 3: Searching for '[Fact]' (using phrase search)...")
        results_3 = table.search('"[Fact]"', query_type="fts").limit(10).to_list()

        print(f"Found {len(results_3)} results:")
        for r in results_3:
            print(f"  - {r['name']} ({r['kind']}): {r['code_pattern']}")

        # Assertions
        assert len(results_3) == 1, f"Expected 1 result, got {len(results_3)}"
        assert results_3[0]['name'] == "TestMethod", "Should find TestMethod"
        assert "[Fact]" in results_3[0]['code_pattern'], "Should contain [Fact] attribute"

        print("✅ TEST 3 PASSED: Attribute pattern search works!")

        print("\n" + "="*60)
        print("🎉 POC VALIDATION COMPLETE - ALL TESTS PASSED!")
        print("="*60)
        print("\n✅ Whitespace tokenizer preserves code patterns")
        print("✅ Can search for inheritance (': BaseClass')")
        print("✅ Can search for generics ('ILogger<')")
        print("✅ Can search for attributes ('[Fact]')")
        print("\n👉 RECOMMENDATION: Proceed with full implementation")

    def test_poc_compare_with_stemming(self, temp_db_path):
        """
        POC TEST 2: Compare whitespace tokenizer vs stemming tokenizer.

        This proves that standard stemming BREAKS code pattern search.
        """
        import lancedb

        db = lancedb.connect(temp_db_path)

        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("code_pattern", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 384)),
        ])

        test_data = [{
            "id": "test_1",
            "code_pattern": "public class UserService : BaseService",
            "vector": np.random.rand(384).astype(np.float32).tolist(),
        }]

        # Test with STEMMING tokenizer (current Miller default)
        print("\n🔬 Testing with EN_STEM tokenizer (current default)...")
        table_stem = db.create_table("poc_stem", pa.Table.from_pylist(test_data, schema=schema), mode="overwrite")
        table_stem.create_fts_index(
            ["code_pattern"],
            use_tantivy=True,
            tokenizer_name="en_stem",  # Standard stemming
            with_position=True,
            replace=True
        )

        results_stem = table_stem.search('": BaseService"', query_type="fts").limit(10).to_list()
        print(f"Results with stemming: {len(results_stem)}")

        # Test with WHITESPACE tokenizer (proposed solution)
        print("\n🔬 Testing with WHITESPACE tokenizer (proposed)...")
        table_ws = db.create_table("poc_whitespace", pa.Table.from_pylist(test_data, schema=schema), mode="overwrite")
        table_ws.create_fts_index(
            ["code_pattern"],
            use_tantivy=True,
            base_tokenizer="whitespace",  # Whitespace only
            with_position=True,
            replace=True
        )

        results_ws = table_ws.search('": BaseService"', query_type="fts").limit(10).to_list()
        print(f"Results with whitespace: {len(results_ws)}")

        # Proof: Stemming tokenizer fails, whitespace works
        print("\n" + "="*60)
        print("COMPARISON RESULTS:")
        print(f"  Stemming (en_stem):  {len(results_stem)} results {'❌ FAIL' if len(results_stem) == 0 else '✅'}")
        print(f"  Whitespace:          {len(results_ws)} results {'✅ PASS' if len(results_ws) > 0 else '❌'}")
        print("="*60)

        # Assertions
        assert len(results_stem) == 0, "Stemming should NOT find ': BaseService' pattern (proves the problem)"
        assert len(results_ws) == 1, "Whitespace should find ': BaseService' pattern (proves the solution)"

        print("\n✅ VALIDATED: Standard stemming breaks patterns, whitespace preserves them")

    def test_poc_match_query_field_targeting(self, temp_db_path):
        """
        POC TEST 3: Test MatchQuery for field-specific searches.

        This validates we can search JUST the pattern field.
        """
        import lancedb
        from lancedb.query import MatchQuery

        db = lancedb.connect(temp_db_path)

        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("name", pa.string()),
            pa.field("signature", pa.string()),
            pa.field("code_pattern", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 384)),
        ])

        test_data = [{
            "id": "test_1",
            "name": "UserService",
            "signature": "public class UserService : BaseService",
            "code_pattern": "public class UserService : BaseService UserService",
            "vector": np.random.rand(384).astype(np.float32).tolist(),
        }]

        table = db.create_table("poc_match_query", pa.Table.from_pylist(test_data, schema=schema), mode="overwrite")
        table.create_fts_index(
            ["code_pattern"],
            use_tantivy=True,
            base_tokenizer="whitespace",
            with_position=True,
            replace=True
        )

        # Test MatchQuery targeting specific field
        print("\n🔬 Testing MatchQuery with field targeting...")
        results = table.search(
            MatchQuery('": BaseService"', "code_pattern"),  # Search ONLY code_pattern field (phrase search)
            query_type="fts"
        ).limit(10).to_list()

        print(f"Found {len(results)} results using MatchQuery")
        for r in results:
            print(f"  - {r['name']}: {r['code_pattern']}")

        assert len(results) == 1, f"Expected 1 result, got {len(results)}"
        assert results[0]['name'] == "UserService"

        print("✅ VALIDATED: MatchQuery field targeting works")

    def test_poc_performance_baseline(self, temp_db_path):
        """
        POC TEST 4: Quick performance check - should be fast.
        """
        import lancedb
        import time

        db = lancedb.connect(temp_db_path)

        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("code_pattern", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 384)),
        ])

        # Create 1000 test symbols
        print("\n🔬 Creating 1000 test symbols...")
        test_data = []
        for i in range(1000):
            test_data.append({
                "id": f"sym_{i}",
                "code_pattern": f"public class Service{i} : BaseService{i % 10}",
                "vector": np.random.rand(384).astype(np.float32).tolist(),
            })

        table = db.create_table("poc_perf", pa.Table.from_pylist(test_data, schema=schema), mode="overwrite")

        # Create FTS index
        start_index = time.time()
        table.create_fts_index(
            ["code_pattern"],
            use_tantivy=True,
            base_tokenizer="whitespace",
            with_position=True,
            replace=True
        )
        index_time = time.time() - start_index

        # Search
        start_search = time.time()
        results = table.search('": BaseService"', query_type="fts").limit(50).to_list()
        search_time = time.time() - start_search

        print(f"\n⏱️  PERFORMANCE:")
        print(f"  Index creation: {index_time*1000:.1f}ms (1000 symbols)")
        print(f"  Search time: {search_time*1000:.1f}ms ({len(results)} results)")

        # Assertions
        assert search_time < 0.2, f"Search should be <200ms, got {search_time*1000:.1f}ms"
        assert len(results) > 0, "Should find results"

        print("✅ VALIDATED: Performance is acceptable")


if __name__ == "__main__":
    # Run POC tests standalone
    pytest.main([__file__, "-v", "-s"])
