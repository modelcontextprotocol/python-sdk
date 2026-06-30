#!/usr/bin/env python3
"""MCP Everything Server - Conformance Test Server

Server implementing all MCP features for conformance testing based on Conformance Server Specification.
"""

import asyncio
import base64
import json
import logging
from typing import Annotated, Any

import click
from mcp.server import ServerRequestContext
from mcp.server.extension import require_client_extension
from mcp.server.mcpserver import Context, MCPServer, RequestStateSecurity
from mcp.server.mcpserver.prompts.base import Prompt, UserMessage
from mcp.server.streamable_http import EventCallback, EventMessage, EventStore
from mcp.server.tasks import EXTENSION_ID as TASKS_EXTENSION_ID
from mcp.server.tasks import Tasks
from mcp.shared.exceptions import MCPError
from mcp_types import (
    AudioContent,
    Completion,
    CompletionArgument,
    CompletionContext,
    CreateMessageRequest,
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    EmbeddedResource,
    EmptyResult,
    ImageContent,
    InputRequest,
    InputRequiredResult,
    JSONRPCMessage,
    ListRootsRequest,
    ListRootsResult,
    PromptReference,
    ResourceTemplateReference,
    SamplingMessage,
    SetLevelRequestParams,
    SubscribeRequestParams,
    TextContent,
    TextResourceContents,
    UnsubscribeRequestParams,
)
from mcp_types.jsonrpc import INTERNAL_ERROR, MISSING_REQUIRED_CLIENT_CAPABILITY
from pydantic import BaseModel, Field

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

# Fixed fixture key (RequestStateSecurity requires at least 32 bytes); a real deployment would load a shared secret.
_REQUEST_STATE_KEY = b"everything-server-fixture-request-state-key"

# SEP-2663 Tasks extension: only these fixture tools are task-augmented, so every
# other tool keeps its synchronous behaviour even for clients that declare the
# extension (the tasks conformance scenarios assert e.g. `greet` stays sync).
TASK_AUGMENTED_TOOLS = frozenset(
    {
        "slow_compute",
        "failing_job",
        "protocol_error_job",
        "confirm_delete",
        "multi_input",
        "test_tool_with_task",
    }
)

mcp = MCPServer(
    name="mcp-conformance-test-server",
    request_state_security=RequestStateSecurity(keys=[_REQUEST_STATE_KEY]),
    extensions=[Tasks(augment=lambda params: params.name in TASK_AUGMENTED_TOOLS)],
)


# Tools
@mcp.tool()
def test_simple_text() -> str:
    """Tests simple text content response"""
    return "This is a simple text response for testing."


@mcp.tool()
def test_image_content() -> list[ImageContent]:
    """Tests image content response"""
    return [ImageContent(type="image", data=TEST_IMAGE_BASE64, mime_type="image/png")]


@mcp.tool()
def test_audio_content() -> list[AudioContent]:
    """Tests audio content response"""
    return [AudioContent(type="audio", data=TEST_AUDIO_BASE64, mime_type="audio/wav")]


@mcp.tool()
def test_embedded_resource() -> list[EmbeddedResource]:
    """Tests embedded resource content response"""
    return [
        EmbeddedResource(
            type="resource",
            resource=TextResourceContents(
                uri="test://embedded-resource",
                mime_type="text/plain",
                text="This is an embedded resource content.",
            ),
        )
    ]


@mcp.tool()
def test_multiple_content_types() -> list[TextContent | ImageContent | EmbeddedResource]:
    """Tests response with multiple content types (text, image, resource)"""
    return [
        TextContent(type="text", text="Multiple content types test:"),
        ImageContent(type="image", data=TEST_IMAGE_BASE64, mime_type="image/png"),
        EmbeddedResource(
            type="resource",
            resource=TextResourceContents(
                uri="test://mixed-content-resource",
                mime_type="application/json",
                text='{"test": "data", "value": 123}',
            ),
        ),
    ]


@mcp.tool()
async def test_tool_with_logging(ctx: Context) -> str:
    """Tests tool that emits log messages during execution"""
    await ctx.info("Tool execution started")  # pyright: ignore[reportDeprecated]
    await asyncio.sleep(0.05)

    await ctx.info("Tool processing data")  # pyright: ignore[reportDeprecated]
    await asyncio.sleep(0.05)

    await ctx.info("Tool execution completed")  # pyright: ignore[reportDeprecated]
    return "Tool with logging executed successfully"


@mcp.tool()
async def test_tool_with_progress(ctx: Context) -> str:
    """Tests tool that reports progress notifications"""
    await ctx.report_progress(progress=0, total=100, message="Completed step 0 of 100")
    await asyncio.sleep(0.05)

    await ctx.report_progress(progress=50, total=100, message="Completed step 50 of 100")
    await asyncio.sleep(0.05)

    await ctx.report_progress(progress=100, total=100, message="Completed step 100 of 100")

    # Return progress token as string
    progress_token = (
        ctx.request_context.meta.get("progress_token") if ctx.request_context and ctx.request_context.meta else 0
    )
    return str(progress_token)


@mcp.tool()
async def test_sampling(prompt: str, ctx: Context) -> str:
    """Tests server-initiated sampling (LLM completion request)"""
    try:
        # Request sampling from client. Without related_request_id the request goes
        # to the standalone GET stream and is silently dropped if it is not open yet.
        result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
            max_tokens=100,
            related_request_id=ctx.request_id,
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
async def test_elicitation(message: str, ctx: Context) -> str:
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
async def test_elicitation_sep1034_defaults(ctx: Context) -> str:
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
async def test_elicitation_sep1330_enums(ctx: Context) -> str:
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
def test_x_mcp_header(
    region: Annotated[
        str,
        Field(
            description="Mirrored into the Mcp-Param-Region header",
            json_schema_extra={"x-mcp-header": "Region"},
        ),
    ] = "<none>",
) -> str:
    """Tests SEP-2243 Mcp-Param-* server-side validation.

    Arms the http-custom-header-server-validation conformance scenario, which
    skips when no tool with an `x-mcp-header` annotation is found.
    """
    return f"region={region}"


@mcp.tool()
async def test_missing_capability(ctx: Context) -> str:
    """Tests that a handler-raised MISSING_REQUIRED_CLIENT_CAPABILITY surfaces as a top-level JSON-RPC error.

    Requires the client to declare the ``sampling`` capability. When absent, raises
    `MCPError` (which the tool dispatch re-raises rather than wrapping in
    ``CallToolResult.isError``) so the conformance harness observes a protocol-level
    error response with ``data.requiredCapabilities``.
    """
    client_params = ctx.session.client_params
    sampling_declared = client_params is not None and client_params.capabilities.sampling is not None
    if not sampling_declared:
        raise MCPError(
            code=MISSING_REQUIRED_CLIENT_CAPABILITY,
            message="This tool requires the client 'sampling' capability",
            data={"requiredCapabilities": ["sampling"]},
        )
    return "Client declared sampling capability; proceeding."


# SEP-2322 InputRequiredResult fixtures (multi-round-trip / ephemeral workflow)

NAME_SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}


def _name_elicitation(message: str = "What is your name?") -> ElicitRequest:
    return ElicitRequest(params=ElicitRequestFormParams(message=message, requested_schema=NAME_SCHEMA))


@mcp.tool()
async def test_input_required_result_elicitation(ctx: Context) -> str | InputRequiredResult:
    """Tests InputRequiredResult with a single elicitation request"""
    responses = ctx.input_responses
    if responses and "user_name" in responses:
        answer = responses["user_name"]
        name = answer.content.get("name", "stranger") if isinstance(answer, ElicitResult) and answer.content else "?"
        return f"Hello, {name}!"
    return InputRequiredResult(input_requests={"user_name": _name_elicitation()})


@mcp.tool()
async def test_input_required_result_sampling(ctx: Context) -> str | InputRequiredResult:
    """Tests InputRequiredResult with a single sampling request"""
    responses = ctx.input_responses
    if responses and "capital_question" in responses:
        answer = responses["capital_question"]
        text = answer.content.text if isinstance(answer, CreateMessageResult) and answer.content.type == "text" else "?"
        return f"Model said: {text}"
    return InputRequiredResult(
        input_requests={
            "capital_question": CreateMessageRequest(
                params=CreateMessageRequestParams(
                    messages=[
                        SamplingMessage(
                            role="user", content=TextContent(type="text", text="What is the capital of France?")
                        )
                    ],
                    max_tokens=100,
                )
            )
        }
    )


@mcp.tool()
async def test_input_required_result_list_roots(ctx: Context) -> str | InputRequiredResult:
    """Tests InputRequiredResult with a single roots/list request"""
    responses = ctx.input_responses
    if responses and "client_roots" in responses:
        answer = responses["client_roots"]
        count = len(answer.roots) if isinstance(answer, ListRootsResult) else 0
        return f"Client exposed {count} root(s)."
    return InputRequiredResult(input_requests={"client_roots": ListRootsRequest()})


@mcp.tool()
async def test_input_required_result_request_state(ctx: Context) -> str | InputRequiredResult:
    """Tests requestState round-tripping in the InputRequiredResult flow"""
    responses = ctx.input_responses
    if responses and "confirm" in responses and ctx.request_state == "request-state-nonce":
        return "state-ok: confirmation received"
    confirm = ElicitRequest(
        params=ElicitRequestFormParams(
            message="Please confirm",
            requested_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
        )
    )
    return InputRequiredResult(input_requests={"confirm": confirm}, request_state="request-state-nonce")


@mcp.tool()
async def test_input_required_result_multiple_inputs(ctx: Context) -> str | InputRequiredResult:
    """Tests InputRequiredResult carrying elicitation, sampling and roots requests together"""
    responses = ctx.input_responses
    if responses and {"user_name", "greeting", "client_roots"} <= responses.keys():
        return "All inputs received."
    return InputRequiredResult(
        input_requests={
            "user_name": _name_elicitation(),
            "greeting": CreateMessageRequest(
                params=CreateMessageRequestParams(
                    messages=[
                        SamplingMessage(role="user", content=TextContent(type="text", text="Generate a greeting"))
                    ],
                    max_tokens=50,
                )
            ),
            "client_roots": ListRootsRequest(),
        },
        request_state="multiple-inputs",
    )


@mcp.tool()
async def test_input_required_result_multi_round(ctx: Context) -> str | InputRequiredResult:
    """Tests a three-round InputRequiredResult flow with evolving requestState"""
    state = json.loads(ctx.request_state) if ctx.request_state else {"round": 0}
    responses = ctx.input_responses or {}

    if state["round"] == 0:
        return InputRequiredResult(
            input_requests={"step1": _name_elicitation("Step 1: What is your name?")},
            request_state=json.dumps({"round": 1}),
        )

    if state["round"] == 1 and "step1" in responses:
        step1 = responses["step1"]
        name = step1.content.get("name") if isinstance(step1, ElicitResult) and step1.content else None
        color_schema = {"type": "object", "properties": {"color": {"type": "string"}}, "required": ["color"]}
        return InputRequiredResult(
            input_requests={
                "step2": ElicitRequest(
                    params=ElicitRequestFormParams(
                        message="Step 2: What is your favorite color?", requested_schema=color_schema
                    )
                )
            },
            request_state=json.dumps({"round": 2, "name": name}),
        )

    if state["round"] == 2 and "step2" in responses:
        step2 = responses["step2"]
        color = step2.content.get("color") if isinstance(step2, ElicitResult) and step2.content else None
        return f"{state.get('name')} likes {color}."

    # Missing or out-of-order response: re-request from the start.
    return InputRequiredResult(
        input_requests={"step1": _name_elicitation("Step 1: What is your name?")},
        request_state=json.dumps({"round": 1}),
    )


@mcp.tool()
async def test_input_required_result_tampered_state(ctx: Context) -> str | InputRequiredResult:
    """Tests that the server rejects a tampered requestState echo.

    The handler stays plaintext; tamper rejection happens in the SDK's request-state boundary.
    """
    if ctx.request_state is None:
        confirm = ElicitRequest(
            params=ElicitRequestFormParams(
                message="Please confirm",
                requested_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            )
        )
        return InputRequiredResult(input_requests={"confirm": confirm}, request_state="round-1")
    return f"state-ok: {ctx.request_state}"


@mcp.tool()
async def test_input_required_result_capabilities(ctx: Context) -> InputRequiredResult:
    """Tests that inputRequests only include methods the client declared support for"""
    caps = ctx.client_capabilities
    requests: dict[str, InputRequest] = {}
    if caps is None or caps.sampling is not None:
        requests["sample"] = CreateMessageRequest(
            params=CreateMessageRequestParams(
                messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Say hello"))],
                max_tokens=50,
            )
        )
    if caps is None or caps.elicitation is not None:
        requests["ask"] = _name_elicitation()
    return InputRequiredResult(input_requests=requests, request_state="capability-gated")


# SEP-2663 Tasks extension fixtures (io.modelcontextprotocol/tasks). The server
# decides augmentation per call via the TASK_AUGMENTED_TOOLS allowlist above;
# `greet` stays deliberately outside it as the synchronous contrast the tasks
# scenarios assert on.

CONFIRM_SCHEMA = {"type": "object", "properties": {"confirm": {"type": "boolean"}}, "required": ["confirm"]}


@mcp.tool()
def greet(name: str) -> str:
    """Sync-only greeting tool; never task-augmented"""
    return f"Hello, {name}!"


@mcp.tool()
def slow_compute(seconds: float, label: str = "") -> str:
    """Task-supporting compute fixture (SEP-2663).

    Conformance passes durations up to 60s and immediately polls or cancels, so
    the fixture records the requested duration instead of sleeping — the
    born-terminal task is then observable well inside the scenario timeouts.
    """
    return f"slow_compute({label or 'unlabelled'}) finished after {seconds}s"


@mcp.tool()
async def failing_job(ctx: Context) -> str:
    """Task-required fixture: rejects non-declaring clients, then reports a tool error (SEP-2663)"""
    require_client_extension(ctx.request_context, TASKS_EXTENSION_ID)
    raise RuntimeError("failing_job always reports a tool execution error")


@mcp.tool()
def protocol_error_job() -> str:
    """Task fixture that fails at the protocol level, recording a `failed` task (SEP-2663)"""
    raise MCPError(code=INTERNAL_ERROR, message="protocol_error_job failed at the protocol level")


@mcp.tool()
async def confirm_delete(filename: str, ctx: Context) -> str | InputRequiredResult:
    """Task fixture gathering a deletion confirmation via elicitation (SEP-2322 + SEP-2663)"""
    responses = ctx.input_responses
    if responses and "confirm" in responses:
        answer = responses["confirm"]
        if isinstance(answer, ElicitResult) and answer.action == "accept" and (answer.content or {}).get("confirm"):
            return f"Deleted {filename}"
        return f"Kept {filename}"
    return InputRequiredResult(
        input_requests={
            "confirm": ElicitRequest(
                params=ElicitRequestFormParams(message=f"Really delete {filename}?", requested_schema=CONFIRM_SCHEMA)
            )
        }
    )


@mcp.tool()
async def multi_input(ctx: Context) -> str | InputRequiredResult:
    """Task fixture fanning out two simultaneous elicitations (SEP-2663 partial fulfillment probe)"""
    responses = ctx.input_responses
    if responses and {"first", "second"} <= responses.keys():
        return "multi_input received both responses"
    return InputRequiredResult(
        input_requests={
            "first": _name_elicitation("First input?"),
            "second": _name_elicitation("Second input?"),
        }
    )


@mcp.tool()
async def test_tool_with_task(ctx: Context) -> str | InputRequiredResult:
    """SEP-2663 MRTR-to-task composition fixture: gathers a name, then the final round becomes a task"""
    responses = ctx.input_responses
    if responses and "user_name" in responses:
        answer = responses["user_name"]
        name = answer.content.get("name", "stranger") if isinstance(answer, ElicitResult) and answer.content else "?"
        return f"Hello, {name}! The gathered-name task is complete."
    return InputRequiredResult(input_requests={"user_name": _name_elicitation()})


# SEP-1613 / SEP-2106 JSON Schema 2020-12 fixture: a tool whose inputSchema carries
# the full set of 2020-12 keywords the conformance scenario asserts on.

JSON_SCHEMA_2020_12_INPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "$defs": {
        "address": {
            "$anchor": "addressDef",
            "type": "object",
            "properties": {"street": {"type": "string"}, "city": {"type": "string"}},
        }
    },
    "properties": {
        "name": {"type": "string"},
        "address": {"$ref": "#/$defs/address"},
        "contactMethod": {"type": "string", "enum": ["phone", "email"]},
        "phone": {"type": "string"},
        "email": {"type": "string"},
    },
    "allOf": [{"anyOf": [{"required": ["phone"]}, {"required": ["email"]}]}],
    "if": {"properties": {"contactMethod": {"const": "phone"}}, "required": ["contactMethod"]},
    "then": {"required": ["phone"]},
    "else": {"required": ["email"]},
    "additionalProperties": False,
}


@mcp.tool(name="json_schema_2020_12_tool")
def json_schema_2020_12_tool() -> str:
    """Tests JSON Schema 2020-12 keyword preservation in tools/list (inputSchema installed below)."""
    return "json_schema_2020_12_tool"


# TODO(felix): replace with a public input_schema= override once MCPServer.tool() grows one.
mcp._tool_manager._tools["json_schema_2020_12_tool"].parameters = (  # pyright: ignore[reportPrivateUsage]
    JSON_SCHEMA_2020_12_INPUT_SCHEMA
)


@mcp.tool()
async def test_reconnection(ctx: Context) -> str:
    """Tests SSE polling by closing stream mid-call (SEP-1699)"""
    await ctx.info("Before disconnect")  # pyright: ignore[reportDeprecated]

    await ctx.close_sse_stream()

    await asyncio.sleep(0.2)  # Wait for client to reconnect

    await ctx.info("After reconnect")  # pyright: ignore[reportDeprecated]
    return "Reconnection test completed"


def _dynamic_tool() -> str:
    """A tool registered and removed by test_trigger_tool_change."""
    return "dynamic"


def _dynamic_prompt() -> str:
    """A prompt registered and removed by test_trigger_prompt_change."""
    return "dynamic"


@mcp.tool()
async def test_trigger_tool_change(ctx: Context) -> str:
    """Mutates the tool list and announces it to subscriptions/listen streams (SEP-2575)"""
    mcp.add_tool(_dynamic_tool, name="test_dynamic_tool")
    mcp.remove_tool("test_dynamic_tool")
    await ctx.notify_tools_changed()
    return "tool list changed"


@mcp.tool()
async def test_trigger_prompt_change(ctx: Context) -> str:
    """Mutates the prompt list and announces it to subscriptions/listen streams (SEP-2575)"""
    mcp.add_prompt(Prompt.from_function(_dynamic_prompt, name="test_dynamic_prompt", description="dynamic"))
    mcp.remove_prompt("test_dynamic_prompt")
    await ctx.notify_prompts_changed()
    return "prompt list changed"


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
                    uri=resourceUri,
                    mime_type="text/plain",
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
        UserMessage(role="user", content=ImageContent(type="image", data=TEST_IMAGE_BASE64, mime_type="image/png")),
        UserMessage(role="user", content=TextContent(type="text", text="Please analyze the image above.")),
    ]


@mcp.prompt()
async def test_input_required_result_prompt(ctx: Context) -> list[UserMessage] | InputRequiredResult:
    """Tests InputRequiredResult from prompts/get (SEP-2322 non-tool request)"""
    responses = ctx.input_responses
    if responses and "user_context" in responses:
        answer = responses["user_context"]
        text = answer.content.get("context", "?") if isinstance(answer, ElicitResult) and answer.content else "?"
        return [UserMessage(role="user", content=TextContent(type="text", text=f"Use the following context: {text}"))]
    return InputRequiredResult(
        input_requests={
            "user_context": ElicitRequest(
                params=ElicitRequestFormParams(
                    message="What context should the prompt use?",
                    requested_schema={
                        "type": "object",
                        "properties": {"context": {"type": "string"}},
                        "required": ["context"],
                    },
                )
            )
        }
    )


# Custom request handlers
# TODO(felix): Add public APIs to MCPServer for subscribe_resource, unsubscribe_resource,
# and set_logging_level to avoid accessing protected _lowlevel_server attribute.
async def handle_set_logging_level(ctx: ServerRequestContext, params: SetLevelRequestParams) -> EmptyResult:
    """Handle logging level changes"""
    logger.info(f"Log level set to: {params.level}")
    return EmptyResult()


async def handle_subscribe(ctx: ServerRequestContext, params: SubscribeRequestParams) -> EmptyResult:
    """Handle resource subscription"""
    resource_subscriptions.add(str(params.uri))
    logger.info(f"Subscribed to resource: {params.uri}")
    return EmptyResult()


async def handle_unsubscribe(ctx: ServerRequestContext, params: UnsubscribeRequestParams) -> EmptyResult:
    """Handle resource unsubscription"""
    resource_subscriptions.discard(str(params.uri))
    logger.info(f"Unsubscribed from resource: {params.uri}")
    return EmptyResult()


mcp._lowlevel_server.add_request_handler(  # pyright: ignore[reportPrivateUsage]
    "logging/setLevel", SetLevelRequestParams, handle_set_logging_level
)
mcp._lowlevel_server.add_request_handler(  # pyright: ignore[reportPrivateUsage]
    "resources/subscribe", SubscribeRequestParams, handle_subscribe
)
mcp._lowlevel_server.add_request_handler(  # pyright: ignore[reportPrivateUsage]
    "resources/unsubscribe", UnsubscribeRequestParams, handle_unsubscribe
)


@mcp.completion()
async def _handle_completion(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion:
    """Handle completion requests"""
    # Basic completion support - returns empty array for conformance
    # Real implementations would provide contextual suggestions
    return Completion(values=[], total=0, has_more=False)


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

    mcp.run(
        transport="streamable-http",
        port=port,
        event_store=event_store,
        retry_interval=100,  # 100ms retry interval for SSE polling
    )

    return 0


if __name__ == "__main__":
    main()
