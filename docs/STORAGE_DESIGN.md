# Miller Storage Layer Design

**Goal:** Python storage layer with 100% schema parity to Julie's Rust implementation.

---

## Architecture

```
Python Application
    ↓
StorageManager (python/miller/storage.py)
    ↓
SQLite Database (.miller/indexes/symbols.db)
    - Tables: 10 total (exact match to Julie)
    - FTS5: files_fts, symbols_fts (auto-synced)
    - Indexes: name, kind, language, file_path, etc.
```

---

## Module Structure

```python
python/miller/
├── storage.py              # Main StorageManager class
│   ├── __init__()         # Connect, enable WAL, initialize schema
│   ├── add_file()         # Insert file record
│   ├── add_symbols()      # Bulk insert symbols
│   ├── add_identifiers()  # Bulk insert identifiers
│   ├── add_relationships() # Bulk insert relationships
│   ├── search_symbols()   # FTS5 search
│   ├── get_symbol_by_id() # Direct lookup
│   └── delete_file()      # Remove file (CASCADE to symbols)
│
└── schemas.py              # Pydantic models (optional for validation)
```

---

## Schema Parity Requirements

### Must Match Julie Exactly

1. **Table names** - Identical
2. **Column names** - Identical (even quirks like `start_col` vs `start_column`)
3. **Column types** - TEXT, INTEGER, REAL, BLOB
4. **Foreign keys** - Same CASCADE behavior
5. **Indexes** - All indexes from Julie
6. **FTS5 config** - unicode61 tokenizer, prefix indexes 2,3,4,5

### Differences Allowed

- Python uses `?` placeholders instead of Rust's named parameters
- Python uses `sqlite3` module instead of `rusqlite`
- No Rust-specific types (Path, Duration) - use strings/ints

---

## Implementation Plan

### Phase 1: Core Tables (symbols, files)

**Tables to create:**
1. `workspaces` - Workspace metadata
2. `files` - Source files with hash/size/language
3. `symbols` - Extracted symbols with metadata
4. `files_fts` - FTS5 virtual table for file content
5. `symbols_fts` - FTS5 virtual table for symbol search

**Why start here?**
- Symbols are the core data type
- FTS5 search is critical for fast queries
- Can test end-to-end: extract → store → search

### Phase 2: References & Relationships

**Tables to create:**
6. `identifiers` - Usage references (calls, variable refs)
7. `relationships` - Symbol relationships (extends, implements)
8. `types` - Type intelligence (optional for now)

### Phase 3: Embeddings (deferred to Phase 3 of main plan)

**Tables to create:**
9. `embeddings` - Symbol → vector mapping
10. `embedding_vectors` - Actual f32 vector data as BLOBs

---

## Python API Design

### StorageManager Class

```python
class StorageManager:
    def __init__(self, db_path: str = ".miller/indexes/symbols.db"):
        """Initialize database with WAL mode and schema."""
        self.conn = sqlite3.connect(db_path)
        self._enable_wal()
        self._initialize_schema()

    def add_file(self, file_path: str, language: str, content: str,
                 hash: str, size: int) -> None:
        """Add or update file record."""
        # INSERT OR REPLACE INTO files ...

    def add_symbols_batch(self, symbols: List[Symbol], file_path: str) -> int:
        """Bulk insert symbols from extraction results."""
        # Convert PySymbol to dict
        # executemany() for bulk insert
        # Return count inserted

    def search_symbols(self, query: str, limit: int = 50) -> List[Dict]:
        """FTS5 search for symbols by name/signature/doc."""
        # SELECT from symbols_fts with MATCH
        # JOIN to symbols table for full data
        # Return list of dicts

    def get_symbol_by_id(self, symbol_id: str) -> Optional[Dict]:
        """Get single symbol by ID."""
        # SELECT WHERE id = ?

    def delete_file(self, file_path: str) -> None:
        """Delete file and CASCADE to symbols/identifiers."""
        # DELETE FROM files WHERE path = ?
```

---

## Testing Strategy (TDD)

### Test 1: Database Initialization
```python
def test_database_creates_with_wal_mode():
    storage = StorageManager(":memory:")
    # Verify WAL mode enabled
    cursor = storage.conn.cursor()
    mode = cursor.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.upper() == "WAL"
```

### Test 2: Schema Creation
```python
def test_schema_creates_all_tables():
    storage = StorageManager(":memory:")
    # Get table names
    tables = storage.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    expected = ['workspaces', 'files', 'symbols', 'identifiers',
                'relationships', 'embeddings', 'embedding_vectors', 'types']
    assert set(t[0] for t in tables) >= set(expected)
```

### Test 3: Symbol Storage
```python
def test_add_symbols_stores_correctly():
    storage = StorageManager(":memory:")

    # Extract symbols from test code
    from miller import miller_core
    result = miller_core.extract_file("def hello(): pass", "python", "test.py")

    # Store symbols
    storage.add_file("test.py", "python", "def hello(): pass", "hash123", 100)
    storage.add_symbols_batch(result.symbols, "test.py")

    # Verify storage
    sym = storage.get_symbol_by_name("hello")
    assert sym['name'] == 'hello'
    assert sym['kind'] == 'function'
```

### Test 4: FTS5 Search
```python
def test_fts_search_finds_symbols():
    storage = StorageManager(":memory:")
    # ... insert symbols ...

    results = storage.search_symbols("hello")
    assert len(results) > 0
    assert any(r['name'] == 'hello' for r in results)
```

### Test 5: CASCADE Delete
```python
def test_delete_file_cascades_to_symbols():
    storage = StorageManager(":memory:")
    # ... insert file + symbols ...

    # Verify symbols exist
    count_before = storage.count_symbols()
    assert count_before > 0

    # Delete file
    storage.delete_file("test.py")

    # Symbols should be gone (CASCADE)
    count_after = storage.count_symbols()
    assert count_after == 0
```

---

## Key Decisions

### 1. Use sqlite3 (Python stdlib) vs SQLAlchemy

**Decision:** Use `sqlite3` directly

**Rationale:**
- Julie uses raw SQL - easier to match exactly
- No ORM overhead
- Full control over FTS5 and triggers
- Simpler dependencies

### 2. Schema Version Tracking

**Decision:** Match Julie's migration system

**Implementation:**
```python
def get_schema_version(self) -> int:
    try:
        cursor = self.conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        )
        return int(cursor.fetchone()[0])
    except:
        return 0

def set_schema_version(self, version: int):
    self.conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ("schema_version", str(version))
    )
```

### 3. Error Handling

**Decision:** Raise exceptions, don't silently fail

**Pattern:**
```python
try:
    self.conn.execute(sql, params)
    self.conn.commit()
except sqlite3.Error as e:
    self.conn.rollback()
    raise StorageError(f"Failed to insert symbols: {e}")
```

### 4. Type Conversion (Rust → Python → SQLite)

**Mapping:**
- Rust `String` → Python `str` → SQLite `TEXT`
- Rust `u32` → Python `int` → SQLite `INTEGER`
- Rust `f32` → Python `float` → SQLite `REAL`
- Rust `Option<T>` → Python `None | T` → SQLite `NULL`
- Rust `HashMap` → Python `dict` → SQLite `TEXT` (JSON)

---

## Performance Targets

**Based on Julie's performance:**
- Bulk insert: >1000 symbols/sec
- FTS5 search: <50ms for typical queries
- Database size: ~10MB per 10k symbols

**Optimization strategies:**
1. Disable FTS triggers during bulk insert
2. Use `executemany()` for batch operations
3. Wrap bulk ops in transactions
4. Rebuild FTS after bulk operations

---

## Compatibility Verification

**How to verify schema matches Julie:**

```python
def test_schema_matches_julie():
    """Compare Miller's schema to Julie's schema."""
    miller_storage = StorageManager(":memory:")

    # Get Miller's schema
    miller_schema = get_create_statements(miller_storage.conn)

    # Load Julie's expected schema (from schema.rs)
    with open("tests/fixtures/julie_schema.sql") as f:
        julie_schema = f.read()

    # Compare (normalize whitespace/ordering)
    assert schemas_equivalent(miller_schema, julie_schema)
```

---

## Next Steps

1. ✅ Research complete (this document)
2. ⏭️ Write storage tests (TDD)
3. ⏭️ Implement StorageManager class
4. ⏭️ Verify schema parity with Julie
5. ⏭️ Test performance (bulk insert, search)
6. ⏭️ Integration test (extract → store → search)

---

**Status:** Design complete, ready for TDD implementation
