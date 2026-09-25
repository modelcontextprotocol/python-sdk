import importlib
import pkgutil
from typing import Any, get_type_hints

import anyio
import mcp_client
import mcp_types
import pytest

import mcp
from mcp.client import Transport
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import MCPServer


def test_client_exports_share_identity_with_the_full_sdk() -> None:
    """The package split preserves the SDK's existing client classes and exceptions."""
    for name in set(mcp_client.__all__) & set(mcp.__all__):
        assert vars(mcp_client)[name] is vars(mcp)[name]


def test_legacy_modules_export_the_extracted_implementations() -> None:
    """Public legacy modules retain their objects rather than loading a second implementation."""
    for info in pkgutil.walk_packages(mcp_client.__path__, prefix="mcp_client."):
        if any(part.startswith("_") for part in info.name.split(".")):
            continue
        implementation = importlib.import_module(info.name)
        legacy = importlib.import_module(info.name.replace("mcp_client.", "mcp.", 1))
        if info.ispkg:
            for name in vars(implementation).get("__all__", []):
                assert vars(legacy)[name] is vars(implementation)[name]
        else:
            assert legacy is implementation


def test_full_sdk_client_annotations_remain_resolvable() -> None:
    """The split keeps runtime annotation inspection available through the full SDK."""
    expected = Server[Any] | MCPServer | Transport | mcp.StdioServerParameters | str
    assert get_type_hints(mcp.Client.__init__)["server"] == expected


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_extracted_client_calls_an_in_process_sdk_server(mode: str) -> None:
    """Both distributions use the same protocol machinery for modern and legacy connections."""
    result = mcp_types.ListToolsResult(tools=[mcp_types.Tool(name="example", input_schema={"type": "object"})])

    async def list_tools(
        ctx: ServerRequestContext, params: mcp_types.PaginatedRequestParams | None
    ) -> mcp_types.ListToolsResult:
        return result

    server = Server("example", on_list_tools=list_tools)
    with anyio.fail_after(5):
        async with mcp_client.Client(server, mode=mode) as client:
            received = await client.list_tools()
            assert isinstance(received, mcp_types.ListToolsResult)
            assert received.tools == result.tools
