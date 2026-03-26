"""
Relationship extraction for glyphh-code.

Builds a repo-wide relationship graph from already-extracted file records.
Uses in-memory joins (no subprocess/grep) for cross-platform compatibility.

Three signals:
  - dependents: files that import this file's module
  - references: files that use symbols (functions/classes) defined in this file
  - co_changed: files that frequently change together in git history

Called as a post-processing step in compile.py after all file_to_record()
calls complete, so the full file set is available for graph construction.
"""

import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


def _module_names_for_file(rel_path: str) -> list[str]:
    """Generate possible import names that could refer to this file.

    src/services/auth.py → ["auth", "services.auth", "src.services.auth"]
    utils/helpers.py     → ["helpers", "utils.helpers"]
    __init__.py          → [] (package init, not directly imported by name)
    """
    p = Path(rel_path)
    if p.name == "__init__.py":
        # Package import — use directory name
        parts = list(p.parent.parts)
        if not parts:
            return []
        names = []
        for i in range(len(parts)):
            names.append(".".join(parts[i:]))
        return names

    stem = p.stem
    parts = list(p.parent.parts) + [stem]

    # Generate progressively qualified names: auth, services.auth, src.services.auth
    names = []
    for i in range(len(parts)):
        candidate = ".".join(parts[i:])
        if candidate:
            names.append(candidate)
    return names


def _tokenize_imports(import_str: str) -> set[str]:
    """Split import string into individual module tokens.

    "os sys pathlib json" → {"os", "sys", "pathlib", "json"}
    Also handles dotted imports: "fastmcp.server" → {"fastmcp.server", "fastmcp", "server"}
    """
    tokens = set()
    for token in import_str.split():
        token = token.strip().lower()
        if not token or len(token) < 2:
            continue
        tokens.add(token)
        # Also add the leaf module for dotted imports
        if "." in token:
            parts = token.split(".")
            for part in parts:
                if len(part) > 1:
                    tokens.add(part)
    return tokens


def _tokenize_defines(defines_str: str) -> set[str]:
    """Split defines string into individual symbol tokens.

    "authenticate check_token UserModel" → {"authenticate", "check_token", "usermodel"}
    """
    tokens = set()
    for token in defines_str.split():
        token = token.strip().lower()
        if token and len(token) > 2:
            tokens.add(token)
    return tokens


def _tokenize_identifiers(identifiers_str: str) -> set[str]:
    """Split identifiers string into a set for fast lookup."""
    return {t.lower() for t in identifiers_str.split() if len(t) > 2}


def build_relationship_graph(
    records: list[dict],
    repo_root: str,
    include_git: bool = True,
    co_change_depth: int = 200,
) -> dict[str, dict[str, str]]:
    """Build relationship graph from already-extracted file records.

    Args:
        records: List of records from file_to_record(), each with
                 concept_text (rel_path) and attributes dict.
        repo_root: Repository root for git operations.
        include_git: Whether to include co-change analysis (requires git).
        co_change_depth: Number of commits to analyze for co-change.

    Returns:
        Dict mapping rel_path → {
            "dependents": "path1 path2 ...",  # files that import me
            "references": "path3 path4 ...",  # files that use my symbols
            "co_changed": "path5 path6 ...",  # files that change with me
        }
        Values are space-separated path tokens for BoW encoding.
    """
    # Index: rel_path → attributes
    file_attrs: dict[str, dict] = {}
    for rec in records:
        rel_path = rec.get("concept_text", "")
        attrs = rec.get("attributes", {})
        if rel_path and attrs:
            file_attrs[rel_path] = attrs

    # --- Phase 1: Dependents (reverse import graph) ---
    # Build: module_name → [files that provide this module]
    module_providers: dict[str, list[str]] = defaultdict(list)
    for rel_path in file_attrs:
        for mod_name in _module_names_for_file(rel_path):
            module_providers[mod_name.lower()].append(rel_path)

    # For each file, find which other files import it
    dependents: dict[str, set[str]] = defaultdict(set)
    for rel_path, attrs in file_attrs.items():
        import_tokens = _tokenize_imports(attrs.get("imports", ""))
        for token in import_tokens:
            for provider in module_providers.get(token, []):
                if provider != rel_path:
                    dependents[provider].add(rel_path)

    # --- Phase 2: References (symbol usage graph) ---
    # Build: symbol → [files that define this symbol]
    symbol_providers: dict[str, list[str]] = defaultdict(list)
    for rel_path, attrs in file_attrs.items():
        for symbol in _tokenize_defines(attrs.get("defines", "")):
            symbol_providers[symbol].append(rel_path)

    # For each file, find which other files use its symbols
    references: dict[str, set[str]] = defaultdict(set)
    for rel_path, attrs in file_attrs.items():
        idents = _tokenize_identifiers(attrs.get("identifiers", ""))
        for ident in idents:
            for provider in symbol_providers.get(ident, []):
                if provider != rel_path:
                    references[provider].add(rel_path)

    # --- Phase 3: Co-change (git history) ---
    co_changed: dict[str, Counter] = defaultdict(Counter)
    if include_git:
        co_changed = _build_co_change_graph(repo_root, file_attrs, co_change_depth)

    # --- Assemble results ---
    # Convert to path-tokenized BoW strings for HDC encoding
    result: dict[str, dict[str, str]] = {}
    for rel_path in file_attrs:
        dep_paths = sorted(dependents.get(rel_path, set()))
        ref_paths = sorted(references.get(rel_path, set()))
        co_paths = sorted(co_changed.get(rel_path, Counter()), key=lambda p: -co_changed[rel_path][p])

        # Tokenize paths for BoW encoding: "src/auth.py" → "src auth py"
        def _path_to_tokens(paths: list[str], max_paths: int = 20) -> str:
            tokens = []
            for p in paths[:max_paths]:
                tokens.extend(_path_tokens(p))
            return " ".join(tokens)

        result[rel_path] = {
            "dependents": _path_to_tokens(dep_paths),
            "references": _path_to_tokens(ref_paths),
            "co_changed": _path_to_tokens(co_paths, max_paths=15),
        }

    return result


def _path_tokens(rel_path: str) -> list[str]:
    """Convert a file path to BoW tokens: src/services/auth.py → [src, services, auth]"""
    p = Path(rel_path)
    parts = list(p.parent.parts) + [p.stem]
    return [t.lower() for t in parts if t and t != "." and len(t) > 1]


def _build_co_change_graph(
    repo_root: str,
    file_attrs: dict[str, dict],
    depth: int,
) -> dict[str, Counter]:
    """Build co-change graph from git log.

    For each commit in the last `depth` commits, record which indexed files
    changed together. Files that frequently appear in the same commits are
    co-changed.
    """
    co_changed: dict[str, Counter] = defaultdict(Counter)

    try:
        # Get recent commit hashes
        result = subprocess.run(
            ["git", "log", f"-{depth}", "--format=%H"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=30,
        )
        if result.returncode != 0:
            return co_changed
        commits = [h.strip() for h in result.stdout.strip().split("\n") if h.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return co_changed

    indexed_files = set(file_attrs.keys())

    for commit_hash in commits:
        try:
            result = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
                capture_output=True,
                text=True,
                cwd=repo_root,
                timeout=10,
            )
            if result.returncode != 0:
                continue
            changed = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
            # Only count indexed files
            changed_indexed = [f for f in changed if f in indexed_files]
            # Record co-changes
            for i, f1 in enumerate(changed_indexed):
                for f2 in changed_indexed[i + 1:]:
                    co_changed[f1][f2] += 1
                    co_changed[f2][f1] += 1
        except (subprocess.TimeoutExpired, OSError):
            continue

    return co_changed
