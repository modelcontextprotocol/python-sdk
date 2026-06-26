"""`docs/run/asgi.md`: every claim the page makes, proved against the real SDK."""

import inspect

import httpx
import pytest
from mcp_types import TextContent
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Mount, Route

from docs_src.asgi import tutorial001, tutorial002, tutorial003, tutorial004, tutorial005, tutorial006
from mcp import Client
from mcp.server import MCPServer

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_streamable_http_app_is_a_starlette_app_with_one_route() -> None:
    """tutorial001: the factory returns a Starlette application with a single route at `/mcp`."""
    (route,) = tutorial001.app.routes
    assert isinstance(route, Route)
    assert route.path == "/mcp"


async def test_the_server_behind_the_app_is_unchanged() -> None:
    """tutorial001: wrapping the server in an ASGI app changes nothing about its tools."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("add_note", {"text": "milk"})
        assert result.content == [TextContent(type="text", text="Saved: milk")]
        assert result.structured_content == {"result": "Saved: milk"}


async def test_streamable_http_app_takes_runs_options_except_port() -> None:
    """The tip: every `run("streamable-http", ...)` option is here except `port`. `host` is one of them."""
    parameters = set(inspect.signature(MCPServer.streamable_http_app).parameters) - {"self"}
    assert parameters == {
        "streamable_http_path",
        "json_response",
        "stateless_http",
        "event_store",
        "retry_interval",
        "transport_security",
        "host",
    }


async def test_a_request_before_the_session_manager_runs_is_rejected() -> None:
    """The `!!! check`: nothing starts the session manager except its lifespan."""
    transport = httpx.ASGITransport(app=tutorial001.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
        with pytest.raises(RuntimeError, match=r"Task group is not initialized\. Make sure to use run\(\)\."):
            await http.post("/mcp")


async def test_mounting_at_the_root_keeps_the_default_path() -> None:
    """tutorial002: `Mount("/")` plus the default `streamable_http_path` leaves the endpoint at `/mcp`."""
    (mount,) = tutorial002.app.routes
    assert isinstance(mount, Mount)
    assert mount.path == ""
    (inner,) = mount.routes
    assert isinstance(inner, Route)
    assert inner.path == "/mcp"


async def test_a_root_mount_swallows_routes_listed_after_it() -> None:
    """The mounting bullet: `Mount("/")` matches every path, so your own routes go before it in the list."""

    async def about(request: Request) -> Response:
        return PlainTextResponse("about")

    mcp_app = MCPServer("Notes").streamable_http_app()
    listed_after = Starlette(routes=[Mount("/", app=mcp_app), Route("/about", about)])
    listed_before = Starlette(routes=[Route("/about", about), Mount("/", app=mcp_app)])

    transport = httpx.ASGITransport(app=listed_after)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
        assert (await http.get("/about")).status_code == 404

    transport = httpx.ASGITransport(app=listed_before)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
        assert (await http.get("/about")).status_code == 200


async def test_the_host_lifespan_enters_the_session_manager() -> None:
    """tutorial002: the host app's lifespan owns `session_manager.run()` and starts and stops cleanly."""
    async with tutorial002.lifespan(tutorial002.app):
        async with Client(tutorial002.mcp) as client:
            result = await client.call_tool("add_note", {"text": "milk"})
            assert result.structured_content == {"result": "Saved: milk"}


async def test_two_servers_get_two_mounts() -> None:
    """tutorial003: each server is mounted under its own prefix, each still ending in `/mcp`."""
    notes_mount, tasks_mount = tutorial003.app.routes
    assert isinstance(notes_mount, Mount)
    assert isinstance(tasks_mount, Mount)
    assert notes_mount.path == "/notes"
    assert tasks_mount.path == "/tasks"


async def test_one_lifespan_starts_both_session_managers() -> None:
    """tutorial003: a single `AsyncExitStack` lifespan runs both managers; both servers answer."""
    async with tutorial003.lifespan(tutorial003.app):
        async with Client(tutorial003.notes) as client:
            notes_result = await client.call_tool("add_note", {"text": "milk"})
            assert notes_result.structured_content == {"result": "Saved: milk"}
        async with Client(tutorial003.tasks) as client:
            tasks_result = await client.call_tool("add_task", {"title": "ship"})
            assert tasks_result.structured_content == {"result": "Created: ship"}


async def test_streamable_http_path_moves_the_endpoint_to_the_mount_prefix() -> None:
    """tutorial004: `streamable_http_path="/"` makes the `Mount` prefix the whole public path."""
    (mount,) = tutorial004.app.routes
    assert isinstance(mount, Mount)
    assert mount.path == "/notes"
    (inner,) = mount.routes
    assert isinstance(inner, Route)
    assert inner.path == "/"


async def test_cors_exposes_the_session_id_header() -> None:
    """tutorial005: the browser origin gets the three MCP methods and can read `Mcp-Session-Id`."""
    (middleware,) = tutorial005.app.user_middleware
    assert middleware.cls is CORSMiddleware
    transport = httpx.ASGITransport(app=tutorial005.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
        preflight = await http.options(
            "/mcp",
            headers={"Origin": "https://app.example.com", "Access-Control-Request-Method": "POST"},
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-methods"] == "GET, POST, DELETE"

        response = await http.get("/not-the-endpoint", headers={"Origin": "https://app.example.com"})
        assert response.headers["access-control-allow-origin"] == "https://app.example.com"
        assert response.headers["access-control-expose-headers"] == "Mcp-Session-Id"


async def test_custom_route_lands_next_to_the_mcp_endpoint() -> None:
    """tutorial006: `@mcp.custom_route()` adds a plain Starlette route to the returned app."""
    mcp_route, health_route = tutorial006.app.routes
    assert isinstance(mcp_route, Route)
    assert isinstance(health_route, Route)
    assert mcp_route.path == "/mcp"
    assert health_route.path == "/health"


async def test_the_health_check_answers_outside_the_protocol() -> None:
    """tutorial006: `GET /health` is ordinary HTTP, with no session manager and no MCP."""
    transport = httpx.ASGITransport(app=tutorial006.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
        response = await http.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
