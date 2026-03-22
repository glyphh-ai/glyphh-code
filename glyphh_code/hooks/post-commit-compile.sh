#!/usr/bin/env bash
#
# Claude Code PostToolUse hook — incremental index update after git commit.
#
# Triggers on any git commit that lands inside SOURCE_DIR (the repo itself,
# a child repo, or a submodule). Runs compile.py --incremental against
# SOURCE_DIR so the Glyphh index stays current.
#
# Usage in .claude/settings.json:
#
#   "command": "/path/to/post-commit-compile.sh /path/to/source/dir"
#
# The first argument is the source directory to index. Any commit inside
# that directory tree (including child repos and submodules) triggers a
# recompile.
#
# Configuration (environment variables):
#   GLYPHH_RUNTIME_URL   Runtime endpoint (default: http://localhost:8002)
#   GLYPHH_TOKEN         Auth token (auto-resolved from CLI session if unset)
#   GLYPHH_ORG_ID        Org ID (auto-resolved from CLI session if unset)
#   GLYPHH_PYTHON        Python interpreter (default: /opt/homebrew/anaconda3/bin/python)
#   GLYPHH_HOOK_DISABLE  Set to "1" to temporarily disable
#

# Allow disabling without removing the hook
if [ "${GLYPHH_HOOK_DISABLE:-}" = "1" ]; then
    exit 0
fi

# Source directory is the first argument
SOURCE_DIR="${1:?Usage: post-commit-compile.sh /path/to/source/dir}"
SOURCE_DIR="$(cd "$SOURCE_DIR" 2>/dev/null && pwd)" || exit 0

# Read the tool input from stdin (JSON with tool_name, tool_input, cwd, etc.)
INPUT="$(cat)"

# Only trigger on Bash commands that contain "git commit"
COMMAND="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null || true)"

if [[ "$COMMAND" != *"git commit"* ]]; then
    exit 0
fi

# Determine the repo that was committed to.
# Commands may cd first: "cd /path && git commit ..."
# Otherwise the commit runs in the hook's cwd.
CWD="$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || true)"
CD_PATH="$(echo "$COMMAND" | sed -n 's|^cd \([^ ;&]*\).*|\1|p')"

if [ -n "$CD_PATH" ] && [ -d "$CD_PATH" ]; then
    COMMIT_DIR="$(cd "$CD_PATH" && git rev-parse --show-toplevel 2>/dev/null || echo "$CD_PATH")"
elif [ -n "$CWD" ] && [ -d "$CWD" ]; then
    COMMIT_DIR="$(cd "$CWD" && git rev-parse --show-toplevel 2>/dev/null || echo "$CWD")"
else
    exit 0
fi

# Normalize to absolute path
COMMIT_DIR="$(cd "$COMMIT_DIR" 2>/dev/null && pwd)" || exit 0

# Only trigger if the commit is inside SOURCE_DIR
case "$COMMIT_DIR" in
    "$SOURCE_DIR"|"$SOURCE_DIR/"*)
        ;;
    *)
        exit 0
        ;;
esac

# Locate compile.py relative to this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPILE="$SCRIPT_DIR/../compile.py"

if [ ! -f "$COMPILE" ]; then
    exit 0
fi

# Build args — always compile SOURCE_DIR, but diff the repo that was committed to
ARGS=("$SOURCE_DIR" "--incremental")

if [ "$COMMIT_DIR" != "$SOURCE_DIR" ]; then
    ARGS+=("--diff-repo" "$COMMIT_DIR")
fi

if [ -n "${GLYPHH_RUNTIME_URL:-}" ]; then
    ARGS+=("--runtime-url" "$GLYPHH_RUNTIME_URL")
fi

if [ -n "${GLYPHH_TOKEN:-}" ]; then
    ARGS+=("--token" "$GLYPHH_TOKEN")
fi

if [ -n "${GLYPHH_ORG_ID:-}" ]; then
    ARGS+=("--org-id" "$GLYPHH_ORG_ID")
fi

# Use anaconda python (has requests) — system python3 may not
PYTHON="${GLYPHH_PYTHON:-/opt/homebrew/anaconda3/bin/python}"

# glyphh SDK lives alongside the source
export PYTHONPATH="$SOURCE_DIR/glyphh-runtime${PYTHONPATH:+:$PYTHONPATH}"

# Run in background — don't block Claude
"$PYTHON" "$COMPILE" "${ARGS[@]}" >> /tmp/glyphh-compile.log 2>&1 &
