#!/usr/bin/env python3
"""INDI Allsky Model Context Protocol (MCP) Server CLI launcher."""

import argparse
import sys
from pathlib import Path

# Ensure package root is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from indi_allsky.mcp.server import main


def cli():
    parser = argparse.ArgumentParser(description="INDI Allsky Model Context Protocol (MCP) Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface for network transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for network transport (default: 8000)",
    )
    args = parser.parse_args()

    main(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    cli()
