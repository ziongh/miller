# Supported Languages

Miller supports **29 programming languages** via tree-sitter parsers from [Julie](https://github.com/anortham/julie).

## Full Language List

| Language | Extensions | Symbol Extraction |
|----------|------------|-------------------|
| Bash | `.sh`, `.bash` | functions, variables |
| C | `.c`, `.h` | functions, structs, typedefs |
| C++ | `.cpp`, `.cc`, `.cxx`, `.hpp` | classes, functions, namespaces |
| C# | `.cs` | classes, methods, properties |
| CSS | `.css` | selectors, properties |
| Dart | `.dart` | classes, functions, methods |
| GDScript | `.gd` | classes, functions |
| Go | `.go` | functions, types, interfaces |
| HTML | `.html`, `.htm` | elements |
| Java | `.java` | classes, methods, interfaces |
| JavaScript | `.js`, `.mjs` | functions, classes, exports |
| JSX | `.jsx` | components, functions |
| Kotlin | `.kt`, `.kts` | classes, functions |
| Lua | `.lua` | functions, tables |
| PHP | `.php` | classes, functions |
| PowerShell | `.ps1`, `.psm1` | functions, cmdlets |
| Python | `.py` | classes, functions, methods |
| QML | `.qml` | components, properties |
| R | `.r`, `.R` | functions, assignments |
| Razor | `.razor`, `.cshtml` | components |
| Regex | embedded | patterns |
| Ruby | `.rb` | classes, modules, methods |
| Rust | `.rs` | functions, structs, traits, impls |
| SQL | `.sql` | tables, procedures |
| Swift | `.swift` | classes, functions, protocols |
| TSX | `.tsx` | components, functions |
| TypeScript | `.ts`, `.mts` | classes, functions, interfaces |
| Vue | `.vue` | components, methods |
| Zig | `.zig` | functions, structs |

## Detection

Language is automatically detected from file extensions. Use `detect_language()` to check:

```python
from miller import miller_core

lang = miller_core.detect_language("src/main.rs")  # Returns "rust"
lang = miller_core.detect_language("app.py")       # Returns "python"
```

## Adding Languages

Languages are provided by the [julie-extractors](https://github.com/anortham/julie) crate. To request a new language, open an issue there.
