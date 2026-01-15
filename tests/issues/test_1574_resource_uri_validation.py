"""Tests for issue #1574: Python SDK incorrectly validates Resource URIs.

The Python SDK previously used Pydantic's AnyUrl for URI fields, which rejected
relative paths like 'users/me' that are valid according to the MCP spec and
accepted by the TypeScript SDK.

The fix changed URI fields to plain strings to match the spec, which defines
uri fields as strings with no JSON Schema format validation.

These tests verify the fix works end-to-end through the JSON-RPC protocol.
"""

import pytest

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.shared.memory import (
    create_connected_server_and_client_session as client_session,
)

pytestmark = pytest.mark.anyio


async def test_relative_uri_roundtrip():
    """Relative URIs survive the full server-client JSON-RPC roundtrip.

    This is the critical regression test - if someone reintroduces AnyUrl,
    the server would fail to serialize resources with relative URIs,
    or the URI would be transformed during the roundtrip.
    """
    server = Server("test")

    @server.list_resources()
    async def list_resources():
        return [
            types.Resource(name="user", uri="users/me"),
            types.Resource(name="config", uri="./config"),
            types.Resource(name="parent", uri="../parent/resource"),
        ]

    @server.read_resource()
    async def read_resource(uri: str):
        return [
            ReadResourceContents(
                content=f"data for {uri}",
                mime_type="text/plain",
            )
        ]

    async with client_session(server) as client:
        # List should return the exact URIs we specified
        resources = await client.list_resources()
        uri_map = {r.uri: r for r in resources.resources}

        assert "users/me" in uri_map, f"Expected 'users/me' in {list(uri_map.keys())}"
        assert "./config" in uri_map, f"Expected './config' in {list(uri_map.keys())}"
        assert "../parent/resource" in uri_map, f"Expected '../parent/resource' in {list(uri_map.keys())}"

        # Read should work with each relative URI and preserve it in the response
        for uri_str in ["users/me", "./config", "../parent/resource"]:
            result = await client.read_resource(uri_str)
            assert len(result.contents) == 1
            assert result.contents[0].uri == uri_str


async def test_custom_scheme_uri_roundtrip():
    """Custom scheme URIs work through the protocol.

    Some MCP servers use custom schemes like "custom://resource".
    These should work end-to-end.
    """
    server = Server("test")

    @server.list_resources()
    async def list_resources():
        return [
            types.Resource(name="custom", uri="custom://my-resource"),
            types.Resource(name="file", uri="file:///path/to/file"),
        ]

    @server.read_resource()
    async def read_resource(uri: str):
        return [ReadResourceContents(content="data", mime_type="text/plain")]

    async with client_session(server) as client:
        resources = await client.list_resources()
        uri_map = {r.uri: r for r in resources.resources}

        assert "custom://my-resource" in uri_map
        assert "file:///path/to/file" in uri_map

        # Read with custom scheme
        result = await client.read_resource("custom://my-resource")
        assert len(result.contents) == 1


def test_uri_json_roundtrip_preserves_value():
    """URI is preserved exactly through JSON serialization.

    This catches any Pydantic validation or normalization that would
    alter the URI during the JSON-RPC message flow.
    """
    test_uris = [
        "users/me",
        "custom://resource",
        "./relative",
        "../parent",
        "file:///absolute/path",
        "https://example.com/path",
    ]

    for uri_str in test_uris:
        resource = types.Resource(name="test", uri=uri_str)
        json_data = resource.model_dump(mode="json")
        restored = types.Resource.model_validate(json_data)
        assert restored.uri == uri_str, f"URI mutated: {uri_str} -> {restored.uri}"


def test_resource_contents_uri_json_roundtrip():
    """TextResourceContents URI is preserved through JSON serialization."""
    test_uris = ["users/me", "./relative", "custom://resource"]

    for uri_str in test_uris:
        contents = types.TextResourceContents(
            uri=uri_str,
            text="data",
            mimeType="text/plain",
        )
        json_data = contents.model_dump(mode="json")
        restored = types.TextResourceContents.model_validate(json_data)
        assert restored.uri == uri_str, f"URI mutated: {uri_str} -> {restored.uri}"
