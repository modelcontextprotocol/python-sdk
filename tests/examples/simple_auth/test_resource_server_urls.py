from typing import Literal

import httpx2
import pytest
from click.testing import CliRunner, Result
from mcp_simple_auth import server

from mcp.server.mcpserver.server import MCPServer


def invoke_resource_server(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> tuple[Result, list[MCPServer], list[dict[str, object]]]:
    created: list[MCPServer] = []
    run_calls: list[dict[str, object]] = []

    def fake_run(
        self: MCPServer,
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
        **kwargs: object,
    ) -> None:
        created.append(self)
        run_calls.append({"transport": transport, "host": host, "port": port, **kwargs})

    monkeypatch.setattr(MCPServer, "run", fake_run)
    return CliRunner().invoke(server.main, args), created, run_calls


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("transport", "expected_path", "method"),
    [("streamable-http", "/mcp", "POST"), ("sse", "/sse", "GET")],
)
async def test_selected_transport_determines_the_advertised_resource(
    monkeypatch: pytest.MonkeyPatch,
    transport: Literal["sse", "streamable-http"],
    expected_path: str,
    method: str,
) -> None:
    """The PRM document and unauthorized response identify the selected public endpoint."""
    result, created, run_calls = invoke_resource_server(monkeypatch, ["--port", "8123", "--transport", transport])

    assert result.exit_code == 0, result.output
    path_argument = "sse_path" if transport == "sse" else "streamable_http_path"
    assert run_calls == [{"transport": transport, "host": "localhost", "port": 8123, path_argument: expected_path}]

    resource_url = f"http://localhost:8123{expected_path}"
    metadata_path = f"/.well-known/oauth-protected-resource{expected_path}"
    app = created[0].sse_app() if transport == "sse" else created[0].streamable_http_app()
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://localhost:8123") as client:
        metadata = await client.get(metadata_path)
        unauthorized = await client.request(method, expected_path)

    assert metadata.status_code == 200
    assert metadata.json()["resource"] == resource_url
    assert unauthorized.status_code == 401
    assert f'resource_metadata="http://localhost:8123{metadata_path}"' in unauthorized.headers["www-authenticate"]


@pytest.mark.anyio
async def test_an_explicit_public_resource_url_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reverse-proxy URL is advertised verbatim without internal-route rewriting."""
    public_url = "https://mcp.example.com/services/time/mcp?tenant=alpha"
    result, created, run_calls = invoke_resource_server(
        monkeypatch,
        [
            "--port",
            "8123",
            "--transport",
            "streamable-http",
            "--resource-server-url",
            public_url,
        ],
    )

    assert result.exit_code == 0, result.output
    assert run_calls == [
        {
            "transport": "streamable-http",
            "host": "localhost",
            "port": 8123,
            "streamable_http_path": "/mcp",
        }
    ]

    app = created[0].streamable_http_app()
    metadata_path = "/.well-known/oauth-protected-resource/services/time/mcp"
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://localhost:8123") as client:
        metadata = await client.get(metadata_path)

    assert metadata.status_code == 200
    assert metadata.json()["resource"] == public_url
