# Miller 2.0: Jina-0.5B Migration Plan

## Overview

Upgrading Miller from BGE-Small (384D, 512 tokens) to Jina-Code-Embeddings-0.5B (896D, 8192+ tokens) for deep semantic code intelligence.

**Hardware Target:** RTX 5070 Ti (16GB VRAM) with FP16 precision

---

## Phase 1: Core Infrastructure (Critical Path)

### 1.1 EmbeddingManager Upgrade

**File:** `python/miller/embeddings/manager.py`

```python
import os
import torch

class EmbeddingManager:
    def __init__(self, model_name: str = None, device: str = "auto"):
        logger = logging.getLogger("miller.embeddings")

        # DYNAMIC CONFIG: Allow model override via environment variable
        # This ensures compatibility with both GPU (Jina) and CPU (BGE) environments
        default_model = "jinaai/jina-code-embeddings-0.5b"
        self.model_name = model_name or os.getenv("MILLER_EMBEDDING_MODEL", default_model)

        # Device detection (existing logic)
        # ...

        # MODEL CONFIGURATION for Jina
        model_kwargs = {
            "trust_remote_code": True,  # REQUIRED for Jina's LastTokenPooling
        }

        if self.device == "cuda":
            # FP16 optimization: doubles throughput, halves VRAM on RTX 5070 Ti
            model_kwargs["torch_dtype"] = torch.float16

        # Load model
        with open(os.devnull, "w") as devnull, redirect_stdout(devnull), redirect_stderr(devnull):
            self.model = SentenceTransformer(
                self.model_name,
                device=self.device,
                model_kwargs=model_kwargs
            )

        # PAPER REQUIREMENT: Set context length (8192 for evaluation)
        self.model.max_seq_length = 8192

        # Get dimension dynamically (896 for Jina, 384 for BGE)
        self.dimensions = self.model.get_sentence_embedding_dimension()

        # JINA PAPER REQUIREMENT (Table 1): Task-specific prefixes
        self.prefixes = {
            "retrieval_query": "Find the most relevant code snippet given the following query:\n",
            "retrieval_doc": "Candidate code snippet:\n",
            "similarity_query": "Find an equivalent code snippet given the following code snippet:\n",
        }

        # Batch size for 16GB VRAM with FP16
        self.batch_size = 64
```

### 1.2 Task-Aware embed_query

**File:** `python/miller/embeddings/manager.py`

```python
    def embed_query(self, query: str, task: str = "retrieval") -> np.ndarray:
        """
        Embed a query with task-appropriate prefix.

        Args:
            query: Text to embed
            task: "retrieval" (NL→Code) or "similarity" (Code→Code)

        Returns:
            L2-normalized embedding vector
        """
        self._ensure_loaded()

        # Apply task-specific prefix (Jina paper requirement)
        if task == "similarity":
            prefix = self.prefixes.get("similarity_query", "")
        else:
            prefix = self.prefixes.get("retrieval_query", "")

        full_query = f"{prefix}{query}" if prefix else query

        embedding = self.model.encode(
            full_query,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return embedding.astype(np.float32)
```

### 1.3 Code-Formatted embed_batch

**File:** `python/miller/embeddings/manager.py`

```python
    def embed_batch(self, symbols: list[Any], is_document: bool = True) -> np.ndarray:
        """
        Embed symbols with code-like formatting for Jina's autoregressive model.
        """
        if not symbols:
            return np.empty((0, self.dimensions), dtype=np.float32)

        self._ensure_loaded()

        # Build pseudo-code representations (better for autoregressive models)
        texts = []
        for sym in symbols:
            parts = []

            # 1. Docstring as comment (if available)
            if hasattr(sym, "doc_comment") and sym.doc_comment:
                parts.append(f"/* {sym.doc_comment} */")

            # 2. Signature (most code-like) or fallback to kind + name
            if hasattr(sym, "signature") and sym.signature:
                parts.append(sym.signature)
            else:
                kind = getattr(sym, "kind", "symbol").lower()
                parts.append(f"{kind} {sym.name}")

            text = "\n".join(parts)
            texts.append(text)

        # Apply document prefix if indexing (not querying)
        if is_document:
            prefix = self.prefixes.get("retrieval_doc", "")
            texts = [f"{prefix}{t}" for t in texts]

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=self.batch_size,
        )

        return embeddings.astype(np.float32)
```

### 1.4 embed_texts with Document Prefix

**File:** `python/miller/embeddings/manager.py`

```python
    def embed_texts(self, texts: list[str], is_document: bool = True) -> np.ndarray:
        """
        Embed raw text strings (for file-level indexing).
        """
        if not texts:
            return np.empty((0, self.dimensions), dtype=np.float32)

        self._ensure_loaded()

        # Apply document prefix for indexing
        if is_document:
            prefix = self.prefixes.get("retrieval_doc", "")
            texts = [f"{prefix}{t}" for t in texts]

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=self.batch_size,
        )

        return embeddings.astype(np.float32)
```

---

## Phase 2: Schema & Migration Safety

### 2.1 VectorStore Schema with Auto-Migration

**File:** `python/miller/embeddings/vector_store.py`

```python
class VectorStore:
    def __init__(
        self,
        db_path: str = ".miller/indexes/vectors.lance",
        embeddings: Optional["EmbeddingManager"] = None,
        expected_dim: int = 896,  # NEW: Dynamic dimension from EmbeddingManager
    ):
        self.db_path = db_path
        self._embeddings = embeddings
        self.expected_dim = expected_dim
        self.was_reset = False  # CRITICAL: Track if we wiped data

        # Build schema dynamically based on expected dimension
        self.SCHEMA = pa.schema([
            pa.field("id", pa.string(), nullable=False),
            pa.field("name", pa.string(), nullable=False),
            pa.field("kind", pa.string(), nullable=False),
            pa.field("language", pa.string(), nullable=False),
            pa.field("file_path", pa.string(), nullable=False),
            pa.field("signature", pa.string(), nullable=True),
            pa.field("doc_comment", pa.string(), nullable=True),
            pa.field("start_line", pa.int32(), nullable=True),
            pa.field("end_line", pa.int32(), nullable=True),
            pa.field("code_pattern", pa.string(), nullable=False),
            pa.field("content", pa.string(), nullable=True),
            pa.field("vector", pa.list_(pa.float32(), expected_dim), nullable=False),
        ])

        # ... connection setup ...

        try:
            self._table = self.db.open_table(self.table_name)

            # AUTO-MIGRATION: Detect dimension mismatch and reset
            current_dim = self._table.schema.field("vector").type.value_type.list_size
            if current_dim != expected_dim:
                logger.warning(
                    f"📉 Vector dimension mismatch: {current_dim} → {expected_dim}. "
                    f"Dropping table for model upgrade."
                )
                self.db.drop_table(self.table_name)
                self._table = None
                self.was_reset = True  # Signal that we wiped data

        except Exception:
            self._table = None
```

### 2.2 Lifecycle Migration Death Spiral Fix

**File:** `python/miller/lifecycle.py`

```python
async def _background_initialization_and_indexing():
    # ... init embeddings ...
    server_state.embeddings = EmbeddingManager(...)

    # ... init storage ...
    server_state.storage = StorageManager(str(db_path))

    # Init vector store with dynamic dimension
    server_state.vector_store = VectorStore(
        db_path=str(vector_path),
        embeddings=server_state.embeddings,
        expected_dim=server_state.embeddings.dimensions,  # Dynamic!
    )

    # CRITICAL FIX: Migration Death Spiral Prevention
    # If vector store was reset (schema upgrade), SQLite still thinks files are indexed.
    # This causes scanner to skip re-indexing, leaving empty search results.
    if server_state.vector_store.was_reset:
        logger.warning(
            "♻️ Vector schema upgrade detected. Invalidating SQLite cache to force full re-index."
        )
        server_state.storage.conn.execute("DELETE FROM files")
        server_state.storage.conn.commit()

    # ... proceed to scanner ...
```

---

## Phase 3: Call Site Updates

### 3.1 Code2Code Similarity Search (task="similarity")

These locations use embed_query for Code→Code comparison:

**File:** `python/miller/tools/trace/search.py`

```python
# Line 166-167: _compute_semantic_similarity
vec1 = embeddings.embed_query(name1, task="similarity")
vec2 = embeddings.embed_query(name2, task="similarity")

# Line 232: semantic_neighbors
query_vector = embeddings.embed_query(searchable_text, task="similarity")
```

**File:** `python/miller/tools/symbols/filters.py`

```python
# Line 86: apply_semantic_filter
target_embedding = embedding_manager.embed_query(target, task="similarity")
```

### 3.2 NL→Code Retrieval (task="retrieval", default)

These locations keep default behavior:

- `python/miller/embeddings/search_methods.py:170, 218`
- `python/miller/tools/recall.py:228`

---

## Phase 4: Configuration Updates

### 4.1 Content Truncation Limit

**File:** `python/miller/workspace/indexer.py`

```python
# Jina's sweet spot is 8192 tokens (paper evaluation context).
# 8192 tokens * ~4 chars/token = ~32KB
# This provides optimal retrieval quality per the Jina paper.
MAX_CONTENT_FOR_EMBEDDING = 32 * 1024  # Was: 10 * 1024
```

### 4.2 Search Contract (Dynamic)

**File:** `python/miller/search_contract.py`

```python
# NOTE: vector_dimension is now dynamic based on model
# Remove hardcoded 384, or make it configurable
VALIDATION_RULES = {
    "schema": {
        "code_pattern_field_required": True,
        "code_pattern_not_nullable": True,
        # vector_dimension is now dynamic - validated at runtime
    },
    # ...
}
```

### 4.3 Dependencies

**File:** `pyproject.toml`

```toml
[project.dependencies]
# Existing dependencies...
transformers = ">=4.53.0"  # Required for Qwen2.5 (Jina's base)
einops = "*"               # Often required for Jina/remote code
```

### 4.4 Model Name References (40+ locations)

Update all hardcoded `"BAAI/bge-small-en-v1.5"` to use dynamic loading:

| File | Line | Change |
|------|------|--------|
| `lifecycle.py` | 282 | Use default from EmbeddingManager |
| `explore_wrapper.py` | 98 | Use default from EmbeddingManager |
| `workspace/indexing.py` | 98 | Use default from EmbeddingManager |
| All test files | Multiple | Add model parameter or use fixture |

---

## Phase 5: Test Updates

### 5.1 Dimension Assertions

Bulk update all `384` assertions:

```bash
# Find all test dimension references
grep -rn "384" python/tests/test_embeddings.py python/tests/test_file_level_indexing.py
```

Options:
1. Change to `896` (if assuming Jina)
2. Use `embeddings.dimensions` dynamically
3. Mock to return consistent value

### 5.2 Model Name in Tests

Either:
- Keep BGE for fast CPU tests: `EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")`
- Add fixture that uses smaller test model
- Use environment variable override

---

## Summary: Files to Modify

### Critical (Must Change)
| File | Changes |
|------|---------|
| `embeddings/manager.py` | Model loading, prefixes, task param, formatting |
| `embeddings/vector_store.py` | Dynamic schema, was_reset flag, expected_dim |
| `lifecycle.py` | Migration check, dynamic dim passing |
| `workspace/indexer.py` | MAX_CONTENT_FOR_EMBEDDING |
| `pyproject.toml` | New dependencies |

### Call Sites (task parameter)
| File | Changes |
|------|---------|
| `tools/trace/search.py` | Add task="similarity" |
| `tools/symbols/filters.py` | Add task="similarity" |

### Schema/Contract
| File | Changes |
|------|---------|
| `search_contract.py` | Remove hardcoded 384 or make dynamic |

### Production Code (model name)
| File | Changes |
|------|---------|
| `explore_wrapper.py` | Use default model |
| `workspace/indexing.py` | Use default model |

### Tests (~50 changes)
| File | Changes |
|------|---------|
| `test_embeddings.py` | Dimension assertions, model names |
| `test_file_level_indexing.py` | Dimension assertions, model names |
| `test_pattern_search_poc.py` | Test vector dimensions |
| `test_recall.py` | Mock dimensions |
| `conftest.py` | Fixture model name |

### Documentation
| File | Changes |
|------|---------|
| `docs/DEVELOPMENT.md` | Update dimension references |

---

## Implementation Order

1. **Phase 1**: Core Infrastructure (EmbeddingManager, task prefixes)
2. **Phase 2**: Schema & Migration Safety (VectorStore, lifecycle)
3. **Phase 3**: Call Site Updates (trace/search, filters)
4. **Phase 4**: Configuration (indexer, contract, dependencies)
5. **Phase 5**: Tests (dimensions, model names)
6. **Phase 6**: Documentation

**Estimated Total Changes:** ~120 code edits across ~20 files

---

## Rollback Strategy

If issues arise, users can:
1. Set `MILLER_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`
2. Delete `.miller/indexes/` to force re-index with old model
3. The dynamic dimension handling will work for either model
