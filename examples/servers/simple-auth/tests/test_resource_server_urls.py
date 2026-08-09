from typing import Literal

import pytest
from click.testing import CliRunner
from mcp_simple_auth import server

from mcp.server.mcpserver.server import MCPServer


@pytest.mark.parametrize(
    ("transport", "endpoint"),
    [("streamable-http", "/mcp"), ("sse", "/sse")],
)
def test_selected_transport_uses_one_resource_path(
    monkeypatch: pytest.MonkeyPatch,
    transport: Literal["sse", "streamable-http"],
    endpoint: str,
) -> None:
    """The example advertises and serves the selected transport path."""
    created: list[MCPServer] = []
    run_arguments: list[dict[str, object]] = []

    def record_run(
        self: MCPServer,
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
        **kwargs: object,
    ) -> None:
        created.append(self)
        run_arguments.append({"transport": transport, "host": host, "port": port, **kwargs})

    monkeypatch.setattr(MCPServer, "run", record_run)
    result = CliRunner().invoke(server.main, ["--port", "8123", "--transport", transport])

    assert result.exit_code == 0, result.output
    auth = created[0].settings.auth
    assert auth is not None
    assert str(auth.resource_server_url) == f"http://localhost:8123{endpoint}"
    path_argument = "sse_path" if transport == "sse" else "streamable_http_path"
    assert run_arguments == [{"transport": transport, "host": "localhost", "port": 8123, path_argument: endpoint}]
