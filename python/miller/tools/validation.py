"""
Import validation tool for preventing hallucinated imports.

Validates that imports in code snippets reference symbols that actually
exist in the indexed codebase, preventing the "import loop" bug where
agents write code with non-existent imports and then loop on errors.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from miller.storage import StorageManager

logger = logging.getLogger("miller.validation")


@dataclass
class ImportValidationResult:
    """Result of validating a single import."""

    import_name: str
    status: Literal["valid", "invalid", "ambiguous", "private"]
    message: str
    suggestions: list[str] = field(default_factory=list)
    matched_symbol: Optional[dict] = None


def _parse_python_imports(code: str) -> list[str]:
    """
    Extract import names from Python code.

    Handles:
    - import module
    - from module import name
    - from module import name1, name2
    - from module import (name1, name2)

    Args:
        code: Python code snippet

    Returns:
        List of imported module/symbol names
    """
    imports = []

    # Match 'import module' or 'import module as alias'
    for match in re.finditer(r"^import\s+([\w.]+)", code, re.MULTILINE):
        imports.append(match.group(1).split(".")[0])  # Top-level module

    # Match 'from module import ...'
    from_pattern = r"^from\s+([\w.]+)\s+import\s+(.+?)(?:\n|$)"
    for match in re.finditer(from_pattern, code, re.MULTILINE):
        module = match.group(1)
        names_str = match.group(2)

        # Handle parenthesized imports
        if "(" in names_str:
            # Find closing paren (may span lines)
            paren_match = re.search(
                r"\(\s*([^)]+)\s*\)", code[match.start() :], re.DOTALL
            )
            if paren_match:
                names_str = paren_match.group(1)

        # Extract individual names
        for name in re.split(r"[,\s]+", names_str):
            name = name.strip()
            if name and name != "(" and name != ")":
                # Remove 'as alias' suffix
                name = re.sub(r"\s+as\s+\w+", "", name)
                if name and name not in ("*", "\\"):
                    imports.append(f"{module}.{name}")

    return imports


def _parse_typescript_imports(code: str) -> list[str]:
    """
    Extract import names from TypeScript/JavaScript code.

    Handles:
    - import { name } from 'module'
    - import name from 'module'
    - import * as name from 'module'
    - import type { Type } from 'module'

    Args:
        code: TypeScript/JavaScript code snippet

    Returns:
        List of imported symbol names
    """
    imports = []

    # Match ES6 imports: import { x, y } from 'module'
    es6_pattern = r"import\s+(?:type\s+)?{([^}]+)}\s+from\s+['\"]([^'\"]+)['\"]"
    for match in re.finditer(es6_pattern, code):
        names_str = match.group(1)
        module = match.group(2)
        for name in re.split(r"[,\s]+", names_str):
            name = name.strip()
            if name and name not in ("type", "as"):
                # Handle 'name as alias' → extract 'name'
                if " as " in name:
                    name = name.split(" as ")[0].strip()
                imports.append(name)

    # Match default imports: import Name from 'module'
    default_pattern = r"import\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]"
    for match in re.finditer(default_pattern, code):
        imports.append(match.group(1))

    # Match namespace imports: import * as name from 'module'
    namespace_pattern = r"import\s+\*\s+as\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]"
    for match in re.finditer(namespace_pattern, code):
        # Namespace imports are module-level, add module path
        imports.append(match.group(1))

    return imports


def _parse_rust_imports(code: str) -> list[str]:
    """
    Extract import names from Rust code.

    Handles:
    - use crate::module::Name;
    - use crate::module::{Name1, Name2};
    - use super::module::*;

    Args:
        code: Rust code snippet

    Returns:
        List of imported symbol names
    """
    imports = []

    # Match 'use path::name' or 'use path::{names}'
    use_pattern = r"use\s+([\w:]+)(?:::({[^}]+}|\w+|\*))?\s*;"
    for match in re.finditer(use_pattern, code):
        path = match.group(1)
        names = match.group(2)

        if names:
            if names.startswith("{"):
                # Multiple imports: use path::{Name1, Name2}
                for name in re.split(r"[,\s]+", names.strip("{}")):
                    name = name.strip()
                    if name and name != "*":
                        imports.append(name)
            elif names != "*":
                # Single import: use path::Name
                imports.append(names)
        else:
            # Module import: use path (last component)
            parts = path.split("::")
            if parts:
                imports.append(parts[-1])

    return imports


def _parse_go_imports(code: str) -> list[str]:
    """
    Extract import names from Go code.

    Handles:
    - import "package"
    - import ( "pkg1" "pkg2" )
    - import alias "package"

    Args:
        code: Go code snippet

    Returns:
        List of imported package names (last path component)
    """
    imports = []

    # Match single import
    single_pattern = r'import\s+(?:\w+\s+)?"([^"]+)"'
    for match in re.finditer(single_pattern, code):
        path = match.group(1)
        # Use last path component as package name
        imports.append(path.split("/")[-1])

    # Match grouped imports
    group_pattern = r"import\s*\(([^)]+)\)"
    for match in re.finditer(group_pattern, code, re.DOTALL):
        for line in match.group(1).split("\n"):
            pkg_match = re.search(r'"([^"]+)"', line)
            if pkg_match:
                path = pkg_match.group(1)
                imports.append(path.split("/")[-1])

    return imports


def _detect_language(code: str) -> str:
    """
    Auto-detect language from code snippet.

    Args:
        code: Code snippet

    Returns:
        Detected language or "unknown"
    """
    # Check for language-specific patterns
    if re.search(r"\bfn\s+\w+|let\s+mut\s|use\s+\w+::", code):
        return "rust"
    if re.search(r"\bfunc\s+\w+|package\s+\w+|import\s+\(", code):
        return "go"
    if re.search(r"import\s+{|from\s+['\"]|export\s+(default|const|function)", code):
        return "typescript"
    if re.search(r"^from\s+\w+\s+import|^import\s+\w+|def\s+\w+\(", code, re.MULTILINE):
        return "python"

    return "unknown"


def _parse_imports(code: str, language: str) -> list[str]:
    """
    Parse imports from code based on language.

    Args:
        code: Code snippet
        language: Programming language

    Returns:
        List of imported symbol/module names
    """
    language = language.lower()

    if language in ("python", "py"):
        return _parse_python_imports(code)
    elif language in ("typescript", "ts", "javascript", "js"):
        return _parse_typescript_imports(code)
    elif language in ("rust", "rs"):
        return _parse_rust_imports(code)
    elif language in ("go", "golang"):
        return _parse_go_imports(code)
    else:
        # Auto-detect
        detected = _detect_language(code)
        if detected != "unknown":
            return _parse_imports(code, detected)
        return []


async def validate_imports(
    code_snippet: str,
    language: Optional[str] = None,
    # Injected dependencies
    storage: Optional["StorageManager"] = None,
) -> str:
    """
    Validate that imports in a code snippet reference existing symbols.

    Use this tool BEFORE writing code that imports from the codebase.
    It prevents the "hallucinated import" bug where agents write imports
    to symbols that don't exist, then loop on compilation errors.

    The tool parses the code snippet, extracts import statements, and
    checks each imported symbol against the indexed codebase.

    Args:
        code_snippet: Code you intend to write (can be partial, just imports)
        language: Programming language (auto-detected if not provided).
                 Supported: python, typescript, javascript, rust, go

    Returns:
        Validation report with status for each import:
        - valid: Symbol exists and is public/exported
        - invalid: Symbol does not exist (with suggestions)
        - ambiguous: Multiple matching symbols found
        - private: Symbol exists but is not exported

    Examples:
        >>> # Validate before writing Python code
        >>> validate_imports('''
        ... from miller.storage import StorageManager
        ... from miller.embeddings import EmbeddingManager
        ... from miller.utils import NonExistentClass
        ... ''', language="python")

        >>> # Auto-detect language from code
        >>> validate_imports('''
        ... import { UserService } from './services/user';
        ... import { NonExistent } from './services/fake';
        ... ''')
    """
    if storage is None:
        return "Error: Storage not available. Workspace may not be indexed."

    # Parse imports from the code snippet
    detected_language = language or _detect_language(code_snippet)
    imports = _parse_imports(code_snippet, detected_language)

    if not imports:
        return f"No imports found in code snippet. Detected language: {detected_language}"

    # Validate each import
    results: list[ImportValidationResult] = []

    # Get all exported symbols (cached for this validation)
    all_symbols = storage.get_exported_symbols()
    symbol_names = {s["name"]: s for s in all_symbols}

    for import_name in imports:
        # Extract the symbol name (last component)
        name_parts = import_name.replace("::", ".").split(".")
        symbol_name = name_parts[-1] if name_parts else import_name

        # Check if symbol exists
        if symbol_name in symbol_names:
            symbol = symbol_names[symbol_name]
            visibility = symbol.get("visibility", "")

            if visibility in ("private", "internal", "protected"):
                results.append(
                    ImportValidationResult(
                        import_name=import_name,
                        status="private",
                        message=f"Symbol '{symbol_name}' exists but is {visibility}",
                        matched_symbol=symbol,
                    )
                )
            else:
                results.append(
                    ImportValidationResult(
                        import_name=import_name,
                        status="valid",
                        message=f"✓ Found in {symbol['file_path']} ({symbol['kind']})",
                        matched_symbol=symbol,
                    )
                )
        else:
            # Symbol not found - look for suggestions
            suggestions = []

            # Try prefix matching
            if len(symbol_name) >= 3:
                similar = storage.find_symbols_by_name_prefix(symbol_name[:3], limit=5)
                suggestions = [s["name"] for s in similar if s["name"] != symbol_name]

            # Also check for case-insensitive matches
            lower_name = symbol_name.lower()
            for s in all_symbols:
                if s["name"].lower() == lower_name and s["name"] != symbol_name:
                    if s["name"] not in suggestions:
                        suggestions.insert(0, s["name"])  # Prioritize exact case match

            results.append(
                ImportValidationResult(
                    import_name=import_name,
                    status="invalid",
                    message=f"✗ Symbol '{symbol_name}' not found in codebase",
                    suggestions=suggestions[:5],
                )
            )

    # Generate report
    lines = [
        f"Import Validation Report ({detected_language})",
        "=" * 50,
        "",
    ]

    valid_count = sum(1 for r in results if r.status == "valid")
    invalid_count = sum(1 for r in results if r.status == "invalid")
    private_count = sum(1 for r in results if r.status == "private")

    lines.append(f"Summary: {valid_count} valid, {invalid_count} invalid, {private_count} private")
    lines.append("")

    for result in results:
        if result.status == "valid":
            lines.append(f"✓ {result.import_name}")
            lines.append(f"  {result.message}")
        elif result.status == "invalid":
            lines.append(f"✗ {result.import_name}")
            lines.append(f"  {result.message}")
            if result.suggestions:
                lines.append(f"  Did you mean: {', '.join(result.suggestions)}")
        elif result.status == "private":
            lines.append(f"⚠ {result.import_name}")
            lines.append(f"  {result.message}")
        lines.append("")

    if invalid_count > 0:
        lines.append("─" * 50)
        lines.append("⚠️ Fix invalid imports before writing this code!")

    return "\n".join(lines)
