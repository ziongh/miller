"""
Tests for TRUE semantic discovery in trace_call_path.

These tests verify that trace_call_path can discover cross-language connections
using vector similarity search, WITHOUT requiring pre-existing database relationships.

This is the key differentiator that was missing from the original Miller port.
The "semantic" feature was only labeling existing relationships, not discovering new ones.

TDD: These tests define the expected behavior BEFORE implementation.
"""

import pytest
from pathlib import Path


class TestTrueSemanticDiscovery:
    """
    Test that semantic discovery actually FINDS symbols via embeddings,
    not just labels existing relationships.
    """

    @pytest.fixture
    def semantic_discovery_workspace(self, tmp_path):
        """
        Create workspace with semantically similar symbols but NO relationships.

        This is the critical test case:
        - Python: authenticate_user (checks credentials)
        - TypeScript: verifyCredentials (same concept, different words)
        - Go: check_auth (abbreviated form)

        These names share NO naming variants (different root words),
        and we intentionally create NO database relationships.

        TRUE semantic discovery should find these via embedding similarity.
        """
        from miller.storage import StorageManager

        db_path = tmp_path / "semantic_discovery.db"
        storage = StorageManager(db_path=str(db_path))

        class MockSymbol:
            def __init__(self, id, name, kind, language, file_path, signature=None,
                         doc_comment=None, start_line=1, start_col=0, end_line=10,
                         end_col=0, start_byte=0, end_byte=100, visibility=None,
                         code_context=None, parent_id=None, semantic_group=None,
                         confidence=1.0, content_type=None):
                self.id = id
                self.name = name
                self.kind = kind
                self.language = language
                self.file_path = file_path
                self.signature = signature
                self.doc_comment = doc_comment
                self.start_line = start_line
                self.start_column = start_col
                self.end_line = end_line
                self.end_column = end_col
                self.start_byte = start_byte
                self.end_byte = end_byte
                self.visibility = visibility
                self.code_context = code_context
                self.parent_id = parent_id
                self.semantic_group = semantic_group
                self.confidence = confidence
                self.content_type = content_type

        # Semantically similar functions in DIFFERENT languages
        # These share CONCEPT but not NAMING VARIANTS
        authenticate_user = MockSymbol(
            id="py_auth",
            name="authenticate_user",
            kind="Function",
            language="python",
            file_path="auth/login.py",
            signature="def authenticate_user(username: str, password: str) -> bool:",
            doc_comment="Authenticate a user by checking their credentials",
            start_line=10,
            end_line=25
        )

        # Different words, same concept - NO naming variant match possible
        verify_credentials = MockSymbol(
            id="ts_verify",
            name="verifyCredentials",
            kind="Function",
            language="typescript",
            file_path="src/auth/credentials.ts",
            signature="function verifyCredentials(creds: Credentials): Promise<boolean>",
            doc_comment="Verify user credentials against the database",
            start_line=15,
            end_line=30
        )

        # Abbreviated form - also no naming variant match
        check_auth = MockSymbol(
            id="go_check",
            name="check_auth",
            kind="Function",
            language="go",
            file_path="pkg/auth/checker.go",
            signature="func check_auth(ctx context.Context, token string) error",
            doc_comment="Check authentication status from token",
            start_line=20,
            end_line=40
        )

        # Completely unrelated function (should NOT match)
        format_date = MockSymbol(
            id="py_date",
            name="format_date",
            kind="Function",
            language="python",
            file_path="utils/dates.py",
            signature="def format_date(dt: datetime) -> str:",
            doc_comment="Format a datetime object as ISO string",
            start_line=5,
            end_line=10
        )

        # Another unrelated function
        calculate_total = MockSymbol(
            id="ts_calc",
            name="calculateTotal",
            kind="Function",
            language="typescript",
            file_path="src/cart/totals.ts",
            signature="function calculateTotal(items: CartItem[]): number",
            doc_comment="Calculate shopping cart total",
            start_line=1,
            end_line=15
        )

        # Add files
        storage.add_file("auth/login.py", "python", "hash_auth", 500, 0)
        storage.add_file("src/auth/credentials.ts", "typescript", "hash_creds", 600, 0)
        storage.add_file("pkg/auth/checker.go", "go", "hash_checker", 700, 0)
        storage.add_file("utils/dates.py", "python", "hash_dates", 200, 0)
        storage.add_file("src/cart/totals.ts", "typescript", "hash_totals", 300, 0)

        # Add symbols
        symbols = [
            authenticate_user,
            verify_credentials,
            check_auth,
            format_date,
            calculate_total,
        ]
        storage.add_symbols_batch(symbols)

        # CRITICAL: NO relationships added!
        # This is the whole point - we want to test discovery WITHOUT relationships

        yield storage
        storage.close()

    @pytest.fixture
    def indexed_semantic_workspace(self, semantic_discovery_workspace, tmp_path):
        """
        Create workspace WITH vector embeddings indexed.

        This extends semantic_discovery_workspace by adding vector embeddings
        for all symbols, enabling true semantic search.
        """
        import numpy as np
        from miller.embeddings import EmbeddingManager
        from miller.embeddings.vector_store import VectorStore

        storage = semantic_discovery_workspace

        # Create vector store
        vector_path = tmp_path / "vectors.lance"
        vector_store = VectorStore(str(vector_path))

        # Get embeddings manager
        embeddings = EmbeddingManager()

        # Index all symbols with embeddings
        cursor = storage.conn.cursor()
        cursor.execute("""
            SELECT id, name, kind, language, file_path, start_line, end_line,
                   signature, doc_comment
            FROM symbols
        """)

        # Create mock symbol objects matching VectorStore expectations
        class MockPySymbol:
            def __init__(self, id, name, kind, language, file_path, start_line,
                         end_line, signature, doc_comment):
                self.id = id
                self.name = name
                self.kind = kind
                self.language = language
                self.file_path = file_path
                self.start_line = start_line
                self.end_line = end_line
                self.signature = signature
                self.doc_comment = doc_comment

        symbols = []
        vectors = []

        for row in cursor.fetchall():
            sym_id, name, kind, language, file_path, start_line, end_line, signature, doc_comment = row

            # Create mock symbol
            sym = MockPySymbol(
                id=sym_id,
                name=name,
                kind=kind,
                language=language,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                signature=signature,
                doc_comment=doc_comment,
            )
            symbols.append(sym)

            # Create searchable text for embedding
            # Include name, signature, and doc comment for rich semantic content
            text_parts = [name]
            if signature:
                text_parts.append(signature)
            if doc_comment:
                text_parts.append(doc_comment)
            searchable_text = " ".join(text_parts)

            # Generate embedding
            embedding = embeddings.embed_query(searchable_text)
            vectors.append(embedding)

        # Add to vector store
        if symbols:
            vectors_array = np.array(vectors)
            vector_store.add_symbols(symbols, vectors_array)

        yield storage, vector_store, embeddings

        vector_store.close()

    @pytest.mark.asyncio
    async def test_discovers_semantically_similar_without_relationship(
        self, indexed_semantic_workspace
    ):
        """
        CRITICAL TEST: Verify semantic discovery finds related symbols
        WITHOUT pre-existing database relationships.

        Given:
        - authenticate_user (Python)
        - verifyCredentials (TypeScript) - semantically similar
        - NO database relationship between them

        When:
        - trace_call_path("authenticate_user", enable_semantic=True, vector_store=...)

        Then:
        - Should find verifyCredentials via embedding similarity
        - match_type should be "semantic"
        - confidence should be >= 0.7

        NOTE: This test requires the vector_store parameter to be added to trace_call_path.
        The current implementation doesn't support true semantic discovery.
        """
        from miller.tools.trace import trace_call_path

        storage, vector_store, embeddings = indexed_semantic_workspace

        # NOTE: We pass vector_store to enable true semantic discovery
        # This is the NEW parameter we need to add to trace_call_path
        result = await trace_call_path(
            storage=storage,
            symbol_name="authenticate_user",
            direction="downstream",
            max_depth=2,
            enable_semantic=True,
            embeddings=embeddings,
            vector_store=vector_store,  # NEW: Pass vector store for discovery
        )

        assert result["query_symbol"] == "authenticate_user"

        root = result["root"]
        assert root["name"] == "authenticate_user"
        assert root["language"] == "python"

        # Should find semantically similar symbols via vector search
        # Even though there are NO database relationships!
        children = root.get("children", [])

        # Find cross-language semantic matches
        semantic_matches = [
            child for child in children
            if child["match_type"] == "semantic"
            and child["language"] != "python"  # Cross-language
        ]

        # CRITICAL ASSERTION: We should find at least one semantic match
        assert len(semantic_matches) > 0, (
            "Expected to find semantically similar symbols via vector search, "
            "but found none. This indicates semantic discovery is not working - "
            "it's only labeling existing relationships, not discovering new ones."
        )

        # Should find verifyCredentials (TypeScript) or check_auth (Go)
        semantic_names = {m["name"] for m in semantic_matches}
        assert "verifyCredentials" in semantic_names or "check_auth" in semantic_names, (
            f"Expected to find auth-related functions, but found: {semantic_names}"
        )

        # Verify confidence scores are present and above threshold
        for match in semantic_matches:
            assert match["confidence"] is not None
            assert match["confidence"] >= 0.7, (
                f"Semantic match {match['name']} has confidence {match['confidence']} < 0.7"
            )

    @pytest.mark.asyncio
    async def test_does_not_match_unrelated_symbols(
        self, indexed_semantic_workspace
    ):
        """
        Verify semantic discovery doesn't return unrelated symbols.

        Given:
        - authenticate_user (Python auth function)
        - format_date (Python date utility) - semantically unrelated

        When:
        - trace_call_path("authenticate_user", enable_semantic=True)

        Then:
        - Should NOT find format_date (different semantic domain)
        """
        from miller.tools.trace import trace_call_path

        storage, vector_store, embeddings = indexed_semantic_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="authenticate_user",
            direction="downstream",
            max_depth=2,
            enable_semantic=True,
            embeddings=embeddings,
            vector_store=vector_store,
        )

        root = result["root"]
        children = root.get("children", [])

        child_names = {child["name"] for child in children}

        # Should NOT find unrelated functions
        assert "format_date" not in child_names, (
            "Found unrelated function 'format_date' - semantic threshold may be too low"
        )
        assert "calculateTotal" not in child_names, (
            "Found unrelated function 'calculateTotal' - semantic threshold may be too low"
        )

    @pytest.mark.asyncio
    async def test_cross_language_only_filter(
        self, indexed_semantic_workspace
    ):
        """
        Verify semantic discovery can filter to cross-language matches only.

        This is the key use case: finding equivalent functionality
        in OTHER languages, not same-language duplicates.
        """
        from miller.tools.trace import trace_call_path

        storage, vector_store, embeddings = indexed_semantic_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="authenticate_user",
            direction="downstream",
            max_depth=2,
            enable_semantic=True,
            embeddings=embeddings,
            vector_store=vector_store,
        )

        root = result["root"]
        children = root.get("children", [])

        # Get semantic matches
        semantic_matches = [
            child for child in children
            if child["match_type"] == "semantic"
        ]

        # All semantic matches should be in DIFFERENT languages
        for match in semantic_matches:
            assert match["language"] != root["language"], (
                f"Semantic match {match['name']} is in same language ({match['language']}) "
                f"as source symbol. Cross-language filter not working."
            )


# Note: Integration tests for semantic_neighbors are covered by
# TestTrueSemanticDiscovery which tests the full trace_call_path flow
