"""
glyphh-code CLI entry point.

Usage:
    glyphh-code init [path]    Set up Glyphh Code for a repository
    glyphh-code compile [path] Recompile the index
    glyphh-code serve [path]   Start the MCP server
    glyphh-code status         Show current status
"""

import click

from . import __version__


@click.group()
@click.version_option(__version__, prog_name="glyphh-code")
def cli():
    """Glyphh Code — codebase intelligence for Claude Code."""
    pass


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--port", "-p", default=8002, type=int, help="Server port (default: 8002)")
def init(path, port):
    """Set up Glyphh Code for a repository.

    Compiles the codebase, starts the MCP server, and configures Claude Code.
    Everything is local — no account, no Docker, no auth required.
    """
    from .setup import run_init
    run_init(path, port)


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True))
def compile(path):
    """Recompile the index for a repository."""
    from .setup import run_compile
    run_compile(path)


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--port", "-p", default=8002, type=int, help="Server port (default: 8002)")
def serve(path, port):
    """Start the MCP server."""
    from .setup import run_serve
    run_serve(path, port)


@cli.command()
def status():
    """Show Glyphh Code status."""
    from .setup import run_status
    run_status()


def main():
    cli()


if __name__ == "__main__":
    main()
