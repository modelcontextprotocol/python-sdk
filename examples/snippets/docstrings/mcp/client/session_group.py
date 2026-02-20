"""Companion examples for src/mcp/client/session_group.py docstrings."""

from __future__ import annotations

from typing import Any

from mcp.client.session_group import ClientSessionGroup


async def ClientSessionGroup_usage(server_params: list[Any]) -> None:
    # region ClientSessionGroup_usage
    def name_fn(name: str, server_info: Any) -> str:
        return f"{server_info.name}_{name}"

    async with ClientSessionGroup(component_name_hook=name_fn) as group:
        for server_param in server_params:
            await group.connect_to_server(server_param)
        ...
    # endregion ClientSessionGroup_usage
