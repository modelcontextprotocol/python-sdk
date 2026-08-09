from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Literal, Protocol, cast

import pytest
from click import Command
from click.testing import CliRunner

from mcp.server.mcpserver.server import MCPServer

SERVER_ROOT = Path(__file__).parents[3] / "examples" / "servers" / "simple-auth"


class ServerModule(Protocol):
    main: Command


@pytest.mark.parametrize(
    ("transport", "endpoint"),
    [("streamable-http", "/mcp"), ("sse", "/sse")],
)
def test_selected_transport_uses_one_resource_path(
    monkeypatch: pytest.MonkeyPatch,
    load_example_module: Callable[[Path, str], ModuleType],
    transport: Literal["sse", "streamable-http"],
    endpoint: str,
) -> None:
    """The example advertises and serves the selected transport path."""
    server = cast(ServerModule, load_example_module(SERVER_ROOT, "mcp_simple_auth.server"))
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
