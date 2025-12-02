"""Tests for transitive closure / reachability computation.

TDD: These tests define the contract for reachability features.
Run these BEFORE implementing to verify they fail (Red phase).
"""

import pytest
from miller.storage import StorageManager


class TestReachabilitySchema:
    """Tests for reachability table schema."""

    def test_reachability_table_exists(self, tmp_path):
        """Reachability table should be created on init."""
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Table should exist
        cursor = storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reachability'"
        )
        assert cursor.fetchone() is not None
        storage.close()

    def test_reachability_table_has_correct_columns(self, tmp_path):
        """Reachability table should have source_id, target_id, min_distance."""
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        cursor = storage.conn.execute("PRAGMA table_info(reachability)")
        columns = {row[1] for row in cursor.fetchall()}

        assert "source_id" in columns
        assert "target_id" in columns
        assert "min_distance" in columns
        storage.close()

    def test_reachability_has_indexes(self, tmp_path):
        """Reachability table should have indexes on source_id and target_id."""
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        cursor = storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='reachability'"
        )
        indexes = {row[0] for row in cursor.fetchall()}

        # Should have indexes (names may vary, check they exist)
        assert len(indexes) >= 2  # At least source and target indexes
        storage.close()


class TestReachabilityStorage:
    """Tests for reachability CRUD operations."""

    def test_add_reachability_batch(self, tmp_path):
        """Can bulk insert reachability entries."""
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        entries = [
            ("sym_a", "sym_b", 1),  # A can reach B directly
            ("sym_a", "sym_c", 2),  # A can reach C in 2 hops
            ("sym_b", "sym_c", 1),  # B can reach C directly
        ]

        count = storage.add_reachability_batch(entries)
        assert count == 3
        storage.close()

    def test_clear_reachability(self, tmp_path):
        """Can clear all reachability data."""
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Add some data
        storage.add_reachability_batch([("a", "b", 1), ("b", "c", 1)])

        # Clear it
        storage.clear_reachability()

        # Should be empty
        cursor = storage.conn.execute("SELECT COUNT(*) FROM reachability")
        assert cursor.fetchone()[0] == 0
        storage.close()

    def test_get_reachability_for_target(self, tmp_path):
        """Can query what symbols can reach a target (upstream)."""
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # A -> B -> C (A and B can reach C)
        storage.add_reachability_batch([
            ("sym_a", "sym_c", 2),
            ("sym_b", "sym_c", 1),
        ])

        # What can reach C?
        upstream = storage.get_reachability_for_target("sym_c")

        assert len(upstream) == 2
        source_ids = {r["source_id"] for r in upstream}
        assert "sym_a" in source_ids
        assert "sym_b" in source_ids
        storage.close()

    def test_get_reachability_from_source(self, tmp_path):
        """Can query what symbols are reachable from source (downstream)."""
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # A -> B, A -> C
        storage.add_reachability_batch([
            ("sym_a", "sym_b", 1),
            ("sym_a", "sym_c", 2),
        ])

        # What can A reach?
        downstream = storage.get_reachability_from_source("sym_a")

        assert len(downstream) == 2
        target_ids = {r["target_id"] for r in downstream}
        assert "sym_b" in target_ids
        assert "sym_c" in target_ids
        storage.close()

    def test_can_reach_returns_true_for_reachable(self, tmp_path):
        """can_reach returns True when path exists."""
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        storage.add_reachability_batch([("sym_a", "sym_b", 1)])

        assert storage.can_reach("sym_a", "sym_b") is True
        storage.close()

    def test_can_reach_returns_false_for_unreachable(self, tmp_path):
        """can_reach returns False when no path exists."""
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        storage.add_reachability_batch([("sym_a", "sym_b", 1)])

        # B cannot reach A (no reverse path)
        assert storage.can_reach("sym_b", "sym_a") is False
        # Unknown symbols
        assert storage.can_reach("unknown", "sym_b") is False
        storage.close()

    def test_get_distance_returns_min_distance(self, tmp_path):
        """get_distance returns shortest path length."""
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        storage.add_reachability_batch([
            ("sym_a", "sym_b", 1),
            ("sym_a", "sym_c", 2),
        ])

        assert storage.get_distance("sym_a", "sym_b") == 1
        assert storage.get_distance("sym_a", "sym_c") == 2
        storage.close()

    def test_get_distance_returns_none_for_unreachable(self, tmp_path):
        """get_distance returns None when no path exists."""
        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        storage.add_reachability_batch([("sym_a", "sym_b", 1)])

        assert storage.get_distance("sym_b", "sym_a") is None
        assert storage.get_distance("unknown", "sym_b") is None
        storage.close()


class TestClosureTrigger:
    """Tests for WHEN closure computation should run."""

    def test_closure_should_run_if_reachability_empty_but_relationships_exist(self, tmp_path):
        """
        Closure should compute if reachability table is empty but relationships exist.

        This is the key bug we're fixing: previously closure only ran on fresh index,
        but if workspace was already indexed, reachability stayed empty forever.
        """
        from miller.closure import compute_transitive_closure, should_compute_closure

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Simulate "already indexed" state: has symbols and relationships but no reachability
        _add_test_symbols(storage, ["sym_a", "sym_b", "sym_c"])
        _add_test_relationships(storage, [
            ("sym_a", "sym_b", "Call"),
            ("sym_b", "sym_c", "Call"),
        ])

        # Verify: relationships exist but reachability is empty
        cursor = storage.conn.execute("SELECT COUNT(*) FROM relationships")
        assert cursor.fetchone()[0] == 2

        cursor = storage.conn.execute("SELECT COUNT(*) FROM reachability")
        assert cursor.fetchone()[0] == 0

        # should_compute_closure should return True
        assert should_compute_closure(storage) is True

        # After computing, should_compute_closure should return False
        compute_transitive_closure(storage)
        assert should_compute_closure(storage) is False

        storage.close()

    def test_closure_should_not_run_if_reachability_populated(self, tmp_path):
        """Closure should NOT recompute if reachability already has entries."""
        from miller.closure import should_compute_closure

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        _add_test_symbols(storage, ["sym_a", "sym_b"])
        _add_test_relationships(storage, [("sym_a", "sym_b", "Call")])

        # Manually add reachability entry
        storage.add_reachability_batch([("sym_a", "sym_b", 1)])

        # should_compute_closure should return False (already populated)
        assert should_compute_closure(storage) is False
        storage.close()

    def test_closure_should_not_run_if_no_relationships(self, tmp_path):
        """Closure should NOT run if there are no relationships (nothing to compute)."""
        from miller.closure import should_compute_closure

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Only symbols, no relationships
        _add_test_symbols(storage, ["sym_a", "sym_b"])

        # should_compute_closure should return False (nothing to compute)
        assert should_compute_closure(storage) is False
        storage.close()


class TestClosureComputation:
    """Tests for transitive closure computation algorithm."""

    def test_compute_closure_simple_chain(self, tmp_path):
        """Compute closure for A -> B -> C chain."""
        from miller.closure import compute_transitive_closure

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Create symbols
        _add_test_symbols(storage, ["sym_a", "sym_b", "sym_c"])

        # Create relationships: A calls B, B calls C
        _add_test_relationships(storage, [
            ("sym_a", "sym_b", "Call"),
            ("sym_b", "sym_c", "Call"),
        ])

        # Compute closure
        count = compute_transitive_closure(storage, max_depth=10)

        # Should have 3 reachability entries:
        # A -> B (1), A -> C (2), B -> C (1)
        assert count == 3

        # Verify paths
        assert storage.can_reach("sym_a", "sym_b")
        assert storage.can_reach("sym_a", "sym_c")
        assert storage.can_reach("sym_b", "sym_c")
        assert not storage.can_reach("sym_c", "sym_a")  # No reverse

        # Verify distances
        assert storage.get_distance("sym_a", "sym_b") == 1
        assert storage.get_distance("sym_a", "sym_c") == 2
        storage.close()

    def test_compute_closure_handles_cycles(self, tmp_path):
        """Closure computation handles cycles without infinite loop."""
        from miller.closure import compute_transitive_closure

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Create symbols
        _add_test_symbols(storage, ["sym_a", "sym_b", "sym_c"])

        # Create cycle: A -> B -> C -> A
        _add_test_relationships(storage, [
            ("sym_a", "sym_b", "Call"),
            ("sym_b", "sym_c", "Call"),
            ("sym_c", "sym_a", "Call"),
        ])

        # Should complete without hanging
        count = compute_transitive_closure(storage, max_depth=10)

        # Each node can reach all others
        assert storage.can_reach("sym_a", "sym_b")
        assert storage.can_reach("sym_a", "sym_c")
        assert storage.can_reach("sym_b", "sym_a")
        assert storage.can_reach("sym_c", "sym_a")
        storage.close()

    def test_compute_closure_respects_max_depth(self, tmp_path):
        """Closure computation stops at max_depth."""
        from miller.closure import compute_transitive_closure

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Create long chain: A -> B -> C -> D -> E
        symbols = ["sym_a", "sym_b", "sym_c", "sym_d", "sym_e"]
        _add_test_symbols(storage, symbols)

        _add_test_relationships(storage, [
            ("sym_a", "sym_b", "Call"),
            ("sym_b", "sym_c", "Call"),
            ("sym_c", "sym_d", "Call"),
            ("sym_d", "sym_e", "Call"),
        ])

        # Compute with max_depth=2
        compute_transitive_closure(storage, max_depth=2)

        # A can reach B (1) and C (2) but NOT D (3) or E (4)
        assert storage.can_reach("sym_a", "sym_b")
        assert storage.can_reach("sym_a", "sym_c")
        assert not storage.can_reach("sym_a", "sym_d")
        assert not storage.can_reach("sym_a", "sym_e")
        storage.close()

    def test_compute_closure_diamond_pattern(self, tmp_path):
        """Closure handles diamond dependency pattern."""
        from miller.closure import compute_transitive_closure

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Diamond: A -> B, A -> C, B -> D, C -> D
        _add_test_symbols(storage, ["sym_a", "sym_b", "sym_c", "sym_d"])

        _add_test_relationships(storage, [
            ("sym_a", "sym_b", "Call"),
            ("sym_a", "sym_c", "Call"),
            ("sym_b", "sym_d", "Call"),
            ("sym_c", "sym_d", "Call"),
        ])

        compute_transitive_closure(storage, max_depth=10)

        # A can reach D (via B or C)
        assert storage.can_reach("sym_a", "sym_d")
        # Distance should be 2 (shortest path)
        assert storage.get_distance("sym_a", "sym_d") == 2
        storage.close()

    def test_compute_closure_empty_graph(self, tmp_path):
        """Closure computation handles empty graph."""
        from miller.closure import compute_transitive_closure

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # No symbols or relationships
        count = compute_transitive_closure(storage, max_depth=10)

        assert count == 0
        storage.close()

    def test_compute_closure_disconnected_components(self, tmp_path):
        """Closure handles disconnected subgraphs."""
        from miller.closure import compute_transitive_closure

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Two disconnected chains: A -> B and C -> D
        _add_test_symbols(storage, ["sym_a", "sym_b", "sym_c", "sym_d"])

        _add_test_relationships(storage, [
            ("sym_a", "sym_b", "Call"),
            ("sym_c", "sym_d", "Call"),
        ])

        compute_transitive_closure(storage, max_depth=10)

        # A can reach B, C can reach D
        assert storage.can_reach("sym_a", "sym_b")
        assert storage.can_reach("sym_c", "sym_d")

        # A cannot reach C or D
        assert not storage.can_reach("sym_a", "sym_c")
        assert not storage.can_reach("sym_a", "sym_d")
        storage.close()


# Test helpers

def _add_test_symbols(storage: StorageManager, symbol_ids: list[str]):
    """Add test symbols to storage."""
    # First add a file
    storage.add_file("test.py", "python", "# test", "hash123", 10)

    # Create mock symbol objects with all required attributes
    class MockSymbol:
        def __init__(self, id):
            self.id = id
            self.name = id
            self.kind = "Function"
            self.language = "python"
            self.file_path = "test.py"
            self.start_line = 1
            self.end_line = 10
            self.start_column = 0
            self.end_column = 0
            self.start_byte = 0
            self.end_byte = 100
            self.signature = f"def {id}()"
            self.doc_comment = None
            self.parent_id = None
            self.visibility = "public"
            self.code_context = None
            self.semantic_group = None
            self.confidence = 1.0
            self.content_type = None

    symbols = [MockSymbol(sid) for sid in symbol_ids]
    storage.add_symbols_batch(symbols)


def _add_test_relationships(storage: StorageManager, rels: list[tuple[str, str, str]]):
    """Add test relationships to storage."""
    class MockRelationship:
        def __init__(self, from_id, to_id, kind):
            self.id = f"rel_{from_id}_{to_id}"
            self.from_symbol_id = from_id
            self.to_symbol_id = to_id
            self.kind = kind
            self.file_path = "test.py"
            self.line_number = 1
            self.confidence = 1.0
            self.metadata = None

    relationships = [MockRelationship(f, t, k) for f, t, k in rels]
    storage.add_relationships_batch(relationships)


class TestIncrementalReachability:
    """Tests for reachability updates after incremental file changes."""

    def test_reachability_stale_after_new_relationships(self, tmp_path):
        """
        After adding new relationships, reachability should be stale.

        This tests the detection of stale reachability data.
        """
        from miller.closure import compute_transitive_closure, is_reachability_stale

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Initial state: A -> B, C exists but no relationships yet
        _add_test_symbols(storage, ["sym_a", "sym_b", "sym_c"])
        _add_test_relationships(storage, [("sym_a", "sym_b", "calls")])

        # Compute initial closure
        compute_transitive_closure(storage, max_depth=10)

        # Should NOT be stale yet
        assert is_reachability_stale(storage) is False

        # Add new relationship: B -> C (sym_c already exists)
        _add_test_relationships(storage, [("sym_b", "sym_c", "calls")])

        # Should now be stale - new relationship exists but A->C path is missing
        assert is_reachability_stale(storage) is True

        storage.close()

    def test_refresh_reachability_after_new_relationships(self, tmp_path):
        """
        After refreshing reachability, new transitive paths should be included.
        """
        from miller.closure import compute_transitive_closure, refresh_reachability

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Initial state: A -> B, C exists but no relationship yet
        _add_test_symbols(storage, ["sym_a", "sym_b", "sym_c"])
        _add_test_relationships(storage, [("sym_a", "sym_b", "calls")])

        # Compute initial closure
        compute_transitive_closure(storage, max_depth=10)

        # Verify A -> B exists
        assert storage.can_reach("sym_a", "sym_b")

        # Add new relationship: B -> C (sym_c already exists)
        _add_test_relationships(storage, [("sym_b", "sym_c", "calls")])

        # A -> C should NOT exist yet (stale)
        assert not storage.can_reach("sym_a", "sym_c")

        # Refresh reachability
        refresh_reachability(storage, max_depth=10)

        # Now A -> C should exist
        assert storage.can_reach("sym_a", "sym_c")

        storage.close()

    def test_refresh_reachability_clears_deleted_paths(self, tmp_path):
        """
        After deleting relationships, refresh should remove stale paths.
        """
        from miller.closure import compute_transitive_closure, refresh_reachability

        db_path = tmp_path / "test.db"
        storage = StorageManager(str(db_path))

        # Initial state: A -> B -> C
        _add_test_symbols(storage, ["sym_a", "sym_b", "sym_c"])
        _add_test_relationships(storage, [
            ("sym_a", "sym_b", "calls"),
            ("sym_b", "sym_c", "calls"),
        ])

        # Compute initial closure
        compute_transitive_closure(storage, max_depth=10)

        # Verify A -> C exists
        assert storage.can_reach("sym_a", "sym_c")

        # Delete B -> C relationship
        storage.conn.execute(
            "DELETE FROM relationships WHERE from_symbol_id = ? AND to_symbol_id = ?",
            ("sym_b", "sym_c")
        )
        storage.conn.commit()

        # A -> C should still exist in stale reachability
        assert storage.can_reach("sym_a", "sym_c")

        # Refresh reachability
        refresh_reachability(storage, max_depth=10)

        # Now A -> C should NOT exist (path was deleted)
        assert not storage.can_reach("sym_a", "sym_c")
        # But A -> B should still exist
        assert storage.can_reach("sym_a", "sym_b")

        storage.close()
