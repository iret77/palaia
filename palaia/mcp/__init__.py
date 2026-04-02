"""palaia MCP Server — expose palaia memory via Model Context Protocol.

Works with Claude Desktop, Cursor, and any MCP-compatible host.
Independent of OpenClaw — palaia as a standalone memory layer.

Usage:
    palaia-mcp                          # stdio transport (default)
    palaia-mcp --root /path/to/.palaia  # explicit store root
    palaia-mcp --read-only              # no writes allowed
    palaia mcp-server                   # via CLI subcommand
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    """Entry point for `palaia-mcp` and `palaia mcp-server`."""
    parser = argparse.ArgumentParser(
        prog="palaia-mcp",
        description="palaia MCP Server — local memory for AI agents via MCP",
    )
    parser.add_argument(
        "--root",
        help="Path to .palaia directory (default: auto-detect via PALAIA_HOME or cwd)",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Disable write operations (store, edit, gc)",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )

    args = parser.parse_args(argv)

    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except ImportError:
        print(
            "Error: MCP SDK not installed. Install with: pip install 'palaia[mcp]'",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from palaia.config import find_palaia_root

    # Resolve store root
    if args.root:
        root = Path(args.root)
        if not root.exists():
            print(f"Error: {root} does not exist", file=sys.stderr)
            sys.exit(1)
        if root.name != ".palaia" and (root / ".palaia").exists():
            root = root / ".palaia"
    else:
        found = find_palaia_root()
        if found is None:
            print(
                "Error: No .palaia store found. Run 'palaia init' first, "
                "or use --root to specify the path.",
                file=sys.stderr,
            )
            sys.exit(1)
        root = found

    from palaia.mcp.server import create_server

    server = create_server(root, read_only=args.read_only)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
