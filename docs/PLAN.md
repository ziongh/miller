# Miller: Python MCP Server with Rust-Powered Core
## Migration Plan from Julie (Rust) to Miller (Python + Rust)

**Version:** 2.0 (Julie-Specific)
**Date:** 2025-11-17
**Source Project:** Julie (c:\source\julie)
**Target Project:** Miller (c:\source\miller)

---

## 1. Executive Summary

### The Problem
Julie is a sophisticated Rust-based code intelligence server with **31 language parsers**, LSP-quality features, and semantic search. However, it suffers from a critical bottleneck on Linux: GPU-accelerated embeddings via the `ort` (ONNX Runtime) crate require complex CUDA setup and frequently fail with driver issues.

### The Solution
**Miller** will be a hybrid Python/Rust architecture that:

1. **Preserves Julie's core asset**: The battle-tested Tree-sitter extraction engine (31 languages, ~697 Rust files)
2. **Solves the GPU problem**: Uses Python's superior AI ecosystem (`onnxruntime-gpu`, `sentence-transformers`) with easier hardware acceleration
3. **Improves the semantic layer**: Leverages better Python ML libraries for embeddings and vector search
4. **Maintains performance**: Keeps Rust for the parsing-heavy work via PyO3 extension modules

### The Strategy
- **Re-compile** Julie's entire `src/extractors/` directory as a Python extension module using PyO3 + Maturin
- **Re-implement** the database, MCP server, and semantic search in Python using battle-tested libraries
- **Incremental migration**: Start with core parsing, then storage, then semantic features
- **Parity validation**: Test against Julie's output to ensure correctness

---

## 2. Current Julie Architecture (What We're Migrating)

### Module Breakdown

Julie's codebase (~697 Rust files, 1006 total files):

```
src/
├── extractors/              # 🎯 MIGRATE TO RUST EXTENSION (Phase 1)
│   ├── manager.rs          # ExtractorManager - main API
│   ├── factory.rs          # Dispatch to 31 language extractors
│   ├── base/               # Shared extraction logic
│   │   ├── types.rs        # Symbol, Identifier, Relationship structs
│   │   ├── extractor.rs    # BaseExtractor trait/helpers
│   │   └── tree_methods.rs # Tree-sitter traversal utilities
│   ├── python/             # Python-specific extractor (example)
│   │   ├── functions.rs
│   │   ├── types.rs
│   │   ├── imports.rs
│   │   ├── relationships.rs
│   │   └── identifiers.rs
│   └── [30 other languages]
│
├── language.rs             # 🎯 MIGRATE TO RUST EXTENSION
│                           # Central language config + detection
│
├── database/               # ✅ REWRITE IN PYTHON (Phase 2)
│   ├── schema.rs           # → Python migrations
│   ├── symbols/            # → SQLite CRUD in Python
│   ├── embeddings.rs       # → Python embedding storage
│   └── migrations.rs       # → Python migration runner
│
├── embeddings/             # ✅ REWRITE IN PYTHON (Phase 3)
│   ├── ort_model.rs        # → Python ONNX Runtime or sentence-transformers
│   ├── vector_store.rs     # → Python HNSW (hnswlib/faiss)
│   └── model_manager.rs    # → Python HuggingFace model downloads
│
├── tools/                  # ✅ REWRITE IN PYTHON (Phase 4)
│   ├── search/             # → MCP tools in Python
│   ├── navigation/         # → fast_goto, fast_refs, etc.
│   ├── editing/            # → Refactoring tools
│   └── workspace/          # → Workspace management
│
├── handler.rs              # ✅ REWRITE IN PYTHON (Phase 4)
│                           # → MCP message handler
│
└── main.rs                 # ✅ REWRITE IN PYTHON (Phase 4)
                            # → Python MCP server entry point
```

### Key Data Structures (Julie)

These **MUST** be ported to PyO3-compatible structs:

```rust
// src/extractors/base/types.rs
pub struct Symbol {
    pub id: String,              // MD5 hash
    pub name: String,
    pub kind: SymbolKind,        // Enum: Function, Class, Method, etc.
    pub language: String,
    pub file_path: String,       // Relative Unix path
    pub start_line: u32,         // 1-based
    pub start_column: u32,       // 0-based
    pub end_line: u32,
    pub end_column: u32,
    pub start_byte: u32,
    pub end_byte: u32,
    pub signature: Option<String>,
    pub doc_comment: Option<String>,
    pub visibility: Option<Visibility>,
    pub parent_id: Option<String>,
    pub metadata: Option<HashMap<String, serde_json::Value>>,
    pub code_context: Option<String>, // 3 lines before/after
    pub content_type: Option<String>,
}

pub struct Identifier {
    pub id: String,
    pub name: String,
    pub kind: IdentifierKind,    // Call, VariableRef, TypeUsage, etc.
    pub language: String,
    pub file_path: String,
    pub start_line: u32,
    pub end_line: u32,
    pub start_column: u32,
    pub end_column: u32,
    pub start_byte: u32,
    pub end_byte: u32,
    pub containing_symbol_id: Option<String>,
    pub target_symbol_id: Option<String>,
    pub confidence: f32,
    pub code_context: Option<String>,
}

pub struct Relationship {
    pub id: String,
    pub from_symbol_id: String,
    pub to_symbol_id: String,
    pub kind: RelationshipKind,  // Calls, Extends, Implements, etc.
    pub file_path: String,
    pub line_number: u32,
    pub confidence: f32,
    pub metadata: Option<HashMap<String, serde_json::Value>>,
}

pub struct ExtractionResults {
    pub symbols: Vec<Symbol>,
    pub relationships: Vec<Relationship>,
    pub identifiers: Vec<Identifier>,
    pub types: HashMap<String, TypeInfo>,
}
```

### Supported Languages (31)

Julie currently supports:
- **Systems**: Rust, C, C++, Go, Zig
- **Web**: TypeScript, JavaScript, TSX, JSX, HTML, CSS, Vue, QML
- **Backend**: Python, Java, C#, PHP, Ruby, Swift, Kotlin, Dart
- **Scripting**: Lua, R, Bash, PowerShell
- **Specialized**: GDScript, Razor, SQL, Regex
- **Documentation**: Markdown, JSON, JSONL, TOML, YAML

All 31 extractors must be compiled into the Rust extension.

---

## 3. Miller Architecture (The Target)

### "Rust Sandwich" Model

```
┌─────────────────────────────────────────────────────────┐
│                     Python Layer                        │
│  ┌───────────────────────────────────────────────────┐  │
│  │  FastMCP Server (MCP Protocol Handler)           │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Embeddings (onnxruntime-gpu / transformers)     │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Database (SQLite + LanceDB)                      │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  🔌 Import miller_core (PyO3 Extension)           │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│              Rust Core (miller_core.pyd)                │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Tree-sitter Parsing (31 Languages)              │  │
│  │  - ExtractorManager                              │  │
│  │  - ExtractorFactory                              │  │
│  │  - BaseExtractor                                 │  │
│  │  - Python/JS/Rust/... extractors                 │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Language Detection & Registry                    │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Data Flow Example: Indexing a File

1. **[Python]** FastMCP receives `index_file(path="src/main.py")`
2. **[Python]** Read file content: `code = open(path).read()`
3. **[Python → Rust]** Call extension: `results = miller_core.extract_file(code, "python")`
4. **[Rust]** Run Tree-sitter parser → Extract symbols/relationships/identifiers
5. **[Rust → Python]** Return `ExtractionResults` (PyO3 auto-converts to Python objects)
6. **[Python]** For each symbol:
   - Generate embedding: `vector = embed_model.encode(symbol.name + symbol.signature)`
   - Insert into SQLite: `INSERT INTO symbols (...)`
   - Insert into LanceDB: `table.add({vector, symbol_id, content})`
7. **[Python]** Return success to MCP client

---

## 4. Phase 1: Build the Rust Core Extension

**Goal**: Compile Julie's `src/extractors/` + `src/language.rs` into a Python-importable module.

### 1.1 Project Structure

```
miller/
├── Cargo.toml              # Rust extension config
├── pyproject.toml          # Maturin build config
├── README.md
├── docs/
│   └── PLAN.md             # This file
│
├── src/                    # Rust extension code
│   ├── lib.rs              # PyO3 module entry (NEW)
│   ├── language.rs         # COPY from Julie
│   ├── extractors/         # COPY from Julie (entire directory)
│   │   ├── mod.rs
│   │   ├── manager.rs
│   │   ├── factory.rs
│   │   ├── base/
│   │   └── [31 language extractors]
│   └── bindings/           # NEW: PyO3 wrapper types
│       ├── mod.rs
│       ├── symbol.rs       # PyO3 wrapper for Symbol
│       ├── identifier.rs   # PyO3 wrapper for Identifier
│       └── relationship.rs # PyO3 wrapper for Relationship
│
├── python/                 # Python MCP server
│   ├── miller/
│   │   ├── __init__.py
│   │   ├── server.py       # FastMCP server (Phase 4)
│   │   ├── storage.py      # SQLite + LanceDB (Phase 2)
│   │   ├── embeddings.py   # Embedding logic (Phase 3)
│   │   ├── tools/          # MCP tool handlers
│   │   └── schemas.py      # Pydantic models
│   └── tests/
│       └── test_extraction.py
│
└── .venv/                  # Python virtual environment
```

### 1.2 Configure `Cargo.toml`

Copy dependencies from Julie and add PyO3:

```toml
[package]
name = "miller_core"
version = "0.1.0"
edition = "2021"

[lib]
name = "miller_core"
crate-type = ["cdylib"]  # CRITICAL: Makes it a Python module

[dependencies]
# PyO3 for Python bindings
pyo3 = { version = "0.22", features = ["extension-module", "anyhow"] }

# Tree-sitter core (MUST match Julie's version)
tree-sitter = "0.25"

# All 31 language grammars (copy from Julie's Cargo.toml)
tree-sitter-rust = "0.24"
tree-sitter-python = "0.23"
tree-sitter-typescript = "0.23"
tree-sitter-javascript = "0.23"
tree-sitter-tsx = "0.23"
tree-sitter-go = "0.23"
tree-sitter-java = "0.23"
tree-sitter-c = "0.24"
tree-sitter-cpp = "0.23"
tree-sitter-c-sharp = "0.23"
tree-sitter-php = "0.23"
tree-sitter-ruby = "0.23"
tree-sitter-swift = "0.23"
tree-sitter-kotlin-ng = "1.1.0"
harper-tree-sitter-dart = "0.0.5"
tree-sitter-lua = "0.1"
tree-sitter-r = "0.23"
tree-sitter-bash = "0.23"
tree-sitter-powershell = "0.1.0"
tree-sitter-gdscript = "1.1.0"
tree-sitter-html = "0.23"
tree-sitter-css = "0.23"
tree-sitter-vue = "0.1.0"
tree-sitter-qmljs = "0.24.0"
tree-sitter-regex = "0.24"
tree-sitter-sql = "0.3.0"
tree-sitter-markdown = { git = "https://github.com/tree-sitter-grammars/tree-sitter-markdown", rev = "62516e8", default-features = false }
tree-sitter-json = "0.24"
tree-sitter-toml = { git = "https://github.com/tree-sitter/tree-sitter-toml.git", rev = "8bd2056" }
tree-sitter-yaml = "0.6"
tree-sitter-zig = "1.1.0"

# Utilities (copy from Julie)
rayon = "1.10"          # Parallel iteration
regex = "1.11"
glob = "0.3"
anyhow = "1.0"
thiserror = "2.0"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
md5 = "0.7"             # For symbol ID hashing

# Optional: if extractors use these
blake3 = "1.5"          # For file hashing
once_cell = "1.20"      # For lazy statics
tracing = "0.1"         # For logging
```

### 1.3 Configure `pyproject.toml`

```toml
[build-system]
requires = ["maturin>=1.7,<2.0"]
build-backend = "maturin"

[project]
name = "miller-core"
version = "0.1.0"
description = "Rust-powered code intelligence core for Miller"
requires-python = ">=3.9"
classifiers = [
    "Programming Language :: Rust",
    "Programming Language :: Python :: Implementation :: CPython",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]

[tool.maturin]
python-source = "python"
module-name = "miller._miller_core"
```

### 1.4 Create `src/lib.rs` (PyO3 Entry Point)

```rust
use pyo3::prelude::*;

// Import Julie's existing modules (copied into this project)
mod language;
mod extractors;

// PyO3 wrapper types (convert Rust → Python)
mod bindings;

use bindings::{PySymbol, PyIdentifier, PyRelationship, PyExtractionResults};
use extractors::manager::ExtractorManager;

/// Extract symbols, relationships, and identifiers from source code.
///
/// Args:
///     code (str): The source code to parse
///     language (str): Language name (e.g., "python", "rust", "typescript")
///     file_path (str, optional): File path for metadata (default: "")
///
/// Returns:
///     ExtractionResults: Object containing symbols, relationships, identifiers
#[pyfunction]
#[pyo3(signature = (code, language, file_path = "".to_string()))]
fn extract_file(
    code: String,
    language: String,
    file_path: Option<String>,
) -> PyResult<PyExtractionResults> {
    let path = file_path.unwrap_or_else(|| "".to_string());

    // Call Julie's existing ExtractorManager
    let manager = ExtractorManager::new();
    let results = manager
        .extract(&code, &language, &path)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("{}", e)))?;

    // Convert Rust results to Python-compatible types
    Ok(PyExtractionResults::from(results))
}

/// Detect programming language from file extension.
///
/// Args:
///     file_path (str): File path with extension
///
/// Returns:
///     str | None: Detected language name or None
#[pyfunction]
fn detect_language(file_path: String) -> Option<String> {
    language::Language::from_path(&file_path).map(|lang| lang.name().to_string())
}

/// Get list of all supported languages.
///
/// Returns:
///     list[str]: All supported language names
#[pyfunction]
fn supported_languages() -> Vec<String> {
    language::Language::all()
        .iter()
        .map(|lang| lang.name().to_string())
        .collect()
}

/// Miller Core - Rust-powered Tree-sitter extraction for 31 languages.
#[pymodule]
fn miller_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Register functions
    m.add_function(wrap_pyfunction!(extract_file, m)?)?;
    m.add_function(wrap_pyfunction!(detect_language, m)?)?;
    m.add_function(wrap_pyfunction!(supported_languages, m)?)?;

    // Register types
    m.add_class::<PySymbol>()?;
    m.add_class::<PyIdentifier>()?;
    m.add_class::<PyRelationship>()?;
    m.add_class::<PyExtractionResults>()?;

    Ok(())
}
```

### 1.5 Create `src/bindings/` (PyO3 Wrappers)

**File: `src/bindings/mod.rs`**
```rust
mod symbol;
mod identifier;
mod relationship;
mod extraction_results;

pub use symbol::PySymbol;
pub use identifier::PyIdentifier;
pub use relationship::PyRelationship;
pub use extraction_results::PyExtractionResults;
```

**File: `src/bindings/symbol.rs`**
```rust
use pyo3::prelude::*;
use crate::extractors::base::types::Symbol;
use std::collections::HashMap;

#[pyclass(name = "Symbol")]
#[derive(Clone, Debug)]
pub struct PySymbol {
    #[pyo3(get)]
    pub id: String,
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub kind: String,
    #[pyo3(get)]
    pub language: String,
    #[pyo3(get)]
    pub file_path: String,
    #[pyo3(get)]
    pub start_line: u32,
    #[pyo3(get)]
    pub start_column: u32,
    #[pyo3(get)]
    pub end_line: u32,
    #[pyo3(get)]
    pub end_column: u32,
    #[pyo3(get)]
    pub start_byte: u32,
    #[pyo3(get)]
    pub end_byte: u32,
    #[pyo3(get)]
    pub signature: Option<String>,
    #[pyo3(get)]
    pub doc_comment: Option<String>,
    #[pyo3(get)]
    pub visibility: Option<String>,
    #[pyo3(get)]
    pub parent_id: Option<String>,
    #[pyo3(get)]
    pub code_context: Option<String>,
    #[pyo3(get)]
    pub content_type: Option<String>,
}

impl From<Symbol> for PySymbol {
    fn from(symbol: Symbol) -> Self {
        PySymbol {
            id: symbol.id,
            name: symbol.name,
            kind: format!("{:?}", symbol.kind), // Convert enum to string
            language: symbol.language,
            file_path: symbol.file_path,
            start_line: symbol.start_line,
            start_column: symbol.start_column,
            end_line: symbol.end_line,
            end_column: symbol.end_column,
            start_byte: symbol.start_byte,
            end_byte: symbol.end_byte,
            signature: symbol.signature,
            doc_comment: symbol.doc_comment,
            visibility: symbol.visibility.map(|v| format!("{:?}", v)),
            parent_id: symbol.parent_id,
            code_context: symbol.code_context,
            content_type: symbol.content_type,
        }
    }
}

#[pymethods]
impl PySymbol {
    fn __repr__(&self) -> String {
        format!(
            "Symbol(name='{}', kind='{}', {}:{}-{}:{})",
            self.name, self.kind, self.start_line, self.start_column,
            self.end_line, self.end_column
        )
    }
}
```

**File: `src/bindings/identifier.rs`** (similar pattern)
```rust
use pyo3::prelude::*;
use crate::extractors::base::types::Identifier;

#[pyclass(name = "Identifier")]
#[derive(Clone, Debug)]
pub struct PyIdentifier {
    #[pyo3(get)]
    pub id: String,
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub kind: String,
    #[pyo3(get)]
    pub language: String,
    #[pyo3(get)]
    pub file_path: String,
    #[pyo3(get)]
    pub start_line: u32,
    #[pyo3(get)]
    pub end_line: u32,
    #[pyo3(get)]
    pub start_column: u32,
    #[pyo3(get)]
    pub end_column: u32,
    #[pyo3(get)]
    pub start_byte: u32,
    #[pyo3(get)]
    pub end_byte: u32,
    #[pyo3(get)]
    pub containing_symbol_id: Option<String>,
    #[pyo3(get)]
    pub target_symbol_id: Option<String>,
    #[pyo3(get)]
    pub confidence: f32,
    #[pyo3(get)]
    pub code_context: Option<String>,
}

impl From<Identifier> for PyIdentifier {
    fn from(id: Identifier) -> Self {
        PyIdentifier {
            id: id.id,
            name: id.name,
            kind: format!("{:?}", id.kind),
            language: id.language,
            file_path: id.file_path,
            start_line: id.start_line,
            end_line: id.end_line,
            start_column: id.start_column,
            end_column: id.end_column,
            start_byte: id.start_byte,
            end_byte: id.end_byte,
            containing_symbol_id: id.containing_symbol_id,
            target_symbol_id: id.target_symbol_id,
            confidence: id.confidence,
            code_context: id.code_context,
        }
    }
}

#[pymethods]
impl PyIdentifier {
    fn __repr__(&self) -> String {
        format!(
            "Identifier(name='{}', kind='{}', line={})",
            self.name, self.kind, self.start_line
        )
    }
}
```

**File: `src/bindings/relationship.rs`** (similar pattern)
```rust
use pyo3::prelude::*;
use crate::extractors::base::types::Relationship;

#[pyclass(name = "Relationship")]
#[derive(Clone, Debug)]
pub struct PyRelationship {
    #[pyo3(get)]
    pub id: String,
    #[pyo3(get)]
    pub from_symbol_id: String,
    #[pyo3(get)]
    pub to_symbol_id: String,
    #[pyo3(get)]
    pub kind: String,
    #[pyo3(get)]
    pub file_path: String,
    #[pyo3(get)]
    pub line_number: u32,
    #[pyo3(get)]
    pub confidence: f32,
}

impl From<Relationship> for PyRelationship {
    fn from(rel: Relationship) -> Self {
        PyRelationship {
            id: rel.id,
            from_symbol_id: rel.from_symbol_id,
            to_symbol_id: rel.to_symbol_id,
            kind: format!("{:?}", rel.kind),
            file_path: rel.file_path,
            line_number: rel.line_number,
            confidence: rel.confidence,
        }
    }
}

#[pymethods]
impl PyRelationship {
    fn __repr__(&self) -> String {
        format!(
            "Relationship(kind='{}', from='{}', to='{}')",
            self.kind, self.from_symbol_id, self.to_symbol_id
        )
    }
}
```

**File: `src/bindings/extraction_results.rs`**
```rust
use pyo3::prelude::*;
use crate::extractors::base::types::ExtractionResults;
use super::{PySymbol, PyIdentifier, PyRelationship};

#[pyclass(name = "ExtractionResults")]
#[derive(Clone, Debug)]
pub struct PyExtractionResults {
    #[pyo3(get)]
    pub symbols: Vec<PySymbol>,
    #[pyo3(get)]
    pub relationships: Vec<PyRelationship>,
    #[pyo3(get)]
    pub identifiers: Vec<PyIdentifier>,
}

impl From<ExtractionResults> for PyExtractionResults {
    fn from(results: ExtractionResults) -> Self {
        PyExtractionResults {
            symbols: results.symbols.into_iter().map(PySymbol::from).collect(),
            relationships: results.relationships.into_iter().map(PyRelationship::from).collect(),
            identifiers: results.identifiers.into_iter().map(PyIdentifier::from).collect(),
        }
    }
}

#[pymethods]
impl PyExtractionResults {
    fn __repr__(&self) -> String {
        format!(
            "ExtractionResults(symbols={}, relationships={}, identifiers={})",
            self.symbols.len(),
            self.relationships.len(),
            self.identifiers.len()
        )
    }
}
```

### 1.6 Copy Julie's Extractors

```bash
# From Julie repository root
cp -r src/extractors miller/src/
cp src/language.rs miller/src/
```

**Important**: After copying, you may need to adjust module paths and remove Julie-specific dependencies (e.g., `crate::database::*`). The extractors should be pure parsing logic with no database calls.

### 1.7 Build and Test

```bash
# Create Python virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install Maturin
pip install maturin

# Build and install the Rust extension
maturin develop --release

# Test in Python
python -c "
import miller_core
print(miller_core.supported_languages())
code = 'def hello(): pass'
result = miller_core.extract_file(code, 'python')
print(result)
print(result.symbols[0])
"
```

---

## 5. Phase 2: Python Storage Layer (SQLite + LanceDB)

**Goal**: Replicate Julie's database schema and add vector storage.

### 2.1 Database Schema (SQLite)

Copy Julie's schema from `src/database/schema.rs` into Python migrations.

**File: `python/miller/storage.py`**

```python
import sqlite3
import lancedb
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import json

@dataclass
class StoredSymbol:
    """Matches Julie's Symbol struct."""
    id: str
    name: str
    kind: str
    language: str
    file_path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    start_byte: int
    end_byte: int
    signature: Optional[str] = None
    doc_comment: Optional[str] = None
    visibility: Optional[str] = None
    parent_id: Optional[str] = None
    code_context: Optional[str] = None
    content_type: Optional[str] = None

class StorageManager:
    """Hybrid storage: SQLite for relational data, LanceDB for vectors."""

    def __init__(self, db_path: str = ".miller/codebase.db", lance_path: str = ".miller/lance"):
        self.db_path = Path(db_path)
        self.lance_path = Path(lance_path)

        # Ensure directories exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lance_path.mkdir(parents=True, exist_ok=True)

        # Initialize databases
        self.sql_conn = sqlite3.connect(str(self.db_path))
        self.sql_conn.row_factory = sqlite3.Row  # Dict-like access
        self._init_sqlite()

        self.lance_db = lancedb.connect(str(self.lance_path))
        self._init_lancedb()

    def _init_sqlite(self):
        """Create tables matching Julie's schema."""
        cursor = self.sql_conn.cursor()

        # Enable foreign keys (critical for CASCADE deletes)
        cursor.execute("PRAGMA foreign_keys = ON")

        # Files table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                language TEXT NOT NULL,
                hash TEXT NOT NULL,
                size INTEGER NOT NULL,
                last_modified INTEGER NOT NULL,
                last_indexed INTEGER DEFAULT 0,
                symbol_count INTEGER DEFAULT 0,
                content TEXT
            )
        """)

        # Files FTS5 table (for full-text search)
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                path,
                content,
                tokenize = 'unicode61 separators ''_::->''',
                prefix='2 3 4 5',
                content='files',
                content_rowid='rowid'
            )
        """)

        # Symbols table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS symbols (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                language TEXT NOT NULL,
                file_path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
                signature TEXT,
                start_line INTEGER,
                start_col INTEGER,
                end_line INTEGER,
                end_col INTEGER,
                start_byte INTEGER,
                end_byte INTEGER,
                doc_comment TEXT,
                visibility TEXT,
                parent_id TEXT REFERENCES symbols(id),
                metadata TEXT,
                code_context TEXT,
                content_type TEXT,
                semantic_group TEXT
            )
        """)

        # Identifiers table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS identifiers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                language TEXT NOT NULL,
                file_path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
                start_line INTEGER,
                end_line INTEGER,
                start_col INTEGER,
                end_col INTEGER,
                start_byte INTEGER,
                end_byte INTEGER,
                containing_symbol_id TEXT REFERENCES symbols(id),
                target_symbol_id TEXT REFERENCES symbols(id),
                confidence REAL,
                code_context TEXT
            )
        """)

        # Relationships table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id TEXT PRIMARY KEY,
                from_symbol_id TEXT NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
                to_symbol_id TEXT NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                file_path TEXT NOT NULL,
                line_number INTEGER,
                confidence REAL DEFAULT 1.0,
                metadata TEXT
            )
        """)

        # Embeddings tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                symbol_id TEXT PRIMARY KEY REFERENCES symbols(id) ON DELETE CASCADE,
                vector_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                embedding_hash TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embedding_vectors (
                id TEXT PRIMARY KEY,
                vector BLOB NOT NULL,
                dimensions INTEGER NOT NULL,
                model_name TEXT NOT NULL
            )
        """)

        # Indexes (critical for performance)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbols_file_path ON symbols(file_path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_identifiers_name ON identifiers(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_identifiers_containing ON identifiers(containing_symbol_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_from ON relationships(from_symbol_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_to ON relationships(to_symbol_id)")

        self.sql_conn.commit()

    def _init_lancedb(self):
        """Initialize LanceDB table for semantic search."""
        try:
            self.lance_table = self.lance_db.open_table("code_vectors")
        except FileNotFoundError:
            # Create table with schema
            schema = pd.DataFrame({
                "symbol_id": pd.Series([], dtype="str"),
                "name": pd.Series([], dtype="str"),
                "kind": pd.Series([], dtype="str"),
                "file_path": pd.Series([], dtype="str"),
                "content": pd.Series([], dtype="str"),
                "vector": pd.Series([], dtype=object),  # Will contain lists of floats
            })
            self.lance_table = self.lance_db.create_table("code_vectors", schema)

    def add_symbols_batch(self, symbols: List[Any], file_path: str):
        """
        Add a batch of symbols to SQLite.

        Args:
            symbols: List of PySymbol objects from miller_core
            file_path: Source file path
        """
        cursor = self.sql_conn.cursor()
        for sym in symbols:
            cursor.execute("""
                INSERT OR REPLACE INTO symbols (
                    id, name, kind, language, file_path,
                    signature, start_line, start_col, end_line, end_col,
                    start_byte, end_byte, doc_comment, visibility,
                    parent_id, code_context, content_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sym.id, sym.name, sym.kind, sym.language, sym.file_path,
                sym.signature, sym.start_line, sym.start_column, sym.end_line, sym.end_column,
                sym.start_byte, sym.end_byte, sym.doc_comment, sym.visibility,
                sym.parent_id, sym.code_context, sym.content_type
            ))
        self.sql_conn.commit()

    def add_embeddings_batch(self, embeddings: List[Dict[str, Any]]):
        """
        Add embeddings to both SQLite and LanceDB.

        Args:
            embeddings: List of dicts with keys: symbol_id, vector, name, kind, file_path, content
        """
        cursor = self.sql_conn.cursor()

        lance_data = []
        for item in embeddings:
            # Store in SQLite (just metadata)
            vector_id = f"vec_{item['symbol_id']}"
            cursor.execute("""
                INSERT OR REPLACE INTO embeddings (symbol_id, vector_id, model_name)
                VALUES (?, ?, ?)
            """, (item['symbol_id'], vector_id, item.get('model_name', 'default')))

            # Prepare for LanceDB (vectors + metadata)
            lance_data.append({
                "symbol_id": item['symbol_id'],
                "name": item['name'],
                "kind": item['kind'],
                "file_path": item['file_path'],
                "content": item['content'],
                "vector": item['vector'],  # List of floats
            })

        self.sql_conn.commit()

        # Bulk add to LanceDB
        if lance_data:
            df = pd.DataFrame(lance_data)
            self.lance_table.add(df)

    def semantic_search(self, query_vector: List[float], limit: int = 10) -> List[Dict]:
        """Perform vector similarity search."""
        results = self.lance_table.search(query_vector).limit(limit).to_pandas()
        return results.to_dict('records')

    def text_search(self, query: str, limit: int = 50) -> List[Dict]:
        """FTS5 full-text search."""
        cursor = self.sql_conn.cursor()
        cursor.execute("""
            SELECT files.path, files.content, rank
            FROM files_fts
            JOIN files ON files.rowid = files_fts.rowid
            WHERE files_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))

        return [dict(row) for row in cursor.fetchall()]

    def get_symbol_by_id(self, symbol_id: str) -> Optional[Dict]:
        """Retrieve a single symbol by ID."""
        cursor = self.sql_conn.cursor()
        cursor.execute("SELECT * FROM symbols WHERE id = ?", (symbol_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def close(self):
        """Close database connections."""
        self.sql_conn.close()
```

### 2.2 Testing Storage

**File: `python/tests/test_storage.py`**

```python
import unittest
from miller.storage import StorageManager
import miller_core

class TestStorage(unittest.TestCase):
    def setUp(self):
        self.storage = StorageManager(
            db_path=":memory:",  # In-memory for testing
            lance_path="./test_lance"
        )

    def test_extract_and_store(self):
        code = """
def hello(name: str) -> str:
    '''Say hello to someone.'''
    return f"Hello, {name}!"

class Greeter:
    def greet(self, name: str):
        return hello(name)
"""
        # Extract with Rust
        results = miller_core.extract_file(code, "python", "test.py")

        # Store in SQLite
        self.storage.add_symbols_batch(results.symbols, "test.py")

        # Verify
        sym = self.storage.get_symbol_by_id(results.symbols[0].id)
        self.assertIsNotNone(sym)
        self.assertEqual(sym['name'], 'hello')

    def tearDown(self):
        self.storage.close()

if __name__ == "__main__":
    unittest.main()
```

---

## 6. Phase 3: Embeddings Layer (Python ML)

**Goal**: Implement semantic search with better GPU support than Julie.

### 6.1 Embedding Manager

**File: `python/miller/embeddings.py`**

```python
from sentence_transformers import SentenceTransformer
import numpy as np
from typing import List
import torch

class EmbeddingManager:
    """
    Handles text → vector conversion using sentence-transformers.

    This replaces Julie's ONNX Runtime approach with a simpler, more reliable
    solution that still supports GPU acceleration.
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", device: str = "auto"):
        """
        Initialize embedding model.

        Args:
            model_name: HuggingFace model identifier
            device: "cuda", "cpu", or "auto" (auto-detect GPU)
        """
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        print(f"Loading embedding model '{model_name}' on {device}...")
        self.model = SentenceTransformer(model_name, device=device)
        self.model_name = model_name
        self.device = device
        self.dimensions = self.model.get_sentence_embedding_dimension()

        print(f"✓ Model loaded ({self.dimensions}D vectors)")

    def embed_symbol(self, symbol) -> np.ndarray:
        """
        Generate embedding for a single symbol.

        Combines: name + kind + signature + doc_comment
        (This matches Julie's approach)
        """
        parts = [symbol.name, symbol.kind]

        if symbol.signature:
            parts.append(symbol.signature)
        if symbol.doc_comment:
            parts.append(symbol.doc_comment)

        text = " ".join(parts)
        return self.model.encode(text, normalize_embeddings=True)

    def embed_batch(self, symbols: List) -> np.ndarray:
        """
        Generate embeddings for multiple symbols (batched for efficiency).

        Returns:
            Array of shape (len(symbols), dimensions)
        """
        texts = []
        for sym in symbols:
            parts = [sym.name, sym.kind]
            if sym.signature:
                parts.append(sym.signature)
            if sym.doc_comment:
                parts.append(sym.doc_comment)
            texts.append(" ".join(parts))

        return self.model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=32,  # Tune based on GPU VRAM
            show_progress_bar=True
        )

    def embed_query(self, query: str) -> np.ndarray:
        """Generate embedding for a search query."""
        return self.model.encode(query, normalize_embeddings=True)
```

### 6.2 Why This is Better Than Julie's Approach

1. **Simpler GPU setup**: `pip install sentence-transformers` handles CUDA automatically
2. **No ONNX conversion needed**: Works directly with PyTorch models
3. **Better error messages**: PyTorch stack is more mature than ONNX Runtime
4. **Automatic device selection**: Falls back to CPU gracefully
5. **Still fast**: sentence-transformers uses PyTorch's optimized kernels

---

## 7. Phase 4: FastMCP Server

**Goal**: Build the MCP server that ties everything together.

### 7.1 Main Server

**File: `python/miller/server.py`**

```python
import miller_core
from fastmcp import FastMCP, Context
from miller.storage import StorageManager
from miller.embeddings import EmbeddingManager
from pathlib import Path
from typing import List, Dict, Any
import asyncio

# Initialize core components
print("🚀 Initializing Miller...")

storage = StorageManager(
    db_path=".miller/codebase.db",
    lance_path=".miller/lance"
)

embeddings = EmbeddingManager(
    model_name="BAAI/bge-small-en-v1.5",
    device="auto"  # Use GPU if available
)

mcp = FastMCP(
    "Miller",
    title="Miller - Rust-Powered Code Intelligence",
    description=f"MCP server with Tree-sitter parsing for {len(miller_core.supported_languages())} languages"
)

print(f"✓ Supported languages: {len(miller_core.supported_languages())}")
print(f"✓ Embedding model: {embeddings.model_name} ({embeddings.dimensions}D)")
print(f"✓ Device: {embeddings.device}")

# ============================================================================
# MCP Tools
# ============================================================================

@mcp.tool()
async def index_file(ctx: Context, file_path: str) -> str:
    """
    Index a source file: parse with Tree-sitter, generate embeddings, store in DB.

    Args:
        file_path: Absolute or relative path to the source file

    Returns:
        Success message with symbol count
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"

        # Detect language
        language = miller_core.detect_language(str(path))
        if not language:
            return f"Error: Unsupported file type: {path.suffix}"

        await ctx.info(f"Indexing {path.name} ({language})...")

        # Read file
        code = path.read_text(encoding='utf-8')

        # Extract with Rust
        await ctx.info("Parsing with Tree-sitter...")
        results = miller_core.extract_file(code, language, str(path))

        if not results.symbols:
            return f"No symbols found in {path.name}"

        # Store symbols in SQLite
        await ctx.info(f"Storing {len(results.symbols)} symbols...")
        storage.add_symbols_batch(results.symbols, str(path))

        # Generate embeddings
        await ctx.info("Generating embeddings...")
        vectors = embeddings.embed_batch(results.symbols)

        # Store embeddings
        embedding_data = [
            {
                "symbol_id": sym.id,
                "vector": vec.tolist(),
                "name": sym.name,
                "kind": sym.kind,
                "file_path": sym.file_path,
                "content": f"{sym.name} {sym.kind} {sym.signature or ''}",
                "model_name": embeddings.model_name,
            }
            for sym, vec in zip(results.symbols, vectors)
        ]
        storage.add_embeddings_batch(embedding_data)

        await ctx.info(f"✓ Indexed {len(results.symbols)} symbols from {path.name}")
        return f"Success: {len(results.symbols)} symbols, {len(results.relationships)} relationships, {len(results.identifiers)} identifiers"

    except Exception as e:
        await ctx.error(f"Failed to index {file_path}: {e}")
        return f"Error: {e}"


@mcp.tool()
async def fast_search(
    ctx: Context,
    query: str,
    search_method: str = "text",
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Search codebase using text or semantic methods.

    Args:
        query: Search query
        search_method: "text" (FTS5) or "semantic" (vector similarity)
        limit: Maximum results to return

    Returns:
        List of matching symbols/files
    """
    await ctx.info(f"Searching for: '{query}' (method: {search_method})")

    if search_method == "semantic":
        # Vector similarity search
        query_vector = embeddings.embed_query(query)
        results = storage.semantic_search(query_vector.tolist(), limit=limit)
        return results
    else:
        # FTS5 text search
        results = storage.text_search(query, limit=limit)
        return results


@mcp.tool()
async def fast_goto(ctx: Context, symbol: str) -> Dict[str, Any]:
    """
    Find definition of a symbol (go-to-definition).

    Args:
        symbol: Symbol name to find

    Returns:
        Symbol definition with location
    """
    await ctx.info(f"Looking up symbol: {symbol}")

    cursor = storage.sql_conn.cursor()
    cursor.execute("""
        SELECT * FROM symbols
        WHERE name = ?
        LIMIT 1
    """, (symbol,))

    row = cursor.fetchone()
    if row:
        return dict(row)
    else:
        return {"error": f"Symbol '{symbol}' not found"}


@mcp.tool()
async def get_symbols(ctx: Context, file_path: str, max_depth: int = 1) -> List[Dict]:
    """
    Get symbol outline for a file (similar to LSP document symbols).

    Args:
        file_path: File to get symbols from
        max_depth: Nesting depth (0=top-level only, 1=include methods, etc.)

    Returns:
        List of symbols in the file
    """
    await ctx.info(f"Getting symbols from {file_path}")

    cursor = storage.sql_conn.cursor()
    cursor.execute("""
        SELECT * FROM symbols
        WHERE file_path = ?
        ORDER BY start_line ASC
    """, (file_path,))

    symbols = [dict(row) for row in cursor.fetchall()]

    # Filter by depth (parent_id nesting)
    if max_depth == 0:
        symbols = [s for s in symbols if s['parent_id'] is None]

    return symbols


@mcp.tool()
async def supported_languages_tool(ctx: Context) -> List[str]:
    """Get list of all supported programming languages."""
    langs = miller_core.supported_languages()
    await ctx.info(f"Miller supports {len(langs)} languages")
    return sorted(langs)


# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("Miller MCP Server Ready")
    print("="*60 + "\n")
    mcp.run()
```

---

## 8. Development Workflow

### 8.1 First-Time Setup

```bash
# Navigate to Miller project
cd C:\source\miller

# Create Python virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install Python dependencies
pip install maturin fastmcp sentence-transformers lancedb pandas torch

# Build Rust extension
maturin develop --release

# Verify installation
python -c "import miller_core; print(miller_core.supported_languages())"
```

### 8.2 Iterative Development

**When you change Rust code** (`src/extractors/`, `src/bindings/`, etc.):
```bash
maturin develop --release
```

**When you change Python code** (`python/miller/`):
```bash
# Just restart the server - no rebuild needed
python python/miller/server.py
```

### 8.3 Running the Server

```bash
# Development mode (stdio transport for Claude Desktop)
python python/miller/server.py

# Or use FastMCP's dev server
fastmcp dev python/miller/server.py
```

---

## 9. Migration Timeline

### Week 1-2: Foundation
- ✅ Set up project structure (Cargo.toml, pyproject.toml)
- ✅ Copy Julie's extractors to `src/`
- ✅ Create PyO3 bindings (`src/bindings/`)
- ✅ Implement `extract_file()` function
- ✅ Test with 3-5 languages (Python, JavaScript, Rust)

**Milestone**: Can call `miller_core.extract_file()` from Python

### Week 3-4: Storage Layer
- ✅ Implement SQLite schema (replicate Julie's)
- ✅ Create StorageManager class
- ✅ Add FTS5 full-text search
- ✅ Test symbol insertion/retrieval
- ✅ Port relationship and identifier storage

**Milestone**: Can index files and search with FTS5

### Week 5-6: Embeddings (Optional for MVP)
- ✅ Set up sentence-transformers
- ✅ Implement EmbeddingManager
- ✅ Test GPU acceleration
- ✅ Integrate with LanceDB
- ✅ Add semantic search

**Milestone**: Semantic search working

### Week 7-8: MCP Server
- ✅ Implement FastMCP server
- ✅ Port core tools (fast_search, fast_goto, get_symbols)
- ✅ Add workspace management
- ✅ Integration testing
- ✅ Performance optimization

**Milestone**: Full MCP server running in Claude Desktop

---

## 10. Success Criteria

1. **Functional parity with Julie** for core features:
   - ✅ Extract symbols from all 31 languages
   - ✅ FTS5 text search
   - ✅ Semantic vector search
   - ✅ Go-to-definition
   - ✅ File outline

2. **GPU acceleration working** on Linux:
   - ✅ `sentence-transformers` uses CUDA
   - ✅ No manual ONNX setup required
   - ✅ Graceful CPU fallback

3. **Performance acceptable**:
   - Parsing speed within 2x of Julie (Rust overhead acceptable)
   - Embedding generation: >100 symbols/second on GPU
   - Search latency: <100ms for typical queries

4. **Developer experience**:
   - Fast iteration (Python changes = instant reload)
   - Clear error messages
   - Easy setup (`pip install` + `maturin develop`)

---

## 11. Key Technologies

### Rust Extension
- **PyO3** 0.22 - Rust ↔ Python bindings
- **Maturin** 1.7 - Build system for Rust extensions
- **tree-sitter** 0.25 - Parser runtime
- **31 tree-sitter grammars** - Language support

### Python Server
- **FastMCP** - MCP server framework
- **sentence-transformers** - Embedding models (replaces ONNX)
- **torch** - GPU acceleration for embeddings
- **SQLite** (stdlib) - Relational storage
- **LanceDB** - Vector database
- **pandas** - Data manipulation

### Why This Stack?

| Component | Choice | Reason |
|-----------|--------|--------|
| Parsing | **Rust** (PyO3) | Keep Julie's battle-tested extractors |
| Embeddings | **sentence-transformers** | Easier GPU setup than ONNX Runtime |
| Vector DB | **LanceDB** | Embedded, no server required |
| MCP | **FastMCP** | Official Python SDK, easiest integration |
| Search | **SQLite FTS5** | Built-in, zero-config full-text search |

---

## 12. Risk Mitigation

### Risk: Tree-sitter Python bindings immature
**Mitigation**: Use PyO3 extension - we control the Rust tree-sitter directly

### Risk: Python slower than Rust
**Mitigation**: Keep parsing in Rust. Python only orchestrates.

### Risk: Semantic search complexity
**Mitigation**: Make it optional. Start with FTS5 only (covers 80% of use cases).

### Risk: Breaking changes in Julie's extractors
**Mitigation**: Copy extractors at a stable commit. Pin versions.

---

## 13. Post-MVP Enhancements

Once core functionality works:

1. **Incremental indexing**: File watcher + delta updates
2. **Multi-workspace support**: Index multiple projects
3. **Better type inference**: Port Julie's type resolution logic
4. **Call graph traversal**: Port `trace_call_path` tool
5. **Refactoring tools**: Port Julie's `rename_symbol`, `edit_symbol`
6. **Memory/checkpoint system**: Port Julie's development memory tools
7. **Performance tuning**: Profile and optimize hot paths

---

## 14. Getting Help

- **PyO3 docs**: https://pyo3.rs/
- **Maturin docs**: https://www.maturin.rs/
- **FastMCP docs**: https://gofastmcp.com/
- **sentence-transformers**: https://www.sbert.net/
- **LanceDB docs**: https://lancedb.github.io/lancedb/

---

## 15. Appendix: Julie's Cargo Dependencies

For reference, here are Julie's critical dependencies to copy:

```toml
[dependencies]
# Tree-sitter (all 31 languages - see section 1.2)
tree-sitter = "0.25"
# ... (31 language grammars)

# Core utilities
rayon = "1.10"
regex = "1.11"
anyhow = "1.0"
thiserror = "2.0"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
md5 = "0.7"
blake3 = "1.5"
once_cell = "1.20"
glob = "0.3"

# PyO3 (NEW for Miller)
pyo3 = { version = "0.22", features = ["extension-module", "anyhow"] }
```

---

**End of Plan**
