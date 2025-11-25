"""
Test the elicitation feature using stdio transport.
"""

from typing import Any

import pytest
from pydantic import BaseModel, Field

from mcp import types
from mcp.client.session import ClientSession, ElicitationFnT
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ElicitRequestParams, ElicitResult, TextContent


# Shared schema for basic tests
class AnswerSchema(BaseModel):
    answer: str = Field(description="The user's answer to the question")


def create_ask_user_tool(mcp: FastMCP):
    """Create a standard ask_user tool that handles all elicitation responses."""

    @mcp.tool(description="A tool that uses elicitation")
    async def ask_user(prompt: str, ctx: Context[ServerSession, None]) -> str:
        result = await ctx.elicit(message=f"Tool wants to ask: {prompt}", schema=AnswerSchema)

        if result.action == "accept" and result.data:
            return f"User answered: {result.data.answer}"
        elif result.action == "decline":
            return "User declined to answer"
        else:  # pragma: no cover
            return "User cancelled"

    return ask_user


async def call_tool_and_assert(
    mcp: FastMCP,
    elicitation_callback: ElicitationFnT,
    tool_name: str,
    args: dict[str, Any],
    expected_text: str | None = None,
    text_contains: list[str] | None = None,
):
    """Helper to create session, call tool, and assert result."""
    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        result = await client_session.call_tool(tool_name, args)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)

        if expected_text is not None:
            assert result.content[0].text == expected_text
        elif text_contains is not None:  # pragma: no branch
            for substring in text_contains:
                assert substring in result.content[0].text

        return result


@pytest.mark.anyio
async def test_stdio_elicitation():
    """Test the elicitation feature using stdio transport."""
    mcp = FastMCP(name="StdioElicitationServer")
    create_ask_user_tool(mcp)

    # Create a custom handler for elicitation requests
    async def elicitation_callback(
        context: RequestContext[ClientSession, None], params: ElicitRequestParams
    ):  # pragma: no cover
        if params.message == "Tool wants to ask: What is your name?":
            return ElicitResult(action="accept", content={"answer": "Test User"})
        else:
            raise ValueError(f"Unexpected elicitation message: {params.message}")

    await call_tool_and_assert(
        mcp, elicitation_callback, "ask_user", {"prompt": "What is your name?"}, "User answered: Test User"
    )


@pytest.mark.anyio
async def test_stdio_elicitation_decline():
    """Test elicitation with user declining."""
    mcp = FastMCP(name="StdioElicitationDeclineServer")
    create_ask_user_tool(mcp)

    async def elicitation_callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        return ElicitResult(action="decline")

    await call_tool_and_assert(
        mcp, elicitation_callback, "ask_user", {"prompt": "What is your name?"}, "User declined to answer"
    )


@pytest.mark.anyio
async def test_elicitation_schema_validation():
    """Test that elicitation schemas must only contain primitive types."""
    mcp = FastMCP(name="ValidationTestServer")

    def create_validation_tool(name: str, schema_class: type[BaseModel]):
        @mcp.tool(name=name, description=f"Tool testing {name}")
        async def tool(ctx: Context[ServerSession, None]) -> str:  # pragma: no cover
            try:
                await ctx.elicit(message="This should fail validation", schema=schema_class)
                return "Should not reach here"
            except TypeError as e:
                return f"Validation failed as expected: {str(e)}"

        return tool

    # Test cases for invalid schemas
    class InvalidListSchema(BaseModel):
        numbers: list[int] = Field(description="List of numbers")

    class NestedModel(BaseModel):
        value: str

    class InvalidNestedSchema(BaseModel):
        nested: NestedModel = Field(description="Nested model")

    create_validation_tool("invalid_list", InvalidListSchema)
    create_validation_tool("nested_model", InvalidNestedSchema)

    # Dummy callback (won't be called due to validation failure)
    async def elicitation_callback(
        context: RequestContext[ClientSession, None], params: ElicitRequestParams
    ):  # pragma: no cover
        return ElicitResult(action="accept", content={})

    async with create_connected_server_and_client_session(
        mcp._mcp_server, elicitation_callback=elicitation_callback
    ) as client_session:
        await client_session.initialize()

        # Test both invalid schemas
        for tool_name, field_name in [("invalid_list", "numbers"), ("nested_model", "nested")]:
            result = await client_session.call_tool(tool_name, {})
            assert len(result.content) == 1
            assert isinstance(result.content[0], TextContent)
            assert "Validation failed as expected" in result.content[0].text
            assert field_name in result.content[0].text


@pytest.mark.anyio
async def test_elicitation_with_optional_fields():
    """Test that Optional fields work correctly in elicitation schemas."""
    mcp = FastMCP(name="OptionalFieldServer")

    class OptionalSchema(BaseModel):
        required_name: str = Field(description="Your name (required)")
        optional_age: int | None = Field(default=None, description="Your age (optional)")
        optional_email: str | None = Field(default=None, description="Your email (optional)")
        subscribe: bool | None = Field(default=False, description="Subscribe to newsletter?")

    @mcp.tool(description="Tool with optional fields")
    async def optional_tool(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.elicit(message="Please provide your information", schema=OptionalSchema)

        if result.action == "accept" and result.data:
            info = [f"Name: {result.data.required_name}"]
            if result.data.optional_age is not None:
                info.append(f"Age: {result.data.optional_age}")
            if result.data.optional_email is not None:
                info.append(f"Email: {result.data.optional_email}")
            info.append(f"Subscribe: {result.data.subscribe}")
            return ", ".join(info)
        else:  # pragma: no cover
            return f"User {result.action}"

    # Test cases with different field combinations
    test_cases: list[tuple[dict[str, Any], str]] = [
        (
            # All fields provided
            {"required_name": "John Doe", "optional_age": 30, "optional_email": "john@example.com", "subscribe": True},
            "Name: John Doe, Age: 30, Email: john@example.com, Subscribe: True",
        ),
        (
            # Only required fields
            {"required_name": "Jane Smith"},
            "Name: Jane Smith, Subscribe: False",
        ),
    ]

    for content, expected in test_cases:

        async def callback(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
            return ElicitResult(action="accept", content=content)

        await call_tool_and_assert(mcp, callback, "optional_tool", {}, expected)

    # Test invalid optional field
    class InvalidOptionalSchema(BaseModel):
        name: str = Field(description="Name")
        optional_list: list[int] | None = Field(default=None, description="Invalid optional list")

    @mcp.tool(description="Tool with invalid optional field")
    async def invalid_optional_tool(ctx: Context[ServerSession, None]) -> str:  # pragma: no cover
        try:
            await ctx.elicit(message="This should fail", schema=InvalidOptionalSchema)
            return "Should not reach here"
        except TypeError as e:
            return f"Validation failed: {str(e)}"

    async def elicitation_callback(
        context: RequestContext[ClientSession, None], params: ElicitRequestParams
    ):  # pragma: no cover
        return ElicitResult(action="accept", content={})

    await call_tool_and_assert(
        mcp,
        elicitation_callback,
        "invalid_optional_tool",
        {},
        text_contains=["Validation failed:", "optional_list"],
    )

    # Test valid list[str] for multi-select enum
    class ValidMultiSelectSchema(BaseModel):
        name: str = Field(description="Name")
        tags: list[str] = Field(description="Tags")

    @mcp.tool(description="Tool with valid list[str] field")
    async def valid_multiselect_tool(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.elicit(message="Please provide tags", schema=ValidMultiSelectSchema)
        if result.action == "accept" and result.data:
            return f"Name: {result.data.name}, Tags: {', '.join(result.data.tags)}"
        return f"User {result.action}"  # pragma: no cover

    async def multiselect_callback(context: RequestContext[ClientSession, Any], params: ElicitRequestParams):
        if "Please provide tags" in params.message:
            return ElicitResult(action="accept", content={"name": "Test", "tags": ["tag1", "tag2"]})
        return ElicitResult(action="decline")  # pragma: no cover

    await call_tool_and_assert(mcp, multiselect_callback, "valid_multiselect_tool", {}, "Name: Test, Tags: tag1, tag2")

    # Test Optional[list[str]] for optional multi-select enum
    class OptionalMultiSelectSchema(BaseModel):
        name: str = Field(description="Name")
        tags: list[str] | None = Field(default=None, description="Optional tags")

    @mcp.tool(description="Tool with optional list[str] field")
    async def optional_multiselect_tool(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.elicit(message="Please provide optional tags", schema=OptionalMultiSelectSchema)
        if result.action == "accept" and result.data:
            tags_str = ", ".join(result.data.tags) if result.data.tags else "none"
            return f"Name: {result.data.name}, Tags: {tags_str}"
        return f"User {result.action}"  # pragma: no cover

    async def optional_multiselect_callback(context: RequestContext[ClientSession, Any], params: ElicitRequestParams):
        if "Please provide optional tags" in params.message:
            return ElicitResult(action="accept", content={"name": "Test", "tags": ["tag1", "tag2"]})
        return ElicitResult(action="decline")  # pragma: no cover

    await call_tool_and_assert(
        mcp, optional_multiselect_callback, "optional_multiselect_tool", {}, "Name: Test, Tags: tag1, tag2"
    )


@pytest.mark.anyio
async def test_elicitation_with_default_values():
    """Test that default values work correctly in elicitation schemas and are included in JSON."""
    mcp = FastMCP(name="DefaultValuesServer")

    class DefaultsSchema(BaseModel):
        name: str = Field(default="Guest", description="User name")
        age: int = Field(default=18, description="User age")
        subscribe: bool = Field(default=True, description="Subscribe to newsletter")
        email: str = Field(description="Email address (required)")

    @mcp.tool(description="Tool with default values")
    async def defaults_tool(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.elicit(message="Please provide your information", schema=DefaultsSchema)

        if result.action == "accept" and result.data:
            return (
                f"Name: {result.data.name}, Age: {result.data.age}, "
                f"Subscribe: {result.data.subscribe}, Email: {result.data.email}"
            )
        else:  # pragma: no cover
            return f"User {result.action}"

    # First verify that defaults are present in the JSON schema sent to clients
    async def callback_schema_verify(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        # Verify the schema includes defaults
        assert isinstance(params, types.ElicitRequestFormParams), "Expected form mode elicitation"
        schema = params.requestedSchema
        props = schema["properties"]

        assert props["name"]["default"] == "Guest"
        assert props["age"]["default"] == 18
        assert props["subscribe"]["default"] is True
        assert "default" not in props["email"]  # Required field has no default

        return ElicitResult(action="accept", content={"email": "test@example.com"})

    await call_tool_and_assert(
        mcp,
        callback_schema_verify,
        "defaults_tool",
        {},
        "Name: Guest, Age: 18, Subscribe: True, Email: test@example.com",
    )

    # Test overriding defaults
    async def callback_override(context: RequestContext[ClientSession, None], params: ElicitRequestParams):
        return ElicitResult(
            action="accept", content={"email": "john@example.com", "name": "John", "age": 25, "subscribe": False}
        )

    await call_tool_and_assert(
        mcp, callback_override, "defaults_tool", {}, "Name: John, Age: 25, Subscribe: False, Email: john@example.com"
    )


@pytest.mark.anyio
async def test_elicitation_with_enum_titles():
    """Test elicitation with enum schemas using oneOf/anyOf for titles."""
    mcp = FastMCP(name="ColorPreferencesApp")

    # Test single-select with titles using oneOf
    class FavoriteColorSchema(BaseModel):
        user_name: str = Field(description="Your name")
        favorite_color: str = Field(
            description="Select your favorite color",
            json_schema_extra={
                "oneOf": [
                    {"const": "red", "title": "Red"},
                    {"const": "green", "title": "Green"},
                    {"const": "blue", "title": "Blue"},
                    {"const": "yellow", "title": "Yellow"},
                ]
            },
        )

    @mcp.tool(description="Single color selection")
    async def select_favorite_color(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.elicit(message="Select your favorite color", schema=FavoriteColorSchema)
        if result.action == "accept" and result.data:
            return f"User: {result.data.user_name}, Favorite: {result.data.favorite_color}"
        return f"User {result.action}"  # pragma: no cover

    # Test multi-select with titles using anyOf
    class FavoriteColorsSchema(BaseModel):
        user_name: str = Field(description="Your name")
        favorite_colors: list[str] = Field(
            description="Select your favorite colors",
            json_schema_extra={
                "items": {
                    "anyOf": [
                        {"const": "red", "title": "Red"},
                        {"const": "green", "title": "Green"},
                        {"const": "blue", "title": "Blue"},
                        {"const": "yellow", "title": "Yellow"},
                    ]
                }
            },
        )

    @mcp.tool(description="Multiple color selection")
    async def select_favorite_colors(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.elicit(message="Select your favorite colors", schema=FavoriteColorsSchema)
        if result.action == "accept" and result.data:
            return f"User: {result.data.user_name}, Colors: {', '.join(result.data.favorite_colors)}"
        return f"User {result.action}"  # pragma: no cover

    # Test legacy enumNames format
    class LegacyColorSchema(BaseModel):
        user_name: str = Field(description="Your name")
        color: str = Field(
            description="Select a color",
            json_schema_extra={"enum": ["red", "green", "blue"], "enumNames": ["Red", "Green", "Blue"]},
        )

    @mcp.tool(description="Legacy enum format")
    async def select_color_legacy(ctx: Context[ServerSession, None]) -> str:
        result = await ctx.elicit(message="Select a color (legacy format)", schema=LegacyColorSchema)
        if result.action == "accept" and result.data:
            return f"User: {result.data.user_name}, Color: {result.data.color}"
        return f"User {result.action}"  # pragma: no cover

    async def enum_callback(context: RequestContext[ClientSession, Any], params: ElicitRequestParams):
        if "colors" in params.message and "legacy" not in params.message:
            return ElicitResult(action="accept", content={"user_name": "Bob", "favorite_colors": ["red", "green"]})
        elif "color" in params.message:
            if "legacy" in params.message:
                return ElicitResult(action="accept", content={"user_name": "Charlie", "color": "green"})
            else:
                return ElicitResult(action="accept", content={"user_name": "Alice", "favorite_color": "blue"})
        return ElicitResult(action="decline")  # pragma: no cover

    # Test single-select with titles
    await call_tool_and_assert(mcp, enum_callback, "select_favorite_color", {}, "User: Alice, Favorite: blue")

    # Test multi-select with titles
    await call_tool_and_assert(mcp, enum_callback, "select_favorite_colors", {}, "User: Bob, Colors: red, green")

    # Test legacy enumNames format
    await call_tool_and_assert(mcp, enum_callback, "select_color_legacy", {}, "User: Charlie, Color: green")
