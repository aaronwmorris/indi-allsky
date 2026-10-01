#!/usr/bin/env python3
"""INDI Allsky Model Context Protocol (MCP) Server CLI launcher."""

import argparse
import logging
import sys
from pathlib import Path

# Ensure package root is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from indi_allsky.mcp.server import main


def cli():
    parser = argparse.ArgumentParser(description="INDI Allsky Model Context Protocol (MCP) Server")
    parser.add_argument(
        "--transport",
        choices=["sse", "streamable-http", "stdio"],
        default="sse",
        help="Transport protocol (default: sse)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host interface for network transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for network transport (default: 8000)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Log verbosity level (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    main(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    cli()
