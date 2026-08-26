import base64
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import httpx2
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    AudioContent,
    BlobResourceContents,
    CallToolResult,
    ClientCapabilities,
    Completion,
    CompletionArgument,
    CompletionContext,
    ContentBlock,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    EmbeddedResource,
    ErrorData,
    GetPromptResult,
    Icon,
    ImageContent,
    InputRequiredResult,
    InputResponses,
    ListPromptsResult,
    ListRootsRequest,
    Prompt,
    PromptArgument,
    PromptMessage,
    PromptReference,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    TextContent,
    TextResourceContents,
)
from pydantic import AfterValidator, BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from typing_extensions import NotRequired, TypedDict

from mcp.client import Client
from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer, RequestStateSecurity, Resolve, ResourceSecurity
from mcp.server.mcpserver.exceptions import (
    ResourceError,
    ResourceNotFoundError,
    ToolError,
    UnexpectedResourceError,
    UnexpectedToolError,
)
from mcp.server.mcpserver.prompts.base import Message, UserMessage
from mcp.server.mcpserver.resources import FileResource, FunctionResource
from mcp.server.mcpserver.resources import Resource as MCPServerResource
from mcp.server.mcpserver.utilities.types import Audio, Image
from mcp.server.subscriptions import (
    InMemorySubscriptionBus,
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    ServerEvent,
    ToolsListChanged,
)
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.shared.uri_template import InvalidUriTemplate

pytestmark = pytest.mark.anyio


class TestServer:
    async def test_create_server(self):
        mcp = MCPServer(
            title="MCPServer Server",
            description="Server description",
            instructions="Server instructions",
            website_url="https://example.com/mcp_server",
            version="1.0",
            icons=[Icon(src="https://example.com/icon.png", mime_type="image/png", sizes=["48x48", "96x96"])],
        )
        assert mcp.name == "mcp-server"
        assert mcp.title == "MCPServer Server"
        assert mcp.description == "Server description"
        assert mcp.instructions == "Server instructions"
        assert mcp.website_url == "https://example.com/mcp_server"
        assert mcp.version == "1.0"
        assert isinstance(mcp.icons, list)
        assert len(mcp.icons) == 1
        assert mcp.icons[0].src == "https://example.com/icon.png"

    def test_dependencies(self):
        """Dependencies list is read by `mcp install` / `mcp dev` CLI commands."""
        mcp = MCPServer("test", dependencies=["pandas", "numpy"])
        assert mcp.dependencies == ["pandas", "numpy"]
        assert mcp.settings.dependencies == ["pandas", "numpy"]

        mcp_no_deps = MCPServer("test")
        assert mcp_no_deps.dependencies == []

    async def test_sse_app_returns_starlette_app(self):
        """Test that sse_app returns a Starlette application with correct routes."""
        mcp = MCPServer("test")
        # Use host="0.0.0.0" to avoid auto DNS protection
        app = mcp.sse_app(host="0.0.0.0")

        assert isinstance(app, Starlette)

        # Verify routes exist
        sse_routes = [r for r in app.routes if isinstance(r, Route)]
        mount_routes = [r for r in app.routes if isinstance(r, Mount)]

        assert len(sse_routes) == 1, "Should have one SSE route"
        assert len(mount_routes) == 1, "Should have one mount route"
        assert sse_routes[0].path == "/sse"
        assert mount_routes[0].path == "/messages"

    async def test_non_ascii_description(self):
        """Test that MCPServer handles non-ASCII characters in descriptions correctly"""
        mcp = MCPServer()

        @mcp.tool(description=("🌟 This tool uses emojis and UTF-8 characters: á é í ó ú ñ 漢字 🎉"))
        def hello_world(name: str = "世界") -> str:
            return f"¡Hola, {name}! 👋"

        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 1
            tool = tools.tools[0]
            assert tool.description is not None
            assert "🌟" in tool.description
            assert "漢字" in tool.description
            assert "🎉" in tool.description

            result = await client.call_tool("hello_world", {})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert "¡Hola, 世界! 👋" == content.text

    async def test_add_tool_decorator(self):
        mcp = MCPServer()

        @mcp.tool()
        def sum(x: int, y: int) -> int:  # pragma: no cover
            return x + y

        assert len(mcp._tool_manager.list_tools()) == 1

    async def test_add_tool_decorator_incorrect_usage(self):
        mcp = MCPServer()

        with pytest.raises(TypeError, match="The @tool decorator was used incorrectly"):

            @mcp.tool  # Missing parentheses #type: ignore
            def sum(x: int, y: int) -> int:  # pragma: no cover
                return x + y

    async def test_add_resource_decorator(self):
        mcp = MCPServer()

        @mcp.resource("r://{x}")
        def get_data(x: str) -> str:  # pragma: no cover
            return f"Data: {x}"

        assert len(mcp._resource_manager._templates) == 1

    async def test_add_resource_decorator_incorrect_usage(self):
        mcp = MCPServer()

        with pytest.raises(TypeError, match="The @resource decorator was used incorrectly"):

            @mcp.resource  # Missing parentheses #type: ignore
            def get_data(x: str) -> str:  # pragma: no cover
                return f"Data: {x}"


class TestDnsRebindingProtection:
    """Tests for automatic DNS rebinding protection on localhost.

    DNS rebinding protection is now configured in sse_app() and streamable_http_app()
    based on the host parameter passed to those methods.
    """

    def test_auto_enabled_for_127_0_0_1_sse(self):
        """DNS rebinding protection should auto-enable for host=127.0.0.1 in SSE app."""
        mcp = MCPServer()
        # Call sse_app with host=127.0.0.1 to trigger auto-config
        # We can't directly inspect the transport_security, but we can verify
        # the app is created without error
        app = mcp.sse_app(host="127.0.0.1")
        assert app is not None

    def test_auto_enabled_for_127_0_0_1_streamable_http(self):
        """DNS rebinding protection should auto-enable for host=127.0.0.1 in StreamableHTTP app."""
        mcp = MCPServer()
        app = mcp.streamable_http_app(host="127.0.0.1")
        assert app is not None

    def test_auto_enabled_for_localhost_sse(self):
        """DNS rebinding protection should auto-enable for host=localhost in SSE app."""
        mcp = MCPServer()
        app = mcp.sse_app(host="localhost")
        assert app is not None

    def test_auto_enabled_for_ipv6_localhost_sse(self):
        """DNS rebinding protection should auto-enable for host=::1 (IPv6 localhost) in SSE app."""
        mcp = MCPServer()
        app = mcp.sse_app(host="::1")
        assert app is not None

    def test_not_auto_enabled_for_other_hosts_sse(self):
        """DNS rebinding protection should NOT auto-enable for other hosts in SSE app."""
        mcp = MCPServer()
        app = mcp.sse_app(host="0.0.0.0")
        assert app is not None

    def test_explicit_settings_not_overridden_sse(self):
        """Explicit transport_security settings should not be overridden in SSE app."""
        custom_settings = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )
        mcp = MCPServer()
        # Explicit transport_security passed to sse_app should be used as-is
        app = mcp.sse_app(host="127.0.0.1", transport_security=custom_settings)
        assert app is not None

    def test_explicit_settings_not_overridden_streamable_http(self):
        """Explicit transport_security settings should not be overridden in StreamableHTTP app."""
        custom_settings = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )
        mcp = MCPServer()
        # Explicit transport_security passed to streamable_http_app should be used as-is
        app = mcp.streamable_http_app(host="127.0.0.1", transport_security=custom_settings)
        assert app is not None


def tool_fn(x: int, y: int) -> int:
    return x + y


def error_tool_fn() -> None:
    raise ValueError("Test error")


def image_tool_fn(path: str) -> Image:
    return Image(path)


def audio_tool_fn(path: str) -> Audio:
    return Audio(path)


def mixed_content_tool_fn() -> list[ContentBlock]:
    return [
        TextContent(type="text", text="Hello"),
        ImageContent(type="image", data="abc", mime_type="image/png"),
        AudioContent(type="audio", data="def", mime_type="audio/wav"),
    ]


class TestServerTools:
    async def test_add_tool(self):
        mcp = MCPServer()
        mcp.add_tool(tool_fn)
        mcp.add_tool(tool_fn)
        assert len(mcp._tool_manager.list_tools()) == 1

    async def test_list_tools(self):
        mcp = MCPServer()
        mcp.add_tool(tool_fn)
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 1

    async def test_call_tool(self):
        mcp = MCPServer()
        mcp.add_tool(tool_fn)
        async with Client(mcp) as client:
            result = await client.call_tool("my_tool", {"arg1": "value"})
            assert not hasattr(result, "error")
            assert len(result.content) > 0

    async def test_tool_exception_handling(self):
        mcp = MCPServer()
        mcp.add_tool(error_tool_fn)
        async with Client(mcp) as client:
            result = await client.call_tool("error_tool_fn", {})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert content.text == "Error executing tool error_tool_fn"
            assert result.is_error is True

    async def test_tool_error_handling(self):
        mcp = MCPServer()
        mcp.add_tool(error_tool_fn)
        async with Client(mcp) as client:
            result = await client.call_tool("error_tool_fn", {})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert content.text == "Error executing tool error_tool_fn"
            assert result.is_error is True

    async def test_tool_error_details(self):
        """Test that exception details are properly formatted in the response"""
        mcp = MCPServer()
        mcp.add_tool(error_tool_fn)
        async with Client(mcp) as client:
            result = await client.call_tool("error_tool_fn", {})
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert isinstance(content.text, str)
            assert content.text == "Error executing tool error_tool_fn"
            assert result.is_error is True

    async def test_tool_return_value_conversion(self):
        mcp = MCPServer()
        mcp.add_tool(tool_fn)
        async with Client(mcp) as client:
            result = await client.call_tool("tool_fn", {"x": 1, "y": 2})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert content.text == "3"
            # Check structured content - int return type should have structured output
            assert result.structured_content is not None
            assert result.structured_content == {"result": 3}

    async def test_call_tool_always_returns_call_tool_result(self):
        mcp = MCPServer()

        @mcp.tool()
        def direct() -> CallToolResult:
            return CallToolResult(content=[TextContent(type="text", text="direct")])

        @mcp.tool(structured_output=False)
        def unstructured() -> str:
            return "plain"

        @mcp.tool()
        def structured() -> int:
            return 3

        assert await mcp.call_tool("direct", {}) == CallToolResult(content=[TextContent(type="text", text="direct")])
        assert await mcp.call_tool("unstructured", {}) == CallToolResult(
            content=[TextContent(type="text", text="plain")]
        )
        assert await mcp.call_tool("structured", {}) == CallToolResult(
            content=[TextContent(type="text", text="3")], structured_content={"result": 3}
        )

    async def test_tool_image_helper(self, tmp_path: Path):
        # Create a test image
        image_path = tmp_path / "test.png"
        image_path.write_bytes(b"fake png data")

        mcp = MCPServer()
        mcp.add_tool(image_tool_fn)
        async with Client(mcp) as client:
            result = await client.call_tool("image_tool_fn", {"path": str(image_path)})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, ImageContent)
            assert content.type == "image"
            assert content.mime_type == "image/png"
            # Verify base64 encoding
            decoded = base64.b64decode(content.data)
            assert decoded == b"fake png data"
            # Check structured content - Image return type should NOT have structured output
            assert result.structured_content is None

    async def test_tool_audio_helper(self, tmp_path: Path):
        # Create a test audio
        audio_path = tmp_path / "test.wav"
        audio_path.write_bytes(b"fake wav data")

        mcp = MCPServer()
        mcp.add_tool(audio_tool_fn)
        async with Client(mcp) as client:
            result = await client.call_tool("audio_tool_fn", {"path": str(audio_path)})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, AudioContent)
            assert content.type == "audio"
            assert content.mime_type == "audio/wav"
            # Verify base64 encoding
            decoded = base64.b64decode(content.data)
            assert decoded == b"fake wav data"
            # Check structured content - Image return type should NOT have structured output
            assert result.structured_content is None

    @pytest.mark.parametrize(
        "filename,expected_mime_type",
        [
            ("test.wav", "audio/wav"),
            ("test.mp3", "audio/mpeg"),
            ("test.ogg", "audio/ogg"),
            ("test.flac", "audio/flac"),
            ("test.aac", "audio/aac"),
            ("test.m4a", "audio/mp4"),
            ("test.unknown", "application/octet-stream"),  # Unknown extension fallback
        ],
    )
    async def test_tool_audio_suffix_detection(self, tmp_path: Path, filename: str, expected_mime_type: str):
        """Test that Audio helper correctly detects MIME types from file suffixes"""
        mcp = MCPServer()
        mcp.add_tool(audio_tool_fn)

        # Create a test audio file with the specific extension
        audio_path = tmp_path / filename
        audio_path.write_bytes(b"fake audio data")

        async with Client(mcp) as client:
            result = await client.call_tool("audio_tool_fn", {"path": str(audio_path)})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, AudioContent)
            assert content.type == "audio"
            assert content.mime_type == expected_mime_type
            # Verify base64 encoding
            decoded = base64.b64decode(content.data)
            assert decoded == b"fake audio data"

    async def test_tool_mixed_content(self):
        mcp = MCPServer()
        mcp.add_tool(mixed_content_tool_fn)
        async with Client(mcp) as client:
            result = await client.call_tool("mixed_content_tool_fn", {})
            assert len(result.content) == 3
            content1, content2, content3 = result.content
            assert isinstance(content1, TextContent)
            assert content1.text == "Hello"
            assert isinstance(content2, ImageContent)
            assert content2.mime_type == "image/png"
            assert content2.data == "abc"
            assert isinstance(content3, AudioContent)
            assert content3.mime_type == "audio/wav"
            assert content3.data == "def"
            # Content blocks are for the model, not data: no output schema, nothing echoed as structured
            assert result.structured_content is None

    async def test_tool_mixed_list_with_audio_and_image(self, tmp_path: Path):
        """Test that lists containing Image objects and other types are handled
        correctly"""
        # Create a test image
        image_path = tmp_path / "test.png"
        image_path.write_bytes(b"test image data")

        # Create a test audio
        audio_path = tmp_path / "test.wav"
        audio_path.write_bytes(b"test audio data")

        def mixed_list_fn() -> list[str | Image | Audio | dict[str, str] | TextContent]:
            return [
                "text message",
                Image(image_path),
                Audio(audio_path),
                {"key": "value"},
                TextContent(type="text", text="direct content"),
            ]

        mcp = MCPServer()
        mcp.add_tool(mixed_list_fn)
        async with Client(mcp) as client:
            result = await client.call_tool("mixed_list_fn", {})
            assert len(result.content) == 5
            # Check text conversion
            content1 = result.content[0]
            assert isinstance(content1, TextContent)
            assert content1.text == "text message"
            # Check image conversion
            content2 = result.content[1]
            assert isinstance(content2, ImageContent)
            assert content2.mime_type == "image/png"
            assert base64.b64decode(content2.data) == b"test image data"
            # Check audio conversion
            content3 = result.content[2]
            assert isinstance(content3, AudioContent)
            assert content3.mime_type == "audio/wav"
            assert base64.b64decode(content3.data) == b"test audio data"
            # Check dict conversion
            content4 = result.content[3]
            assert isinstance(content4, TextContent)
            assert '"key": "value"' in content4.text
            # Check direct TextContent
            content5 = result.content[4]
            assert isinstance(content5, TextContent)
            assert content5.text == "direct content"
            # Image/Audio/TextContent in the annotation: no output schema, so nothing echoed as structured
            assert result.structured_content is None

    async def test_tool_structured_output_basemodel(self):
        """Test tool with structured output returning BaseModel"""

        class UserOutput(BaseModel):
            name: str
            age: int
            active: bool = True

        def get_user(user_id: int) -> UserOutput:
            """Get user by ID"""
            return UserOutput(name="John Doe", age=30)

        mcp = MCPServer()
        mcp.add_tool(get_user)

        async with Client(mcp) as client:
            # Check that the tool has outputSchema
            tools = await client.list_tools()
            tool = next(t for t in tools.tools if t.name == "get_user")
            assert tool.output_schema is not None
            assert tool.output_schema["type"] == "object"
            assert "name" in tool.output_schema["properties"]
            assert "age" in tool.output_schema["properties"]

            # Call the tool and check structured output
            result = await client.call_tool("get_user", {"user_id": 123})
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content == {"name": "John Doe", "age": 30, "active": True}
            # Content should be JSON serialized version
            assert len(result.content) == 1
            assert isinstance(result.content[0], TextContent)
            assert '"name": "John Doe"' in result.content[0].text

    async def test_tool_structured_output_primitive(self):
        """Test tool with structured output returning primitive type"""

        def calculate_sum(a: int, b: int) -> int:
            """Add two numbers"""
            return a + b

        mcp = MCPServer()
        mcp.add_tool(calculate_sum)

        async with Client(mcp) as client:
            # Check that the tool has outputSchema
            tools = await client.list_tools()
            tool = next(t for t in tools.tools if t.name == "calculate_sum")
            assert tool.output_schema is not None
            # Primitive types are wrapped
            assert tool.output_schema["type"] == "object"
            assert "result" in tool.output_schema["properties"]
            assert tool.output_schema["properties"]["result"]["type"] == "integer"

            # Call the tool
            result = await client.call_tool("calculate_sum", {"a": 5, "b": 7})
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content == {"result": 12}

    async def test_tool_structured_output_list(self):
        """Test tool with structured output returning list"""

        def get_numbers() -> list[int]:
            """Get a list of numbers"""
            return [1, 2, 3, 4, 5]

        mcp = MCPServer()
        mcp.add_tool(get_numbers)

        async with Client(mcp) as client:
            result = await client.call_tool("get_numbers", {})
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content == {"result": [1, 2, 3, 4, 5]}

    async def test_tool_structured_output_server_side_validation_error(self):
        """Test that server-side validation errors are handled properly"""

        def get_numbers() -> list[int]:
            return [1, 2, 3, 4, [5]]  # type: ignore

        mcp = MCPServer()
        mcp.add_tool(get_numbers)

        async with Client(mcp) as client:
            result = await client.call_tool("get_numbers", {})
            assert result.is_error is True
            assert result.structured_content is None
            assert len(result.content) == 1
            assert isinstance(result.content[0], TextContent)

    async def test_tool_structured_output_dict_str_any(self):
        """Test tool with dict[str, Any] structured output"""

        def get_metadata() -> dict[str, Any]:
            """Get metadata dictionary"""
            return {
                "version": "1.0.0",
                "enabled": True,
                "count": 42,
                "tags": ["production", "stable"],
                "config": {"nested": {"value": 123}},
            }

        mcp = MCPServer()
        mcp.add_tool(get_metadata)

        async with Client(mcp) as client:
            # Check schema
            tools = await client.list_tools()
            tool = next(t for t in tools.tools if t.name == "get_metadata")
            assert tool.output_schema is not None
            assert tool.output_schema["type"] == "object"
            # dict[str, Any] should have minimal schema
            assert (
                "additionalProperties" not in tool.output_schema
                or tool.output_schema.get("additionalProperties") is True
            )

            # Call tool
            result = await client.call_tool("get_metadata", {})
            assert result.is_error is False
            assert result.structured_content is not None
            expected = {
                "version": "1.0.0",
                "enabled": True,
                "count": 42,
                "tags": ["production", "stable"],
                "config": {"nested": {"value": 123}},
            }
            assert result.structured_content == expected

    async def test_tool_structured_output_dict_str_typed(self):
        """Test tool with dict[str, T] structured output for specific T"""

        def get_settings() -> dict[str, str]:
            """Get settings as string dictionary"""
            return {"theme": "dark", "language": "en", "timezone": "UTC"}

        mcp = MCPServer()
        mcp.add_tool(get_settings)

        async with Client(mcp) as client:
            # Check schema
            tools = await client.list_tools()
            tool = next(t for t in tools.tools if t.name == "get_settings")
            assert tool.output_schema is not None
            assert tool.output_schema["type"] == "object"
            assert tool.output_schema["additionalProperties"]["type"] == "string"

            # Call tool
            result = await client.call_tool("get_settings", {})
            assert result.is_error is False
            assert result.structured_content == {"theme": "dark", "language": "en", "timezone": "UTC"}

    async def test_remove_tool(self):
        """Test removing a tool from the server."""
        mcp = MCPServer()
        mcp.add_tool(tool_fn)

        # Verify tool exists
        assert len(mcp._tool_manager.list_tools()) == 1

        # Remove the tool
        mcp.remove_tool("tool_fn")

        # Verify tool is removed
        assert len(mcp._tool_manager.list_tools()) == 0

    async def test_remove_nonexistent_tool(self):
        """Test that removing a non-existent tool raises ToolError."""
        mcp = MCPServer()

        with pytest.raises(ToolError, match="Unknown tool: nonexistent"):
            mcp.remove_tool("nonexistent")

    async def test_remove_tool_and_list(self):
        """Test that a removed tool doesn't appear in list_tools."""
        mcp = MCPServer()
        mcp.add_tool(tool_fn)
        mcp.add_tool(error_tool_fn)

        # Verify both tools exist
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 2
            tool_names = [t.name for t in tools.tools]
            assert "tool_fn" in tool_names
            assert "error_tool_fn" in tool_names

        # Remove one tool
        mcp.remove_tool("tool_fn")

        # Verify only one tool remains
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 1
            assert tools.tools[0].name == "error_tool_fn"

    async def test_remove_tool_and_call(self):
        """Test that calling a removed tool fails appropriately."""
        mcp = MCPServer()
        mcp.add_tool(tool_fn)

        # Verify tool works before removal
        async with Client(mcp) as client:
            result = await client.call_tool("tool_fn", {"x": 1, "y": 2})
            assert not result.is_error
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert content.text == "3"

        # Remove the tool
        mcp.remove_tool("tool_fn")

        # Verify calling removed tool returns an error
        async with Client(mcp) as client:
            result = await client.call_tool("tool_fn", {"x": 1, "y": 2})
            assert result.is_error
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert "Unknown tool" in content.text


async def test_typeddict_tool_omitting_optional_keys_passes_client_validation():
    """The client validates structured content against the tool's output schema, so a `NotRequired`
    key the tool leaves out must be absent from `structured_content` rather than null."""

    class Person(TypedDict):
        name: str
        age: NotRequired[int]

    mcp = MCPServer()

    @mcp.tool()
    def get_person() -> Person:
        return {"name": "Dave"}

    async with Client(mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema == {
            "type": "object",
            "title": "Person",
            "properties": {"name": {"title": "Name", "type": "string"}, "age": {"title": "Age", "type": "integer"}},
            "required": ["name"],
        }
        result = await client.call_tool("get_person", {})
        assert result.structured_content == {"name": "Dave"}


class TestServerResources:
    async def test_init_with_resources(self):
        def get_text() -> str:
            """Seeded resource."""
            return "Hello from init!"

        resource = FunctionResource.from_function(fn=get_text, uri="resource://init", name="init_resource")

        mcp = MCPServer(resources=[resource])

        async with Client(mcp) as client:
            assert client.server_capabilities.resources is not None

            resources = await client.list_resources()
            assert len(resources.resources) == 1
            listed = resources.resources[0]
            assert listed.uri == "resource://init"
            assert listed.name == "init_resource"
            assert listed.description == "Seeded resource."

            result = await client.read_resource("resource://init")

            assert len(result.contents) == 1
            content = result.contents[0]
            assert isinstance(content, TextResourceContents)
            assert content.text == "Hello from init!"

    async def test_text_resource(self):
        mcp = MCPServer()

        def get_text():
            return "Hello, world!"

        resource = FunctionResource(uri="resource://test", name="test", fn=get_text)
        mcp.add_resource(resource)

        async with Client(mcp) as client:
            result = await client.read_resource("resource://test")

            assert isinstance(result.contents[0], TextResourceContents)
            assert result.contents[0].text == "Hello, world!"

    async def test_read_unknown_resource(self):
        """Test that reading an unknown resource returns -32602 with uri in data (SEP-2164)."""
        mcp = MCPServer()

        async with Client(mcp) as client:
            with pytest.raises(MCPError, match="Unknown resource: unknown://missing") as exc_info:
                await client.read_resource("unknown://missing")

            assert exc_info.value.error.code == INVALID_PARAMS
            assert exc_info.value.error.data == {"uri": "unknown://missing"}

    async def test_read_resource_error(self):
        """Test that resource read errors are properly wrapped in MCPError."""
        mcp = MCPServer()

        @mcp.resource("resource://failing")
        def failing_resource():
            raise ValueError("Resource read failed")

        async with Client(mcp) as client:
            with pytest.raises(MCPError, match="Error reading resource resource://failing"):
                await client.read_resource("resource://failing")

    async def test_binary_resource(self):
        mcp = MCPServer()

        def get_binary():
            return b"Binary data"

        resource = FunctionResource(
            uri="resource://binary",
            name="binary",
            fn=get_binary,
            mime_type="application/octet-stream",
        )
        mcp.add_resource(resource)

        async with Client(mcp) as client:
            result = await client.read_resource("resource://binary")

            assert isinstance(result.contents[0], BlobResourceContents)
            assert result.contents[0].blob == base64.b64encode(b"Binary data").decode()

    async def test_file_resource_text(self, tmp_path: Path):
        mcp = MCPServer()

        # Create a text file
        text_file = tmp_path / "test.txt"
        text_file.write_text("Hello from file!", encoding="utf-8")

        resource = FileResource(uri="file://test.txt", name="test.txt", path=text_file)
        mcp.add_resource(resource)

        async with Client(mcp) as client:
            result = await client.read_resource("file://test.txt")

            assert isinstance(result.contents[0], TextResourceContents)
            assert result.contents[0].text == "Hello from file!"

    async def test_file_resource_binary(self, tmp_path: Path):
        mcp = MCPServer()

        # Create a binary file
        binary_file = tmp_path / "test.bin"
        binary_file.write_bytes(b"Binary file data")

        resource = FileResource(
            uri="file://test.bin",
            name="test.bin",
            path=binary_file,
            mime_type="application/octet-stream",
        )
        mcp.add_resource(resource)

        async with Client(mcp) as client:
            result = await client.read_resource("file://test.bin")

            assert isinstance(result.contents[0], BlobResourceContents)
            assert result.contents[0].blob == base64.b64encode(b"Binary file data").decode()

    async def test_function_resource(self):
        mcp = MCPServer()

        @mcp.resource("function://test", name="test_get_data")
        def get_data() -> str:  # pragma: no cover
            """get_data returns a string"""
            return "Hello, world!"

        async with Client(mcp) as client:
            resources = await client.list_resources()
            assert len(resources.resources) == 1
            resource = resources.resources[0]
            assert resource.description == "get_data returns a string"
            assert resource.uri == "function://test"
            assert resource.name == "test_get_data"
            assert resource.mime_type == "text/plain"


class TestServerResourceTemplates:
    async def test_resource_with_params(self):
        """Test that a resource with function parameters raises an error if the URI
        parameters don't match"""
        mcp = MCPServer()

        with pytest.raises(ValueError, match="has no URI template variables"):

            @mcp.resource("resource://data")
            def get_data_fn(param: str) -> str:  # pragma: no cover
                return f"Data: {param}"

    async def test_resource_with_uri_params(self):
        """Test that a resource with URI parameters is automatically a template"""
        mcp = MCPServer()

        with pytest.raises(ValueError, match="Mismatch between URI parameters"):

            @mcp.resource("resource://{param}")
            def get_data() -> str:  # pragma: no cover
                return "Data"

    async def test_resource_with_untyped_params(self):
        """Test that a resource with untyped parameters raises an error"""
        mcp = MCPServer()

        @mcp.resource("resource://{param}")
        def get_data(param) -> str:  # type: ignore  # pragma: no cover
            return "Data"

    async def test_resource_matching_params(self):
        """Test that a resource with matching URI and function parameters works"""
        mcp = MCPServer()

        @mcp.resource("resource://{name}/data")
        def get_data(name: str) -> str:
            return f"Data for {name}"

        async with Client(mcp) as client:
            result = await client.read_resource("resource://test/data")

            assert isinstance(result.contents[0], TextResourceContents)
            assert result.contents[0].text == "Data for test"

    async def test_resource_mismatched_params(self):
        """Test that mismatched parameters raise an error"""
        mcp = MCPServer()

        with pytest.raises(ValueError, match="Mismatch between URI parameters"):

            @mcp.resource("resource://{name}/data")
            def get_data(user: str) -> str:  # pragma: no cover
                return f"Data for {user}"

    async def test_resource_multiple_params(self):
        """Test that multiple parameters work correctly"""
        mcp = MCPServer()

        @mcp.resource("resource://{org}/{repo}/data")
        def get_data(org: str, repo: str) -> str:
            return f"Data for {org}/{repo}"

        async with Client(mcp) as client:
            result = await client.read_resource("resource://cursor/myrepo/data")

            assert isinstance(result.contents[0], TextResourceContents)
            assert result.contents[0].text == "Data for cursor/myrepo"

    async def test_resource_multiple_mismatched_params(self):
        """Test that mismatched parameters raise an error"""
        mcp = MCPServer()

        with pytest.raises(ValueError, match="Mismatch between URI parameters"):

            @mcp.resource("resource://{org}/{repo}/data")
            def get_data_mismatched(org: str, repo_2: str) -> str:  # pragma: no cover
                return f"Data for {org}"

        """Test that a resource with no parameters works as a regular resource"""
        mcp = MCPServer()

        @mcp.resource("resource://static")
        def get_static_data() -> str:
            return "Static data"

        async with Client(mcp) as client:
            result = await client.read_resource("resource://static")

            assert isinstance(result.contents[0], TextResourceContents)
            assert result.contents[0].text == "Static data"

    async def test_template_to_resource_conversion(self):
        """Test that templates are properly converted to resources when accessed"""
        mcp = MCPServer()

        @mcp.resource("resource://{name}/data")
        def get_data(name: str) -> str:
            return f"Data for {name}"

        # Should be registered as a template
        assert len(mcp._resource_manager._templates) == 1
        assert len(await mcp.list_resources()) == 0

        # When accessed, should create a concrete resource
        resource = await mcp._resource_manager.get_resource("resource://test/data", Context())
        assert isinstance(resource, FunctionResource)
        result = await resource.read()
        assert result == "Data for test"

    async def test_resource_template_includes_mime_type(self):
        """Test that list resource templates includes the correct mimeType."""
        mcp = MCPServer()

        @mcp.resource("resource://{user}/csv", mime_type="text/csv")
        def get_csv(user: str) -> str:
            return f"csv for {user}"

        templates = await mcp.list_resource_templates()
        assert templates == snapshot(
            [
                ResourceTemplate(
                    name="get_csv", uri_template="resource://{user}/csv", description="", mime_type="text/csv"
                )
            ]
        )

        async with Client(mcp) as client:
            result = await client.read_resource("resource://bob/csv")
            assert result == snapshot(
                ReadResourceResult(
                    _meta={"io.modelcontextprotocol/serverInfo": {"name": "mcp-server", "version": ""}},
                    contents=[TextResourceContents(uri="resource://bob/csv", mime_type="text/csv", text="csv for bob")],
                )
            )


class TestServerResourceMetadata:
    """Test MCPServer @resource decorator meta parameter for list operations.

    Meta flows: @resource decorator -> resource/template storage -> list_resources/list_resource_templates.
    Note: read_resource does NOT pass meta to protocol response (lowlevel/server.py only extracts content/mime_type).
    """

    async def test_resource_decorator_with_metadata(self):
        """Test that @resource decorator accepts and passes meta parameter."""
        # Tests static resource flow: decorator -> FunctionResource -> list_resources (server.py:544,635,361)
        mcp = MCPServer()

        @mcp.resource("resource://config", meta={"ui": {"component": "file-viewer"}, "priority": "high"})
        def get_config() -> str: ...  # pragma: no branch

        resources = await mcp.list_resources()
        assert resources == snapshot(
            [
                Resource(
                    name="get_config",
                    uri="resource://config",
                    description="",
                    mime_type="text/plain",
                    meta={"ui": {"component": "file-viewer"}, "priority": "high"},  # type: ignore[reportCallIssue]
                )
            ]
        )

    async def test_resource_template_decorator_with_metadata(self):
        """Test that @resource decorator passes meta to templates."""
        # Tests template resource flow: decorator -> add_template() -> list_resource_templates (server.py:544,622,377)
        mcp = MCPServer()

        @mcp.resource("resource://{city}/weather", meta={"api_version": "v2", "deprecated": False})
        def get_weather(city: str) -> str: ...  # pragma: no branch

        templates = await mcp.list_resource_templates()
        assert templates == snapshot(
            [
                ResourceTemplate(
                    name="get_weather",
                    uri_template="resource://{city}/weather",
                    description="",
                    mime_type="text/plain",
                    meta={"api_version": "v2", "deprecated": False},  # type: ignore[reportCallIssue]
                )
            ]
        )

    async def test_read_resource_returns_meta(self):
        """Test that read_resource includes meta in response."""
        # Tests end-to-end: Resource.meta -> ReadResourceContents.meta -> protocol _meta (lowlevel/server.py:341,371)
        mcp = MCPServer()

        @mcp.resource("resource://data", meta={"version": "1.0", "category": "config"})
        def get_data() -> str:
            return "test data"

        async with Client(mcp) as client:
            result = await client.read_resource("resource://data")
            assert result == snapshot(
                ReadResourceResult(
                    _meta={"io.modelcontextprotocol/serverInfo": {"name": "mcp-server", "version": ""}},
                    contents=[
                        TextResourceContents(
                            uri="resource://data",
                            mime_type="text/plain",
                            meta={"version": "1.0", "category": "config"},  # type: ignore[reportUnknownMemberType]
                            text="test data",
                        )
                    ],
                )
            )


class TestContextInjection:
    """Test context injection in tools, resources, and prompts."""

    async def test_context_detection(self):
        """Test that context parameters are properly detected."""
        mcp = MCPServer()

        def tool_with_context(x: int, ctx: Context) -> str:  # pragma: no cover
            return f"Request {ctx.request_id}: {x}"

        tool = mcp._tool_manager.add_tool(tool_with_context)
        assert tool.context_kwarg == "ctx"

    async def test_context_injection(self):
        """Test that context is properly injected into tool calls."""
        mcp = MCPServer()

        def tool_with_context(x: int, ctx: Context) -> str:
            assert ctx.request_id is not None
            return f"Request {ctx.request_id}: {x}"

        mcp.add_tool(tool_with_context)
        async with Client(mcp) as client:
            result = await client.call_tool("tool_with_context", {"x": 42})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert "Request" in content.text
            assert "42" in content.text

    async def test_async_context(self):
        """Test that context works in async functions."""
        mcp = MCPServer()

        async def async_tool(x: int, ctx: Context) -> str:
            assert ctx.request_id is not None
            return f"Async request {ctx.request_id}: {x}"

        mcp.add_tool(async_tool)
        async with Client(mcp) as client:
            result = await client.call_tool("async_tool", {"x": 42})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert "Async request" in content.text
            assert "42" in content.text

    async def test_context_logging(self):
        """Test that context logging methods work."""
        mcp = MCPServer()

        async def logging_tool(msg: str, ctx: Context) -> str:
            await ctx.debug("Debug message")  # pyright: ignore[reportDeprecated]
            await ctx.info("Info message")  # pyright: ignore[reportDeprecated]
            await ctx.warning("Warning message")  # pyright: ignore[reportDeprecated]
            await ctx.error("Error message")  # pyright: ignore[reportDeprecated]
            return f"Logged messages for {msg}"

        mcp.add_tool(logging_tool)

        with patch("mcp.server.session.ServerSession.send_log_message") as mock_log:
            async with Client(mcp, mode="legacy") as client:
                result = await client.call_tool("logging_tool", {"msg": "test"})
                assert len(result.content) == 1
                content = result.content[0]
                assert isinstance(content, TextContent)
                assert "Logged messages for test" in content.text

                assert mock_log.call_count == 4
                mock_log.assert_any_call(level="debug", data="Debug message", logger=None, related_request_id="2")
                mock_log.assert_any_call(level="info", data="Info message", logger=None, related_request_id="2")
                mock_log.assert_any_call(level="warning", data="Warning message", logger=None, related_request_id="2")
                mock_log.assert_any_call(level="error", data="Error message", logger=None, related_request_id="2")

    async def test_optional_context(self):
        """Test that context is optional."""
        mcp = MCPServer()

        def no_context(x: int) -> int:
            return x * 2

        mcp.add_tool(no_context)
        async with Client(mcp) as client:
            result = await client.call_tool("no_context", {"x": 21})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert content.text == "42"

    async def test_context_resource_access(self):
        """Test that context can access resources."""
        mcp = MCPServer()

        @mcp.resource("test://data")
        def test_resource() -> str:
            return "resource data"

        @mcp.tool()
        async def tool_with_resource(ctx: Context) -> str:
            r_iter = await ctx.read_resource("test://data")
            r_list = list(r_iter)
            assert len(r_list) == 1
            r = r_list[0]
            return f"Read resource: {r.content} with mime type {r.mime_type}"

        async with Client(mcp) as client:
            result = await client.call_tool("tool_with_resource", {})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert "Read resource: resource data" in content.text

    async def test_resource_with_context(self):
        """Test that resources can receive context parameter."""
        mcp = MCPServer()

        @mcp.resource("resource://context/{name}")
        def resource_with_context(name: str, ctx: Context) -> str:
            """Resource that receives context."""
            assert ctx is not None
            return f"Resource {name} - context injected"

        # Verify template has context_kwarg set
        templates = mcp._resource_manager.list_templates()
        assert len(templates) == 1
        template = templates[0]
        assert hasattr(template, "context_kwarg")
        assert template.context_kwarg == "ctx"

        async with Client(mcp) as client:
            result = await client.read_resource("resource://context/test")

            assert len(result.contents) == 1
            content = result.contents[0]
            assert isinstance(content, TextResourceContents)
            # Should have either request_id or indication that context was injected
            assert "Resource test - context injected" == content.text

    async def test_resource_without_context(self):
        """Test that resources without context work normally."""
        mcp = MCPServer()

        @mcp.resource("resource://nocontext/{name}")
        def resource_no_context(name: str) -> str:
            """Resource without context."""
            return f"Resource {name} works"

        # Verify template has no context_kwarg
        templates = mcp._resource_manager.list_templates()
        assert len(templates) == 1
        template = templates[0]
        assert template.context_kwarg is None

        async with Client(mcp) as client:
            result = await client.read_resource("resource://nocontext/test")
            assert result == snapshot(
                ReadResourceResult(
                    _meta={"io.modelcontextprotocol/serverInfo": {"name": "mcp-server", "version": ""}},
                    contents=[
                        TextResourceContents(
                            uri="resource://nocontext/test", mime_type="text/plain", text="Resource test works"
                        )
                    ],
                )
            )

    async def test_resource_context_custom_name(self):
        """Test resource context with custom parameter name."""
        mcp = MCPServer()

        @mcp.resource("resource://custom/{id}")
        def resource_custom_ctx(id: str, my_ctx: Context) -> str:
            """Resource with custom context parameter name."""
            assert my_ctx is not None
            return f"Resource {id} with context"

        # Verify template detects custom context parameter
        templates = mcp._resource_manager.list_templates()
        assert len(templates) == 1
        template = templates[0]
        assert template.context_kwarg == "my_ctx"

        async with Client(mcp) as client:
            result = await client.read_resource("resource://custom/123")
            assert result == snapshot(
                ReadResourceResult(
                    _meta={"io.modelcontextprotocol/serverInfo": {"name": "mcp-server", "version": ""}},
                    contents=[
                        TextResourceContents(
                            uri="resource://custom/123", mime_type="text/plain", text="Resource 123 with context"
                        )
                    ],
                )
            )

    async def test_prompt_with_context(self):
        """Test that prompts can receive context parameter."""
        mcp = MCPServer()

        @mcp.prompt("prompt_with_ctx")
        def prompt_with_context(text: str, ctx: Context) -> str:
            """Prompt that expects context."""
            assert ctx is not None
            return f"Prompt '{text}' - context injected"

        # Test via client
        async with Client(mcp) as client:
            # Try calling without passing ctx explicitly
            result = await client.get_prompt("prompt_with_ctx", {"text": "test"})
            # If this succeeds, check if context was injected
            assert len(result.messages) == 1
            content = result.messages[0].content
            assert isinstance(content, TextContent)
            assert "Prompt 'test' - context injected" in content.text

    async def test_prompt_without_context(self):
        """Test that prompts without context work normally."""
        mcp = MCPServer()

        @mcp.prompt("prompt_no_ctx")
        def prompt_no_context(text: str) -> str:
            """Prompt without context."""
            return f"Prompt '{text}' works"

        # Test via client
        async with Client(mcp) as client:
            result = await client.get_prompt("prompt_no_ctx", {"text": "test"})
            assert len(result.messages) == 1
            message = result.messages[0]
            content = message.content
            assert isinstance(content, TextContent)
            assert content.text == "Prompt 'test' works"


class TestServerPrompts:
    """Test prompt functionality in MCPServer server."""

    async def test_get_prompt_direct_call_without_context(self):
        """Test calling mcp.get_prompt() directly without passing context."""
        mcp = MCPServer()

        @mcp.prompt()
        def fn() -> str:
            return "Hello, world!"

        result = await mcp.get_prompt("fn")
        assert not isinstance(result, InputRequiredResult)
        content = result.messages[0].content
        assert isinstance(content, TextContent)
        assert content.text == "Hello, world!"

    async def test_prompt_decorator(self):
        """Test that the prompt decorator registers prompts correctly."""
        mcp = MCPServer()

        @mcp.prompt()
        def fn() -> str:
            return "Hello, world!"

        prompts = mcp._prompt_manager.list_prompts()
        assert len(prompts) == 1
        assert prompts[0].name == "fn"
        # Don't compare functions directly since validate_call wraps them
        content = await prompts[0].render(None, Context())
        assert not isinstance(content, InputRequiredResult)
        assert isinstance(content[0].content, TextContent)
        assert content[0].content.text == "Hello, world!"

    async def test_prompt_decorator_with_name(self):
        """Test prompt decorator with custom name."""
        mcp = MCPServer()

        @mcp.prompt(name="custom_name")
        def fn() -> str:
            return "Hello, world!"

        prompts = mcp._prompt_manager.list_prompts()
        assert len(prompts) == 1
        assert prompts[0].name == "custom_name"
        content = await prompts[0].render(None, Context())
        assert not isinstance(content, InputRequiredResult)
        assert isinstance(content[0].content, TextContent)
        assert content[0].content.text == "Hello, world!"

    async def test_prompt_decorator_with_description(self):
        """Test prompt decorator with custom description."""
        mcp = MCPServer()

        @mcp.prompt(description="A custom description")
        def fn() -> str:
            return "Hello, world!"

        prompts = mcp._prompt_manager.list_prompts()
        assert len(prompts) == 1
        assert prompts[0].description == "A custom description"
        content = await prompts[0].render(None, Context())
        assert not isinstance(content, InputRequiredResult)
        assert isinstance(content[0].content, TextContent)
        assert content[0].content.text == "Hello, world!"

    def test_prompt_decorator_error(self):
        """Test error when decorator is used incorrectly."""
        mcp = MCPServer()
        with pytest.raises(TypeError, match="decorator was used incorrectly"):

            @mcp.prompt  # type: ignore
            def fn() -> str: ...  # pragma: no branch

    async def test_list_prompts(self):
        """Test listing prompts through MCP protocol."""
        mcp = MCPServer()

        @mcp.prompt()
        def fn(name: str, optional: str = "default") -> str: ...  # pragma: no branch

        async with Client(mcp) as client:
            result = await client.list_prompts()
            assert result == snapshot(
                ListPromptsResult(
                    _meta={"io.modelcontextprotocol/serverInfo": {"name": "mcp-server", "version": ""}},
                    prompts=[
                        Prompt(
                            name="fn",
                            description="",
                            arguments=[
                                PromptArgument(name="name", required=True),
                                PromptArgument(name="optional", required=False),
                            ],
                        )
                    ],
                )
            )

    async def test_get_prompt(self):
        """Test getting a prompt through MCP protocol."""
        mcp = MCPServer()

        @mcp.prompt()
        def fn(name: str) -> str:
            return f"Hello, {name}!"

        async with Client(mcp) as client:
            result = await client.get_prompt("fn", {"name": "World"})
            assert result == snapshot(
                GetPromptResult(
                    _meta={"io.modelcontextprotocol/serverInfo": {"name": "mcp-server", "version": ""}},
                    description="",
                    messages=[PromptMessage(role="user", content=TextContent(text="Hello, World!"))],
                )
            )

    async def test_get_prompt_with_description(self):
        """Test getting a prompt through MCP protocol."""
        mcp = MCPServer()

        @mcp.prompt(description="Test prompt description")
        def fn(name: str) -> str:
            return f"Hello, {name}!"

        async with Client(mcp) as client:
            result = await client.get_prompt("fn", {"name": "World"})
            assert result.description == "Test prompt description"

    async def test_get_prompt_with_docstring_description(self):
        """Test prompt uses docstring as description when not explicitly provided."""
        mcp = MCPServer()

        @mcp.prompt()
        def fn(name: str) -> str:
            """This is the function docstring."""
            return f"Hello, {name}!"

        async with Client(mcp) as client:
            result = await client.get_prompt("fn", {"name": "World"})
            assert result == snapshot(
                GetPromptResult(
                    _meta={"io.modelcontextprotocol/serverInfo": {"name": "mcp-server", "version": ""}},
                    description="This is the function docstring.",
                    messages=[PromptMessage(role="user", content=TextContent(text="Hello, World!"))],
                )
            )

    async def test_get_prompt_with_resource(self):
        """Test getting a prompt that returns resource content."""
        mcp = MCPServer()

        @mcp.prompt()
        def fn() -> Message:
            return UserMessage(
                content=EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(uri="file://file.txt", text="File contents", mime_type="text/plain"),
                )
            )

        async with Client(mcp) as client:
            result = await client.get_prompt("fn")
            assert result == snapshot(
                GetPromptResult(
                    _meta={"io.modelcontextprotocol/serverInfo": {"name": "mcp-server", "version": ""}},
                    description="",
                    messages=[
                        PromptMessage(
                            role="user",
                            content=EmbeddedResource(
                                resource=TextResourceContents(
                                    uri="file://file.txt", mime_type="text/plain", text="File contents"
                                )
                            ),
                        )
                    ],
                )
            )

    async def test_get_unknown_prompt(self):
        """Test error when getting unknown prompt."""
        mcp = MCPServer()

        async with Client(mcp, mode="legacy") as client:
            with pytest.raises(MCPError, match="Unknown prompt"):
                await client.get_prompt("unknown")

    async def test_get_prompt_missing_args(self):
        """Test error when required arguments are missing."""
        mcp = MCPServer()

        @mcp.prompt()
        def prompt_fn(name: str) -> str: ...  # pragma: no branch

        async with Client(mcp, mode="legacy") as client:
            with pytest.raises(MCPError, match="Missing required arguments"):
                await client.get_prompt("prompt_fn")


async def test_resource_decorator_rfc6570_reserved_expansion():
    # Regression: old regex-based param extraction couldn't see `path`
    # in `{+path}` and failed with a confusing mismatch error.
    mcp = MCPServer()

    @mcp.resource("file://docs/{+path}")
    def read_doc(path: str) -> str:
        raise NotImplementedError

    templates = await mcp.list_resource_templates()
    assert [t.uri_template for t in templates] == ["file://docs/{+path}"]


async def test_resource_decorator_rejects_malformed_template():
    mcp = MCPServer()
    with pytest.raises(InvalidUriTemplate, match="Unclosed expression"):
        mcp.resource("file://{name")


async def test_resource_optional_query_params_use_function_defaults():
    """Omitted {?...} query params should fall through to the
    handler's Python defaults. Partial and reordered params work."""
    mcp = MCPServer()

    @mcp.resource("logs://{service}{?since,level}")
    def tail_logs(service: str, since: str = "1h", level: str = "info") -> str:
        return f"{service}|{since}|{level}"

    async with Client(mcp) as client:
        # No query → all defaults
        r = await client.read_resource("logs://api")
        assert isinstance(r.contents[0], TextResourceContents)
        assert r.contents[0].text == "api|1h|info"

        # Partial query → one default
        r = await client.read_resource("logs://api?since=15m")
        assert isinstance(r.contents[0], TextResourceContents)
        assert r.contents[0].text == "api|15m|info"

        # Reordered, both present
        r = await client.read_resource("logs://api?level=error&since=5m")
        assert isinstance(r.contents[0], TextResourceContents)
        assert r.contents[0].text == "api|5m|error"

        # Extra param ignored
        r = await client.read_resource("logs://api?since=2h&utm=x")
        assert isinstance(r.contents[0], TextResourceContents)
        assert r.contents[0].text == "api|2h|info"


async def test_resource_query_param_without_default_rejected_at_decoration():
    """A handler parameter bound to a {?...} query variable must have a
    Python default: a client may omit a query parameter, so the handler has
    to be callable without it. Omitting the default is an error when the
    decorator runs, not on the first request that leaves the parameter out."""
    mcp = MCPServer()

    with pytest.raises(ValueError, match=r"logs://.*\['level'\].*must declare a default"):

        @mcp.resource("logs://{service}{?level}")
        def tail_logs(service: str, level: str) -> str:
            raise NotImplementedError


async def test_resource_path_param_without_default_accepted():
    """The default requirement applies only to query-bound parameters.
    A path variable is always present in a matching URI, so its handler
    parameter may be required."""
    mcp = MCPServer()

    @mcp.resource("logs://{service}{?level}")
    def tail_logs(service: str, level: str = "info") -> str:
        raise NotImplementedError

    templates = await mcp.list_resource_templates()
    assert [t.uri_template for t in templates] == ["logs://{service}{?level}"]


async def test_resource_security_default_rejects_traversal():
    mcp = MCPServer()

    @mcp.resource("data://items/{name}")
    def get_item(name: str) -> str:
        return f"item:{name}"

    async with Client(mcp) as client:
        # Safe value passes through to the handler
        r = await client.read_resource("data://items/widget")
        assert isinstance(r.contents[0], TextResourceContents)
        assert r.contents[0].text == "item:widget"

        # ".." as a path component is rejected by default policy
        with pytest.raises(MCPError, match="Unknown resource"):
            await client.read_resource("data://items/..")


async def test_resource_template_non_match_is_unknown_resource():
    """A URI that doesn't satisfy a registered template — including one
    shorter than the template's literal segments — must surface as the
    standard -32602 Unknown resource, not an internal error."""
    mcp = MCPServer()

    @mcp.resource("api://{+path}/{id}")
    def get(path: str, id: str) -> str:
        return f"{path}|{id}"

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("api://foo")
        assert exc_info.value.error.code == INVALID_PARAMS
        assert exc_info.value.error.message == "Unknown resource: api://foo"

        # And a satisfying URI still routes to the handler.
        r = await client.read_resource("api://a/b/c")
        assert isinstance(r.contents[0], TextResourceContents)
        assert r.contents[0].text == "a/b|c"


async def test_resource_security_rejection_indistinguishable_from_not_found():
    """A path-safety rejection must produce the same wire error as a
    genuinely-absent resource: same code, same message shape, no hint
    about which check failed."""
    mcp = MCPServer()

    @mcp.resource("data://items/{name}")
    def get_item(name: str) -> str:  # pragma: no cover - never reached
        return name

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as rejected:
            await client.read_resource("data://items/..")
        with pytest.raises(MCPError) as absent:
            await client.read_resource("nosuch://thing")

        assert rejected.value.error.code == absent.value.error.code == INVALID_PARAMS
        # Message echoes the requested URI and nothing else; no
        # reference to which validation step rejected it.
        assert rejected.value.error.message == "Unknown resource: data://items/.."
        assert absent.value.error.message == "Unknown resource: nosuch://thing"
        assert rejected.value.error.data == {"uri": "data://items/.."}
        assert absent.value.error.data == {"uri": "nosuch://thing"}


async def test_resource_security_per_resource_override():
    mcp = MCPServer()

    @mcp.resource(
        "git://diff/{+range}",
        security=ResourceSecurity(exempt_params={"range"}),
    )
    def git_diff(range: str) -> str:
        return f"diff:{range}"

    async with Client(mcp) as client:
        # "../foo" would be rejected by default, but "range" is exempt
        result = await client.read_resource("git://diff/../foo")
        assert isinstance(result.contents[0], TextResourceContents)
        assert result.contents[0].text == "diff:../foo"


async def test_resource_security_server_wide_override():
    mcp = MCPServer(resource_security=ResourceSecurity(reject_path_traversal=False))

    @mcp.resource("data://items/{name}")
    def get_item(name: str) -> str:
        return f"item:{name}"

    async with Client(mcp) as client:
        # Server-wide policy disabled traversal check; ".." now allowed
        result = await client.read_resource("data://items/..")
        assert isinstance(result.contents[0], TextResourceContents)
        assert result.contents[0].text == "item:.."


async def test_resource_security_namespaced_identifier_requires_exempt():
    """Single-letter-colon values like ``x:y`` are flagged by the
    default absolute-path check (they parse as Windows drive-relative,
    which discards the join base). A non-filesystem parameter that
    legitimately accepts such values opts out via ``exempt_params``."""
    mcp = MCPServer()

    @mcp.resource("data://items/{id}")
    def get_item(id: str) -> str:  # pragma: no cover - rejected before call
        return f"item:{id}"

    async with Client(mcp) as client:
        with pytest.raises(MCPError, match="Unknown resource") as exc:
            await client.read_resource("data://items/x:y")
        assert exc.value.error.code == INVALID_PARAMS

    # Exempting the parameter lets the value through.
    mcp = MCPServer()

    @mcp.resource("data://items/{id}", security=ResourceSecurity(exempt_params={"id"}))
    def get_item_exempt(id: str) -> str:
        return f"item:{id}"

    async with Client(mcp) as client:
        r = await client.read_resource("data://items/x:y")
        assert isinstance(r.contents[0], TextResourceContents)
        assert r.contents[0].text == "item:x:y"


async def test_resource_security_rejection_halts_template_iteration():
    """A strict template's security rejection must surface as
    not-found and stop; a later permissive template must not be
    reached."""
    mcp = MCPServer()

    @mcp.resource("file://docs/{name}")
    def strict(name: str) -> str:  # pragma: no cover - never reached
        return name

    @mcp.resource(
        "file://docs/{+path}",
        security=ResourceSecurity(exempt_params={"path"}),
    )
    def lax(path: str) -> str:  # pragma: no cover - must not be reached
        raise AssertionError("permissive template reached after security rejection")

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.read_resource("file://docs/..%2Fsecrets")
        assert exc.value.error.code == INVALID_PARAMS
        assert "Unknown resource" in exc.value.error.message


async def test_static_resource_with_context_param_errors():
    """A non-template URI with a Context-only handler should error
    at decoration time with a clear message, not silently register
    an unreachable resource."""
    mcp = MCPServer()

    with pytest.raises(ValueError, match="Context injection for static resources is not supported"):

        @mcp.resource("weather://current")
        def current_weather(ctx: Context) -> str:
            raise NotImplementedError


async def test_static_resource_with_extra_params_errors():
    """A non-template URI with non-Context params should error at
    decoration time."""
    mcp = MCPServer()

    with pytest.raises(ValueError, match="has no URI template variables"):

        @mcp.resource("data://fixed")
        def get_data(name: str) -> str:
            raise NotImplementedError


async def test_completion_decorator() -> None:
    """Test that the completion decorator registers a working handler."""
    mcp = MCPServer()

    @mcp.completion()
    async def handle_completion(
        ref: PromptReference, argument: CompletionArgument, context: CompletionContext | None
    ) -> Completion:
        assert argument.name == "style"
        return Completion(values=["bold", "italic", "underline"])

    async with Client(mcp) as client:
        ref = PromptReference(type="ref/prompt", name="test")
        result = await client.complete(ref=ref, argument={"name": "style", "value": "b"})
        assert result.completion.values == ["bold", "italic", "underline"]


async def test_custom_resource_returning_the_wrong_type_is_a_crash(caplog: pytest.LogCaptureFixture) -> None:
    """SDK-defined: a Resource subclass whose read() returns something other than str or bytes is the
    server's bug, so it is logged as a crash and answered with the generic -32603, not with
    'Invalid request parameters'; read_resource() called directly raises instead of returning it."""
    mcp = MCPServer()

    class Miscoded(MCPServerResource):
        async def read(self) -> Any:
            return 42

    mcp.add_resource(Miscoded(uri="data://answer", name="answer"))

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.read_resource("data://answer")

    assert exc.value.error == snapshot(
        ErrorData(code=INTERNAL_ERROR, message="Error reading resource data://answer", data={"uri": "data://answer"})
    )
    assert _server_records(caplog) == snapshot(
        [("ERROR", "Resource 'data://answer' raised an unexpected exception", True)]
    )
    cause = _logged_exception(caplog).__cause__
    assert isinstance(cause, TypeError)
    assert str(cause) == "Resource.read() must return str or bytes, not int"
    with pytest.raises(UnexpectedResourceError):
        await mcp.read_resource("data://answer")


async def test_completion_handler_crash_is_logged_and_reaches_the_client_generically(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK-defined: a crashing completion handler is one ERROR record with its traceback, and the client
    gets -32603 naming only the argument, not the exception's text."""
    mcp = MCPServer()
    raised = RuntimeError("index warmup failed on shard 3")

    @mcp.completion()
    async def complete(ref: PromptReference, argument: CompletionArgument, context: CompletionContext | None):
        raise raised

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.complete(
                ref=PromptReference(type="ref/prompt", name="greet"), argument={"name": "style", "value": "b"}
            )

    assert exc.value.error == snapshot(ErrorData(code=INTERNAL_ERROR, message="Error completing argument style"))
    assert _server_records(caplog) == snapshot(
        [("ERROR", "Completion for argument 'style' raised an unexpected exception", True)]
    )
    assert raised in _cause_chain(_logged_exception(caplog))


async def test_completion_handler_returning_the_wrong_type_is_a_crash(caplog: pytest.LogCaptureFixture) -> None:
    """SDK-defined: a completion handler whose return value isn't a Completion is the server's bug, so it is
    logged as a crash and answered with the same generic -32603, not with 'Invalid request parameters'."""
    mcp = MCPServer()

    @mcp.completion()
    async def complete(ref: PromptReference, argument: CompletionArgument, context: CompletionContext | None):
        wrong: Any = ["bold", "italic"]
        return wrong

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.complete(
                ref=PromptReference(type="ref/prompt", name="greet"), argument={"name": "style", "value": "b"}
            )

    assert exc.value.error == snapshot(ErrorData(code=INTERNAL_ERROR, message="Error completing argument style"))
    assert _server_records(caplog) == snapshot(
        [("ERROR", "Completion for argument 'style' raised an unexpected exception", True)]
    )
    assert isinstance(_cause_chain(_logged_exception(caplog))[-1], ValidationError)


async def test_completion_handler_raising_mcp_error_passes_through(caplog: pytest.LogCaptureFixture) -> None:
    """SDK-defined: MCPError from a completion handler keeps its code and message and is not logged."""
    mcp = MCPServer()

    @mcp.completion()
    async def complete(ref: PromptReference, argument: CompletionArgument, context: CompletionContext | None):
        raise MCPError(code=INVALID_PARAMS, message="unknown argument")

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.complete(
                ref=PromptReference(type="ref/prompt", name="greet"), argument={"name": "style", "value": "b"}
            )

    assert exc.value.error == snapshot(ErrorData(code=INVALID_PARAMS, message="unknown argument"))
    assert _server_records(caplog) == []


def test_streamable_http_no_redirect() -> None:
    """Test that streamable HTTP routes are correctly configured."""
    mcp = MCPServer()
    # streamable_http_path defaults to "/mcp"
    app = mcp.streamable_http_app()

    # Find routes by type - streamable_http_app creates Route objects, not Mount objects
    streamable_routes = [r for r in app.routes if isinstance(r, Route) and hasattr(r, "path") and r.path == "/mcp"]

    # Verify routes exist
    assert len(streamable_routes) == 1, "Should have one streamable route"

    # Verify path values
    assert streamable_routes[0].path == "/mcp", "Streamable route path should be /mcp"


async def test_sse_app_applies_the_configured_request_body_limit() -> None:
    """`sse_app(max_request_body_size=...)` rejects larger POSTs to the message endpoint with HTTP 413."""
    app = MCPServer("test").sse_app(max_request_body_size=8, host="0.0.0.0")
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://localhost") as http:
        response = await http.post(
            "/messages/?session_id=12345678123456781234567812345678",
            content=b"123456789",
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 413


async def test_report_progress_delegates_to_session_report_progress():
    """Context.report_progress delegates to ServerSession.report_progress unconditionally.

    Stream routing (related_request_id, progress-token gating) is encapsulated in the
    per-request DispatchContext that ServerSession holds, so Context never inspects
    request metadata itself. See #953 and #2001 for the original streamable-HTTP routing bug.
    """
    mock_session = AsyncMock()
    mock_session.report_progress = AsyncMock()

    request_context = ServerRequestContext(
        request_id="req-abc-123",
        session=mock_session,
        method="tools/call",
        meta=None,
        lifespan_context=None,
        protocol_version="2025-11-25",
    )

    ctx = Context(request_context=request_context, mcp_server=MagicMock())

    await ctx.report_progress(50, 100, message="halfway")

    mock_session.report_progress.assert_awaited_once_with(50, 100, "halfway")


def _request_context(request: object | None) -> ServerRequestContext[None, object]:
    return ServerRequestContext(
        session=AsyncMock(),
        method="tools/call",
        lifespan_context=None,
        protocol_version="2025-11-25",
        request=request,
    )


def test_context_headers_returns_request_headers():
    request = SimpleNamespace(headers={"x-github-user": "octocat"})
    ctx = Context(request_context=_request_context(request), mcp_server=MagicMock())
    assert ctx.headers == {"x-github-user": "octocat"}


def test_context_headers_is_none_without_request():
    ctx = Context(request_context=_request_context(None), mcp_server=MagicMock())
    assert ctx.headers is None


def test_context_headers_is_none_when_request_carries_no_headers():
    """A transport may attach a custom request object that has no headers attribute."""
    ctx = Context(request_context=_request_context(object()), mcp_server=MagicMock())
    assert ctx.headers is None


async def test_read_resource_template_error():
    """Template-creation failure must surface as INTERNAL_ERROR, not INVALID_PARAMS (not-found)."""
    mcp = MCPServer()

    @mcp.resource("resource://item/{item_id}")
    def get_item(item_id: str) -> str:
        raise RuntimeError("backend unavailable")

    async with Client(mcp) as client:
        with pytest.raises(MCPError, match="Error creating resource from template") as exc_info:
            await client.read_resource("resource://item/42")

        assert exc_info.value.error.code == INTERNAL_ERROR


async def test_read_resource_template_not_found():
    """A template handler raising ResourceNotFoundError must surface as INVALID_PARAMS per SEP-2164."""
    mcp = MCPServer()

    @mcp.resource("resource://users/{user_id}")
    def get_user(user_id: str) -> str:
        raise ResourceNotFoundError(f"no user {user_id}")

    async with Client(mcp) as client:
        with pytest.raises(MCPError, match="no user 999") as exc_info:
            await client.read_resource("resource://users/999")

        assert exc_info.value.error.code == INVALID_PARAMS
        assert exc_info.value.error.data == {"uri": "resource://users/999"}


async def test_tool_returning_input_required_result_reaches_client_sealed():
    # Default posture: the wire carries an opaque sealed token, never the handler's plaintext.
    mcp = MCPServer()

    @mcp.tool()
    async def ask(ctx: Context) -> str | InputRequiredResult:
        return InputRequiredResult(input_requests={"roots": ListRootsRequest()}, request_state="round-1")

    with anyio.fail_after(5):
        async with Client(mcp, mode="2026-07-28") as client:
            result = await client.session.call_tool("ask", allow_input_required=True)

    assert isinstance(result, InputRequiredResult)
    _assert_sealed(result.request_state, "round-1")
    assert result.input_requests is not None
    assert result.input_requests["roots"].method == "roots/list"


async def test_tool_reads_input_responses_and_request_state_from_context_on_retry():
    mcp = MCPServer()

    @mcp.tool()
    async def greet(ctx: Context) -> str | InputRequiredResult:
        responses = ctx.input_responses
        if responses and "who" in responses:
            who = responses["who"]
            assert isinstance(who, ElicitResult) and who.content is not None
            return f"Hello, {who.content['name']}! (state={ctx.request_state})"
        return InputRequiredResult(
            input_requests={
                "who": ElicitRequest(
                    params=ElicitRequestFormParams(
                        message="What is your name?",
                        requested_schema={
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                        },
                    )
                )
            },
            request_state="r1",
        )

    with anyio.fail_after(5):
        async with Client(mcp, mode="2026-07-28") as client:
            r1 = await client.session.call_tool("greet", allow_input_required=True)
            assert isinstance(r1, InputRequiredResult)
            assert r1.input_requests is not None and "who" in r1.input_requests

            r2 = await client.session.call_tool(
                "greet",
                input_responses={"who": ElicitResult(action="accept", content={"name": "Alice"})},
                request_state=r1.request_state,
                allow_input_required=True,
            )
    assert isinstance(r2, CallToolResult)
    block = r2.content[0]
    assert isinstance(block, TextContent)
    assert block.text == "Hello, Alice! (state=r1)"


def _assert_sealed(state: str | None, plaintext: str) -> None:
    """The wire form is an opaque sealed token, never the handler's plaintext."""
    assert state is not None
    assert state != plaintext
    assert state.startswith("v1.")


def _ask_who() -> ElicitRequest:
    return ElicitRequest(
        params=ElicitRequestFormParams(
            message="Who is this for?",
            requested_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
    )


async def test_prompt_returning_input_required_result_reaches_client_sealed():
    """A prompt function may return an InputRequiredResult and the pipeline delivers it
    to the client with the state sealed (spec-mandated: SEP-2322 allows it on prompts/get)."""
    mcp = MCPServer()

    @mcp.prompt()
    async def briefing(ctx: Context) -> list[UserMessage] | InputRequiredResult:
        return InputRequiredResult(input_requests={"who": _ask_who()}, request_state="round-1")

    with anyio.fail_after(5):
        async with Client(mcp, mode="2026-07-28") as client:
            result = await client.session.get_prompt("briefing", allow_input_required=True)

    assert isinstance(result, InputRequiredResult)
    _assert_sealed(result.request_state, "round-1")
    assert result.input_requests is not None
    assert result.input_requests["who"].method == "elicitation/create"


async def test_prompt_reads_input_responses_and_request_state_from_context_on_retry():
    """The prompts/get retry carries input_responses and request_state to the prompt
    function via the Context, completing the SEP-2322 multi-round-trip flow."""
    mcp = MCPServer()

    @mcp.prompt()
    async def briefing(ctx: Context) -> list[UserMessage] | InputRequiredResult:
        responses = ctx.input_responses
        if responses and "who" in responses:
            who = responses["who"]
            assert isinstance(who, ElicitResult) and who.content is not None
            return [UserMessage(content=f"Brief {who.content['name']} (state={ctx.request_state})")]
        return InputRequiredResult(input_requests={"who": _ask_who()}, request_state="r1")

    with anyio.fail_after(5):
        async with Client(mcp, mode="2026-07-28") as client:
            r1 = await client.session.get_prompt("briefing", allow_input_required=True)
            assert isinstance(r1, InputRequiredResult)
            assert r1.input_requests is not None and "who" in r1.input_requests

            r2 = await client.session.get_prompt(
                "briefing",
                input_responses={"who": ElicitResult(action="accept", content={"name": "Alice"})},
                request_state=r1.request_state,
                allow_input_required=True,
            )
    assert isinstance(r2, GetPromptResult)
    block = r2.messages[0].content
    assert isinstance(block, TextContent)
    assert block.text == "Brief Alice (state=r1)"


async def test_prompt_input_required_result_on_legacy_session_is_a_serialization_error():
    """Pins the shared era gate: a pre-2026 session has no input_required vocabulary, so
    the runner rejects the frame with -32603 — the same posture the tools path has."""
    mcp = MCPServer()

    @mcp.prompt()
    async def briefing(ctx: Context) -> list[UserMessage] | InputRequiredResult:
        return InputRequiredResult(input_requests={"who": _ask_who()})

    async with Client(mcp, mode="legacy") as client:
        with pytest.raises(MCPError) as exc:
            await client.get_prompt("briefing")
    assert exc.value.error.code == INTERNAL_ERROR
    assert exc.value.error.message == "Handler returned an invalid result"


async def test_recursive_tool_return_type_lists_and_calls_on_legacy_session():
    """A 2025-11-25 session requires `type: object` at the outputSchema root; a self-referential
    return type must not fail the whole listing, and its result validates client-side via `$defs`."""

    class Node(BaseModel):
        name: str
        children: list["Node"] = []

    mcp = MCPServer()

    @mcp.tool()
    def tree() -> Node:
        return Node(name="root", children=[Node(name="leaf")])

    async with Client(mcp, mode="legacy") as client:
        [tool] = (await client.list_tools()).tools
        assert tool.output_schema is not None
        assert tool.output_schema["type"] == "object"
        assert tool.output_schema["properties"]["children"]["items"] == {"$ref": "#/$defs/Node"}
        result = await client.call_tool("tree", {})
    assert result.structured_content == {"name": "root", "children": [{"name": "leaf", "children": []}]}


async def test_resource_template_input_required_result_on_legacy_session_is_a_serialization_error():
    """Pins the shared era gate for resources/read: a pre-2026 session has no
    input_required vocabulary, so the runner rejects the frame with -32603."""
    mcp = MCPServer()

    @mcp.resource("ask://{topic}")
    async def ask(topic: str, ctx: Context) -> str | InputRequiredResult:
        return InputRequiredResult(input_requests={"who": _ask_who()})

    async with Client(mcp, mode="legacy") as client:
        with pytest.raises(MCPError) as exc:
            await client.read_resource("ask://databases")
    assert exc.value.error.code == INTERNAL_ERROR
    assert exc.value.error.message == "Handler returned an invalid result"


async def test_resource_template_returning_input_required_result_reaches_client_sealed():
    """A resource template function may return an InputRequiredResult and the pipeline
    delivers it with the state sealed (spec-mandated: SEP-2322 allows it on resources/read)."""
    mcp = MCPServer()

    @mcp.resource("ask://{topic}")
    async def ask(topic: str, ctx: Context) -> str | InputRequiredResult:
        return InputRequiredResult(input_requests={"who": _ask_who()}, request_state="round-1")

    with anyio.fail_after(5):
        async with Client(mcp, mode="2026-07-28") as client:
            result = await client.session.read_resource("ask://databases", allow_input_required=True)

    assert isinstance(result, InputRequiredResult)
    _assert_sealed(result.request_state, "round-1")
    assert result.input_requests is not None
    assert result.input_requests["who"].method == "elicitation/create"


async def test_resource_template_reads_input_responses_from_context_on_retry():
    """The resources/read retry carries input_responses to the template function via the
    Context, completing the SEP-2322 multi-round-trip flow."""
    mcp = MCPServer()

    @mcp.resource("ask://{topic}")
    async def ask(topic: str, ctx: Context) -> str | InputRequiredResult:
        responses = ctx.input_responses
        if responses and "who" in responses:
            who = responses["who"]
            assert isinstance(who, ElicitResult) and who.content is not None
            return f"{topic} notes for {who.content['name']}"
        return InputRequiredResult(input_requests={"who": _ask_who()})

    with anyio.fail_after(5):
        async with Client(mcp, mode="2026-07-28") as client:
            r1 = await client.session.read_resource("ask://databases", allow_input_required=True)
            assert isinstance(r1, InputRequiredResult)
            assert r1.input_requests is not None and "who" in r1.input_requests

            r2 = await client.session.read_resource(
                "ask://databases",
                input_responses={"who": ElicitResult(action="accept", content={"name": "Alice"})},
                allow_input_required=True,
            )
    assert isinstance(r2, ReadResourceResult)
    contents = r2.contents[0]
    assert isinstance(contents, TextResourceContents)
    assert contents.text == "databases notes for Alice"


async def test_context_read_resource_raises_on_input_required_result():
    """ctx.read_resource is a content reader: an InputRequiredResult from the template
    raises with a pointer at the forwarding path instead of widening every caller."""
    mcp = MCPServer()

    @mcp.resource("ask://{topic}")
    async def ask(topic: str, ctx: Context) -> str | InputRequiredResult:
        return InputRequiredResult(input_requests={"who": _ask_who()})

    context = Context(mcp_server=mcp)
    with pytest.raises(RuntimeError) as exc:
        await context.read_resource("ask://databases")
    assert str(exc.value) == snapshot(
        "Resource returned InputRequiredResult; ctx.read_resource() only returns "
        "content — use MCPServer.read_resource(uri, context) to receive and forward it."
    )


async def test_mcpserver_read_resource_returns_input_required_result_for_handler_forwarding():
    """MCPServer.read_resource hands the template's InputRequiredResult to a direct caller
    unchanged — the composition path for a handler that forwards it as its own result."""
    mcp = MCPServer()
    sentinel = InputRequiredResult(input_requests={"who": _ask_who()})

    @mcp.resource("ask://{topic}")
    async def ask(topic: str, ctx: Context) -> str | InputRequiredResult:
        return sentinel

    context = Context(mcp_server=mcp)
    result = await mcp.read_resource("ask://databases", context)
    assert result is sentinel


async def test_context_read_resource_keeps_outer_input_responses_from_the_nested_template():
    """ctx.read_resource never participates in the multi-round-trip flow, so the nested
    template must not see the outer request's input_responses/request_state — a colliding
    key would otherwise consume an answer meant for the outer handler's own question."""
    mcp = MCPServer()
    seen_responses: list[InputResponses | None] = []
    seen_state: list[str | None] = []

    @mcp.resource("ask://{topic}")
    async def ask(topic: str, ctx: Context) -> str:
        seen_responses.append(ctx.input_responses)
        seen_state.append(ctx.request_state)
        return f"{topic} content"

    @mcp.tool()
    async def outer(ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses is None:
            return InputRequiredResult(input_requests={"who": _ask_who()}, request_state="outer-state")
        contents = list(await ctx.read_resource("ask://databases"))
        assert isinstance(contents[0].content, str)
        return f"{contents[0].content} (state={ctx.request_state})"

    with anyio.fail_after(5):
        async with Client(mcp, mode="2026-07-28") as client:
            r1 = await client.session.call_tool("outer", allow_input_required=True)
            assert isinstance(r1, InputRequiredResult)
            result = await client.session.call_tool(
                "outer",
                input_responses={"who": ElicitResult(action="accept", content={"name": "Alice"})},
                request_state=r1.request_state,
            )
    assert isinstance(result, CallToolResult)
    block = result.content[0]
    assert isinstance(block, TextContent)
    assert block.text == "databases content (state=outer-state)"
    assert seen_responses == [None]
    assert seen_state == [None]


async def test_prompt_raising_mcp_error_surfaces_code_and_data_to_client():
    """A handler-raised MCPError keeps its code and data through the prompt pipeline —
    the same parity tools/call has, needed for self-service capability rejection."""
    mcp = MCPServer()

    @mcp.prompt()
    async def briefing(ctx: Context) -> str:
        raise MCPError(
            code=MISSING_REQUIRED_CLIENT_CAPABILITY,
            message="needs elicitation",
            data={"requiredCapabilities": ["elicitation"]},
        )

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.get_prompt("briefing")
    assert exc.value.error.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc.value.error.message == "needs elicitation"
    assert exc.value.error.data == {"requiredCapabilities": ["elicitation"]}


async def test_resource_template_raising_mcp_error_surfaces_code_and_data_to_client():
    """A handler-raised MCPError keeps its code and data through the resource template
    pipeline instead of being wrapped into a generic ResourceError."""
    mcp = MCPServer()

    @mcp.resource("ask://{topic}")
    async def ask(topic: str, ctx: Context) -> str:
        raise MCPError(
            code=MISSING_REQUIRED_CLIENT_CAPABILITY,
            message="needs elicitation",
            data={"requiredCapabilities": ["elicitation"]},
        )

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.read_resource("ask://databases")
    assert exc.value.error.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc.value.error.message == "needs elicitation"
    assert exc.value.error.data == {"requiredCapabilities": ["elicitation"]}


async def test_static_resource_raising_mcp_error_surfaces_code_and_data_to_client():
    """A handler-raised MCPError keeps its code and data through the static resource
    read path too — parity with the template path above."""
    mcp = MCPServer()

    @mcp.resource("static://thing")
    def thing() -> str:
        raise MCPError(
            code=MISSING_REQUIRED_CLIENT_CAPABILITY,
            message="needs elicitation",
            data={"requiredCapabilities": ["elicitation"]},
        )

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.read_resource("static://thing")
    assert exc.value.error.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc.value.error.message == "needs elicitation"
    assert exc.value.error.data == {"requiredCapabilities": ["elicitation"]}


def _cause_chain(exc: BaseException | None) -> list[BaseException]:
    """`exc` and everything it explicitly chains back to via `__cause__` (`raise ... from ...`)."""
    chain: list[BaseException] = []
    while exc is not None:
        chain.append(exc)
        exc = exc.__cause__
    return chain


def _server_records(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str, bool]]:
    """(level, message, has-traceback) for every record MCPServer itself wrote."""
    return [
        (r.levelname, r.getMessage(), r.exc_info is not None)
        for r in caplog.records
        if r.name == "mcp.server.mcpserver.server"
    ]


def _logged_exception(caplog: pytest.LogCaptureFixture) -> BaseException:
    """The exception attached to the one MCPServer record that carries a traceback."""
    (exc_info,) = [r.exc_info for r in caplog.records if r.name == "mcp.server.mcpserver.server" and r.exc_info]
    assert exc_info[1] is not None
    return exc_info[1]


async def test_tool_raising_unexpected_exception_is_logged_once_at_error_with_its_traceback(
    caplog: pytest.LogCaptureFixture,
):
    """SDK-defined: a tool crash still reaches the model as is_error, and the server logs the
    original exception exactly once, at ERROR, with the traceback the result text lacks."""
    mcp = MCPServer()
    raised = KeyError("k")

    @mcp.tool()
    def lookup() -> str:
        raise raised

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("lookup", {})

    assert result.is_error is True
    assert result.content == [TextContent(type="text", text="Error executing tool lookup")]
    assert _server_records(caplog) == snapshot([("ERROR", "Tool 'lookup' raised an unexpected exception", True)])
    assert raised in _cause_chain(_logged_exception(caplog))
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


async def test_tool_raising_tool_error_is_logged_at_info_without_traceback(caplog: pytest.LogCaptureFixture):
    """SDK-defined: ToolError marks an anticipated failure, so the same is_error result is
    logged as one INFO record with no traceback rather than as a crash."""
    mcp = MCPServer()

    @mcp.tool()
    def forecast(city: str) -> str:
        raise ToolError(f"no forecast for {city}")

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("forecast", {"city": "Atlantis"})

    assert result.is_error is True
    assert result.content == [TextContent(type="text", text="Error executing tool forecast: no forecast for Atlantis")]
    assert _server_records(caplog) == snapshot(
        [("INFO", "Tool 'forecast' failed: 'Error executing tool forecast: no forecast for Atlantis'", False)]
    )
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_tool_error_subclass_is_still_anticipated(caplog: pytest.LogCaptureFixture):
    """SDK-defined: a user's ToolError subclass is treated like ToolError - INFO, no traceback -
    and reaches a programmatic caller as a plain ToolError carrying the tool-name prefix."""
    mcp = MCPServer()

    class QuotaExceeded(ToolError):
        pass

    @mcp.tool()
    def spend() -> str:
        raise QuotaExceeded("daily quota used up")

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("spend", {})
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("spend", {})

    assert result.is_error is True
    assert type(exc.value) is ToolError
    assert str(exc.value) == snapshot("Error executing tool spend: daily quota used up")
    assert _server_records(caplog) == snapshot(
        [("INFO", "Tool 'spend' failed: 'Error executing tool spend: daily quota used up'", False)]
    )


async def test_tool_argument_validation_failure_is_logged_at_info_without_traceback(
    caplog: pytest.LogCaptureFixture,
):
    """SDK-defined: arguments the model got wrong are the model's to correct, so the rejection
    is logged as one INFO record with no traceback, naming the fields but not the values."""
    mcp = MCPServer()

    @mcp.tool()
    def add(a: int, b: int) -> int:
        raise NotImplementedError

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": "one", "b": 2})

    assert result.is_error is True
    ((level, message, has_traceback),) = _server_records(caplog)
    assert (level, has_traceback) == ("INFO", False)
    # Field names only, repr-quoted: the rejected values are the caller's data and stay out of the log.
    assert message == "Tool 'add' rejected arguments: ['a']"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_tool_argument_validation_failure_chains_directly_to_the_validation_error():
    """SDK-defined: a programmatic caller sees a plain ToolError whose `__cause__` is pydantic's
    ValidationError, with no intermediate wrapper."""
    mcp = MCPServer()

    @mcp.tool()
    def add(a: int, b: int) -> int:
        raise NotImplementedError

    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("add", {"a": "one", "b": 2})
    assert type(exc.value) is ToolError
    assert isinstance(exc.value.__cause__, ValidationError)


async def test_validation_error_raised_inside_the_tool_body_is_a_crash(caplog: pytest.LogCaptureFixture):
    """SDK-defined: only the SDK's own argument validation is anticipated; a pydantic
    ValidationError from the tool's code is logged as a crash with its traceback."""
    mcp = MCPServer()

    class Row(BaseModel):
        n: int

    @mcp.tool()
    def parse() -> str:
        Row.model_validate({"n": "x"})
        raise NotImplementedError

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("parse", {})

    assert result.is_error is True
    assert _server_records(caplog) == snapshot([("ERROR", "Tool 'parse' raised an unexpected exception", True)])
    assert isinstance(_cause_chain(_logged_exception(caplog))[-1], ValidationError)


async def test_return_value_failing_the_output_schema_is_a_crash(caplog: pytest.LogCaptureFixture):
    """SDK-defined: a return value that doesn't match the declared output schema is the tool's
    bug, so it is logged as a crash even though the model still gets an is_error result."""
    mcp = MCPServer()

    class Weather(BaseModel):
        temperature: float

    @mcp.tool()
    def get_weather() -> Weather:
        reading: Any = {"temperature": "warm"}
        return reading

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("get_weather", {})

    assert result.is_error is True
    assert _server_records(caplog) == snapshot([("ERROR", "Tool 'get_weather' raised an unexpected exception", True)])


async def test_unknown_tool_is_logged_at_info_without_traceback(caplog: pytest.LogCaptureFixture):
    """SDK-defined: a call to a name that was never registered is the caller's mistake, logged
    as one INFO record alongside the is_error result."""
    mcp = MCPServer()

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("nope", {})

    assert result.is_error is True
    assert _server_records(caplog) == snapshot([("INFO", "Tool 'nope' failed: 'Unknown tool: nope'", False)])
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_tool_raising_mcp_error_is_not_logged_by_mcpserver(caplog: pytest.LogCaptureFixture):
    """SDK-defined: MCPError is a protocol answer the tool chose, so MCPServer writes no record for it."""
    mcp = MCPServer()

    @mcp.tool()
    def gated() -> str:
        raise MCPError(code=INVALID_PARAMS, message="not for you")

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool("gated", {})

    assert exc.value.error.code == INVALID_PARAMS
    assert _server_records(caplog) == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_resolver_raising_tool_error_is_anticipated(caplog: pytest.LogCaptureFixture):
    """SDK-defined: a ToolError from a Resolve() resolver is classified like one from the tool
    body - INFO, no traceback."""
    mcp = MCPServer(name="resolvers", request_state_security=RequestStateSecurity.ephemeral())

    async def current_user(ctx: Context) -> str:
        raise ToolError("sign in first")

    @mcp.tool()
    async def whoami(user: Annotated[str, Resolve(current_user)]) -> str:
        raise NotImplementedError

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("whoami", {})

    assert result.content == [TextContent(type="text", text="Error executing tool whoami: sign in first")]
    assert _server_records(caplog) == snapshot(
        [("INFO", "Tool 'whoami' failed: 'Error executing tool whoami: sign in first'", False)]
    )


async def test_resolver_crash_is_logged_as_the_tools_crash(caplog: pytest.LogCaptureFixture):
    """SDK-defined: an unexpected exception in a Resolve() resolver is the tool's crash - ERROR
    with a traceback reaching the resolver's exception."""
    mcp = MCPServer(name="resolvers", request_state_security=RequestStateSecurity.ephemeral())
    raised = ConnectionError("user directory unreachable")

    async def current_user(ctx: Context) -> str:
        raise raised

    @mcp.tool()
    async def whoami(user: Annotated[str, Resolve(current_user)]) -> str:
        raise NotImplementedError

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("whoami", {})

    assert result.is_error is True
    assert _server_records(caplog) == snapshot([("ERROR", "Tool 'whoami' raised an unexpected exception", True)])
    assert raised in _cause_chain(_logged_exception(caplog))


async def test_argument_validator_that_crashes_is_the_tools_crash(caplog: pytest.LogCaptureFixture):
    """SDK-defined: pydantic only turns ValueError/AssertionError into ValidationError, so a validator
    raising anything else is a bug in the tool's schema and is wrapped and logged as a crash."""
    mcp = MCPServer()
    raised = TypeError("codes are compared as integers")

    def check(code: str) -> str:
        raise raised

    @mcp.tool()
    def redeem(code: Annotated[str, AfterValidator(check)]) -> str:
        raise NotImplementedError

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("redeem", {"code": "SAVE10"})
    with pytest.raises(UnexpectedToolError) as exc:
        await mcp.call_tool("redeem", {"code": "SAVE10"})

    assert result.content == [TextContent(type="text", text="Error executing tool redeem")]
    assert exc.value.__cause__ is raised
    assert _server_records(caplog) == snapshot([("ERROR", "Tool 'redeem' raised an unexpected exception", True)])


async def test_argument_validator_raising_mcp_error_is_a_protocol_error(caplog: pytest.LogCaptureFixture):
    """SDK-defined: MCPError keeps its meaning wherever it is raised, including inside an argument
    validator: the request fails with that code and MCPServer logs nothing."""
    mcp = MCPServer()

    def check(code: str) -> str:
        raise MCPError(code=INVALID_PARAMS, message="codes are issued per session")

    @mcp.tool()
    def redeem(code: Annotated[str, AfterValidator(check)]) -> str:
        raise NotImplementedError

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool("redeem", {"code": "SAVE10"})

    assert exc.value.error == snapshot(ErrorData(code=INVALID_PARAMS, message="codes are issued per session"))
    assert _server_records(caplog) == []


async def test_resource_error_escaping_a_tool_is_anticipated(caplog: pytest.LogCaptureFixture):
    """SDK-defined: a tool that lets ResourceNotFoundError from ctx.read_resource() propagate has
    reported an anticipated failure, so it is INFO here just as it is for resources/read."""
    mcp = MCPServer()

    @mcp.resource("books://{title}")
    def book(title: str) -> str:
        raise ResourceNotFoundError(f"No book titled {title!r}.")

    @mcp.tool()
    async def summarise(title: str, ctx: Context) -> str:
        await ctx.read_resource(f"books://{title}")
        raise NotImplementedError

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("summarise", {"title": "Nothing"})
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("summarise", {"title": "Nothing"})

    assert result.content == [
        TextContent(type="text", text="Error executing tool summarise: No book titled 'Nothing'.")
    ]
    assert type(exc.value) is ToolError
    assert _server_records(caplog) == snapshot(
        [("INFO", "Tool 'summarise' failed: \"Error executing tool summarise: No book titled 'Nothing'.\"", False)]
    )
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_resource_crash_escaping_a_tool_is_the_tools_crash(caplog: pytest.LogCaptureFixture):
    """SDK-defined: a crashing resource read inside a tool stays a crash under the tool's name, logged
    once, with the traceback reaching the resource function's own exception."""
    mcp = MCPServer()
    raised = ConnectionError("catalog database unreachable")

    @mcp.resource("books://{title}")
    def book(title: str) -> str:
        raise raised

    @mcp.tool()
    async def summarise(title: str, ctx: Context) -> str:
        await ctx.read_resource(f"books://{title}")
        raise NotImplementedError

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("summarise", {"title": "Dune"})

    assert result.content == [
        TextContent(
            type="text",
            text="Error executing tool summarise: Error creating resource from template books://Dune",
        )
    ]
    assert _server_records(caplog) == snapshot([("ERROR", "Tool 'summarise' raised an unexpected exception", True)])
    assert raised in _cause_chain(_logged_exception(caplog))


async def test_tool_that_recovers_from_a_missing_resource_logs_nothing(caplog: pytest.LogCaptureFixture):
    """SDK-defined: MCPServer.read_resource() itself writes no record, so a tool that catches
    ResourceNotFoundError and carries on leaves the log clean."""
    mcp = MCPServer()

    @mcp.resource("books://{title}")
    def book(title: str) -> str:
        raise ResourceNotFoundError(f"No book titled {title!r}.")

    @mcp.tool()
    async def summarise(title: str, ctx: Context) -> str:
        try:
            await ctx.read_resource(f"books://{title}")
        except ResourceNotFoundError:
            return "not in the catalog"
        raise NotImplementedError

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("summarise", {"title": "Nothing"})

    assert result.content == [TextContent(type="text", text="not in the catalog")]
    assert _server_records(caplog) == []


async def test_static_resource_raising_unexpected_exception_is_logged_once_at_error_with_its_traceback(
    caplog: pytest.LogCaptureFixture,
):
    """SDK-defined: the client gets a -32603 naming only the URI, and the withheld original is
    logged exactly once, at ERROR, with its traceback."""
    mcp = MCPServer()
    raised = RuntimeError("connection pool exhausted")

    @mcp.resource("db://stats")
    def stats() -> str:
        raise raised

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.read_resource("db://stats")

    assert exc.value.error == snapshot(
        ErrorData(code=INTERNAL_ERROR, message="Error reading resource db://stats", data={"uri": "db://stats"})
    )
    assert _server_records(caplog) == snapshot(
        [("ERROR", "Resource 'db://stats' raised an unexpected exception", True)]
    )
    assert raised in _cause_chain(_logged_exception(caplog))
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


async def test_resource_template_raising_unexpected_exception_is_logged_once_at_error_with_its_traceback(
    caplog: pytest.LogCaptureFixture,
):
    """SDK-defined: a template handler crash surfaces as -32603 naming only the URI, and the
    withheld original is logged exactly once, at ERROR, with its traceback."""
    mcp = MCPServer()
    raised = RuntimeError("connection pool exhausted")

    @mcp.resource("db://tables/{table}")
    def describe(table: str) -> str:
        raise raised

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.read_resource("db://tables/users")

    assert exc.value.error == snapshot(
        ErrorData(
            code=INTERNAL_ERROR,
            message="Error creating resource from template db://tables/users",
            data={"uri": "db://tables/users"},
        )
    )
    assert _server_records(caplog) == snapshot(
        [("ERROR", "Resource 'db://tables/users' raised an unexpected exception", True)]
    )
    assert raised in _cause_chain(_logged_exception(caplog))
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 1


async def test_read_resource_wraps_a_crash_as_unexpected_resource_error_chained_to_the_original():
    """SDK-defined: for static and template resources alike, a programmatic caller gets
    UnexpectedResourceError naming only the URI, with `__cause__` the handler's own exception."""
    mcp = MCPServer()
    raised = RuntimeError("connection pool exhausted")

    @mcp.resource("db://stats")
    def stats() -> str:
        raise raised

    @mcp.resource("db://tables/{table}")
    def describe(table: str) -> str:
        raise raised

    with pytest.raises(UnexpectedResourceError) as static:
        await mcp.read_resource("db://stats")
    with pytest.raises(UnexpectedResourceError) as template:
        await mcp.read_resource("db://tables/users")

    assert str(static.value) == snapshot("Error reading resource db://stats")
    assert static.value.__cause__ is raised
    assert str(template.value) == snapshot("Error creating resource from template db://tables/users")
    assert template.value.__cause__ is raised


async def test_custom_resource_subclass_crash_is_wrapped_and_logged_like_a_function_resource(
    caplog: pytest.LogCaptureFixture,
):
    """SDK-defined: a hand-written Resource subclass whose read() raises gets the same treatment as
    a decorated function - -32603 naming only the URI, one ERROR record chaining to the original."""
    raised = OSError("sensor bus offline")

    class SensorResource(MCPServerResource):
        async def read(self) -> str:
            raise raised

    mcp = MCPServer()
    mcp.add_resource(SensorResource(uri="sensor://temp", name="temp"))

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.read_resource("sensor://temp")

    assert exc.value.error == snapshot(
        ErrorData(code=INTERNAL_ERROR, message="Error reading resource sensor://temp", data={"uri": "sensor://temp"})
    )
    assert _server_records(caplog) == snapshot(
        [("ERROR", "Resource 'sensor://temp' raised an unexpected exception", True)]
    )
    logged = _logged_exception(caplog)
    assert isinstance(logged, UnexpectedResourceError) and logged.__cause__ is raised


async def test_static_resource_raising_resource_not_found_error_is_invalid_params_logged_at_info(
    caplog: pytest.LogCaptureFixture,
):
    """SDK-defined: ResourceNotFoundError from a static resource handler passes through as -32602
    with the handler's message, as it does from a template handler, and is logged at INFO."""
    mcp = MCPServer()

    @mcp.resource("reports://latest")
    def latest() -> str:
        raise ResourceNotFoundError("no report has been generated yet")

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.read_resource("reports://latest")

    assert exc.value.error == snapshot(
        ErrorData(code=INVALID_PARAMS, message="no report has been generated yet", data={"uri": "reports://latest"})
    )
    assert _server_records(caplog) == snapshot(
        [("INFO", "Resource 'reports://latest' failed: 'no report has been generated yet'", False)]
    )
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_deliberate_resource_error_passes_its_message_through_and_is_logged_at_info(
    caplog: pytest.LogCaptureFixture,
):
    """SDK-defined: a ResourceError the handler raised on purpose reaches the client as -32603 with
    the handler's message, from a static resource as from a template, and is one INFO record each."""
    mcp = MCPServer()

    @mcp.resource("db://stats")
    def stats() -> str:
        raise ResourceError("stats database is in maintenance")

    @mcp.resource("db://tables/{table}")
    def describe(table: str) -> str:
        raise ResourceError(f"table {table} is being rebuilt")

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as static:
            await client.read_resource("db://stats")
        with pytest.raises(MCPError) as template:
            await client.read_resource("db://tables/users")

    assert static.value.error == snapshot(
        ErrorData(code=INTERNAL_ERROR, message="stats database is in maintenance", data={"uri": "db://stats"})
    )
    assert template.value.error == snapshot(
        ErrorData(code=INTERNAL_ERROR, message="table users is being rebuilt", data={"uri": "db://tables/users"})
    )
    assert _server_records(caplog) == snapshot(
        [
            ("INFO", "Resource 'db://stats' failed: 'stats database is in maintenance'", False),
            ("INFO", "Resource 'db://tables/users' failed: 'table users is being rebuilt'", False),
        ]
    )
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_prompt_raising_unexpected_exception_is_logged_once(caplog: pytest.LogCaptureFixture):
    """SDK-defined: a prompt crash is logged exactly once, by the dispatcher boundary that turns it
    into the JSON-RPC error, and not a second time by MCPServer."""
    mcp = MCPServer()
    raised = RuntimeError("template store unreachable")

    @mcp.prompt()
    def briefing() -> str:
        raise raised

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc:
            await client.get_prompt("briefing")

    assert exc.value.error.code == INTERNAL_ERROR
    assert _server_records(caplog) == []
    (record,) = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None and raised in _cause_chain(record.exc_info[1])


async def test_call_tool_wraps_a_crash_as_unexpected_tool_error_chained_to_the_original():
    """SDK-defined: programmatic callers can tell a crash from a deliberate ToolError by type and
    reach the original exception through `__cause__`."""
    mcp = MCPServer()
    raised = RuntimeError("boom")

    @mcp.tool()
    def explode() -> str:
        raise raised

    with pytest.raises(UnexpectedToolError) as exc:
        await mcp.call_tool("explode", {})
    assert str(exc.value) == snapshot("Error executing tool explode")
    assert exc.value.__cause__ is raised


async def test_call_tool_keeps_a_deliberate_tool_error_a_plain_tool_error():
    """SDK-defined: a ToolError raised by the tool is re-raised as a plain ToolError carrying the
    tool-name prefix, never reclassified as unexpected."""
    mcp = MCPServer()

    @mcp.tool()
    def refuse() -> str:
        raise ToolError("not today")

    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("refuse", {})
    assert type(exc.value) is ToolError
    assert str(exc.value) == snapshot("Error executing tool refuse: not today")


async def test_nested_tool_crash_stays_unexpected_through_the_outer_tool(caplog: pytest.LogCaptureFixture):
    """SDK-defined: when a tool awaits another tool that crashes, the outer wrapper keeps the
    UnexpectedToolError classification, so the crash is still logged once with its traceback."""
    mcp = MCPServer()
    raised = ZeroDivisionError("division by zero")

    @mcp.tool()
    def inner() -> str:
        raise raised

    @mcp.tool()
    async def outer(ctx: Context) -> str:
        await ctx.mcp_server.call_tool("inner", {})
        raise NotImplementedError

    caplog.set_level(logging.INFO)
    async with Client(mcp) as client:
        result = await client.call_tool("outer", {})

    assert result.content == [TextContent(type="text", text="Error executing tool outer: Error executing tool inner")]
    assert _server_records(caplog) == snapshot([("ERROR", "Tool 'outer' raised an unexpected exception", True)])
    assert raised in _cause_chain(_logged_exception(caplog))


async def test_context_exposes_client_capabilities_from_connection():
    mcp = MCPServer()
    seen: list[ClientCapabilities | None] = []

    @mcp.tool()
    async def probe(ctx: Context) -> str:
        seen.append(ctx.client_capabilities)
        return "ok"

    with anyio.fail_after(5):
        async with Client(mcp, mode="2026-07-28") as client:
            await client.call_tool("probe")

    assert len(seen) == 1
    assert isinstance(seen[0], ClientCapabilities)


async def test_context_input_responses_and_request_state_are_none_on_initial_round():
    mcp = MCPServer()
    captured: dict[str, Any] = {}

    @mcp.tool()
    async def probe(ctx: Context) -> str:
        captured["responses"] = ctx.input_responses
        captured["state"] = ctx.request_state
        return "ok"

    with anyio.fail_after(5):
        async with Client(mcp, mode="2026-07-28") as client:
            await client.call_tool("probe")

    assert captured == {"responses": None, "state": None}


async def test_context_notify_methods_publish_to_the_configured_bus() -> None:
    bus = InMemorySubscriptionBus()
    mcp = MCPServer(subscriptions=bus)
    seen: list[ServerEvent] = []
    bus.subscribe(seen.append)

    @mcp.tool()
    async def touch(ctx: Context) -> str:
        await ctx.notify_tools_changed()
        await ctx.notify_prompts_changed()
        await ctx.notify_resources_changed()
        await ctx.notify_resource_updated("r://x")
        return "ok"

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            await client.call_tool("touch")

    assert seen == [ToolsListChanged(), PromptsListChanged(), ResourcesListChanged(), ResourceUpdated(uri="r://x")]


async def test_programmatic_entry_points_carry_the_subscription_bus() -> None:
    """`ctx.notify_*` works when tools, resources, and prompts are invoked
    programmatically (no wire request): the server-scoped bus rides along in
    the fallback Context."""
    bus = InMemorySubscriptionBus()
    mcp = MCPServer(subscriptions=bus)
    seen: list[ServerEvent] = []
    bus.subscribe(seen.append)

    @mcp.tool()
    async def touch_tools(ctx: Context) -> str:
        await ctx.notify_tools_changed()
        return "ok"

    @mcp.resource("res://{name}")
    async def thing(name: str, ctx: Context) -> str:
        await ctx.notify_resources_changed()
        return "data"

    @mcp.prompt()
    async def ask(ctx: Context) -> str:
        await ctx.notify_prompts_changed()
        return "question"

    await mcp.call_tool("touch_tools", {})
    await mcp.read_resource("res://thing")
    await mcp.get_prompt("ask")

    assert seen == [ToolsListChanged(), ResourcesListChanged(), PromptsListChanged()]


def test_context_mcp_server_outside_request_raises() -> None:
    with pytest.raises(ValueError, match="outside of a request"):
        _ = Context().mcp_server


async def test_context_notify_outside_a_request_raises() -> None:
    with pytest.raises(ValueError, match="outside of a request"):
        await Context().notify_tools_changed()


def test_context_exposes_its_mcp_server() -> None:
    mcp = MCPServer()
    assert Context(mcp_server=mcp).mcp_server is mcp


def test_remove_prompt_removes_and_unknown_name_raises() -> None:
    mcp = MCPServer()

    @mcp.prompt()
    def greeting() -> str:  # pragma: no cover
        return "hello"

    assert len(mcp._prompt_manager.list_prompts()) == 1
    mcp.remove_prompt("greeting")
    assert mcp._prompt_manager.list_prompts() == []
    with pytest.raises(ValueError, match="Unknown prompt: greeting"):
        mcp.remove_prompt("greeting")


@pytest.mark.anyio
async def test_middleware_kwarg_and_property_share_the_low_level_chain() -> None:
    """SDK-defined: `MCPServer(middleware=[...])` appends to the low-level chain after
    the SDK's built-ins, and `mcp.middleware` is that same live list, so a
    middleware appended later still wraps requests."""
    seen: list[str] = []

    async def from_ctor(ctx: ServerRequestContext[Any, Any], call_next: Any) -> Any:
        seen.append(f"ctor:{ctx.method}")
        return await call_next(ctx)

    async def appended(ctx: ServerRequestContext[Any, Any], call_next: Any) -> Any:
        seen.append(f"appended:{ctx.method}")
        return await call_next(ctx)

    mcp = MCPServer("mw", middleware=[from_ctor])
    assert mcp.middleware is mcp._lowlevel_server.middleware
    assert mcp.middleware[-1] is from_ctor  # after the built-ins, outermost-first
    mcp.middleware.append(appended)

    @mcp.tool()
    def ping() -> str:
        return "pong"

    async with Client(mcp) as client:
        await client.call_tool("ping", {})
    assert "ctor:tools/call" in seen
    assert seen.index("ctor:tools/call") < seen.index("appended:tools/call")


@pytest.mark.anyio
async def test_middleware_can_refuse_subscriptions_listen_before_the_ack() -> None:
    """Spec-adjacent: a middleware that raises on `subscriptions/listen` refuses the
    request in-band - the client gets the error and no stream is opened."""

    async def refuse_listen(ctx: ServerRequestContext[Any, Any], call_next: Any) -> Any:
        if ctx.method == "subscriptions/listen":
            raise MCPError(INVALID_REQUEST, "not permitted to watch the requested resources")
        return await call_next(ctx)

    mcp = MCPServer("mw", middleware=[refuse_listen])

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            async with client.listen(resource_subscriptions=["files://payroll.csv"]):
                pass  # pragma: no cover - the refusal precedes the stream
    assert exc_info.value.error.code == INVALID_REQUEST
    assert exc_info.value.error.message == "not permitted to watch the requested resources"
