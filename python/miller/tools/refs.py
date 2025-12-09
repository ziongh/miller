"""
fast_refs - Find all symbol references.

Provides refactoring safety by showing where symbols are used.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import re
from miller.storage import StorageManager


def find_references(
    storage: StorageManager,
    symbol_name: str,
    kind_filter: Optional[List[str]] = None,
    include_context: bool = False,
    context_file: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Find all references to a symbol.

    Args:
        storage: StorageManager instance
        symbol_name: Name of the symbol to find references for (supports qualified names like "Class.method")
        kind_filter: Optional list of relationship kinds to filter by (e.g., ["Call", "Import"])
        include_context: Whether to include code context snippets
        context_file: Optional file path to disambiguate symbols (only find symbols in this file)
        limit: Optional maximum number of references to return (for pagination)

    Returns:
        Dictionary with structure:
        {
            "symbol": str,
            "total_references": int,
            "files": [
                {
                    "path": str,
                    "references_count": int,
                    "references": [
                        {
                            "line": int,
                            "kind": str,
                            "context": str (optional),
                            "access": str (optional) # "read" | "write" | "unknown"
                        }
                    ]
                }
            ]
        }
    """
    cursor = storage.conn.cursor()
    
    # Store the leaf name for heuristic analysis later (e.g., "Prop" from "Class.Prop")
    leaf_symbol_name = symbol_name
    
    # 1. Resolve Symbol IDs (with Recursive CTE for qualified names)
    if "." in symbol_name:
        parts = symbol_name.rsplit(".", 1)
        ancestor_path = parts[0]
        leaf_symbol_name = parts[1]
        
        ancestor_name = ancestor_path.rsplit(".", 1)[-1] if "." in ancestor_path else ancestor_path

        query = """
            WITH RECURSIVE Ancestors(id, parent_id, name, origin_id) AS (
                SELECT s.id, s.parent_id, s.name, s.id
                FROM symbols s
                WHERE s.name = ?
                CONTEXT_FILTER_PLACEHOLDER

                UNION ALL

                SELECT p.id, p.parent_id, p.name, a.origin_id
                FROM symbols p
                JOIN Ancestors a ON p.id = a.parent_id
            )
            SELECT DISTINCT origin_id
            FROM Ancestors
            WHERE name = ?
        """
        
        params = [leaf_symbol_name]
        
        if context_file:
            query = query.replace("CONTEXT_FILTER_PLACEHOLDER", "AND s.file_path = ?")
            params.append(context_file)
        else:
            query = query.replace("CONTEXT_FILTER_PLACEHOLDER", "")
            
        params.append(ancestor_name)
        
        cursor.execute(query, params)
    else:
        query = "SELECT id FROM symbols WHERE name = ?"
        params = [symbol_name]

        if context_file:
            query += " AND file_path = ?"
            params.append(context_file)

        cursor.execute(query, params)

    symbol_ids = [row[0] for row in cursor.fetchall()]

    if not symbol_ids:
        return {
            "symbol": symbol_name,
            "total_references": 0,
            "files": [],
        }

    # 2. Query Relationships
    placeholders = ",".join("?" * len(symbol_ids))
    query = f"""
        SELECT
            r.from_symbol_id,
            r.to_symbol_id,
            r.kind,
            r.file_path,
            r.line_number,
            s_from.name as from_name
        FROM relationships r
        JOIN symbols s_from ON r.from_symbol_id = s_from.id
        WHERE r.to_symbol_id IN ({placeholders})
    """

    params = list(symbol_ids)

    if kind_filter:
        kind_placeholders = ",".join("?" * len(kind_filter))
        query += f" AND r.kind IN ({kind_placeholders})"
        params.extend(kind_filter)

    cursor.execute(query, params)
    relationship_rows = cursor.fetchall()

    # 3. Query Identifiers (Usages not in relationships)
    ident_query = """
        SELECT
            i.id,
            i.name,
            i.kind,
            i.file_path,
            i.start_line,
            i.containing_symbol_id
        FROM identifiers i
        WHERE i.name = ?
    """
    search_name = symbol_name.rsplit(".", 1)[-1] if "." in symbol_name else symbol_name
    ident_params: List[Any] = [search_name]

    if kind_filter:
        kind_placeholders = ",".join("?" * len(kind_filter))
        ident_query += f" AND i.kind IN ({kind_placeholders})"
        ident_params.extend(kind_filter)

    cursor.execute(ident_query, ident_params)
    identifier_rows = cursor.fetchall()

    # 4. Group and Deduplicate
    files_dict: Dict[str, Dict[str, Any]] = {}
    seen_refs: set[tuple[str, int]] = set()

    for row in relationship_rows:
        file_path = row[3]
        line_number = row[4]
        kind = row[2]
        _process_row(files_dict, seen_refs, file_path, line_number, kind)

    for row in identifier_rows:
        file_path = row[3]
        line_number = row[4]
        kind = row[2]
        _process_row(files_dict, seen_refs, file_path, line_number, kind)

    files_list = list(files_dict.values())
    files_list.sort(key=lambda f: f["references_count"], reverse=True)

    for file_data in files_list:
        file_data["references"].sort(key=lambda r: r["line"])

    # 5. Analyze Access Type (Read/Write)
    # We always do this analysis if we can read the file, as it powers the [R]/[W] flags
    _add_context_and_analyze_access(files_list, leaf_symbol_name, include_output_context=include_context)

    # 6. Pagination
    total_references = sum(f["references_count"] for f in files_list)
    truncated = False
    if limit is not None and limit > 0:
        refs_count = 0
        limited_files = []
        for file_data in files_list:
            remaining = limit - refs_count
            if remaining <= 0:
                truncated = True
                break
            if file_data["references_count"] <= remaining:
                limited_files.append(file_data)
                refs_count += file_data["references_count"]
            else:
                truncated_file = file_data.copy()
                truncated_file["references"] = file_data["references"][:remaining]
                truncated_file["references_count"] = len(truncated_file["references"])
                limited_files.append(truncated_file)
                refs_count += truncated_file["references_count"]
                truncated = True
                break
        files_list = limited_files

    result = {
        "symbol": symbol_name,
        "total_references": total_references,
        "files": files_list,
    }

    if truncated:
        result["truncated"] = True

    return result

def _process_row(files_dict, seen_refs, file_path, line_number, kind):
    ref_key = (file_path, line_number)
    if ref_key in seen_refs:
        return
    seen_refs.add(ref_key)

    if file_path not in files_dict:
        files_dict[file_path] = {
            "path": file_path,
            "references_count": 0,
            "references": [],
        }

    files_dict[file_path]["references"].append({
        "line": line_number,
        "kind": kind,
        "access": "unknown"
    })
    files_dict[file_path]["references_count"] += 1

def _infer_access_type(line: str, symbol_name: str) -> str:
    escaped_name = re.escape(symbol_name)
    
    # Write detection
    if re.search(rf"{escaped_name}\s*=(?![=>])", line): return "write" # Assignment
    if re.search(rf"{escaped_name}\s*[-+*/%&|^<>!]=\s*", line): return "write" # Compound
    if re.search(rf"({escaped_name}\s*(\+\+|--)|(\+\+|--)\s*{escaped_name})", line): return "write" # Increment
    if re.search(rf"\b(out|ref)\s+{escaped_name}\b", line): return "write" # Ref/Out
    
    return "read"

def _add_context_and_analyze_access(
    files_list: List[Dict[str, Any]], 
    symbol_name: str,
    include_output_context: bool
) -> None:
    for file_data in files_list:
        file_path = file_data["path"]
        try:
            path = Path(file_path)
            if not path.exists():
                for ref in file_data["references"]:
                    ref["context"] = None
                continue

            with path.open("r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            for ref in file_data["references"]:
                line_idx = ref["line"] - 1
                if 0 <= line_idx < len(lines):
                    context = lines[line_idx].strip()
                    ref["access"] = _infer_access_type(context, symbol_name)
                    if include_output_context:
                        ref["context"] = context
                    else:
                        ref["context"] = None
                else:
                    ref["context"] = None
        except Exception:
            pass