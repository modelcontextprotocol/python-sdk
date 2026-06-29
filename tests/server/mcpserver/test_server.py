import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
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
    GetPromptResult,
    Icon,
    ImageContent,
    InputRequiredResult,
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
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from mcp.client import Client
from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer, ResourceSecurity
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from mcp.server.mcpserver.prompts.base import Message, UserMessage
from mcp.server.mcpserver.resources import FileResource, FunctionResource
from mcp.server.mcpserver.utilities.types import Audio, Image
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
        mcp = MCPServer("test")
        # Use host="0.0.0.0" to avoid auto DNS protection
        app = mcp.sse_app(host="0.0.0.0")

        assert isinstance(app, Starlette)

        sse_routes = [r for r in app.routes if isinstance(r, Route)]
        mount_routes = [r for r in app.routes if isinstance(r, Mount)]

        assert len(sse_routes) == 1, "Should have one SSE route"
        assert len(mount_routes) == 1, "Should have one mount route"
        assert sse_routes[0].path == "/sse"
        assert mount_routes[0].path == "/messages"

    async def test_non_ascii_description(self):
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
    """DNS rebinding protection auto-config is driven by the host passed to sse_app()/streamable_http_app()."""

    def test_auto_enabled_for_127_0_0_1_sse(self):
        mcp = MCPServer()
        # transport_security isn't externally inspectable; assert only that the app builds
        app = mcp.sse_app(host="127.0.0.1")
        assert app is not None

    def test_auto_enabled_for_127_0_0_1_streamable_http(self):
        mcp = MCPServer()
        app = mcp.streamable_http_app(host="127.0.0.1")
        assert app is not None

    def test_auto_enabled_for_localhost_sse(self):
        mcp = MCPServer()
        app = mcp.sse_app(host="localhost")
        assert app is not None

    def test_auto_enabled_for_ipv6_localhost_sse(self):
        mcp = MCPServer()
        app = mcp.sse_app(host="::1")
        assert app is not None

    def test_not_auto_enabled_for_other_hosts_sse(self):
        mcp = MCPServer()
        app = mcp.sse_app(host="0.0.0.0")
        assert app is not None

    def test_explicit_settings_not_overridden_sse(self):
        custom_settings = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )
        mcp = MCPServer()
        app = mcp.sse_app(host="127.0.0.1", transport_security=custom_settings)
        assert app is not None

    def test_explicit_settings_not_overridden_streamable_http(self):
        custom_settings = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )
        mcp = MCPServer()
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
            assert "Test error" in content.text
            assert result.is_error is True

    async def test_tool_error_handling(self):
        mcp = MCPServer()
        mcp.add_tool(error_tool_fn)
        async with Client(mcp) as client:
            result = await client.call_tool("error_tool_fn", {})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert "Test error" in content.text
            assert result.is_error is True

    async def test_tool_error_details(self):
        mcp = MCPServer()
        mcp.add_tool(error_tool_fn)
        async with Client(mcp) as client:
            result = await client.call_tool("error_tool_fn", {})
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert isinstance(content.text, str)
            assert "Test error" in content.text
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
            decoded = base64.b64decode(content.data)
            assert decoded == b"fake png data"
            # Image/Audio helper returns produce no structured output
            assert result.structured_content is None

    async def test_tool_audio_helper(self, tmp_path: Path):
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
            decoded = base64.b64decode(content.data)
            assert decoded == b"fake wav data"
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
        mcp = MCPServer()
        mcp.add_tool(audio_tool_fn)

        audio_path = tmp_path / filename
        audio_path.write_bytes(b"fake audio data")

        async with Client(mcp) as client:
            result = await client.call_tool("audio_tool_fn", {"path": str(audio_path)})
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, AudioContent)
            assert content.type == "audio"
            assert content.mime_type == expected_mime_type
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
            assert result.structured_content is not None
            assert "result" in result.structured_content
            structured_result = result.structured_content["result"]
            assert len(structured_result) == 3

            expected_content = [
                {"type": "text", "text": "Hello"},
                {"type": "image", "data": "abc", "mimeType": "image/png"},
                {"type": "audio", "data": "def", "mimeType": "audio/wav"},
            ]

            for i, expected in enumerate(expected_content):
                for key, value in expected.items():
                    assert structured_result[i][key] == value

    async def test_tool_mixed_list_with_audio_and_image(self, tmp_path: Path):
        image_path = tmp_path / "test.png"
        image_path.write_bytes(b"test image data")

        audio_path = tmp_path / "test.wav"
        audio_path.write_bytes(b"test audio data")

        # TODO(Marcelo): adding the proper type hint generates an invalid JSON schema.
        def mixed_list_fn() -> list:  # type: ignore
            return [  # type: ignore
                "text message",
                Image(image_path),
                Audio(audio_path),
                {"key": "value"},
                TextContent(type="text", text="direct content"),
            ]

        mcp = MCPServer()
        mcp.add_tool(mixed_list_fn)  # type: ignore
        async with Client(mcp) as client:
            result = await client.call_tool("mixed_list_fn", {})
            assert len(result.content) == 5
            content1 = result.content[0]
            assert isinstance(content1, TextContent)
            assert content1.text == "text message"
            content2 = result.content[1]
            assert isinstance(content2, ImageContent)
            assert content2.mime_type == "image/png"
            assert base64.b64decode(content2.data) == b"test image data"
            content3 = result.content[2]
            assert isinstance(content3, AudioContent)
            assert content3.mime_type == "audio/wav"
            assert base64.b64decode(content3.data) == b"test audio data"
            content4 = result.content[3]
            assert isinstance(content4, TextContent)
            assert '"key": "value"' in content4.text
            content5 = result.content[4]
            assert isinstance(content5, TextContent)
            assert content5.text == "direct content"
            # Untyped list containing Image objects yields no structured output
            assert result.structured_content is None

    async def test_tool_structured_output_basemodel(self):
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
            tools = await client.list_tools()
            tool = next(t for t in tools.tools if t.name == "get_user")
            assert tool.output_schema is not None
            assert tool.output_schema["type"] == "object"
            assert "name" in tool.output_schema["properties"]
            assert "age" in tool.output_schema["properties"]

            result = await client.call_tool("get_user", {"user_id": 123})
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content == {"name": "John Doe", "age": 30, "active": True}
            assert len(result.content) == 1
            assert isinstance(result.content[0], TextContent)
            assert '"name": "John Doe"' in result.content[0].text

    async def test_tool_structured_output_primitive(self):
        def calculate_sum(a: int, b: int) -> int:
            """Add two numbers"""
            return a + b

        mcp = MCPServer()
        mcp.add_tool(calculate_sum)

        async with Client(mcp) as client:
            tools = await client.list_tools()
            tool = next(t for t in tools.tools if t.name == "calculate_sum")
            assert tool.output_schema is not None
            # Primitive types are wrapped
            assert tool.output_schema["type"] == "object"
            assert "result" in tool.output_schema["properties"]
            assert tool.output_schema["properties"]["result"]["type"] == "integer"

            result = await client.call_tool("calculate_sum", {"a": 5, "b": 7})
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content == {"result": 12}

    async def test_tool_structured_output_list(self):
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
            tools = await client.list_tools()
            tool = next(t for t in tools.tools if t.name == "get_metadata")
            assert tool.output_schema is not None
            assert tool.output_schema["type"] == "object"
            # dict[str, Any] should have minimal schema
            assert (
                "additionalProperties" not in tool.output_schema
                or tool.output_schema.get("additionalProperties") is True
            )

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
        def get_settings() -> dict[str, str]:
            """Get settings as string dictionary"""
            return {"theme": "dark", "language": "en", "timezone": "UTC"}

        mcp = MCPServer()
        mcp.add_tool(get_settings)

        async with Client(mcp) as client:
            tools = await client.list_tools()
            tool = next(t for t in tools.tools if t.name == "get_settings")
            assert tool.output_schema is not None
            assert tool.output_schema["type"] == "object"
            assert tool.output_schema["additionalProperties"]["type"] == "string"

            result = await client.call_tool("get_settings", {})
            assert result.is_error is False
            assert result.structured_content == {"theme": "dark", "language": "en", "timezone": "UTC"}

    async def test_remove_tool(self):
        mcp = MCPServer()
        mcp.add_tool(tool_fn)

        assert len(mcp._tool_manager.list_tools()) == 1

        mcp.remove_tool("tool_fn")

        assert len(mcp._tool_manager.list_tools()) == 0

    async def test_remove_nonexistent_tool(self):
        mcp = MCPServer()

        with pytest.raises(ToolError, match="Unknown tool: nonexistent"):
            mcp.remove_tool("nonexistent")

    async def test_remove_tool_and_list(self):
        mcp = MCPServer()
        mcp.add_tool(tool_fn)
        mcp.add_tool(error_tool_fn)

        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 2
            tool_names = [t.name for t in tools.tools]
            assert "tool_fn" in tool_names
            assert "error_tool_fn" in tool_names

        mcp.remove_tool("tool_fn")

        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 1
            assert tools.tools[0].name == "error_tool_fn"

    async def test_remove_tool_and_call(self):
        mcp = MCPServer()
        mcp.add_tool(tool_fn)

        async with Client(mcp) as client:
            result = await client.call_tool("tool_fn", {"x": 1, "y": 2})
            assert not result.is_error
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert content.text == "3"

        mcp.remove_tool("tool_fn")

        async with Client(mcp) as client:
            result = await client.call_tool("tool_fn", {"x": 1, "y": 2})
            assert result.is_error
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert "Unknown tool" in content.text


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

        text_file = tmp_path / "test.txt"
        text_file.write_text("Hello from file!")

        resource = FileResource(uri="file://test.txt", name="test.txt", path=text_file)
        mcp.add_resource(resource)

        async with Client(mcp) as client:
            result = await client.read_resource("file://test.txt")

            assert isinstance(result.contents[0], TextResourceContents)
            assert result.contents[0].text == "Hello from file!"

    async def test_file_resource_binary(self, tmp_path: Path):
        mcp = MCPServer()

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
        mcp = MCPServer()

        with pytest.raises(ValueError, match="has no URI template variables"):

            @mcp.resource("resource://data")
            def get_data_fn(param: str) -> str:  # pragma: no cover
                return f"Data: {param}"

    async def test_resource_with_uri_params(self):
        mcp = MCPServer()

        with pytest.raises(ValueError, match="Mismatch between URI parameters"):

            @mcp.resource("resource://{param}")
            def get_data() -> str:  # pragma: no cover
                return "Data"

    async def test_resource_with_untyped_params(self):
        mcp = MCPServer()

        @mcp.resource("resource://{param}")
        def get_data(param) -> str:  # type: ignore  # pragma: no cover
            return "Data"

    async def test_resource_matching_params(self):
        mcp = MCPServer()

        @mcp.resource("resource://{name}/data")
        def get_data(name: str) -> str:
            return f"Data for {name}"

        async with Client(mcp) as client:
            result = await client.read_resource("resource://test/data")

            assert isinstance(result.contents[0], TextResourceContents)
            assert result.contents[0].text == "Data for test"

    async def test_resource_mismatched_params(self):
        mcp = MCPServer()

        with pytest.raises(ValueError, match="Mismatch between URI parameters"):

            @mcp.resource("resource://{name}/data")
            def get_data(user: str) -> str:  # pragma: no cover
                return f"Data for {user}"

    async def test_resource_multiple_params(self):
        mcp = MCPServer()

        @mcp.resource("resource://{org}/{repo}/data")
        def get_data(org: str, repo: str) -> str:
            return f"Data for {org}/{repo}"

        async with Client(mcp) as client:
            result = await client.read_resource("resource://cursor/myrepo/data")

            assert isinstance(result.contents[0], TextResourceContents)
            assert result.contents[0].text == "Data for cursor/myrepo"

    async def test_resource_multiple_mismatched_params(self):
        mcp = MCPServer()

        with pytest.raises(ValueError, match="Mismatch between URI parameters"):

            @mcp.resource("resource://{org}/{repo}/data")
            def get_data_mismatched(org: str, repo_2: str) -> str:  # pragma: no cover
                return f"Data for {org}"

        mcp = MCPServer()

        @mcp.resource("resource://static")
        def get_static_data() -> str:
            return "Static data"

        async with Client(mcp) as client:
            result = await client.read_resource("resource://static")

            assert isinstance(result.contents[0], TextResourceContents)
            assert result.contents[0].text == "Static data"

    async def test_template_to_resource_conversion(self):
        mcp = MCPServer()

        @mcp.resource("resource://{name}/data")
        def get_data(name: str) -> str:
            return f"Data for {name}"

        assert len(mcp._resource_manager._templates) == 1
        assert len(await mcp.list_resources()) == 0

        resource = await mcp._resource_manager.get_resource("resource://test/data", Context())
        assert isinstance(resource, FunctionResource)
        result = await resource.read()
        assert result == "Data for test"

    async def test_resource_template_includes_mime_type(self):
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
                    contents=[TextResourceContents(uri="resource://bob/csv", mime_type="text/csv", text="csv for bob")]
                )
            )


class TestServerResourceMetadata:
    """Meta from the @resource decorator flows through to list and read responses."""

    async def test_resource_decorator_with_metadata(self):
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
        mcp = MCPServer()

        @mcp.resource("resource://data", meta={"version": "1.0", "category": "config"})
        def get_data() -> str:
            return "test data"

        async with Client(mcp) as client:
            result = await client.read_resource("resource://data")
            assert result == snapshot(
                ReadResourceResult(
                    contents=[
                        TextResourceContents(
                            uri="resource://data",
                            mime_type="text/plain",
                            meta={"version": "1.0", "category": "config"},  # type: ignore[reportUnknownMemberType]
                            text="test data",
                        )
                    ]
                )
            )


class TestContextInjection:
    async def test_context_detection(self):
        mcp = MCPServer()

        def tool_with_context(x: int, ctx: Context) -> str:  # pragma: no cover
            return f"Request {ctx.request_id}: {x}"

        tool = mcp._tool_manager.add_tool(tool_with_context)
        assert tool.context_kwarg == "ctx"

    async def test_context_injection(self):
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
        mcp = MCPServer()

        @mcp.resource("resource://context/{name}")
        def resource_with_context(name: str, ctx: Context) -> str:
            """Resource that receives context."""
            assert ctx is not None
            return f"Resource {name} - context injected"

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
            assert "Resource test - context injected" == content.text

    async def test_resource_without_context(self):
        mcp = MCPServer()

        @mcp.resource("resource://nocontext/{name}")
        def resource_no_context(name: str) -> str:
            """Resource without context."""
            return f"Resource {name} works"

        templates = mcp._resource_manager.list_templates()
        assert len(templates) == 1
        template = templates[0]
        assert template.context_kwarg is None

        async with Client(mcp) as client:
            result = await client.read_resource("resource://nocontext/test")
            assert result == snapshot(
                ReadResourceResult(
                    contents=[
                        TextResourceContents(
                            uri="resource://nocontext/test", mime_type="text/plain", text="Resource test works"
                        )
                    ]
                )
            )

    async def test_resource_context_custom_name(self):
        mcp = MCPServer()

        @mcp.resource("resource://custom/{id}")
        def resource_custom_ctx(id: str, my_ctx: Context) -> str:
            """Resource with custom context parameter name."""
            assert my_ctx is not None
            return f"Resource {id} with context"

        templates = mcp._resource_manager.list_templates()
        assert len(templates) == 1
        template = templates[0]
        assert template.context_kwarg == "my_ctx"

        async with Client(mcp) as client:
            result = await client.read_resource("resource://custom/123")
            assert result == snapshot(
                ReadResourceResult(
                    contents=[
                        TextResourceContents(
                            uri="resource://custom/123", mime_type="text/plain", text="Resource 123 with context"
                        )
                    ]
                )
            )

    async def test_prompt_with_context(self):
        mcp = MCPServer()

        @mcp.prompt("prompt_with_ctx")
        def prompt_with_context(text: str, ctx: Context) -> str:
            """Prompt that expects context."""
            assert ctx is not None
            return f"Prompt '{text}' - context injected"

        async with Client(mcp) as client:
            result = await client.get_prompt("prompt_with_ctx", {"text": "test"})
            assert len(result.messages) == 1
            content = result.messages[0].content
            assert isinstance(content, TextContent)
            assert "Prompt 'test' - context injected" in content.text

    async def test_prompt_without_context(self):
        mcp = MCPServer()

        @mcp.prompt("prompt_no_ctx")
        def prompt_no_context(text: str) -> str:
            """Prompt without context."""
            return f"Prompt '{text}' works"

        async with Client(mcp) as client:
            result = await client.get_prompt("prompt_no_ctx", {"text": "test"})
            assert len(result.messages) == 1
            message = result.messages[0]
            content = message.content
            assert isinstance(content, TextContent)
            assert content.text == "Prompt 'test' works"


class TestServerPrompts:
    async def test_get_prompt_direct_call_without_context(self):
        mcp = MCPServer()

        @mcp.prompt()
        def fn() -> str:
            return "Hello, world!"

        result = await mcp.get_prompt("fn")
        content = result.messages[0].content
        assert isinstance(content, TextContent)
        assert content.text == "Hello, world!"

    async def test_prompt_decorator(self):
        mcp = MCPServer()

        @mcp.prompt()
        def fn() -> str:
            return "Hello, world!"

        prompts = mcp._prompt_manager.list_prompts()
        assert len(prompts) == 1
        assert prompts[0].name == "fn"
        # Don't compare functions directly since validate_call wraps them
        content = await prompts[0].render(None, Context())
        assert isinstance(content[0].content, TextContent)
        assert content[0].content.text == "Hello, world!"

    async def test_prompt_decorator_with_name(self):
        mcp = MCPServer()

        @mcp.prompt(name="custom_name")
        def fn() -> str:
            return "Hello, world!"

        prompts = mcp._prompt_manager.list_prompts()
        assert len(prompts) == 1
        assert prompts[0].name == "custom_name"
        content = await prompts[0].render(None, Context())
        assert isinstance(content[0].content, TextContent)
        assert content[0].content.text == "Hello, world!"

    async def test_prompt_decorator_with_description(self):
        mcp = MCPServer()

        @mcp.prompt(description="A custom description")
        def fn() -> str:
            return "Hello, world!"

        prompts = mcp._prompt_manager.list_prompts()
        assert len(prompts) == 1
        assert prompts[0].description == "A custom description"
        content = await prompts[0].render(None, Context())
        assert isinstance(content[0].content, TextContent)
        assert content[0].content.text == "Hello, world!"

    def test_prompt_decorator_error(self):
        mcp = MCPServer()
        with pytest.raises(TypeError, match="decorator was used incorrectly"):

            @mcp.prompt  # type: ignore
            def fn() -> str: ...  # pragma: no branch

    async def test_list_prompts(self):
        mcp = MCPServer()

        @mcp.prompt()
        def fn(name: str, optional: str = "default") -> str: ...  # pragma: no branch

        async with Client(mcp) as client:
            result = await client.list_prompts()
            assert result == snapshot(
                ListPromptsResult(
                    prompts=[
                        Prompt(
                            name="fn",
                            description="",
                            arguments=[
                                PromptArgument(name="name", required=True),
                                PromptArgument(name="optional", required=False),
                            ],
                        )
                    ]
                )
            )

    async def test_get_prompt(self):
        mcp = MCPServer()

        @mcp.prompt()
        def fn(name: str) -> str:
            return f"Hello, {name}!"

        async with Client(mcp) as client:
            result = await client.get_prompt("fn", {"name": "World"})
            assert result == snapshot(
                GetPromptResult(
                    description="",
                    messages=[PromptMessage(role="user", content=TextContent(text="Hello, World!"))],
                )
            )

    async def test_get_prompt_with_description(self):
        mcp = MCPServer()

        @mcp.prompt(description="Test prompt description")
        def fn(name: str) -> str:
            return f"Hello, {name}!"

        async with Client(mcp) as client:
            result = await client.get_prompt("fn", {"name": "World"})
            assert result.description == "Test prompt description"

    async def test_get_prompt_with_docstring_description(self):
        mcp = MCPServer()

        @mcp.prompt()
        def fn(name: str) -> str:
            """This is the function docstring."""
            return f"Hello, {name}!"

        async with Client(mcp) as client:
            result = await client.get_prompt("fn", {"name": "World"})
            assert result == snapshot(
                GetPromptResult(
                    description="This is the function docstring.",
                    messages=[PromptMessage(role="user", content=TextContent(text="Hello, World!"))],
                )
            )

    async def test_get_prompt_with_resource(self):
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
        mcp = MCPServer()

        async with Client(mcp, mode="legacy") as client:
            with pytest.raises(MCPError, match="Unknown prompt"):
                await client.get_prompt("unknown")

    async def test_get_prompt_missing_args(self):
        mcp = MCPServer()

        @mcp.prompt()
        def prompt_fn(name: str) -> str: ...  # pragma: no branch

        async with Client(mcp, mode="legacy") as client:
            with pytest.raises(MCPError, match="Missing required arguments"):
                await client.get_prompt("prompt_fn")


async def test_resource_decorator_rfc6570_reserved_expansion():
    # Regression: regex-based param extraction couldn't see `path` in `{+path}` and raised a confusing mismatch.
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
    """Clients may omit {?...} query params, so the bound handler parameter must declare a default."""
    mcp = MCPServer()

    with pytest.raises(ValueError, match=r"logs://.*\['level'\].*must declare a default"):

        @mcp.resource("logs://{service}{?level}")
        def tail_logs(service: str, level: str) -> str:
            raise NotImplementedError


async def test_resource_path_param_without_default_accepted():
    """Path variables are always present in a matching URI, so their parameters may be required."""
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
        r = await client.read_resource("data://items/widget")
        assert isinstance(r.contents[0], TextResourceContents)
        assert r.contents[0].text == "item:widget"

        with pytest.raises(MCPError, match="Unknown resource"):
            await client.read_resource("data://items/..")


async def test_resource_template_non_match_is_unknown_resource():
    """A URI shorter than the template's literal segments is -32602 Unknown resource, not an internal error."""
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
    """Security rejections and absent resources are wire-identical: no hint about which check failed."""
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
        result = await client.read_resource("git://diff/../foo")
        assert isinstance(result.contents[0], TextResourceContents)
        assert result.contents[0].text == "diff:../foo"


async def test_resource_security_server_wide_override():
    mcp = MCPServer(resource_security=ResourceSecurity(reject_path_traversal=False))

    @mcp.resource("data://items/{name}")
    def get_item(name: str) -> str:
        return f"item:{name}"

    async with Client(mcp) as client:
        result = await client.read_resource("data://items/..")
        assert isinstance(result.contents[0], TextResourceContents)
        assert result.contents[0].text == "item:.."


async def test_resource_security_namespaced_identifier_requires_exempt():
    """Values like `x:y` parse as Windows drive-relative (discarding the join base), so the default
    absolute-path check flags them; non-filesystem params opt out via `exempt_params`."""
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
    """Errors at decoration time instead of silently registering an unreachable resource."""
    mcp = MCPServer()

    with pytest.raises(ValueError, match="Context injection for static resources is not supported"):

        @mcp.resource("weather://current")
        def current_weather(ctx: Context) -> str:
            raise NotImplementedError


async def test_static_resource_with_extra_params_errors():
    mcp = MCPServer()

    with pytest.raises(ValueError, match="has no URI template variables"):

        @mcp.resource("data://fixed")
        def get_data(name: str) -> str:
            raise NotImplementedError


async def test_completion_decorator() -> None:
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


def test_streamable_http_no_redirect() -> None:
    mcp = MCPServer()
    # streamable_http_path defaults to "/mcp"
    app = mcp.streamable_http_app()

    streamable_routes = [r for r in app.routes if isinstance(r, Route) and hasattr(r, "path") and r.path == "/mcp"]

    assert len(streamable_routes) == 1, "Should have one streamable route"
    assert streamable_routes[0].path == "/mcp", "Streamable route path should be /mcp"


async def test_report_progress_delegates_to_session_report_progress():
    """Stream routing lives in ServerSession's per-request DispatchContext, so Context never
    inspects request metadata itself; see #953 and #2001 for the streamable-HTTP routing bug."""
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


async def test_tool_returning_input_required_result_reaches_client_unchanged():
    mcp = MCPServer()

    @mcp.tool()
    async def ask(ctx: Context) -> str | InputRequiredResult:
        return InputRequiredResult(input_requests={"roots": ListRootsRequest()}, request_state="round-1")

    with anyio.fail_after(5):
        async with Client(mcp, mode="2026-07-28") as client:
            result = await client.session.call_tool("ask", allow_input_required=True)

    assert isinstance(result, InputRequiredResult)
    assert result.request_state == "round-1"
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
