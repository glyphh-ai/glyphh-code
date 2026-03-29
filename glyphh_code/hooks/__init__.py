"""
glyphh-hook — CLI entry point for Claude Code hooks.

Usage:
    glyphh-hook search-gate /path/to/.glyphh
    glyphh-hook post-git-compile /path/to/source/dir

Installed via `pip install glyphh-code` as a console script.
Replaces hardcoded absolute paths to shell scripts in .claude/settings.json.
"""

import json
import os
import sys
from pathlib import Path


def _search_gate():
    """PreToolUse hook: block Grep/Glob/Bash(grep|find) until glyphh_search called."""
    glyphh_dir = sys.argv[2] if len(sys.argv) > 2 else ".glyphh"

    # If glyphh_search already called this session, allow everything
    if os.path.isfile(os.path.join(glyphh_dir, ".search_used")):
        sys.exit(0)

    # Read hook input from stdin
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")

    # Grep/Glob — always block before search
    if tool_name in ("Grep", "Glob"):
        print(
            "BLOCKED: Call glyphh_search first. "
            "Grep/Glob unlock after glyphh_search has been called.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Bash — block if command looks like a file search
    if tool_name == "Bash":
        cmd = data.get("tool_input", {}).get("command", "")
        import re
        if re.search(r"\bgrep\b|\brg\b|\bfind\b|\bfd\b", cmd, re.IGNORECASE):
            print(
                "BLOCKED: Call glyphh_search first. "
                "Bash grep/find/rg unlock after glyphh_search has been called.",
                file=sys.stderr,
            )
            sys.exit(2)

    sys.exit(0)


def _post_git_compile():
    """PostToolUse hook: incremental compile after git operations."""
    # Delegate to the shell script (complex git logic, background processes)
    hook_dir = Path(__file__).parent
    script = hook_dir / "post-git-compile.sh"
    if not script.exists():
        sys.exit(0)

    source_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    os.execvp("bash", ["bash", str(script), source_dir])


_COMMANDS = {
    "search-gate": _search_gate,
    "post-git-compile": _post_git_compile,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        cmds = ", ".join(_COMMANDS)
        print(f"Usage: glyphh-hook <{cmds}> [args...]", file=sys.stderr)
        sys.exit(1)

    _COMMANDS[sys.argv[1]]()
