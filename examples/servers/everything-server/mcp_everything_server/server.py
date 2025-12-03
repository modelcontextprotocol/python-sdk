#!/usr/bin/env python3
"""
MCP Everything Server - Conformance Test Server

Server implementing all MCP features for conformance testing based on Conformance Server Specification.
"""

import asyncio
import base64
import json
import logging

import click
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.prompts.base import UserMessage
from mcp.server.session import ServerSession
from mcp.server.streamable_http import EventCallback, EventMessage, EventStore
from mcp.types import (
    AudioContent,
    Completion,
    CompletionArgument,
    CompletionContext,
    EmbeddedResource,
    ImageContent,
    JSONRPCMessage,
    PromptReference,
    ResourceTemplateReference,
    SamplingMessage,
    TextContent,
    TextResourceContents,
)
from pydantic import AnyUrl, BaseModel, Field

logger = logging.getLogger(__name__)

# Type aliases for event store
StreamId = str
EventId = str


class InMemoryEventStore(EventStore):
    """Simple in-memory event store for SSE resumability testing."""

    def __init__(self) -> None:
        self._events: list[tuple[StreamId, EventId, JSONRPCMessage | None]] = []
        self._event_id_counter = 0

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        """Store an event and return its ID."""
        self._event_id_counter += 1
        event_id = str(self._event_id_counter)
        self._events.append((stream_id, event_id, message))
        return event_id

    async def replay_events_after(self, last_event_id: EventId, send_callback: EventCallback) -> StreamId | None:
        """Replay events after the specified ID."""
        target_stream_id = None
        for stream_id, event_id, _ in self._events:
            if event_id == last_event_id:
                target_stream_id = stream_id
                break
        if target_stream_id is None:
            return None
        last_event_id_int = int(last_event_id)
        for stream_id, event_id, message in self._events:
            if stream_id == target_stream_id and int(event_id) > last_event_id_int:
                # Skip priming events (None message)
                if message is not None:
                    await send_callback(EventMessage(message, event_id))
        return target_stream_id


# Test data
TEST_IMAGE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
TEST_AUDIO_BASE64 = "UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAAB9AAACABAAZGF0YQIAAAA="

# Server state
resource_subscriptions: set[str] = set()
watched_resource_content = "Watched resource content"

# Create event store for SSE resumability (SEP-1699)
event_store = InMemoryEventStore()

mcp = FastMCP(
    name="mcp-conformance-test-server",
    event_store=event_store,
    retry_interval=100,  # 100ms retry interval for SSE polling
)


# Tools
@mcp.tool()
def test_simple_text() -> str:
    """Tests simple text content response"""
    return "This is a simple text response for testing."


@mcp.tool()
def test_image_content() -> list[ImageContent]:
    """Tests image content response"""
    return [ImageContent(type="image", data=TEST_IMAGE_BASE64, mimeType="image/png")]


@mcp.tool()
def test_audio_content() -> list[AudioContent]:
    """Tests audio content response"""
    return [AudioContent(type="audio", data=TEST_AUDIO_BASE64, mimeType="audio/wav")]


@mcp.tool()
def test_embedded_resource() -> list[EmbeddedResource]:
    """Tests embedded resource content response"""
    return [
        EmbeddedResource(
            type="resource",
            resource=TextResourceContents(
                uri=AnyUrl("test://embedded-resource"),
                mimeType="text/plain",
                text="This is an embedded resource content.",
            ),
        )
    ]


@mcp.tool()
def test_multiple_content_types() -> list[TextContent | ImageContent | EmbeddedResource]:
    """Tests response with multiple content types (text, image, resource)"""
    return [
        TextContent(type="text", text="Multiple content types test:"),
        ImageContent(type="image", data=TEST_IMAGE_BASE64, mimeType="image/png"),
        EmbeddedResource(
            type="resource",
            resource=TextResourceContents(
                uri=AnyUrl("test://mixed-content-resource"),
                mimeType="application/json",
                text='{"test": "data", "value": 123}',
            ),
        ),
    ]


@mcp.tool()
async def test_tool_with_logging(ctx: Context[ServerSession, None]) -> str:
    """Tests tool that emits log messages during execution"""
    await ctx.info("Tool execution started")
    await asyncio.sleep(0.05)

    await ctx.info("Tool processing data")
    await asyncio.sleep(0.05)

    await ctx.info("Tool execution completed")
    return "Tool with logging executed successfully"


@mcp.tool()
async def test_tool_with_progress(ctx: Context[ServerSession, None]) -> str:
    """Tests tool that reports progress notifications"""
    await ctx.report_progress(progress=0, total=100, message="Completed step 0 of 100")
    await asyncio.sleep(0.05)

    await ctx.report_progress(progress=50, total=100, message="Completed step 50 of 100")
    await asyncio.sleep(0.05)

    await ctx.report_progress(progress=100, total=100, message="Completed step 100 of 100")

    # Return progress token as string
    progress_token = ctx.request_context.meta.progressToken if ctx.request_context and ctx.request_context.meta else 0
    return str(progress_token)


@mcp.tool()
async def test_sampling(prompt: str, ctx: Context[ServerSession, None]) -> str:
    """Tests server-initiated sampling (LLM completion request)"""
    try:
        # Request sampling from client
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
            max_tokens=100,
        )

        # Since we're not passing tools param, result.content is single content
        if result.content.type == "text":
            model_response = result.content.text
        else:
            model_response = "No response"

        return f"LLM response: {model_response}"
    except Exception as e:
        return f"Sampling not supported or error: {str(e)}"


class UserResponse(BaseModel):
    response: str = Field(description="User's response")


@mcp.tool()
async def test_elicitation(message: str, ctx: Context[ServerSession, None]) -> str:
    """Tests server-initiated elicitation (user input request)"""
    try:
        # Request user input from client
        result = await ctx.elicit(message=message, schema=UserResponse)

        # Type-safe discriminated union narrowing using action field
        if result.action == "accept":
            content = result.data.model_dump_json()
        else:  # decline or cancel
            content = "{}"

        return f"User response: action={result.action}, content={content}"
    except Exception as e:
        return f"Elicitation not supported or error: {str(e)}"


class SEP1034DefaultsSchema(BaseModel):
    """Schema for testing SEP-1034 elicitation with default values for all primitive types"""

    name: str = Field(default="John Doe", description="User name")
    age: int = Field(default=30, description="User age")
    score: float = Field(default=95.5, description="User score")
    status: str = Field(
        default="active",
        description="User status",
        json_schema_extra={"enum": ["active", "inactive", "pending"]},
    )
    verified: bool = Field(default=True, description="Verification status")


@mcp.tool()
async def test_elicitation_sep1034_defaults(ctx: Context[ServerSession, None]) -> str:
    """Tests elicitation with default values for all primitive types (SEP-1034)"""
    try:
        # Request user input with defaults for all primitive types
        result = await ctx.elicit(message="Please provide user information", schema=SEP1034DefaultsSchema)

        # Type-safe discriminated union narrowing using action field
        if result.action == "accept":
            content = result.data.model_dump_json()
        else:  # decline or cancel
            content = "{}"

        return f"Elicitation result: action={result.action}, content={content}"
    except Exception as e:
        return f"Elicitation not supported or error: {str(e)}"


class EnumSchemasTestSchema(BaseModel):
    """Schema for testing enum schema variations (SEP-1330)"""

    untitledSingle: str = Field(
        description="Simple enum without titles", json_schema_extra={"enum": ["active", "inactive", "pending"]}
    )
    titledSingle: str = Field(
        description="Enum with titled options (oneOf)",
        json_schema_extra={
            "oneOf": [
                {"const": "low", "title": "Low Priority"},
                {"const": "medium", "title": "Medium Priority"},
                {"const": "high", "title": "High Priority"},
            ]
        },
    )
    untitledMulti: list[str] = Field(
        description="Multi-select without titles",
        json_schema_extra={"items": {"type": "string", "enum": ["read", "write", "execute"]}},
    )
    titledMulti: list[str] = Field(
        description="Multi-select with titled options",
        json_schema_extra={
            "items": {
                "anyOf": [
                    {"const": "feature", "title": "New Feature"},
                    {"const": "bug", "title": "Bug Fix"},
                    {"const": "docs", "title": "Documentation"},
                ]
            }
        },
    )
    legacyEnum: str = Field(
        description="Legacy enum with enumNames",
        json_schema_extra={
            "enum": ["small", "medium", "large"],
            "enumNames": ["Small Size", "Medium Size", "Large Size"],
        },
    )


@mcp.tool()
async def test_elicitation_sep1330_enums(ctx: Context[ServerSession, None]) -> str:
    """Tests elicitation with enum schema variations per SEP-1330"""
    try:
        result = await ctx.elicit(
            message="Please select values using different enum schema types", schema=EnumSchemasTestSchema
        )

        if result.action == "accept":
            content = result.data.model_dump_json()
        else:
            content = "{}"

        return f"Elicitation completed: action={result.action}, content={content}"
    except Exception as e:
        return f"Elicitation not supported or error: {str(e)}"


@mcp.tool()
def test_error_handling() -> str:
    """Tests error response handling"""
    raise RuntimeError("This tool intentionally returns an error for testing")


@mcp.tool()
async def test_reconnection(ctx: Context[ServerSession, None]) -> str:
    """Tests SSE polling by closing stream mid-call (SEP-1699)"""
    await ctx.info("Before disconnect")

    await ctx.close_sse_stream()

    await asyncio.sleep(0.2)  # Wait for client to reconnect

    await ctx.info("After reconnect")
    return "Reconnection test completed"


# Resources
@mcp.resource("test://static-text")
def static_text_resource() -> str:
    """A static text resource for testing"""
    return "This is the content of the static text resource."


@mcp.resource("test://static-binary")
def static_binary_resource() -> bytes:
    """A static binary resource (image) for testing"""
    return base64.b64decode(TEST_IMAGE_BASE64)


@mcp.resource("test://template/{id}/data")
def template_resource(id: str) -> str:
    """A resource template with parameter substitution"""
    return json.dumps({"id": id, "templateTest": True, "data": f"Data for ID: {id}"})


@mcp.resource("test://watched-resource")
def watched_resource() -> str:
    """A resource that can be subscribed to for updates"""
    return watched_resource_content


# Prompts
@mcp.prompt()
def test_simple_prompt() -> list[UserMessage]:
    """A simple prompt without arguments"""
    return [UserMessage(role="user", content=TextContent(type="text", text="This is a simple prompt for testing."))]


@mcp.prompt()
def test_prompt_with_arguments(arg1: str, arg2: str) -> list[UserMessage]:
    """A prompt with required arguments"""
    return [
        UserMessage(
            role="user", content=TextContent(type="text", text=f"Prompt with arguments: arg1='{arg1}', arg2='{arg2}'")
        )
    ]


@mcp.prompt()
def test_prompt_with_embedded_resource(resourceUri: str) -> list[UserMessage]:
    """A prompt that includes an embedded resource"""
    return [
        UserMessage(
            role="user",
            content=EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri=AnyUrl(resourceUri),
                    mimeType="text/plain",
                    text="Embedded resource content for testing.",
                ),
            ),
        ),
        UserMessage(role="user", content=TextContent(type="text", text="Please process the embedded resource above.")),
    ]


@mcp.prompt()
def test_prompt_with_image() -> list[UserMessage]:
    """A prompt that includes image content"""
    return [
        UserMessage(role="user", content=ImageContent(type="image", data=TEST_IMAGE_BASE64, mimeType="image/png")),
        UserMessage(role="user", content=TextContent(type="text", text="Please analyze the image above.")),
    ]


# Custom request handlers
# TODO(felix): Add public APIs to FastMCP for subscribe_resource, unsubscribe_resource,
# and set_logging_level to avoid accessing protected _mcp_server attribute.
@mcp._mcp_server.set_logging_level()  # pyright: ignore[reportPrivateUsage]
async def handle_set_logging_level(level: str) -> None:
    """Handle logging level changes"""
    logger.info(f"Log level set to: {level}")
    # In a real implementation, you would adjust the logging level here
    # For conformance testing, we just acknowledge the request


async def handle_subscribe(uri: AnyUrl) -> None:
    """Handle resource subscription"""
    resource_subscriptions.add(str(uri))
    logger.info(f"Subscribed to resource: {uri}")


async def handle_unsubscribe(uri: AnyUrl) -> None:
    """Handle resource unsubscription"""
    resource_subscriptions.discard(str(uri))
    logger.info(f"Unsubscribed from resource: {uri}")


mcp._mcp_server.subscribe_resource()(handle_subscribe)  # pyright: ignore[reportPrivateUsage]
mcp._mcp_server.unsubscribe_resource()(handle_unsubscribe)  # pyright: ignore[reportPrivateUsage]


@mcp.completion()
async def _handle_completion(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion:
    """Handle completion requests"""
    # Basic completion support - returns empty array for conformance
    # Real implementations would provide contextual suggestions
    return Completion(values=[], total=0, hasMore=False)


# CLI
@click.command()
@click.option("--port", default=3001, help="Port to listen on for HTTP")
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
def main(port: int, log_level: str) -> int:
    """Run the MCP Everything Server."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(f"Starting MCP Everything Server on port {port}")
    logger.info(f"Endpoint will be: http://localhost:{port}/mcp")

    mcp.settings.port = port
    mcp.run(transport="streamable-http")

    return 0


if __name__ == "__main__":
    main()
