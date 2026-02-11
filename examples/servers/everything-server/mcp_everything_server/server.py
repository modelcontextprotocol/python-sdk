#!/usr/bin/env python3
"""MCP Everything Server - Conformance Test Server

Server implementing all MCP features for conformance testing based on Conformance Server Specification.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import click
from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.elicitation import ElicitationResult, elicit_with_validation
from mcp.server.lowlevel import Server
from mcp.server.streamable_http import EventCallback, EventMessage, EventStore
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Type aliases for event store
StreamId = str
EventId = str


class InMemoryEventStore(EventStore):
    """Simple in-memory event store for SSE resumability testing."""

    def __init__(self) -> None:
        self._events: list[tuple[StreamId, EventId, types.JSONRPCMessage | None]] = []
        self._event_id_counter = 0

    async def store_event(self, stream_id: StreamId, message: types.JSONRPCMessage | None) -> EventId:
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


# --- Pydantic models for elicitation ---


class UserResponse(BaseModel):
    response: str = Field(description="User's response")


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


# --- Helper to perform elicitation through the low-level API ---


async def _elicit(
    ctx: ServerRequestContext[Any],
    message: str,
    schema: type[BaseModel],
) -> ElicitationResult[Any]:
    """Elicit information from the client using the low-level ServerRequestContext."""
    return await elicit_with_validation(
        session=ctx.session,
        message=message,
        schema=schema,
        related_request_id=ctx.request_id,
    )


# --- Tool definitions ---

TOOLS: list[types.Tool] = [
    types.Tool(
        name="test_simple_text",
        description="Tests simple text content response",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="test_image_content",
        description="Tests image content response",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="test_audio_content",
        description="Tests audio content response",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="test_embedded_resource",
        description="Tests embedded resource content response",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="test_multiple_content_types",
        description="Tests response with multiple content types (text, image, resource)",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="test_tool_with_logging",
        description="Tests tool that emits log messages during execution",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="test_tool_with_progress",
        description="Tests tool that reports progress notifications",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="test_sampling",
        description="Tests server-initiated sampling (LLM completion request)",
        input_schema={
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "Prompt for sampling"}},
            "required": ["prompt"],
        },
    ),
    types.Tool(
        name="test_elicitation",
        description="Tests server-initiated elicitation (user input request)",
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string", "description": "Message for elicitation"}},
            "required": ["message"],
        },
    ),
    types.Tool(
        name="test_elicitation_sep1034_defaults",
        description="Tests elicitation with default values for all primitive types (SEP-1034)",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="test_elicitation_sep1330_enums",
        description="Tests elicitation with enum schema variations per SEP-1330",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="test_error_handling",
        description="Tests error response handling",
        input_schema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="test_reconnection",
        description="Tests SSE polling by closing stream mid-call (SEP-1699)",
        input_schema={"type": "object", "properties": {}},
    ),
]


# --- Resource definitions ---

RESOURCES: list[types.Resource] = [
    types.Resource(
        uri="test://static-text",
        name="Static Text Resource",
        description="A static text resource for testing",
        mime_type="text/plain",
    ),
    types.Resource(
        uri="test://static-binary",
        name="Static Binary Resource",
        description="A static binary resource (image) for testing",
        mime_type="image/png",
    ),
    types.Resource(
        uri="test://watched-resource",
        name="Watched Resource",
        description="A resource that can be subscribed to for updates",
        mime_type="text/plain",
    ),
]

RESOURCE_TEMPLATES: list[types.ResourceTemplate] = [
    types.ResourceTemplate(
        uriTemplate="test://template/{id}/data",
        name="Template Resource",
        description="A resource template with parameter substitution",
        mime_type="application/json",
    ),
]

# --- Prompt definitions ---

PROMPTS: list[types.Prompt] = [
    types.Prompt(
        name="test_simple_prompt",
        description="A simple prompt without arguments",
    ),
    types.Prompt(
        name="test_prompt_with_arguments",
        description="A prompt with required arguments",
        arguments=[
            types.PromptArgument(name="arg1", description="First argument", required=True),
            types.PromptArgument(name="arg2", description="Second argument", required=True),
        ],
    ),
    types.Prompt(
        name="test_prompt_with_embedded_resource",
        description="A prompt that includes an embedded resource",
        arguments=[
            types.PromptArgument(name="resourceUri", description="URI of the resource to embed", required=True),
        ],
    ),
    types.Prompt(
        name="test_prompt_with_image",
        description="A prompt that includes image content",
    ),
]


# --- Handler implementations ---


async def handle_list_tools(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    """List available tools."""
    return types.ListToolsResult(tools=TOOLS)


async def handle_call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
    """Handle tool calls."""
    name = params.name
    arguments = params.arguments or {}

    if name == "test_simple_text":
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="This is a simple text response for testing.")]
        )

    elif name == "test_image_content":
        return types.CallToolResult(
            content=[types.ImageContent(type="image", data=TEST_IMAGE_BASE64, mime_type="image/png")]
        )

    elif name == "test_audio_content":
        return types.CallToolResult(
            content=[types.AudioContent(type="audio", data=TEST_AUDIO_BASE64, mime_type="audio/wav")]
        )

    elif name == "test_embedded_resource":
        return types.CallToolResult(
            content=[
                types.EmbeddedResource(
                    type="resource",
                    resource=types.TextResourceContents(
                        uri="test://embedded-resource",
                        mime_type="text/plain",
                        text="This is an embedded resource content.",
                    ),
                )
            ]
        )

    elif name == "test_multiple_content_types":
        return types.CallToolResult(
            content=[
                types.TextContent(type="text", text="Multiple content types test:"),
                types.ImageContent(type="image", data=TEST_IMAGE_BASE64, mime_type="image/png"),
                types.EmbeddedResource(
                    type="resource",
                    resource=types.TextResourceContents(
                        uri="test://mixed-content-resource",
                        mime_type="application/json",
                        text='{"test": "data", "value": 123}',
                    ),
                ),
            ]
        )

    elif name == "test_tool_with_logging":
        await ctx.session.send_log_message(
            level="info", data="Tool execution started", related_request_id=ctx.request_id
        )
        await asyncio.sleep(0.05)

        await ctx.session.send_log_message(level="info", data="Tool processing data", related_request_id=ctx.request_id)
        await asyncio.sleep(0.05)

        await ctx.session.send_log_message(
            level="info", data="Tool execution completed", related_request_id=ctx.request_id
        )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="Tool with logging executed successfully")]
        )

    elif name == "test_tool_with_progress":
        progress_token = ctx.meta.get("progress_token") if ctx.meta else None

        if progress_token is not None:
            await ctx.session.send_progress_notification(
                progress_token=progress_token, progress=0, total=100, message="Completed step 0 of 100"
            )
            await asyncio.sleep(0.05)

            await ctx.session.send_progress_notification(
                progress_token=progress_token, progress=50, total=100, message="Completed step 50 of 100"
            )
            await asyncio.sleep(0.05)

            await ctx.session.send_progress_notification(
                progress_token=progress_token, progress=100, total=100, message="Completed step 100 of 100"
            )

        return types.CallToolResult(
            content=[types.TextContent(type="text", text=str(progress_token if progress_token is not None else 0))]
        )

    elif name == "test_sampling":
        prompt = str(arguments.get("prompt", ""))
        try:
            result = await ctx.session.create_message(
                messages=[types.SamplingMessage(role="user", content=types.TextContent(type="text", text=prompt))],
                max_tokens=100,
                related_request_id=ctx.request_id,
            )

            if result.content.type == "text":
                model_response = result.content.text
            else:
                model_response = "No response"

            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"LLM response: {model_response}")]
            )
        except Exception as e:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Sampling not supported or error: {str(e)}")]
            )

    elif name == "test_elicitation":
        message = str(arguments.get("message", ""))
        try:
            result = await _elicit(ctx, message=message, schema=UserResponse)

            if result.action == "accept":
                content = result.data.model_dump_json()
            else:
                content = "{}"

            return types.CallToolResult(
                content=[
                    types.TextContent(type="text", text=f"User response: action={result.action}, content={content}")
                ]
            )
        except Exception as e:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Elicitation not supported or error: {str(e)}")]
            )

    elif name == "test_elicitation_sep1034_defaults":
        try:
            result = await _elicit(ctx, message="Please provide user information", schema=SEP1034DefaultsSchema)

            if result.action == "accept":
                content = result.data.model_dump_json()
            else:
                content = "{}"

            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text", text=f"Elicitation result: action={result.action}, content={content}"
                    )
                ]
            )
        except Exception as e:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Elicitation not supported or error: {str(e)}")]
            )

    elif name == "test_elicitation_sep1330_enums":
        try:
            result = await _elicit(
                ctx, message="Please select values using different enum schema types", schema=EnumSchemasTestSchema
            )

            if result.action == "accept":
                content = result.data.model_dump_json()
            else:
                content = "{}"

            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text", text=f"Elicitation completed: action={result.action}, content={content}"
                    )
                ]
            )
        except Exception as e:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Elicitation not supported or error: {str(e)}")]
            )

    elif name == "test_error_handling":
        raise RuntimeError("This tool intentionally returns an error for testing")

    elif name == "test_reconnection":
        await ctx.session.send_log_message(level="info", data="Before disconnect", related_request_id=ctx.request_id)

        if ctx.close_sse_stream:
            await ctx.close_sse_stream()

        await asyncio.sleep(0.2)  # Wait for client to reconnect

        await ctx.session.send_log_message(level="info", data="After reconnect", related_request_id=ctx.request_id)
        return types.CallToolResult(content=[types.TextContent(type="text", text="Reconnection test completed")])

    raise ValueError(f"Unknown tool: {name}")


async def handle_list_resources(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListResourcesResult:
    """List available resources."""
    return types.ListResourcesResult(resources=RESOURCES)


async def handle_list_resource_templates(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListResourceTemplatesResult:
    """List available resource templates."""
    return types.ListResourceTemplatesResult(resource_templates=RESOURCE_TEMPLATES)


async def handle_read_resource(
    ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
) -> types.ReadResourceResult:
    """Read a specific resource."""
    uri = str(params.uri)

    if uri == "test://static-text":
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=uri,
                    mime_type="text/plain",
                    text="This is the content of the static text resource.",
                )
            ]
        )

    elif uri == "test://static-binary":
        return types.ReadResourceResult(
            contents=[
                types.BlobResourceContents(
                    uri=uri,
                    mime_type="image/png",
                    blob=TEST_IMAGE_BASE64,
                )
            ]
        )

    elif uri == "test://watched-resource":
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=uri,
                    mime_type="text/plain",
                    text=watched_resource_content,
                )
            ]
        )

    # Check for template match: test://template/{id}/data
    elif uri.startswith("test://template/") and uri.endswith("/data"):
        resource_id = uri[len("test://template/") : -len("/data")]
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=uri,
                    mime_type="application/json",
                    text=json.dumps({"id": resource_id, "templateTest": True, "data": f"Data for ID: {resource_id}"}),
                )
            ]
        )

    raise ValueError(f"Unknown resource: {uri}")


async def handle_list_prompts(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListPromptsResult:
    """List available prompts."""
    return types.ListPromptsResult(prompts=PROMPTS)


async def handle_get_prompt(
    ctx: ServerRequestContext[Any], params: types.GetPromptRequestParams
) -> types.GetPromptResult:
    """Get a specific prompt by name."""
    name = params.name
    arguments = params.arguments or {}

    if name == "test_simple_prompt":
        return types.GetPromptResult(
            description="A simple prompt without arguments",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text="This is a simple prompt for testing."),
                )
            ],
        )

    elif name == "test_prompt_with_arguments":
        arg1 = arguments.get("arg1", "")
        arg2 = arguments.get("arg2", "")
        return types.GetPromptResult(
            description="A prompt with required arguments",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=f"Prompt with arguments: arg1='{arg1}', arg2='{arg2}'"),
                )
            ],
        )

    elif name == "test_prompt_with_embedded_resource":
        resource_uri = arguments.get("resourceUri", "")
        return types.GetPromptResult(
            description="A prompt that includes an embedded resource",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.EmbeddedResource(
                        type="resource",
                        resource=types.TextResourceContents(
                            uri=resource_uri,
                            mime_type="text/plain",
                            text="Embedded resource content for testing.",
                        ),
                    ),
                ),
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text="Please process the embedded resource above."),
                ),
            ],
        )

    elif name == "test_prompt_with_image":
        return types.GetPromptResult(
            description="A prompt that includes image content",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.ImageContent(type="image", data=TEST_IMAGE_BASE64, mime_type="image/png"),
                ),
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text="Please analyze the image above."),
                ),
            ],
        )

    raise ValueError(f"Unknown prompt: {name}")


async def handle_set_logging_level(
    ctx: ServerRequestContext[Any], params: types.SetLevelRequestParams
) -> types.EmptyResult:
    """Handle logging level changes."""
    logger.info(f"Log level set to: {params.level}")
    return types.EmptyResult()


async def handle_subscribe_resource(
    ctx: ServerRequestContext[Any], params: types.SubscribeRequestParams
) -> types.EmptyResult:
    """Handle resource subscription."""
    resource_subscriptions.add(str(params.uri))
    logger.info(f"Subscribed to resource: {params.uri}")
    return types.EmptyResult()


async def handle_unsubscribe_resource(
    ctx: ServerRequestContext[Any], params: types.UnsubscribeRequestParams
) -> types.EmptyResult:
    """Handle resource unsubscription."""
    resource_subscriptions.discard(str(params.uri))
    logger.info(f"Unsubscribed from resource: {params.uri}")
    return types.EmptyResult()


async def handle_completion(
    ctx: ServerRequestContext[Any], params: types.CompleteRequestParams
) -> types.CompleteResult:
    """Handle completion requests."""
    # Basic completion support - returns empty array for conformance
    # Real implementations would provide contextual suggestions
    return types.CompleteResult(completion=types.Completion(values=[], total=0, has_more=False))


# --- Server instance ---

server = Server(
    "mcp-conformance-test-server",
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
    on_list_resources=handle_list_resources,
    on_list_resource_templates=handle_list_resource_templates,
    on_read_resource=handle_read_resource,
    on_subscribe_resource=handle_subscribe_resource,
    on_unsubscribe_resource=handle_unsubscribe_resource,
    on_list_prompts=handle_list_prompts,
    on_get_prompt=handle_get_prompt,
    on_set_logging_level=handle_set_logging_level,
    on_completion=handle_completion,
)


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
    import uvicorn

    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(f"Starting MCP Everything Server on port {port}")
    logger.info(f"Endpoint will be: http://localhost:{port}/mcp")

    starlette_app = server.streamable_http_app(
        event_store=event_store,
        retry_interval=100,  # 100ms retry interval for SSE polling
    )

    config = uvicorn.Config(
        starlette_app,
        host="127.0.0.1",
        port=port,
        log_level=log_level.lower(),
    )
    uvicorn_server = uvicorn.Server(config)
    import anyio

    anyio.run(uvicorn_server.serve)

    return 0


if __name__ == "__main__":
    main()
