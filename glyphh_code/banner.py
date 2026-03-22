"""
Banner for the glyphh-code CLI.
Reuses the Glyphh brand theme from the runtime.
"""

import sys
import time
import click

try:
    from glyphh.cli import theme
except ImportError:
    # Fallback if runtime not installed yet
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


# Characters per second for streaming effect
_CPS = 800


def _stream(text: str, fg: str | None = None, bold: bool = False):
    """Print text character-by-character with optional color."""
    delay = 1.0 / _CPS
    styled = click.style(text, fg=fg, bold=bold) if (fg or bold) else text
    i = 0
    while i < len(styled):
        if styled[i] == '\x1b':
            j = i + 1
            while j < len(styled) and styled[j] != 'm':
                j += 1
            sys.stdout.write(styled[i:j + 1])
            i = j + 1
        else:
            sys.stdout.write(styled[i])
            sys.stdout.flush()
            time.sleep(delay)
            i += 1
    sys.stdout.write('\n')
    sys.stdout.flush()


def print_banner():
    """Print the glyphh-code welcome banner."""
    click.echo()
    _stream("        _             _     _             _", fg=theme.PRIMARY)
    _stream("   __ _| |_   _ _ __ | |__ | |__     __ _(_)", fg=theme.PRIMARY)
    _stream("  / _` | | | | | '_ \\| '_ \\| '_ \\   / _` | |", fg=theme.PRIMARY)
    _stream(" | (_| | | |_| | |_) | | | | | | | | (_| | |", fg=theme.ACCENT)
    _stream("  \\__, |_|\\__, | .__/|_| |_|_| |_|  \\__,_|_|", fg="cyan")
    _stream("  |___/   |___/|_|                      code", fg="bright_cyan")
    click.echo()
    _stream("  codebase intelligence for claude code", fg="bright_cyan")
    click.echo()


def print_status(repo: str, port: int, mcp_url: str, file_count: int):
    """Print init status after setup completes."""
    dot = click.style("●", fg=theme.SUCCESS)
    click.echo(f"  {dot} {click.style('ready', fg=theme.SUCCESS)}")
    click.echo()
    click.secho(f"  Repo:      {repo}", fg=theme.TEXT_DIM)
    click.secho(f"  Files:     {file_count} indexed", fg=theme.TEXT_DIM)
    click.secho(f"  MCP:       {mcp_url}", fg=theme.ACCENT)
    click.secho(f"  Storage:   SQLite (local)", fg=theme.TEXT_DIM)
    click.secho(f"  Auth:      none (local mode)", fg=theme.TEXT_DIM)
    click.echo()
