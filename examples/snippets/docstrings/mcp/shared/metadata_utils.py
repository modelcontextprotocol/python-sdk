"""Companion examples for src/mcp/shared/metadata_utils.py docstrings."""

from __future__ import annotations

from mcp.client.session import ClientSession
from mcp.shared.metadata_utils import get_display_name


async def get_display_name_usage(session: ClientSession) -> None:
    # region get_display_name_usage
    # In a client displaying available tools
    tools = await session.list_tools()
    for tool in tools.tools:
        display_name = get_display_name(tool)
        print(f"Available tool: {display_name}")
    # endregion get_display_name_usage
