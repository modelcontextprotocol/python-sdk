from __future__ import annotations

import pytest
from logfire.testing import CaptureLogfire

from mcp import types
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer

pytestmark = pytest.mark.anyio


# Logfire warns about propagated trace context by default (distributed_tracing=None).
# This is expected here since we're testing cross-boundary context propagation.
@pytest.mark.filterwarnings("ignore::RuntimeWarning")
async def test_client_and_server_spans(capfire: CaptureLogfire):
    """Verify that calling a tool produces client and server spans with correct attributes."""
    server = MCPServer("test")

    @server.tool()
    def greet(name: str) -> str:
        """Greet someone."""
        return f"Hello, {name}!"

    async with Client(server) as client:
        result = await client.call_tool("greet", {"name": "World"})

    assert isinstance(result.content[0], types.TextContent)
    assert result.content[0].text == "Hello, World!"

    spans = capfire.exporter.exported_spans_as_dict()
    span_names = {s["name"] for s in spans}

    assert "MCP send tools/call greet" in span_names
    assert "MCP handle tools/call greet" in span_names

    client_span = next(s for s in spans if s["name"] == "MCP send tools/call greet")
    server_span = next(s for s in spans if s["name"] == "MCP handle tools/call greet")

    assert client_span["attributes"]["rpc.system"] == "mcp"
    assert client_span["attributes"]["rpc.method"] == "tools/call"
    assert client_span["attributes"]["mcp.method.name"] == "tools/call"
    assert server_span["attributes"]["rpc.system"] == "mcp"
    assert server_span["attributes"]["rpc.service"] == "test"
    assert server_span["attributes"]["rpc.method"] == "tools/call"
    assert server_span["attributes"]["mcp.method.name"] == "tools/call"

    # Server span should be in the same trace as the client span (context propagation).
    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
async def test_resource_read_spans_include_resource_uri(capfire: CaptureLogfire):
    """Verify that resource reads include MCP resource and RPC attributes."""
    server = MCPServer("test")

    @server.resource("test://resource")
    def test_resource() -> str:
        return "hello"

    async with Client(server) as client:
        result = await client.read_resource("test://resource")

    assert result.contents[0].uri == "test://resource"

    spans = capfire.exporter.exported_spans_as_dict()

    client_span = next(s for s in spans if s["name"] == "MCP send resources/read")
    server_span = next(s for s in spans if s["name"] == "MCP handle resources/read")

    assert client_span["attributes"]["rpc.system"] == "mcp"
    assert client_span["attributes"]["rpc.method"] == "resources/read"
    assert client_span["attributes"]["mcp.method.name"] == "resources/read"
    assert client_span["attributes"]["mcp.resource.uri"] == "test://resource"

    assert server_span["attributes"]["rpc.system"] == "mcp"
    assert server_span["attributes"]["rpc.service"] == "test"
    assert server_span["attributes"]["rpc.method"] == "resources/read"
    assert server_span["attributes"]["mcp.method.name"] == "resources/read"
    assert server_span["attributes"]["mcp.resource.uri"] == "test://resource"

    # Server span should be in the same trace as the client span (context propagation).
    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
async def test_completion_spans_include_resource_template_uri(capfire: CaptureLogfire):
    """Verify completion spans include the referenced resource template URI."""
    server = MCPServer("test")

    @server.completion()
    async def handle_completion(
        ref: types.ResourceTemplateReference | types.PromptReference,
        argument: types.CompletionArgument,
        context: types.CompletionContext | None,
    ) -> types.Completion:
        assert isinstance(ref, types.ResourceTemplateReference)
        assert argument.name == "path"
        assert argument.value == "rea"
        assert context is None
        return types.Completion(values=["README.md"])

    async with Client(server) as client:
        result = await client.complete(
            ref=types.ResourceTemplateReference(type="ref/resource", uri="repo://files/{path}"),
            argument={"name": "path", "value": "rea"},
        )

    assert result.completion.values == ["README.md"]

    spans = capfire.exporter.exported_spans_as_dict()

    client_span = next(s for s in spans if s["name"] == "MCP send completion/complete")
    server_span = next(s for s in spans if s["name"] == "MCP handle completion/complete")

    assert client_span["attributes"]["rpc.system"] == "mcp"
    assert client_span["attributes"]["rpc.method"] == "completion/complete"
    assert client_span["attributes"]["mcp.method.name"] == "completion/complete"
    assert client_span["attributes"]["mcp.resource.uri"] == "repo://files/{path}"

    assert server_span["attributes"]["rpc.system"] == "mcp"
    assert server_span["attributes"]["rpc.service"] == "test"
    assert server_span["attributes"]["rpc.method"] == "completion/complete"
    assert server_span["attributes"]["mcp.method.name"] == "completion/complete"
    assert server_span["attributes"]["mcp.resource.uri"] == "repo://files/{path}"
    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]
