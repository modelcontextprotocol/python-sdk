"""Regression tests for issue #1574: URI fields are plain strings, not Pydantic AnyUrl.

AnyUrl rejected relative URIs like `users/me`, which the spec (it types `uri` as a plain
string) and the TypeScript SDK accept; the fix changed URI fields to `str`.
"""

import mcp_types as types
import pytest
from mcp_types import (
    ListResourcesResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    TextResourceContents,
)

from mcp import Client
from mcp.server import Server, ServerRequestContext

pytestmark = pytest.mark.anyio


async def test_relative_uri_roundtrip():
    """Reintroducing AnyUrl would fail serialization or transform relative URIs in flight."""

    async def handle_list_resources(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        return ListResourcesResult(
            resources=[
                types.Resource(name="user", uri="users/me"),
                types.Resource(name="config", uri="./config"),
                types.Resource(name="parent", uri="../parent/resource"),
            ]
        )

    async def handle_read_resource(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
        return ReadResourceResult(
            contents=[TextResourceContents(uri=str(params.uri), text=f"data for {params.uri}", mime_type="text/plain")]
        )

    server = Server("test", on_list_resources=handle_list_resources, on_read_resource=handle_read_resource)

    async with Client(server) as client:
        resources = await client.list_resources()
        uri_map = {r.uri: r for r in resources.resources}

        assert "users/me" in uri_map, f"Expected 'users/me' in {list(uri_map.keys())}"
        assert "./config" in uri_map, f"Expected './config' in {list(uri_map.keys())}"
        assert "../parent/resource" in uri_map, f"Expected '../parent/resource' in {list(uri_map.keys())}"

        for uri_str in ["users/me", "./config", "../parent/resource"]:
            result = await client.read_resource(uri_str)
            assert len(result.contents) == 1
            assert result.contents[0].uri == uri_str


async def test_custom_scheme_uri_roundtrip():
    async def handle_list_resources(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        return ListResourcesResult(
            resources=[
                types.Resource(name="custom", uri="custom://my-resource"),
                types.Resource(name="file", uri="file:///path/to/file"),
            ]
        )

    async def handle_read_resource(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
        return ReadResourceResult(
            contents=[TextResourceContents(uri=str(params.uri), text="data", mime_type="text/plain")]
        )

    server = Server("test", on_list_resources=handle_list_resources, on_read_resource=handle_read_resource)

    async with Client(server) as client:
        resources = await client.list_resources()
        uri_map = {r.uri: r for r in resources.resources}

        assert "custom://my-resource" in uri_map
        assert "file:///path/to/file" in uri_map

        result = await client.read_resource("custom://my-resource")
        assert len(result.contents) == 1


def test_uri_json_roundtrip_preserves_value():
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
    test_uris = ["users/me", "./relative", "custom://resource"]

    for uri_str in test_uris:
        contents = types.TextResourceContents(
            uri=uri_str,
            text="data",
            mime_type="text/plain",
        )
        json_data = contents.model_dump(mode="json")
        restored = types.TextResourceContents.model_validate(json_data)
        assert restored.uri == uri_str, f"URI mutated: {uri_str} -> {restored.uri}"
