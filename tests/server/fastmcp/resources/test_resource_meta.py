"""Tests for _meta attribute support in FastMCP resources."""

import pytest
from pydantic import AnyUrl

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FunctionResource


@pytest.mark.anyio
async def test_resource_with_meta_direct_creation():
    """Test resource with _meta attribute via direct creation."""
    mcp = FastMCP()

    def get_data() -> str:
        return "data"

    resource = FunctionResource.from_function(
        fn=get_data,
        uri="resource://test",
        **{"_meta": {"widgetDomain": "example.com"}},
    )
    mcp.add_resource(resource)

    # Get the resource
    retrieved = await mcp._resource_manager.get_resource("resource://test")
    assert retrieved is not None
    assert retrieved.meta is not None
    assert retrieved.meta["widgetDomain"] == "example.com"

    # Read the resource and verify _meta is passed through
    contents = await mcp.read_resource("resource://test")
    assert len(contents) == 1
    assert contents[0].meta is not None
    assert contents[0].meta["widgetDomain"] == "example.com"


@pytest.mark.anyio
async def test_resource_with_meta_from_function():
    """Test creating a resource with _meta using from_function."""

    def get_data() -> str:
        return "data"

    resource = FunctionResource.from_function(
        fn=get_data,
        uri="resource://test",
        **{"_meta": {"custom": "value", "key": 123}},
    )

    assert resource.meta is not None
    assert resource.meta["custom"] == "value"
    assert resource.meta["key"] == 123


@pytest.mark.anyio
async def test_resource_without_meta():
    """Test that resources work correctly without _meta (backwards compatibility)."""
    mcp = FastMCP()

    @mcp.resource("resource://test")
    def get_test() -> str:
        """A test resource."""
        return "test data"

    # Get the resource
    resource = await mcp._resource_manager.get_resource("resource://test")
    assert resource is not None
    assert resource.meta is None

    # Read the resource and verify _meta is None
    contents = await mcp.read_resource("resource://test")
    assert len(contents) == 1
    assert contents[0].meta is None


@pytest.mark.anyio
async def test_resource_meta_end_to_end():
    """Test _meta attributes end-to-end with server handler."""
    mcp = FastMCP()

    def get_widget() -> str:
        """A widget resource."""
        return "widget content"

    resource = FunctionResource.from_function(
        fn=get_widget,
        uri="resource://widget",
        **{"_meta": {"widgetDomain": "example.com", "version": "1.0"}},
    )
    mcp.add_resource(resource)

    # Simulate the full request/response cycle
    # Get the handler
    handler = mcp._mcp_server.request_handlers[types.ReadResourceRequest]

    # Create a request
    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=AnyUrl("resource://widget")),
    )

    # Call the handler
    result = await handler(request)
    assert isinstance(result.root, types.ReadResourceResult)
    assert len(result.root.contents) == 1

    content = result.root.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.text == "widget content"
    assert content.meta is not None
    assert content.meta["widgetDomain"] == "example.com"
    assert content.meta["version"] == "1.0"


@pytest.mark.anyio
async def test_resource_meta_with_complex_nested_structure():
    """Test _meta with complex nested data structures."""
    mcp = FastMCP()

    complex_meta = {
        "widgetDomain": "example.com",
        "config": {"nested": {"value": 42}, "list": [1, 2, 3]},
        "tags": ["tag1", "tag2"],
    }

    def get_complex() -> str:
        """A resource with complex _meta."""
        return "complex data"

    resource = FunctionResource.from_function(
        fn=get_complex,
        uri="resource://complex",
        **{"_meta": complex_meta},
    )
    mcp.add_resource(resource)

    # Read the resource
    contents = await mcp.read_resource("resource://complex")
    assert len(contents) == 1
    assert contents[0].meta is not None
    assert contents[0].meta["widgetDomain"] == "example.com"
    assert contents[0].meta["config"]["nested"]["value"] == 42
    assert contents[0].meta["config"]["list"] == [1, 2, 3]
    assert contents[0].meta["tags"] == ["tag1", "tag2"]


@pytest.mark.anyio
async def test_resource_meta_json_serialization():
    """Test that _meta is correctly serialized as '_meta' in JSON output."""
    mcp = FastMCP()

    def get_widget() -> str:
        return "widget content"

    resource = FunctionResource.from_function(
        fn=get_widget,
        uri="resource://widget",
        **{"_meta": {"widgetDomain": "example.com", "version": "1.0"}},
    )
    mcp.add_resource(resource)

    # First check the resource itself serializes correctly
    resource_json = resource.model_dump(by_alias=True, mode="json")
    assert "_meta" in resource_json, "Expected '_meta' key in resource JSON"
    assert resource_json["_meta"]["widgetDomain"] == "example.com"

    # Get the full response through the handler
    handler = mcp._mcp_server.request_handlers[types.ReadResourceRequest]
    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=AnyUrl("resource://widget")),
    )
    result = await handler(request)

    # Serialize to JSON with aliases
    result_json = result.model_dump(by_alias=True, mode="json")

    # Verify _meta is in the JSON output (not "meta")
    content_json = result_json["root"]["contents"][0]
    assert "_meta" in content_json, "Expected '_meta' key in content JSON output"
    assert "meta" not in content_json or content_json.get("meta") is None, "Should not have 'meta' key in JSON output"
    assert content_json["_meta"]["widgetDomain"] == "example.com"
    assert content_json["_meta"]["version"] == "1.0"

    # Also verify in the JSON string
    result_json_str = result.model_dump_json(by_alias=True)
    assert '"_meta"' in result_json_str, "Expected '_meta' string in JSON output"

    # Verify the full structure matches expected MCP format
    assert content_json["uri"] == "resource://widget"
    assert content_json["text"] == "widget content"
    assert content_json["mimeType"] == "text/plain"
    assert content_json["_meta"]["widgetDomain"] == "example.com"
