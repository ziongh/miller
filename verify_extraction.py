#!/usr/bin/env python3
"""Manual verification script for Miller extraction."""

from miller import miller_core
from pathlib import Path

def verify_file(file_path: str, language: str):
    """Extract and display symbols from a file."""
    path = Path(file_path)
    content = path.read_text()

    print(f"\n{'='*70}")
    print(f"File: {file_path}")
    print(f"Language: {language}")
    print(f"{'='*70}")

    result = miller_core.extract_file(content, language, str(path))

    print(f"[STATS] Extraction Results:")
    print(f"   Symbols: {len(result.symbols)}")
    print(f"   Identifiers: {len(result.identifiers)}")
    print(f"   Relationships: {len(result.relationships)}")
    print()

    print("[SYMBOLS] Extracted:")
    for sym in result.symbols:
        parent = f" (parent: ...{sym.parent_id[-8:]})" if sym.parent_id else ""
        sig = f" -> {sym.signature}" if sym.signature else ""
        doc = f' DOC: "{sym.doc_comment[:30]}..."' if sym.doc_comment else ""
        print(f"   [{sym.kind:12}] {sym.name:25} @ line {sym.start_line:3}{parent}{sig}{doc}")

    if result.identifiers:
        print(f"\n[IDENTIFIERS] (first 10):")
        for i, ident in enumerate(result.identifiers[:10]):
            print(f"   [{ident.kind:15}] {ident.name:20} @ line {ident.start_line}")

    if result.relationships:
        print(f"\n[RELATIONSHIPS]:")
        for rel in result.relationships:
            from_id = rel.from_symbol_id[-8:]
            to_id = rel.to_symbol_id[-8:]
            print(f"   [{rel.kind:12}] ...{from_id} -> ...{to_id} @ line {rel.line_number}")

    return result

def main():
    print("\n*** MILLER EXTRACTION VERIFICATION ***")
    print("Testing with realistic code samples\n")

    test_files = [
        ("test_samples/user_manager.py", "python"),
        ("test_samples/app.js", "javascript"),
        ("test_samples/lib.rs", "rust"),
    ]

    results = {}
    for file_path, language in test_files:
        try:
            results[file_path] = verify_file(file_path, language)
        except Exception as e:
            print(f"❌ Error processing {file_path}: {e}")

    # Summary
    print(f"\n{'='*70}")
    print("[SUMMARY]")
    print(f"{'='*70}")
    for file_path, result in results.items():
        lang = file_path.split('.')[-1]
        print(f"{file_path:40} -> {len(result.symbols):2} symbols, "
              f"{len(result.identifiers):3} identifiers, "
              f"{len(result.relationships):2} relationships")

    print("\n[SUCCESS] Verification complete!")

if __name__ == "__main__":
    main()
