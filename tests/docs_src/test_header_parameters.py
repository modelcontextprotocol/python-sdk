"""`docs/advanced/header-parameters.md`: every claim the page makes, proved against the real SDK."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

import httpx2
import pytest
from mcp_types import HEADER_MISMATCH, ListToolsResult, PaginatedRequestParams
from pydantic import Field, WithJsonSchema
from starlette.applications import Starlette

from docs_src.header_parameters import tutorial001, tutorial002, tutorial003
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer, Server, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult
from mcp.server.mcpserver.exceptions import InvalidSignature

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]

URL = "http://localhost:8000/mcp"
ARGUMENTS = {"title": "Dune", "region": "eu"}


@asynccontextmanager
async def check_stock_over_http(
    app: Starlette, mode: Literal["auto", "legacy"] = "auto"
) -> AsyncIterator[tuple[httpx2.AsyncClient, httpx2.Request]]:
    """List the tools and call `check_stock` over in-process HTTP; yield the HTTP client and the call's request."""
    requests: list[httpx2.Request] = []

    async def record(request: httpx2.Request) -> None:
        requests.append(request)

    async with (
        app.router.lifespan_context(app),
        httpx2.ASGITransport(app) as transport,
        httpx2.AsyncClient(transport=transport, event_hooks={"request": [record]}) as http,
        Client(streamable_http_client(URL, http_client=http), mode=mode) as client,
    ):
        await client.list_tools()
        result = await client.call_tool("check_stock", ARGUMENTS)
        assert not result.is_error
        yield http, next(request for request in requests if b'"tools/call"' in request.content)


@pytest.mark.parametrize(
    "app", [tutorial001.mcp.streamable_http_app(), tutorial002.app], ids=["tutorial001", "tutorial002"]
)
async def test_a_2026_http_client_sends_the_marked_argument_as_a_header_as_well(app: Starlette) -> None:
    """Both tutorials: `region` travels as `Mcp-Param-Region` and stays in the body; `title` is body only."""
    async with check_stock_over_http(app) as (_, call):
        assert {k: v for k, v in call.headers.items() if k.startswith("mcp-param-")} == {"mcp-param-region": "eu"}
        assert b'"region":"eu"' in call.content


async def test_a_call_whose_header_and_body_disagree_is_rejected() -> None:
    """tutorial001: the client's own request, replayed with a different `Mcp-Param-Region`, is a 400."""
    async with check_stock_over_http(tutorial001.mcp.streamable_http_app()) as (http, call):
        tampered = await http.post(URL, content=call.content, headers={**call.headers, "mcp-param-region": "us"})
    assert tampered.status_code == 400
    assert tampered.json()["error"]["code"] == HEADER_MISMATCH


async def test_a_legacy_http_connection_ignores_the_annotation() -> None:
    """tutorial001: before 2026-07-28 the same call succeeds and carries no `Mcp-Param-*` header."""
    async with check_stock_over_http(tutorial001.mcp.streamable_http_app(), mode="legacy") as (_, call):
        assert not [name for name in call.headers if name.startswith("mcp-param-")]


async def test_a_connection_that_is_not_http_ignores_the_annotation() -> None:
    """tutorial001: in memory there are no headers to send, and the call succeeds all the same."""
    async with Client(tutorial001.mcp) as client:
        assert client.protocol_version == "2026-07-28"
        result = await client.call_tool("check_stock", ARGUMENTS)
    assert result.structured_content == {"result": "Dune: 3 copies in eu."}


async def test_int_and_bool_arguments_can_be_marked() -> None:
    """`str` is tutorial001; `int` and `bool` register too, and a 2026-07-28 client keeps the tool."""
    mcp = MCPServer("Bookshop")

    @mcp.tool()
    def reserve(
        copies: Annotated[int, Field(json_schema_extra={"x-mcp-header": "Copies"})],
        gift: Annotated[bool, Field(json_schema_extra={"x-mcp-header": "Gift"})],
    ) -> None:
        """Never called: registering and listing it is the claim."""

    async with Client(mcp) as client:
        assert [tool.name for tool in (await client.list_tools()).tools] == ["reserve"]


async def test_any_other_type_is_refused_when_the_tool_is_registered() -> None:
    """A marked `list[str]` raises `InvalidSignature` from the decorator, before any client connects."""
    mcp = MCPServer("Bookshop")
    with pytest.raises(InvalidSignature):

        @mcp.tool()
        def check_stock(regions: Annotated[list[str], Field(json_schema_extra={"x-mcp-header": "Regions"})]) -> None:
            """Never called: the decoration itself is what raises."""

    assert await mcp.list_tools() == []


async def test_a_plain_optional_argument_is_refused_and_the_spelled_out_schema_registers() -> None:
    """`str | None` has no single `type`, so it is refused; the page's `WithJsonSchema` spelling is kept."""
    mcp = MCPServer("Bookshop")
    with pytest.raises(InvalidSignature):

        @mcp.tool()
        def refused(region: Annotated[str | None, Field(json_schema_extra={"x-mcp-header": "Region"})] = None) -> None:
            """Never called: the decoration itself is what raises."""

    @mcp.tool()
    def check_stock(
        region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None,
    ) -> str:
        """Count the copies of a book in one region's warehouses."""
        return f"3 copies in {region}."

    async with Client(mcp) as client:
        assert [tool.name for tool in (await client.list_tools()).tools] == ["check_stock"]
        result = await client.call_tool("check_stock", {})
    assert result.structured_content == {"result": "3 copies in None."}


async def test_the_low_level_server_serves_an_invalid_annotation_and_a_2026_client_leaves_the_tool_out() -> None:
    """tutorial002's tool with `region` turned into an array: a legacy client is shown it, a 2026-07-28 one is not."""
    properties = {"region": {"type": "array", "x-mcp-header": "Region"}}
    invalid = tutorial002.CHECK_STOCK.model_copy(update={"input_schema": {"type": "object", "properties": properties}})

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[invalid])

    server = Server("Bookshop", on_list_tools=list_tools)
    async with Client(server, mode="legacy") as legacy:
        assert [tool.name for tool in (await legacy.list_tools()).tools] == ["check_stock"]
    async with Client(server) as modern:
        assert modern.protocol_version == "2026-07-28"
        assert (await modern.list_tools()).tools == []


@pytest.mark.parametrize(
    ("server", "expected"),
    [(tutorial002.server, ["tools/list", "tools/call"]), (tutorial003.server, ["tools/call"])],
    ids=["tutorial002", "tutorial003"],
)
async def test_a_call_runs_the_list_handler_unless_the_server_looks_schemas_up_by_name(
    server: Server, expected: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """tutorial002 and tutorial003: the client's own `tools/call`, replayed, dispatches a `tools/list` first
    on the server without `get_tool_input_schema` and only itself on the server with it."""
    dispatched: list[str] = []

    async def record(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        dispatched.append(ctx.method)
        return await call_next(ctx)

    monkeypatch.setattr(server, "middleware", [*server.middleware, record])
    async with check_stock_over_http(server.streamable_http_app()) as (http, call):
        dispatched.clear()
        replayed = await http.post(URL, content=call.content, headers=call.headers)
    assert replayed.status_code == 200
    assert dispatched == expected


async def test_the_schema_the_lookup_returns_is_the_one_the_header_is_checked_against() -> None:
    """tutorial003: the client's own request, replayed with a different `Mcp-Param-Region`, is a 400."""
    async with check_stock_over_http(tutorial003.app) as (http, call):
        tampered = await http.post(URL, content=call.content, headers={**call.headers, "mcp-param-region": "us"})
    assert tampered.status_code == 400
    assert tampered.json()["error"]["code"] == HEADER_MISMATCH
