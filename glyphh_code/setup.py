"""
Core setup logic for glyphh-code init.

Handles: compile, server start, Claude Code config, CLAUDE.md, hooks.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import click

try:
    from glyphh.cli import theme
except ImportError:
    class _FallbackTheme:
        PRIMARY = "magenta"
        ACCENT = "bright_magenta"
        MUTED = "bright_black"
        SUCCESS = "green"
        WARNING = "yellow"
        ERROR = "red"
        INFO = "cyan"
        TEXT = "white"
        TEXT_DIM = "bright_black"
    theme = _FallbackTheme()

from .banner import print_banner, print_status

# Paths
_GLYPHH_DIR = Path.home() / ".glyphh"
_PID_FILE = _GLYPHH_DIR / "code.pid"
_STATE_FILE = _GLYPHH_DIR / "code.json"
_PACKAGE_DIR = Path(__file__).parent.parent  # Root of glyphh-code repo


def _find_free_port(start: int, max_attempts: int = 20) -> int:
    """Find a free port starting from `start`."""
    for offset in range(max_attempts):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    return start


def _is_server_running() -> dict | None:
    """Check if a glyphh-code server is already running."""
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # Check process exists
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text())
        return {"pid": pid}
    except (ProcessLookupError, ValueError):
        _PID_FILE.unlink(missing_ok=True)
        _STATE_FILE.unlink(missing_ok=True)
        return None


def _compile_repo(repo_path: str, runtime_url: str) -> int:
    """Compile the repository into the Glyphh index."""
    compile_script = _PACKAGE_DIR / "compile.py"
    if not compile_script.exists():
        click.secho("  Error: compile.py not found in package", fg=theme.ERROR)
        sys.exit(1)

    result = subprocess.run(
        [sys.executable, str(compile_script), repo_path,
         "--runtime-url", runtime_url],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        click.secho(f"  Compile error: {result.stderr.strip()[:200]}", fg=theme.ERROR)
        sys.exit(1)

    # Parse file count from output
    for line in result.stdout.strip().split("\n"):
        if "files indexed" in line:
            try:
                return int(line.split(":")[1].strip().split()[0])
            except (IndexError, ValueError):
                pass
        if "Encoded:" in line:
            try:
                return int(line.split(":")[1].strip().split()[0])
            except (IndexError, ValueError):
                pass
    return 0


def _deploy_model(runtime_url: str) -> bool:
    """Deploy the code model to the running runtime."""
    try:
        import requests
        manifest_path = _PACKAGE_DIR / "manifest.yaml"
        if not manifest_path.exists():
            click.secho("  Warning: manifest.yaml not found", fg=theme.WARNING)
            return False

        # Use the glyphh CLI to deploy
        result = subprocess.run(
            [sys.executable, "-m", "glyphh.cli.main", "model", "deploy",
             str(_PACKAGE_DIR)],
            capture_output=True,
            text=True,
            env={**os.environ, "GLYPHH_RUNTIME_URL": runtime_url},
        )
        return result.returncode == 0
    except Exception:
        return False


def _start_server(repo_path: str, port: int) -> tuple[int, str]:
    """Start the runtime server in background with SQLite storage.

    Returns (port, mcp_url).
    """
    actual_port = _find_free_port(port)
    if actual_port != port:
        click.secho(f"  Port {port} in use — using {actual_port}", fg=theme.WARNING)

    # SQLite database in the repo's .glyphh directory
    repo_glyphh_dir = Path(repo_path).resolve() / ".glyphh"
    repo_glyphh_dir.mkdir(parents=True, exist_ok=True)
    db_path = repo_glyphh_dir / "code.db"

    env = os.environ.copy()
    env["DEPLOYMENT_MODE"] = "local"
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    env["GLYPHH_PORT"] = str(actual_port)

    # Start uvicorn as a background daemon
    _GLYPHH_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _GLYPHH_DIR / "code.log"

    cmd = [
        sys.executable, "-m", "uvicorn",
        "glyphh.server:app",
        "--host", "0.0.0.0",
        "--port", str(actual_port),
        "--workers", "1",
        "--log-level", "warning",
    ]

    log_fd = open(log_file, "a")
    proc = subprocess.Popen(
        cmd,
        stdout=log_fd,
        stderr=log_fd,
        start_new_session=True,
        env=env,
    )

    _PID_FILE.write_text(str(proc.pid))

    org_id = "local-dev-org"
    model_id = "code"
    mcp_url = f"http://localhost:{actual_port}/{org_id}/{model_id}/mcp"

    # Save state
    _STATE_FILE.write_text(json.dumps({
        "pid": proc.pid,
        "port": actual_port,
        "repo": str(Path(repo_path).resolve()),
        "mcp_url": mcp_url,
        "db_path": str(db_path),
    }))

    # Wait for server to be ready
    click.echo("  Starting server", nl=False)
    for _ in range(30):
        try:
            with socket.create_connection(("localhost", actual_port), timeout=1):
                click.echo(" ✓")
                return actual_port, mcp_url
        except (ConnectionRefusedError, OSError):
            click.echo(".", nl=False)
            time.sleep(0.5)

    click.echo()
    click.secho("  Warning: server may not be ready yet", fg=theme.WARNING)
    return actual_port, mcp_url


def _configure_claude_code(repo_path: str, mcp_url: str):
    """Configure Claude Code: MCP server, CLAUDE.md, hooks."""
    repo = Path(repo_path).resolve()

    # 1. Add MCP server to Claude Code
    try:
        result = subprocess.run(
            ["claude", "mcp", "add", "--transport", "http", "glyphh", mcp_url],
            capture_output=True,
            text=True,
            cwd=str(repo),
        )
        if result.returncode == 0:
            click.secho("  ✓ MCP server added to Claude Code", fg=theme.SUCCESS)
        else:
            click.secho(f"  ✗ Failed to add MCP server: {result.stderr.strip()[:100]}", fg=theme.WARNING)
            click.secho(f"    Run manually: claude mcp add --transport http glyphh {mcp_url}", fg=theme.TEXT_DIM)
    except FileNotFoundError:
        click.secho("  ✗ Claude Code CLI not found", fg=theme.WARNING)
        click.secho(f"    Install Claude Code, then run: claude mcp add --transport http glyphh {mcp_url}", fg=theme.TEXT_DIM)

    # 2. Copy CLAUDE.md if not present
    target_claude_md = repo / "CLAUDE.md"
    source_claude_md = _PACKAGE_DIR / "CLAUDE.md"
    if not target_claude_md.exists() and source_claude_md.exists():
        shutil.copy2(source_claude_md, target_claude_md)
        click.secho("  ✓ CLAUDE.md added to project root", fg=theme.SUCCESS)
    elif target_claude_md.exists():
        click.secho("  ○ CLAUDE.md already exists (skipped)", fg=theme.TEXT_DIM)

    # 3. Add hooks to .claude/settings.json
    claude_dir = repo / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_file = claude_dir / "settings.json"

    settings = {}
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
        except json.JSONDecodeError:
            pass

    # Add MCP tool permissions
    permissions = settings.setdefault("permissions", {})
    allow_list = permissions.setdefault("allow", [])
    mcp_permission = "mcp__glyphh__*"
    if mcp_permission not in allow_list:
        allow_list.append(mcp_permission)

    # Add hooks
    hooks = settings.setdefault("hooks", {})

    # PreToolUse hook — enforce glyphh_search
    enforce_script = _PACKAGE_DIR / "hooks" / "enforce-glyphh-search.sh"
    if enforce_script.exists():
        pre_hooks = hooks.setdefault("PreToolUse", [])
        hook_entry = {
            "matcher": "Grep|Glob",
            "hooks": [{"type": "command", "command": str(enforce_script)}],
        }
        # Check if already present
        existing_matchers = [h.get("matcher") for h in pre_hooks]
        if "Grep|Glob" not in existing_matchers:
            pre_hooks.append(hook_entry)

    # PostToolUse hook — incremental compile on commit
    compile_script = _PACKAGE_DIR / "hooks" / "post-commit-compile.sh"
    if compile_script.exists():
        post_hooks = hooks.setdefault("PostToolUse", [])
        hook_entry = {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": f"{compile_script} {repo}"}],
        }
        existing_cmds = [
            h.get("hooks", [{}])[0].get("command", "")
            for h in post_hooks
        ]
        if not any("post-commit-compile" in c for c in existing_cmds):
            post_hooks.append(hook_entry)

    settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    click.secho("  ✓ Hooks and permissions added to .claude/settings.json", fg=theme.SUCCESS)

    # 4. Add .glyphh/ to .gitignore
    gitignore = repo / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".glyphh/" not in content:
            with open(gitignore, "a") as f:
                f.write("\n# Glyphh local index\n.glyphh/\n")
            click.secho("  ✓ .glyphh/ added to .gitignore", fg=theme.SUCCESS)
    else:
        gitignore.write_text("# Glyphh local index\n.glyphh/\n")
        click.secho("  ✓ .gitignore created with .glyphh/", fg=theme.SUCCESS)


def run_init(path: str, port: int):
    """Full init: banner → compile → serve → configure Claude Code."""
    repo = str(Path(path).resolve())

    print_banner()

    # Check if already running
    existing = _is_server_running()
    if existing and existing.get("repo") == repo:
        click.secho("  Glyphh Code is already running for this repo.", fg=theme.WARNING)
        click.secho(f"  MCP: {existing.get('mcp_url', '?')}", fg=theme.ACCENT)
        click.echo()
        return

    click.secho(f"  Initializing: {repo}", fg=theme.TEXT, bold=True)
    click.echo()

    # Step 1: Start the server
    click.secho("  [1/3] Starting server...", fg=theme.MUTED)
    actual_port, mcp_url = _start_server(repo, port)

    # Step 2: Deploy model + compile
    click.secho("  [2/3] Compiling codebase...", fg=theme.MUTED)
    runtime_url = f"http://localhost:{actual_port}"
    _deploy_model(runtime_url)
    file_count = _compile_repo(repo, runtime_url)

    # Step 3: Configure Claude Code
    click.secho("  [3/3] Configuring Claude Code...", fg=theme.MUTED)
    _configure_claude_code(repo, mcp_url)

    click.echo()
    print_status(repo, actual_port, mcp_url, file_count)
    click.secho("  Restart Claude Code to activate. In VS Code: Cmd+Shift+P → 'Claude Code: Restart'", fg=theme.MUTED)
    click.echo()


def run_compile(path: str):
    """Recompile the index."""
    state = _is_server_running()
    if not state:
        click.secho("  No server running. Run: glyphh-code init", fg=theme.ERROR)
        return

    repo = str(Path(path).resolve())
    runtime_url = f"http://localhost:{state.get('port', 8002)}"

    click.secho(f"  Compiling: {repo}", fg=theme.TEXT)
    count = _compile_repo(repo, runtime_url)
    click.secho(f"  Done: {count} files indexed", fg=theme.SUCCESS)


def run_serve(path: str, port: int):
    """Start the server only (no compile, no Claude config)."""
    existing = _is_server_running()
    if existing:
        click.secho(f"  Server already running (PID {existing.get('pid', '?')})", fg=theme.WARNING)
        click.secho(f"  MCP: {existing.get('mcp_url', '?')}", fg=theme.ACCENT)
        return

    print_banner()
    actual_port, mcp_url = _start_server(path, port)
    click.echo()
    click.secho(f"  MCP:  {mcp_url}", fg=theme.ACCENT)
    click.secho(f"  Docs: http://localhost:{actual_port}/docs", fg=theme.TEXT_DIM)
    click.echo()


def run_status():
    """Show current status."""
    state = _is_server_running()
    if not state:
        click.secho("  Glyphh Code is not running.", fg=theme.TEXT_DIM)
        click.secho("  Run: glyphh-code init /path/to/repo", fg=theme.MUTED)
        return

    click.echo()
    dot = click.style("●", fg=theme.SUCCESS)
    click.echo(f"  {dot} {click.style('running', fg=theme.SUCCESS)}")
    click.echo()
    click.secho(f"  Repo:    {state.get('repo', '?')}", fg=theme.TEXT_DIM)
    click.secho(f"  MCP:     {state.get('mcp_url', '?')}", fg=theme.ACCENT)
    click.secho(f"  PID:     {state.get('pid', '?')}", fg=theme.TEXT_DIM)
    click.secho(f"  Storage: {state.get('db_path', '?')}", fg=theme.TEXT_DIM)
    click.echo()
