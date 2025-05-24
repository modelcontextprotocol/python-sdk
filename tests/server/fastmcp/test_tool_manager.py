import json
import logging

import pytest
from pydantic import BaseModel

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools import ToolManager
from mcp.server.session import ServerSessionT
from mcp.shared.context import LifespanContextT
from mcp.types import ToolAnnotations


class TestAddTools:
    def test_basic_function(self):
        """Test registering and running a basic function."""

        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        manager = ToolManager()
        manager.add_tool(add)

        tool = manager.get_tool("add")
        assert tool is not None
        assert tool.name == "add"
        assert tool.description == "Add two numbers."
        assert tool.is_async is False
        assert tool.parameters["properties"]["a"]["type"] == "integer"
        assert tool.parameters["properties"]["b"]["type"] == "integer"

    @pytest.mark.anyio
    async def test_async_function(self):
        """Test registering and running an async function."""

        async def fetch_data(url: str) -> str:
            """Fetch data from URL."""
            return f"Data from {url}"

        manager = ToolManager()
        manager.add_tool(fetch_data)

        tool = manager.get_tool("fetch_data")
        assert tool is not None
        assert tool.name == "fetch_data"
        assert tool.description == "Fetch data from URL."
        assert tool.is_async is True
        assert tool.parameters["properties"]["url"]["type"] == "string"

    def test_pydantic_model_function(self):
        """Test registering a function that takes a Pydantic model."""

        class UserInput(BaseModel):
            name: str
            age: int

        def create_user(user: UserInput, flag: bool) -> dict:
            """Create a new user."""
            return {"id": 1, **user.model_dump()}

        manager = ToolManager()
        manager.add_tool(create_user)

        tool = manager.get_tool("create_user")
        assert tool is not None
        assert tool.name == "create_user"
        assert tool.description == "Create a new user."
        assert tool.is_async is False
        assert "name" in tool.parameters["$defs"]["UserInput"]["properties"]
        assert "age" in tool.parameters["$defs"]["UserInput"]["properties"]
        assert "flag" in tool.parameters["properties"]

    def test_add_invalid_tool(self):
        manager = ToolManager()
        with pytest.raises(AttributeError):
            manager.add_tool(1)  # type: ignore

    def test_add_lambda(self):
        manager = ToolManager()
        tool = manager.add_tool(lambda x: x, name="my_tool")
        assert tool.name == "my_tool"

    def test_add_lambda_with_no_name(self):
        manager = ToolManager()
        with pytest.raises(
            ValueError, match="You must provide a name for lambda functions"
        ):
            manager.add_tool(lambda x: x)

    def test_warn_on_duplicate_tools(self, caplog):
        """Test warning on duplicate tools."""

        def f(x: int) -> int:
            return x

        manager = ToolManager()
        manager.add_tool(f)
        with caplog.at_level(logging.WARNING):
            manager.add_tool(f)
            assert "Tool already exists: f" in caplog.text

    def test_disable_warn_on_duplicate_tools(self, caplog):
        """Test disabling warning on duplicate tools."""

        def f(x: int) -> int:
            return x

        manager = ToolManager()
        manager.add_tool(f)
        manager.warn_on_duplicate_tools = False
        with caplog.at_level(logging.WARNING):
            manager.add_tool(f)
            assert "Tool already exists: f" not in caplog.text


class TestCallTools:
    @pytest.mark.anyio
    async def test_call_tool(self):
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        manager = ToolManager()
        manager.add_tool(add)
        result = await manager.call_tool("add", {"a": 1, "b": 2})
        assert result == 3

    @pytest.mark.anyio
    async def test_call_async_tool(self):
        async def double(n: int) -> int:
            """Double a number."""
            return n * 2

        manager = ToolManager()
        manager.add_tool(double)
        result = await manager.call_tool("double", {"n": 5})
        assert result == 10

    @pytest.mark.anyio
    async def test_call_tool_with_default_args(self):
        def add(a: int, b: int = 1) -> int:
            """Add two numbers."""
            return a + b

        manager = ToolManager()
        manager.add_tool(add)
        result = await manager.call_tool("add", {"a": 1})
        assert result == 2

    @pytest.mark.anyio
    async def test_call_tool_with_missing_args(self):
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        manager = ToolManager()
        manager.add_tool(add)
        with pytest.raises(ToolError):
            await manager.call_tool("add", {"a": 1})

    @pytest.mark.anyio
    async def test_call_unknown_tool(self):
        manager = ToolManager()
        with pytest.raises(ToolError):
            await manager.call_tool("unknown", {"a": 1})

    @pytest.mark.anyio
    async def test_call_tool_with_list_int_input(self):
        def sum_vals(vals: list[int]) -> int:
            return sum(vals)

        manager = ToolManager()
        manager.add_tool(sum_vals)
        # Try both with plain list and with JSON list
        result = await manager.call_tool("sum_vals", {"vals": "[1, 2, 3]"})
        assert result == 6
        result = await manager.call_tool("sum_vals", {"vals": [1, 2, 3]})
        assert result == 6

    @pytest.mark.anyio
    async def test_call_tool_with_list_str_or_str_input(self):
        def concat_strs(vals: list[str] | str) -> str:
            return vals if isinstance(vals, str) else "".join(vals)

        manager = ToolManager()
        manager.add_tool(concat_strs)
        # Try both with plain python object and with JSON list
        result = await manager.call_tool("concat_strs", {"vals": ["a", "b", "c"]})
        assert result == "abc"
        result = await manager.call_tool("concat_strs", {"vals": '["a", "b", "c"]'})
        assert result == "abc"
        result = await manager.call_tool("concat_strs", {"vals": "a"})
        assert result == "a"
        result = await manager.call_tool("concat_strs", {"vals": '"a"'})
        assert result == '"a"'

    @pytest.mark.anyio
    async def test_call_tool_with_complex_model(self):
        class MyShrimpTank(BaseModel):
            class Shrimp(BaseModel):
                name: str

            shrimp: list[Shrimp]
            x: None

        def name_shrimp(tank: MyShrimpTank, ctx: Context) -> list[str]:
            return [x.name for x in tank.shrimp]

        manager = ToolManager()
        manager.add_tool(name_shrimp)
        result = await manager.call_tool(
            "name_shrimp",
            {"tank": {"x": None, "shrimp": [{"name": "rex"}, {"name": "gertrude"}]}},
        )
        assert result == ["rex", "gertrude"]
        result = await manager.call_tool(
            "name_shrimp",
            {"tank": '{"x": null, "shrimp": [{"name": "rex"}, {"name": "gertrude"}]}'},
        )
        assert result == ["rex", "gertrude"]


class TestToolSchema:
    @pytest.mark.anyio
    async def test_context_arg_excluded_from_schema(self):
        def something(a: int, ctx: Context) -> int:
            return a

        manager = ToolManager()
        tool = manager.add_tool(something)
        assert "ctx" not in json.dumps(tool.parameters)
        assert "Context" not in json.dumps(tool.parameters)
        assert "ctx" not in tool.fn_metadata.arg_model.model_fields


class TestContextHandling:
    """Test context handling in the tool manager."""

    def test_context_parameter_detection(self):
        """Test that context parameters are properly detected in
        Tool.from_function()."""

        def tool_with_context(x: int, ctx: Context) -> str:
            return str(x)

        manager = ToolManager()
        tool = manager.add_tool(tool_with_context)
        assert tool.context_kwarg == "ctx"

        def tool_without_context(x: int) -> str:
            return str(x)

        tool = manager.add_tool(tool_without_context)
        assert tool.context_kwarg is None

        def tool_with_parametrized_context(
            x: int, ctx: Context[ServerSessionT, LifespanContextT]
        ) -> str:
            return str(x)

        tool = manager.add_tool(tool_with_parametrized_context)
        assert tool.context_kwarg == "ctx"

    @pytest.mark.anyio
    async def test_context_injection(self):
        """Test that context is properly injected during tool execution."""

        def tool_with_context(x: int, ctx: Context) -> str:
            assert isinstance(ctx, Context)
            return str(x)

        manager = ToolManager()
        manager.add_tool(tool_with_context)

        mcp = FastMCP()
        ctx = mcp.get_context()
        result = await manager.call_tool("tool_with_context", {"x": 42}, context=ctx)
        assert result == "42"

    @pytest.mark.anyio
    async def test_context_injection_async(self):
        """Test that context is properly injected in async tools."""

        async def async_tool(x: int, ctx: Context) -> str:
            assert isinstance(ctx, Context)
            return str(x)

        manager = ToolManager()
        manager.add_tool(async_tool)

        mcp = FastMCP()
        ctx = mcp.get_context()
        result = await manager.call_tool("async_tool", {"x": 42}, context=ctx)
        assert result == "42"

    @pytest.mark.anyio
    async def test_context_optional(self):
        """Test that context is optional when calling tools."""

        def tool_with_context(x: int, ctx: Context | None = None) -> str:
            return str(x)

        manager = ToolManager()
        manager.add_tool(tool_with_context)
        # Should not raise an error when context is not provided
        result = await manager.call_tool("tool_with_context", {"x": 42})
        assert result == "42"

    @pytest.mark.anyio
    async def test_context_error_handling(self):
        """Test error handling when context injection fails."""

        def tool_with_context(x: int, ctx: Context) -> str:
            raise ValueError("Test error")

        manager = ToolManager()
        manager.add_tool(tool_with_context)

        mcp = FastMCP()
        ctx = mcp.get_context()
        with pytest.raises(ToolError, match="Error executing tool tool_with_context"):
            await manager.call_tool("tool_with_context", {"x": 42}, context=ctx)


class TestToolAnnotations:
    def test_tool_annotations(self):
        """Test that tool annotations are correctly added to tools."""

        def read_data(path: str) -> str:
            """Read data from a file."""
            return f"Data from {path}"

        annotations = ToolAnnotations(
            title="File Reader",
            readOnlyHint=True,
            openWorldHint=False,
        )

        manager = ToolManager()
        tool = manager.add_tool(read_data, annotations=annotations)

        assert tool.annotations is not None
        assert tool.annotations.title == "File Reader"
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.openWorldHint is False

    @pytest.mark.anyio
    async def test_tool_annotations_in_fastmcp(self):
        """Test that tool annotations are included in MCPTool conversion."""

        app = FastMCP()

        @app.tool(annotations=ToolAnnotations(title="Echo Tool", readOnlyHint=True))
        def echo(message: str) -> str:
            """Echo a message back."""
            return message

        tools = await app.list_tools()
        assert len(tools) == 1
        assert tools[0].annotations is not None
        assert tools[0].annotations.title == "Echo Tool"
        assert tools[0].annotations.readOnlyHint is True


class TestOutputSchema:
    """Test the output schema generation for tools."""

    def test_primitive_type_output_schemas(self):
        """Test output schema generation for primitive return types."""
        manager = ToolManager()

        # String return type
        def string_tool(text: str) -> str:
            return text

        tool = manager.add_tool(string_tool)
        assert tool.output_schema == {"type": "string"}

        # Integer return type
        def int_tool(number: int) -> int:
            return number

        tool = manager.add_tool(int_tool)
        assert tool.output_schema == {"type": "integer"}

        # Float return type
        def float_tool(number: float) -> float:
            return number

        tool = manager.add_tool(float_tool)
        assert tool.output_schema == {"type": "number"}

        # Boolean return type
        def bool_tool(value: bool) -> bool:
            return value

        tool = manager.add_tool(bool_tool)
        assert tool.output_schema == {"type": "boolean"}

        # Dictionary return type
        def dict_tool(data: dict) -> dict:
            return data

        tool = manager.add_tool(dict_tool)
        assert tool.output_schema == {"type": "object"}

        # List return type
        def list_tool(items: list) -> list:
            return items

        tool = manager.add_tool(list_tool)
        assert tool.output_schema == {"type": "array"}

    def test_pydantic_model_output_schema(self):
        """Test output schema generation for Pydantic model return types."""
        manager = ToolManager()

        class Person(BaseModel):
            name: str
            age: int
            email: str | None = None

        def create_person(name: str, age: int) -> Person:
            return Person(name=name, age=age)

        tool = manager.add_tool(create_person)
        assert tool.output_schema is not None
        assert tool.output_schema["type"] == "object"
        assert "properties" in tool.output_schema
        assert "name" in tool.output_schema["properties"]
        assert "age" in tool.output_schema["properties"]
        assert "email" in tool.output_schema["properties"]
        assert tool.output_schema["properties"]["name"]["type"] == "string"
        assert tool.output_schema["properties"]["age"]["type"] == "integer"
        assert "anyOf" in tool.output_schema["properties"]["email"]
        assert "string" in [
            t["type"]
            for t in tool.output_schema["properties"]["email"]["anyOf"]
            if "type" in t
        ]
        assert "null" in [
            t["type"]
            for t in tool.output_schema["properties"]["email"]["anyOf"]
            if "type" in t
        ]

        # Check semantic enhancements
        assert tool.output_schema["properties"]["email"]["semantic_type"] == "email"
        assert (
            "semantic_type" not in tool.output_schema["properties"]["name"]
        )  # Non-semantic field
        assert (
            "semantic_type" not in tool.output_schema["properties"]["age"]
        )  # Non-semantic field

        # Check that required field is removed from output schema
        assert "required" not in tool.output_schema

    def test_complex_output_schema(self):
        """Test output schema generation for complex return types."""
        manager = ToolManager()

        class Person(BaseModel):
            name: str
            age: int

        class ApiResponse(BaseModel):
            status: str
            code: int
            data: list[Person] | Person | None = None

        def complex_response(success: bool) -> ApiResponse:
            return ApiResponse(
                status="success" if success else "error",
                code=200 if success else 400,
                data=None,
            )

        tool = manager.add_tool(complex_response)
        assert tool.output_schema is not None
        assert tool.output_schema["type"] == "object"
        assert "properties" in tool.output_schema
        assert "status" in tool.output_schema["properties"]
        assert "code" in tool.output_schema["properties"]
        assert "data" in tool.output_schema["properties"]
        assert "anyOf" in tool.output_schema["properties"]["data"]

        # Check semantic enhancements
        assert tool.output_schema["properties"]["status"]["semantic_type"] == "status"
        assert (
            "semantic_type" not in tool.output_schema["properties"]["code"]
        )  # Non-semantic field
        assert (
            "semantic_type" not in tool.output_schema["properties"]["data"]
        )  # Non-semantic field

        # Check that required field is removed from output schema
        assert "required" not in tool.output_schema

    def test_generic_list_output_schema(self):
        """Test output schema generation for generic list return types."""
        manager = ToolManager()

        def list_of_strings() -> list[str]:
            return ["a", "b", "c"]

        tool = manager.add_tool(list_of_strings)
        assert tool.output_schema is not None
        assert "items" in tool.output_schema
        assert tool.output_schema["items"]["type"] == "string"

    @pytest.mark.anyio
    async def test_output_schema_in_fastmcp(self):
        """Test that output schemas are included in FastMCP tool listing."""
        app = FastMCP()

        @app.tool()
        def string_tool(text: str) -> str:
            """Returns the input text"""
            return text

        @app.tool()
        def int_tool(number: int) -> int:
            """Returns the input number"""
            return number

        class Person(BaseModel):
            name: str
            age: int
            email: str | None = None  # Add email field to test semantic enhancement

        @app.tool()
        def create_person(name: str, age: int) -> Person:
            """Creates a person object"""
            return Person(name=name, age=age)

        tools = await app.list_tools()
        assert len(tools) == 3

        # Check string tool
        string_tool_info = next(t for t in tools if t.name == "string_tool")
        assert string_tool_info.outputSchema == {"type": "string"}

        # Check int tool
        int_tool_info = next(t for t in tools if t.name == "int_tool")
        assert int_tool_info.outputSchema == {"type": "integer"}

        # Check complex tool
        person_tool_info = next(t for t in tools if t.name == "create_person")
        assert person_tool_info.outputSchema is not None
        assert person_tool_info.outputSchema["type"] == "object"
        assert "properties" in person_tool_info.outputSchema
        assert "name" in person_tool_info.outputSchema["properties"]
        assert "age" in person_tool_info.outputSchema["properties"]
        assert "email" in person_tool_info.outputSchema["properties"]

        # Check semantic enhancements in FastMCP listing
        properties = person_tool_info.outputSchema["properties"]
        assert properties["email"]["semantic_type"] == "email"
        assert "semantic_type" not in properties["name"]  # Non-semantic field
        assert "semantic_type" not in properties["age"]  # Non-semantic field

        # Check that required field is removed from output schema
        assert "required" not in person_tool_info.outputSchema

    def test_enhanced_output_schema_with_semantic_fields(self):
        """Test that output schemas are enhanced with semantic information."""
        manager = ToolManager()

        class UserProfile(BaseModel):
            user_id: str
            email: str
            profile_url: str
            avatar_image: str
            created_date: str
            last_login_time: str
            account_amount: float  # Changed to trigger currency detection
            completion_percentage: int
            primary_color: str
            status: str
            name: str  # Should not get semantic enhancement

        def get_user_profile(user_id: str) -> UserProfile:
            """Get user profile with semantic fields"""
            return UserProfile(
                user_id="usr_123",
                email="user@example.com",
                profile_url="https://example.com/user/123",
                avatar_image="https://example.com/avatar.jpg",
                created_date="2023-06-15",
                last_login_time="2024-01-15T14:22:00Z",
                account_amount=150.75,
                completion_percentage=85,
                primary_color="#3498db",
                status="active",
                name="John Doe",
            )

        tool = manager.add_tool(get_user_profile)
        assert tool.output_schema is not None

        properties = tool.output_schema["properties"]

        # Check semantic enhancements
        assert properties["user_id"]["semantic_type"] == "identifier"
        assert properties["email"]["semantic_type"] == "email"
        assert properties["profile_url"]["semantic_type"] == "url"
        assert properties["avatar_image"]["semantic_type"] == "image"
        assert properties["created_date"]["semantic_type"] == "datetime"
        assert properties["created_date"]["datetime_type"] == "date_only"
        assert properties["last_login_time"]["semantic_type"] == "datetime"
        assert (
            properties["last_login_time"]["datetime_type"] == "time_only"
        )  # Contains "time" but not "date"
        assert properties["account_amount"]["semantic_type"] == "currency"
        assert properties["completion_percentage"]["semantic_type"] == "percentage"
        assert properties["primary_color"]["semantic_type"] == "color"
        assert properties["status"]["semantic_type"] == "status"

        # Check that non-semantic fields don't get enhancement
        assert "semantic_type" not in properties["name"]

        # Check that required field is removed from output schema
        assert "required" not in tool.output_schema

    @pytest.mark.anyio
    async def test_enhanced_schemas_in_fastmcp_listing(self):
        """Test that enhanced schemas are included in FastMCP tool listing."""
        app = FastMCP()

        class MediaFile(BaseModel):
            name: str  # Changed from "filename" to avoid file_path detection
            file_path: str
            audio_url: str
            video_url: str
            image_url: str
            created_timestamp: str
            size: int  # Changed from "file_size" to avoid file_path detection

        @app.tool()
        def get_media_file(file_id: str) -> MediaFile:
            """Get media file information with semantic fields"""
            return MediaFile(
                name="example.mp3",
                file_path="/media/audio/example.mp3",
                audio_url="https://example.com/audio/example.mp3",
                video_url="https://example.com/video/example.mp4",
                image_url="https://example.com/images/thumbnail.jpg",
                created_timestamp="2024-01-15T10:30:00Z",
                size=1024000,
            )

        tools = await app.list_tools()
        assert len(tools) == 1

        media_tool = tools[0]
        assert media_tool.outputSchema is not None

        properties = media_tool.outputSchema["properties"]

        # Verify semantic enhancements are present in the listing
        assert properties["file_path"]["semantic_type"] == "file_path"
        assert properties["audio_url"]["semantic_type"] == "url"
        assert properties["video_url"]["semantic_type"] == "url"
        assert properties["image_url"]["semantic_type"] == "url"
        assert properties["created_timestamp"]["semantic_type"] == "datetime"
        assert (
            properties["created_timestamp"]["datetime_type"] == "time_only"
        )  # Contains "time" but not "date"

        # Non-semantic fields should not have enhancements
        assert "semantic_type" not in properties["name"]
        assert "semantic_type" not in properties["size"]

    def test_enhanced_schema_with_media_formats(self):
        """Test schema enhancement with specific media format detection."""
        manager = ToolManager()

        class MediaCollection(BaseModel):
            audio_mp3: str
            video_mp4: str
            image_jpg: str
            generic_audio: str
            generic_video: str
            generic_image: str

        def get_media_collection() -> MediaCollection:
            """Get media collection with format-specific fields"""
            return MediaCollection(
                audio_mp3="song.mp3",
                video_mp4="movie.mp4",
                image_jpg="photo.jpg",
                generic_audio="sound",
                generic_video="clip",
                generic_image="picture",
            )

        tool = manager.add_tool(get_media_collection)
        assert tool.output_schema is not None
        properties = tool.output_schema["properties"]

        # Check media format detection
        assert properties["audio_mp3"]["semantic_type"] == "audio"
        assert properties["audio_mp3"]["media_format"] == "audio_file"

        assert properties["video_mp4"]["semantic_type"] == "video"
        assert properties["video_mp4"]["media_format"] == "video_file"

        assert properties["image_jpg"]["semantic_type"] == "image"
        assert properties["image_jpg"]["media_format"] == "image_file"

        # Generic media fields should have semantic_type but no media_format
        assert properties["generic_audio"]["semantic_type"] == "audio"
        assert "media_format" not in properties["generic_audio"]

        assert properties["generic_video"]["semantic_type"] == "video"
        assert "media_format" not in properties["generic_video"]

        assert properties["generic_image"]["semantic_type"] == "image"
        assert "media_format" not in properties["generic_image"]
