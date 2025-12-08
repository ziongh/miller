"""
fast_refs - Find all symbol references.

Provides refactoring safety by showing where symbols are used.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
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
                            "context": str (optional)
                        }
                    ]
                }
            ]
        }
    """
    # Handle qualified names (e.g., "Class.method")
    cursor = storage.conn.cursor()
    if "." in symbol_name:
        # Qualified name: find methods/attributes with parent/ancestor
        # Use rsplit to handle "Namespace.Class.Method" -> ancestor="Namespace.Class", child="Method"
        parts = symbol_name.rsplit(".", 1)
        ancestor_path = parts[0]
        child_name = parts[1]
        
        # We strictly check against the immediate component provided in the query
        # e.g. "Akrual.PUDiario.Prop" -> look for Prop with ancestor PUDiario
        ancestor_name = ancestor_path.rsplit(".", 1)[-1] if "." in ancestor_path else ancestor_path

        # Recursive CTE to find child symbol that has specific ancestor
        query = """
            WITH RECURSIVE Ancestors(id, parent_id, name, origin_id) AS (
                -- Base case: symbols matching child name
                SELECT s.id, s.parent_id, s.name, s.id
                FROM symbols s
                WHERE s.name = ?
                CONTEXT_FILTER_PLACEHOLDER

                UNION ALL

                -- Recursive step: walk up the parent tree
                SELECT p.id, p.parent_id, p.name, a.origin_id
                FROM symbols p
                JOIN Ancestors a ON p.id = a.parent_id
            )
            SELECT DISTINCT origin_id
            FROM Ancestors
            WHERE name = ?
        """
        
        params = [child_name]
        
        if context_file:
            query = query.replace("CONTEXT_FILTER_PLACEHOLDER", "AND s.file_path = ?")
            params.append(context_file)
        else:
            query = query.replace("CONTEXT_FILTER_PLACEHOLDER", "")
            
        params.append(ancestor_name)
        
        cursor.execute(query, params)
    else:
        # Simple name: find all symbols with this name
        query = "SELECT id FROM symbols WHERE name = ?"
        params = [symbol_name]

        if context_file:
            query += " AND file_path = ?"
            params.append(context_file)

        cursor.execute(query, params)

    symbol_ids = [row[0] for row in cursor.fetchall()]

    # If no symbols found, return empty result
    if not symbol_ids:
        return {
            "symbol": symbol_name,
            "total_references": 0,
            "files": [],
        }

    # Build query for relationships
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

    params = symbol_ids

    # Add kind filter if specified
    if kind_filter:
        kind_placeholders = ",".join("?" * len(kind_filter))
        query += f" AND r.kind IN ({kind_placeholders})"
        params.extend(kind_filter)

    cursor.execute(query, params)
    relationship_rows = cursor.fetchall()

    # Also query identifiers table for usages (class instantiations, imports, etc.)
    # that aren't captured as explicit relationships
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
    # Note: For identifiers search, we always use the leaf name (child_name if qualified)
    # Identifiers don't track parent info directly in the name
    search_name = symbol_name.rsplit(".", 1)[-1] if "." in symbol_name else symbol_name
    ident_params: List[Any] = [search_name]

    # Apply kind filter to identifiers if specified
    if kind_filter:
        kind_placeholders = ",".join("?" * len(kind_filter))
        ident_query += f" AND i.kind IN ({kind_placeholders})"
        ident_params.extend(kind_filter)

    cursor.execute(ident_query, ident_params)
    identifier_rows = cursor.fetchall()

    # Group references by file, combining both sources
    files_dict: Dict[str, Dict[str, Any]] = {}

    # Track seen (file, line) to avoid duplicates - ignore kind for deduplication
    # because relationships table uses "calls" while identifiers uses "call"
    seen_refs: set[tuple[str, int]] = set()

    # Process relationship rows first
    for row in relationship_rows:
        file_path = row[3]
        line_number = row[4]
        kind = row[2]

        ref_key = (file_path, line_number)
        if ref_key in seen_refs:
            continue
        seen_refs.add(ref_key)

        if file_path not in files_dict:
            files_dict[file_path] = {
                "path": file_path,
                "references_count": 0,
                "references": [],
            }

        files_dict[file_path]["references"].append(
            {
                "line": line_number,
                "kind": kind,
            }
        )
        files_dict[file_path]["references_count"] += 1

    # Process identifier rows (usages not in relationships)
    for row in identifier_rows:
        file_path = row[3]
        line_number = row[4]
        kind = row[2]
        
        # Optional: Filter identifiers if we found specific symbol_ids
        # Only include identifiers that match the resolved symbols? 
        # Identifiers table doesn't link to definition symbol ID directly in all cases (target_symbol_id is optional/sparse).
        # So we keep the name-based match for robustness.

        ref_key = (file_path, line_number)
        if ref_key in seen_refs:
            continue
        seen_refs.add(ref_key)

        if file_path not in files_dict:
            files_dict[file_path] = {
                "path": file_path,
                "references_count": 0,
                "references": [],
            }

        files_dict[file_path]["references"].append(
            {
                "line": line_number,
                "kind": kind,
            }
        )
        files_dict[file_path]["references_count"] += 1

    # Convert to list and sort by reference count (most-used first)
    files_list = list(files_dict.values())
    files_list.sort(key=lambda f: f["references_count"], reverse=True)

    # Sort references within each file by line number
    for file_data in files_list:
        file_data["references"].sort(key=lambda r: r["line"])

    # Add context snippets if requested
    if include_context:
        _add_context_snippets(files_list)

    # Calculate total references BEFORE limiting
    total_references = sum(f["references_count"] for f in files_list)

    # Apply limit if specified (truncate references, not files)
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
                # Include entire file
                limited_files.append(file_data)
                refs_count += file_data["references_count"]
            else:
                # Partially include file (truncate references)
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


def _add_context_snippets(files_list: List[Dict[str, Any]]) -> None:
    """
    Add context snippets to references by reading source files.

    Reads each file once and extracts all needed lines.
    Modifies files_list in place.

    Args:
        files_list: List of file dictionaries with references
    """
    for file_data in files_list:
        file_path = file_data["path"]

        # Try to read the file
        try:
            path = Path(file_path)
            if not path.exists():
                # File doesn't exist - skip context extraction
                for ref in file_data["references"]:
                    ref["context"] = None
                continue

            # Read all lines
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            # Extract context for each reference
            for ref in file_data["references"]:
                line_num = ref["line"]
                # Convert to 0-based index
                line_idx = line_num - 1

                if 0 <= line_idx < len(lines):
                    # Get the line and strip whitespace
                    context = lines[line_idx].strip()
                    ref["context"] = context
                else:
                    # Line number out of range
                    ref["context"] = None

        except Exception:
            # File read error - skip context extraction
            for ref in file_data["references"]:
                ref["context"] = None