"""INDI Allsky Model Context Protocol (MCP) Server."""

import logging
import argparse
import sys
from typing import Optional

from mcp.server.mcpserver import MCPServer

from .tools_config import register_config_tools
from .tools_images import register_image_tools
from .tools_simulator import register_simulator_tools
from .tools_astrometry import register_astrometry_tools
from .tools_hardware import register_hardware_tools
from .tools_darks import register_dark_tools
from .tools_ops import register_ops_tools
from .tools_ephemeris import register_ephemeris_tools
from .resources import register_resources
from .prompts import register_prompts

logger = logging.getLogger('indi_allsky.mcp')


def create_mcp_server(name: str = "indi-allsky-mcp") -> MCPServer:
    """Instantiate and configure the comprehensive INDI Allsky MCPServer.

    Args:
        name: Identifier name for the MCP server.

    Returns:
        Configured MCPServer instance with all tools, resources, and prompts registered.
    """
    server = MCPServer(name)

    # Register toolsets
    register_config_tools(server)
    register_image_tools(server)
    register_simulator_tools(server)
    register_astrometry_tools(server)
    register_hardware_tools(server)
    register_dark_tools(server)
    register_ops_tools(server)
    register_ephemeris_tools(server)

    # Register resources & prompt workflows
    register_resources(server)
    register_prompts(server)

    return server


def main(transport: str = "sse", host: str = "0.0.0.0", port: int = 8000) -> None:
    """CLI entry point for running the MCP server."""
    server = create_mcp_server()
    if transport == "sse":
        server.run(transport="sse", host=host, port=port)
    elif transport == "streamable-http":
        server.run(transport="streamable-http", host=host, port=port)
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
