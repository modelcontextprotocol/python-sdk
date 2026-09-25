import importlib
import pkgutil
import subprocess
import sys
from contextlib import AsyncExitStack
from typing import Any, get_type_hints

import anyio
import mcp_client
import mcp_types
import pytest
from typing_extensions import Self

import mcp
from mcp.client import Transport
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import MCPServer


class ContextManagedServer(Server):
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class ContextManagedMCPServer(MCPServer):
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


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


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("server_type", [ContextManagedServer, ContextManagedMCPServer])
async def test_servers_take_precedence_over_context_manager_transports(
    server_type: type[ContextManagedServer] | type[ContextManagedMCPServer], mode: str
) -> None:
    """The SDK connects server subclasses in-process even when they also manage an async context."""
    name = "context-managed-server"
    server = server_type(name)
    with anyio.fail_after(5):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(server)
            client = await stack.enter_async_context(mcp_client.Client(server, mode=mode))
            assert client.server_info is not None
            assert client.server_info.name == name


@pytest.mark.parametrize("first_import", ["mcp", "mcp_client"])
def test_full_sdk_imports_preserve_module_attributes_and_exception_names(first_import: str) -> None:
    """The SDK keeps its namespace in either import order.

    A fresh interpreter prevents other tests from populating missing module attributes.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import {first_import}\n"
            + """
import pickle

import mcp
import mcp_client

for name in (
    "caching", "client", "context", "extension", "session", "session_group",
    "sse", "stdio", "streamable_http", "subscriptions",
):
    assert vars(mcp.client)[name] is vars(mcp_client.client)[name], name

import mcp.client.auth
import mcp_client.client.auth

for name in ("exceptions", "oauth2", "utils"):
    assert vars(mcp.client.auth)[name] is vars(mcp_client.client.auth)[name], name

for name in ("MCPError", "MCPDeprecationWarning", "NoBackChannelError", "UrlElicitationRequiredError"):
    error_type = vars(mcp.shared.exceptions)[name]
    assert error_type is vars(mcp_client.shared.exceptions)[name]
    assert error_type.__module__ == "mcp.shared.exceptions", name
    assert pickle.loads(pickle.dumps(error_type)) is error_type
""",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
