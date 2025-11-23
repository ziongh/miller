Yes, here is a complete **Master Plan & Implementation Guide** in Markdown format. You can save this as `README.md` or `IMPLEMENTATION_PLAN.md` in your project root to keep the entire architecture and code references in one place.

````markdown
# Master Plan: Rust-Core MCP Server with Python Orchestration

**Architecture:** "The Rust Sandwich"
**Goal:** High-performance Tree-sitter parsing (Rust) + Universal AI/ML compatibility (Python) + Hybrid Search (LanceDB + SQLite).

---

## 1. Directory Structure

```text
my-mcp-server/
├── Cargo.toml              # Rust config (Core Logic)
├── pyproject.toml          # Python build config (Maturin)
├── .python-version         # Pin to 3.12 (Safety)
├── src/
│   ├── lib.rs              # PyO3 Bridge (The Entry Point)
│   └── parser.rs           # Existing Tree-sitter extraction logic
├── python/
│   ├── server.py           # FastMCP Server (The App)
│   └── storage.py          # Hybrid DB Logic (The Brain)
└── .venv/                  # Managed by uv
````

-----

## 2\. Infrastructure & Setup

**Tooling:** Use `uv` for robust dependency management.
**Python Version:** 3.12 (Avoid 3.13 for now due to ONNX/PyO3 stability).

```bash
# Initial Setup
uv init
echo "3.12" > .python-version
uv add fastmcp maturin onnxruntime-gpu lancedb pandas torch transformers

# Development Loop
# 1. Compile Rust changes
uv run maturin develop
# 2. Run Python Server
uv run fastmcp dev python/server.py
```

-----

## 3\. The Rust Core (`Cargo.toml` & `lib.rs`)

### `Cargo.toml`

Configured to build a Dynamic Library (`cdylib`) that Python can import.

```toml
[package]
name = "my_mcp_core"
version = "0.1.0"
edition = "2021"

[lib]
name = "my_mcp_core"
crate-type = ["cdylib"] # Critical for Python import

[dependencies]
pyo3 = { version = "0.20", features = ["extension-module"] }
tree-sitter = "0.20.10"
# Add your 31 language parsers here
tree-sitter-c-sharp = "0.20.0"
tree-sitter-python = "0.20.0"
serde = { version = "1.0", features = ["derive"] }
```

### `pyproject.toml`

Tells `maturin` how to build the wheel.

```toml
[build-system]
requires = ["maturin>=1.0,<2.0"]
build-backend = "maturin"

[project]
name = "my_mcp_core"
requires-python = ">=3.12"
classifiers = [
    "Programming Language :: Rust",
    "Programming Language :: Python :: Implementation :: CPython",
]
```

### `src/lib.rs` (The Bridge)

Wraps your existing logic in PyO3 types.

```rust
use pyo3::prelude::*;

// Define the Python-facing object
#[pyclass]
#[derive(Clone, Debug)]
struct CodeSymbol {
    #[pyo3(get, set)]
    name: String,
    #[pyo3(get, set)]
    kind: String,
    #[pyo3(get, set)]
    start_line: usize,
    #[pyo3(get, set)]
    end_line: usize,
    #[pyo3(get, set)]
    docstring: Option<String>, // Critical for RAG
}

#[pymethods]
impl CodeSymbol {
    fn __repr__(&self) -> String {
        format!("<Symbol '{}' ({})>", self.name, self.kind)
    }
}

#[pyfunction]
fn extract_symbols(code: String, lang: String) -> PyResult<Vec<CodeSymbol>> {
    // CALL YOUR EXISTING LOGIC HERE
    // let rust_symbols = crate::parser::parse(&code, &lang);
    
    // Convert to PyClass for return
    // This is just placeholder logic
    let symbols = vec![CodeSymbol {
        name: "example_func".to_string(),
        kind: "function".to_string(),
        start_line: 10,
        end_line: 20,
        docstring: Some("Handles auth validation".to_string()),
    }];
    Ok(symbols)
}

#[pymodule]
fn my_mcp_core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(extract_symbols, m)?)?;
    m.add_class::<CodeSymbol>()?;
    Ok(())
}
```

-----

## 4\. The Hybrid Storage (`python/storage.py`)

Handles "Dual-Write" consistency and Hybrid Search.

```python
import sqlite3
import lancedb
import pandas as pd
from typing import List, Dict, Any

class StorageManager:
    def __init__(self, db_path="codebase.db", lance_path="./lance_index"):
        self.sql_conn = sqlite3.connect(db_path)
        self.lance_db = lancedb.connect(lance_path)
        
        self._init_sqlite()
        self._init_lancedb()

    def _init_sqlite(self):
        with self.sql_conn:
            self.sql_conn.execute("""
                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    kind TEXT,
                    file_path TEXT,
                    definition_body TEXT, -- Store full code here for retrieval
                    parent_id INTEGER
                )
            """)
            # Add 'references' table for Graph RAG here

    def _init_lancedb(self):
        # Open table or create if missing
        try:
            self.lance_table = self.lance_db.open_table("code_chunks")
        except FileNotFoundError:
            # Schema inference usually works, but explicit is safer
            self.lance_table = self.lance_db.create_table("code_chunks", data=[
                {"vector": [0.0]*768, "content": "init", "symbol_id": 0, "name": "init"}
            ])
            # CRITICAL: Create FTS index for Hybrid Search
            self.lance_table.create_fts_index("content", replace=True)

    def add_batch(self, symbols_data: List[Dict[str, Any]]):
        cursor = self.sql_conn.cursor()
        try:
            # 1. Write to SQLite (The Spine)
            for item in symbols_data:
                sym = item["symbol"]
                cursor.execute(
                    "INSERT INTO symbols (name, kind, definition_body) VALUES (?, ?, ?)",
                    (sym.name, sym.kind, item["code_body"])
                )
                item["symbol_id"] = cursor.lastrowid # Capture ID
            
            # 2. Write to LanceDB (The Brain)
            lance_payload = [{
                "symbol_id": x["symbol_id"],
                "content": x["representation"], # The "Signature + Docstring" combo
                "vector": x["vector"],
                "name": x["symbol"].name
            } for x in symbols_data]
            
            self.lance_table.add(lance_payload)
            
            # 3. Commit only if both succeeded
            self.sql_conn.commit()
            
        except Exception as e:
            self.sql_conn.rollback() # Transaction Safety
            raise e

    def hybrid_search(self, query_vector, query_text):
        # LanceDB Hybrid Search (Vector + FTS)
        return self.lance_table.search(query_vector) \
            .where(f"content LIKE '%{query_text}%'") \
            .limit(20) \
            .to_pandas()
```

-----

## 5\. The Application Server (`python/server.py`)

Orchestrates Rust parsing and PyTorch embeddings.

```python
import my_mcp_core  # <--- The Rust Library
from fastmcp import FastMCP, Context
from storage import StorageManager
import torch
from transformers import AutoTokenizer, AutoModel
import numpy as np

# 1. Initialize Components
mcp = FastMCP("RustPoweredMCP")
storage = StorageManager()

print("Loading PyTorch (CodeBERT)...")
device = "cuda" if torch.cuda.is_available() else "cpu"
tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")
model = AutoModel.from_pretrained("microsoft/codebert-base").to(device)

def get_embedding(text: str):
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512).to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    # Use CLS token for embedding
    return outputs.last_hidden_state[:, 0, :].cpu().numpy()[0]

@mcp.tool()
async def index_file(ctx: Context, file_path: str):
    """Parses file with Rust, embeds with PyTorch, saves to Hybrid DB."""
    with open(file_path, 'r') as f:
        code = f.read()

    # A. Rust Parsing
    ctx.info(f"Parsing {file_path}...")
    symbols = my_mcp_core.extract_symbols(code, "python") # Add lang detection

    batch = []
    for sym in symbols:
        # B. Smart Representation (Sig + Docs)
        rep_string = f"{sym.kind} {sym.name}\n{sym.docstring or ''}"
        
        # C. PyTorch Embedding
        vec = get_embedding(rep_string)
        
        batch.append({
            "symbol": sym,
            "representation": rep_string,
            "code_body": "...", # Extract actual body from 'code' using lines
            "vector": vec
        })

    # D. Save
    storage.add_batch(batch)
    return f"Indexed {len(symbols)} symbols."

@mcp.tool()
async def search(ctx: Context, query: str):
    """Graph-Expanded RAG Search"""
    ctx.info(f"Searching: {query}")
    
    # 1. Hybrid Retrieval
    vec = get_embedding(query)
    results = storage.hybrid_search(vec, query)
    
    # 2. Graph Expansion (The "Pro" Move)
    # Iterate results, fetch full definitions AND dependencies from SQLite
    # (See "Graph Expansion" logic in Phase 3 of conversation)
    
    return results.to_dict('records') # Return enriched context
```

```
```
