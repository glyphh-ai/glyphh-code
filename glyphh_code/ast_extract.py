"""
Language-agnostic AST extraction for Glyphh Code model.

Uses tree-sitter to extract structural signals from source files:
  - defines: top-level class/function/method names (split into words)
  - imports: module/package dependencies
  - docstring: module-level description (first docstring or comment block)
  - file_role: source, test, config, docs, example, script

Supports any language with a tree-sitter grammar installed.
Falls back to regex extraction for unsupported languages.

Usage:
    from ast_extract import extract_file_symbols

    result = extract_file_symbols("src/server/auth.py", content)
    # {"defines": "AuthMiddleware check_scope ...",
    #  "imports": "fastmcp.server.middleware ...",
    #  "docstring": "Authorization middleware for ...",
    #  "file_role": "source"}
"""

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Tree-sitter grammar loading
# ---------------------------------------------------------------------------

_PARSERS: dict[str, object] = {}
_TS_AVAILABLE = False

try:
    from tree_sitter import Language, Parser
    _TS_AVAILABLE = True
except ImportError:
    pass

# Extension → (grammar module name, tree-sitter language name)
_GRAMMAR_MAP: dict[str, tuple[str, str]] = {
    ".py": ("tree_sitter_python", "python"),
    ".js": ("tree_sitter_javascript", "javascript"),
    ".jsx": ("tree_sitter_javascript", "javascript"),
    ".ts": ("tree_sitter_typescript", "typescript"),
    ".tsx": ("tree_sitter_typescript", "tsx"),
    ".go": ("tree_sitter_go", "go"),
    ".rs": ("tree_sitter_rust", "rust"),
    ".java": ("tree_sitter_java", "java"),
    ".c": ("tree_sitter_c", "c"),
    ".h": ("tree_sitter_c", "c"),
    ".cpp": ("tree_sitter_cpp", "cpp"),
    ".hpp": ("tree_sitter_cpp", "cpp"),
    ".rb": ("tree_sitter_ruby", "ruby"),
    ".cs": ("tree_sitter_c_sharp", "c_sharp"),
    ".swift": ("tree_sitter_swift", "swift"),
}

# Node types for definitions across languages
_DEFINE_TYPES = frozenset({
    # Python
    "function_definition", "class_definition",
    # JS/TS
    "function_declaration", "class_declaration",
    "method_definition", "arrow_function",
    "export_statement",
    # Go
    "function_declaration", "method_declaration",
    "type_declaration",
    # Rust
    "function_item", "struct_item", "enum_item",
    "impl_item", "trait_item", "type_item",
    # Java
    "method_declaration", "class_declaration",
    "interface_declaration", "enum_declaration",
    # C/C++
    "function_definition", "struct_specifier",
    "class_specifier", "enum_specifier",
    # Ruby
    "method", "class", "module",
})

# Node types for imports across languages
_IMPORT_TYPES = frozenset({
    # Python
    "import_statement", "import_from_statement",
    # JS/TS
    "import_statement", "import_declaration",
    # Go
    "import_declaration", "import_spec",
    # Rust
    "use_declaration",
    # Java
    "import_declaration",
    # C/C++
    "preproc_include",
    # Ruby
    "call",  # require/require_relative — filtered by content
})


def _get_parser(ext: str):
    """Get or create a tree-sitter parser for the given file extension."""
    if not _TS_AVAILABLE:
        return None
    if ext in _PARSERS:
        return _PARSERS[ext]

    grammar_info = _GRAMMAR_MAP.get(ext)
    if not grammar_info:
        _PARSERS[ext] = None
        return None

    module_name, lang_name = grammar_info
    try:
        import importlib
        mod = importlib.import_module(module_name)
        # tree-sitter 0.22+ API: language() function returns Language
        if hasattr(mod, "language"):
            lang = Language(mod.language())
        else:
            # tree-sitter 0.21 API: use Language.build_library or direct path
            _PARSERS[ext] = None
            return None

        parser = Parser(lang)
        _PARSERS[ext] = parser
        return parser
    except (ImportError, Exception):
        _PARSERS[ext] = None
        return None


# ---------------------------------------------------------------------------
# Tree-sitter extraction
# ---------------------------------------------------------------------------

def _split_name(name: str) -> str:
    """Split CamelCase and snake_case into space-separated words.

    AuthorizationMiddleware → authorization middleware
    check_scope → check scope
    SSETransport → sse transport
    """
    # Insert space before uppercase runs: SSETransport → SSE Transport
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    # Insert space before single uppercase: checkScope → check Scope
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    # Replace underscores with spaces
    s = s.replace("_", " ")
    return s.lower().strip()


def _extract_name_from_node(node) -> str:
    """Extract the name identifier from a definition node."""
    for child in node.children:
        if child.type in ("identifier", "name", "property_identifier",
                          "type_identifier"):
            return child.text.decode("utf-8")
        # For export statements, look deeper
        if child.type in ("function_declaration", "class_declaration",
                          "lexical_declaration", "variable_declaration"):
            return _extract_name_from_node(child)
    return ""


def _extract_ts(content: str, ext: str) -> dict:
    """Extract symbols using tree-sitter."""
    parser = _get_parser(ext)
    if parser is None:
        return {}

    tree = parser.parse(content.encode("utf-8"))
    root = tree.root_node

    defines = []
    imports = []
    docstring = ""

    for node in root.children:
        # Top-level definitions
        if node.type in _DEFINE_TYPES:
            name = _extract_name_from_node(node)
            if name and not name.startswith("_"):
                defines.append(name)

        # Imports
        elif node.type in _IMPORT_TYPES:
            text = node.text.decode("utf-8").strip()
            imports.append(text)

        # Module docstring — first expression_statement containing a string
        elif not docstring and node.type == "expression_statement":
            for child in node.children:
                if child.type in ("string", "concatenated_string"):
                    raw = child.text.decode("utf-8")
                    # Strip quotes
                    for q in ('"""', "'''", '"', "'"):
                        if raw.startswith(q) and raw.endswith(q):
                            raw = raw[len(q):-len(q)]
                            break
                    docstring = raw.strip()
                    break

        # Module docstring — first comment block
        elif not docstring and node.type == "comment":
            docstring = node.text.decode("utf-8").lstrip("/#* ").strip()

    return {
        "defines_raw": defines,
        "imports_raw": imports,
        "docstring": docstring,
    }


# ---------------------------------------------------------------------------
# Regex fallback extraction
# ---------------------------------------------------------------------------

# Patterns for common definition syntaxes
_DEF_PATTERNS = [
    # Python: def name, class Name
    re.compile(r"^(?:def|class)\s+(\w+)", re.MULTILINE),
    # JS/TS: function name, class Name, export function name
    re.compile(r"^(?:export\s+)?(?:function|class)\s+(\w+)", re.MULTILINE),
    # Go: func Name, func (r *Receiver) Name, type Name struct
    re.compile(r"^func\s+(?:\([^)]*\)\s+)?(\w+)", re.MULTILINE),
    re.compile(r"^type\s+(\w+)\s+(?:struct|interface)", re.MULTILINE),
    # Rust: fn name, struct Name, enum Name, impl Name
    re.compile(r"^(?:pub\s+)?(?:fn|struct|enum|trait|impl)\s+(\w+)", re.MULTILINE),
    # Java/C#: public class Name, void methodName
    re.compile(r"^(?:public|private|protected)?\s*(?:static\s+)?(?:class|interface|enum)\s+(\w+)", re.MULTILINE),
    # C/C++: return_type function_name(
    re.compile(r"^(?:\w+\s+)+(\w+)\s*\(", re.MULTILINE),
    # Ruby: def name, class Name, module Name
    re.compile(r"^(?:def|class|module)\s+(\w+)", re.MULTILINE),
]

_IMPORT_PATTERNS = [
    # Python: import x, from x import y
    re.compile(r"^(?:from\s+([\w.]+)\s+)?import\s+([\w., ]+)", re.MULTILINE),
    # JS/TS: import ... from "module"
    re.compile(r"""^import\s+.*?from\s+['"]([^'"]+)['"]""", re.MULTILINE),
    # Go: import "package"
    re.compile(r"""^\s*"([^"]+)"$""", re.MULTILINE),
    # Rust: use crate::path
    re.compile(r"^use\s+([\w:]+)", re.MULTILINE),
    # C/C++: #include <file> or "file"
    re.compile(r'^#include\s+[<"]([^>"]+)[>"]', re.MULTILINE),
    # Ruby: require "file"
    re.compile(r"""^require(?:_relative)?\s+['"]([^'"]+)['"]""", re.MULTILINE),
]


def _extract_regex(content: str) -> dict:
    """Fallback: extract symbols using regex patterns."""
    defines = []
    for pat in _DEF_PATTERNS:
        for m in pat.finditer(content):
            name = m.group(1)
            if name and not name.startswith("_") and name not in defines:
                defines.append(name)

    imports = []
    for pat in _IMPORT_PATTERNS:
        for m in pat.finditer(content):
            # Take the last non-None group
            for g in reversed(m.groups()):
                if g:
                    imports.append(g.strip())
                    break

    # Docstring: first triple-quoted string or comment block
    docstring = ""
    m = re.search(r'^(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')', content, re.DOTALL)
    if m:
        docstring = (m.group(1) or m.group(2) or "").strip()
    elif not docstring:
        # First comment block
        lines = content.split("\n")
        comment_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*", "/*")):
                comment_lines.append(stripped.lstrip("#/* "))
            elif comment_lines:
                break
            elif stripped:
                break
        if comment_lines:
            docstring = " ".join(comment_lines)

    return {
        "defines_raw": defines,
        "imports_raw": imports,
        "docstring": docstring,
    }


# ---------------------------------------------------------------------------
# Role detection
# ---------------------------------------------------------------------------

def _detect_role(file_path: str) -> str:
    """Detect file role from path heuristics."""
    parts = Path(file_path).parts
    name = Path(file_path).stem
    ext = Path(file_path).suffix

    # Test files
    if any(p in ("tests", "test", "__tests__", "spec") for p in parts):
        return "test"
    if name.startswith("test_") or name.endswith("_test") or name.endswith(".test"):
        return "test"
    if name.startswith("spec_") or name.endswith("_spec") or name.endswith(".spec"):
        return "test"

    # Examples
    if any(p in ("examples", "example", "demo", "demos", "samples") for p in parts):
        return "example"

    # Config
    if ext in (".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".conf"):
        return "config"
    if name in ("setup", "pyproject", "package", "tsconfig", "webpack",
                "Makefile", "Dockerfile", "docker-compose", "Cargo"):
        return "config"

    # Docs
    if ext in (".md", ".rst", ".txt"):
        return "docs"
    if any(p in ("docs", "doc", "documentation") for p in parts):
        return "docs"

    # Scripts
    if ext in (".sh", ".bash", ".zsh"):
        return "script"

    return "source"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_file_symbols(file_path: str, content: str) -> dict:
    """Extract structural symbols from a source file.

    Args:
        file_path: Relative path to the file (for role detection + extension)
        content: File contents as string

    Returns:
        dict with keys:
            defines — space-separated words from top-level symbol names
            imports — space-separated import module/package names
            docstring — module-level description (first docstring/comment)
            file_role — source, test, config, docs, example, script
    """
    ext = Path(file_path).suffix

    # Try tree-sitter first, fall back to regex
    result = _extract_ts(content, ext)
    if not result:
        result = _extract_regex(content)

    # Split define names into searchable words
    define_words = []
    for name in result.get("defines_raw", []):
        define_words.append(name)  # Keep original name
        split = _split_name(name)
        if split != name.lower():
            define_words.append(split)

    # Clean up imports into module names
    import_names = []
    for imp in result.get("imports_raw", []):
        # Extract module name from full import statement
        # "from fastmcp.server import auth" → "fastmcp server auth"
        cleaned = re.sub(r"^(?:from|import|use|require|include)\s+", "", imp)
        cleaned = re.sub(r"\s+import\s+.*", "", cleaned)
        cleaned = cleaned.replace(".", " ").replace("::", " ").replace("/", " ")
        cleaned = re.sub(r"[^a-zA-Z0-9_ ]", "", cleaned)
        if cleaned.strip():
            import_names.append(cleaned.strip())

    docstring = result.get("docstring", "")
    # Truncate long docstrings — first sentence is usually enough
    if len(docstring) > 200:
        # Cut at first period or newline
        for sep in (".\n", ". ", "\n\n", "\n"):
            idx = docstring.find(sep)
            if 20 < idx < 200:
                docstring = docstring[:idx + 1]
                break
        else:
            docstring = docstring[:200]

    return {
        "defines": " ".join(define_words),
        "imports": " ".join(import_names),
        "docstring": docstring.strip(),
        "file_role": _detect_role(file_path),
    }
