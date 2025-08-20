"""
ServerSession Module

This module provides the ServerSession class, which manages communication between the
server and client in the MCP (Model Context Protocol) framework. It is most commonly
used in MCP servers to interact with the client.

Common usage pattern:
```python
server = Server(name)

@server.call_tool()
async def handle_tool_call(ctx: RequestContext, arguments: dict[str, Any]) -> Any:
    # Check client capabilities before proceeding
    if ctx.session.check_client_capability(
        types.ClientCapabilities(experimental={"advanced_tools": dict()})
    ):
        # Perform advanced tool operations
        result = await perform_advanced_tool_operation(arguments)
    else:
        # Fall back to basic tool operations
        result = await perform_basic_tool_operation(arguments)
    return result

@server.list_prompts()
async def handle_list_prompts(ctx: RequestContext) -> list[types.Prompt]:
    # Access session for any necessary checks or operations
    if ctx.session.client_params:
        # Customize prompts based on client initialization parameters
        return generate_custom_prompts(ctx.session.client_params)
    else:
        return default_prompts
```

The ServerSession class is typically used internally by the Server class and should not
be instantiated directly by users of the MCP framework.
"""

from enum import Enum
from typing import Any, TypeVar

import anyio
import anyio.lowlevel
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import AnyUrl

import mcp.types as types
from mcp.server.models import InitializationOptions
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.session import (
    BaseSession,
    RequestResponder,
)
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS


class InitializationState(Enum):
    NotInitialized = 1
    Initializing = 2
    Initialized = 3


ServerSessionT = TypeVar("ServerSessionT", bound="ServerSession")

ServerRequestResponder = (
    RequestResponder[types.ClientRequest, types.ServerResult] | types.ClientNotification | Exception
)


class ServerSession(
    BaseSession[
        types.ServerRequest,
        types.ServerNotification,
        types.ServerResult,
        types.ClientRequest,
        types.ClientNotification,
    ]
):
    _initialized: InitializationState = InitializationState.NotInitialized
    _client_params: types.InitializeRequestParams | None = None

    def __init__(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        init_options: InitializationOptions,
        stateless: bool = False,
    ) -> None:
        super().__init__(read_stream, write_stream, types.ClientRequest, types.ClientNotification)
        self._initialization_state = (
            InitializationState.Initialized if stateless else InitializationState.NotInitialized
        )

        self._init_options = init_options
        self._incoming_message_stream_writer, self._incoming_message_stream_reader = anyio.create_memory_object_stream[
            ServerRequestResponder
        ](0)
        self._exit_stack.push_async_callback(lambda: self._incoming_message_stream_reader.aclose())

    @property
    def client_params(self) -> types.InitializeRequestParams | None:
        return self._client_params

    def check_client_capability(self, capability: types.ClientCapabilities) -> bool:
        """Check if the client supports specific capabilities before using advanced MCP features.

        This method allows MCP servers to verify that the connected client supports
        required capabilities before calling methods that depend on them. It performs
        an AND operation - the client must support ALL capabilities specified in the
        request, not just some of them.

        You typically access this method through the session available in your request
        context via [`app.request_context.session`][mcp.shared.context.RequestContext] 
        within handler functions. Always check capabilities before using features like
        sampling, elicitation, or experimental functionality.

        Args:
            capability: A [`types.ClientCapabilities`][mcp.types.ClientCapabilities] object
                specifying which capabilities to check. Can include:

                - `roots`: Check if client supports root listing operations
                - `sampling`: Check if client supports LLM sampling via [`create_message`][mcp.server.session.ServerSession.create_message] 
                - `elicitation`: Check if client supports user interaction via [`elicit`][mcp.server.session.ServerSession.elicit]
                - `experimental`: Check for non-standard experimental capabilities

        Returns:
            bool: `True` if the client supports ALL requested capabilities, `False` if
                the client hasn't been initialized yet or lacks any of the requested
                capabilities.

        Examples:
            Check sampling capability before creating LLM messages:

            ```python
            from typing import Any
            from mcp.server.lowlevel import Server
            import mcp.types as types

            app = Server("example-server")

            @app.call_tool()
            async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
                ctx = app.request_context
                
                # Check if client supports LLM sampling
                if ctx.session.check_client_capability(
                    types.ClientCapabilities(sampling=types.SamplingCapability())
                ):
                    # Safe to use create_message
                    response = await ctx.session.create_message(
                        messages=[types.SamplingMessage(
                            role="user", 
                            content=types.TextContent(type="text", text="Help me analyze this data")
                        )],
                        max_tokens=100
                    )
                    return [types.TextContent(type="text", text=response.content.text)]
                else:
                    return [types.TextContent(type="text", text="Client doesn't support LLM sampling")]
            ```

            Check experimental capabilities:

            ```python
            @app.call_tool()
            async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
                ctx = app.request_context
                
                # Check for experimental advanced tools capability
                if ctx.session.check_client_capability(
                    types.ClientCapabilities(experimental={"advanced_tools": {}})
                ):
                    # Use experimental features
                    return await use_advanced_tool_features(arguments)
                else:
                    # Fall back to basic functionality
                    return await use_basic_tool_features(arguments)
            ```

            Check multiple capabilities at once:

            ```python
            # Client must support BOTH sampling AND elicitation
            if ctx.session.check_client_capability(
                types.ClientCapabilities(
                    sampling=types.SamplingCapability(),
                    elicitation=types.ElicitationCapability()
                )
            ):
                # Safe to use both features
                user_input = await ctx.session.elicit("What would you like to analyze?", schema)
                llm_response = await ctx.session.create_message(messages, max_tokens=100)
            ```

        Note:
            This method returns `False` if the session hasn't been initialized yet
            (before the client sends the initialization request). It also returns
            `False` if the client lacks ANY of the requested capabilities - all
            specified capabilities must be supported for this method to return `True`.
        """
        if self._client_params is None:
            return False

        # Get client capabilities from initialization params
        client_caps = self._client_params.capabilities

        # Check each specified capability in the passed in capability object
        if capability.roots is not None:
            if client_caps.roots is None:
                return False
            if capability.roots.listChanged and not client_caps.roots.listChanged:
                return False

        if capability.sampling is not None:
            if client_caps.sampling is None:
                return False

        if capability.elicitation is not None:
            if client_caps.elicitation is None:
                return False

        if capability.experimental is not None:
            if client_caps.experimental is None:
                return False
            # Check each experimental capability
            for exp_key, exp_value in capability.experimental.items():
                if exp_key not in client_caps.experimental or client_caps.experimental[exp_key] != exp_value:
                    return False

        return True

    async def _receive_loop(self) -> None:
        async with self._incoming_message_stream_writer:
            await super()._receive_loop()

    async def _received_request(self, responder: RequestResponder[types.ClientRequest, types.ServerResult]):
        match responder.request.root:
            case types.InitializeRequest(params=params):
                requested_version = params.protocolVersion
                self._initialization_state = InitializationState.Initializing
                self._client_params = params
                with responder:
                    await responder.respond(
                        types.ServerResult(
                            types.InitializeResult(
                                protocolVersion=requested_version
                                if requested_version in SUPPORTED_PROTOCOL_VERSIONS
                                else types.LATEST_PROTOCOL_VERSION,
                                capabilities=self._init_options.capabilities,
                                serverInfo=types.Implementation(
                                    name=self._init_options.server_name,
                                    version=self._init_options.server_version,
                                ),
                                instructions=self._init_options.instructions,
                            )
                        )
                    )
            case _:
                if self._initialization_state != InitializationState.Initialized:
                    raise RuntimeError("Received request before initialization was complete")

    async def _received_notification(self, notification: types.ClientNotification) -> None:
        # Need this to avoid ASYNC910
        await anyio.lowlevel.checkpoint()
        match notification.root:
            case types.InitializedNotification():
                self._initialization_state = InitializationState.Initialized
            case _:
                if self._initialization_state != InitializationState.Initialized:
                    raise RuntimeError("Received notification before initialization was complete")

    async def send_log_message(
        self,
        level: types.LoggingLevel,
        data: Any,
        logger: str | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        """Send a log message notification from the server to the client.

        This method allows MCP servers to send log messages to the connected client for
        debugging, monitoring, and error reporting purposes. The client can filter these
        messages based on the logging level it has configured via the logging/setLevel
        request. Check client capabilities using [`check_client_capability`][mcp.server.session.ServerSession.check_client_capability]
        if you need to verify logging support.
        
        You typically access this method through the session available in your request
        context. When using the low-level SDK, access it via 
        [`app.request_context.session`][mcp.shared.context.RequestContext] within handler
        functions. With FastMCP, use the convenience logging methods on the 
        [`Context`][mcp.server.fastmcp.Context] object instead, like
        [`ctx.info()`][mcp.server.fastmcp.Context.info] or 
        [`ctx.error()`][mcp.server.fastmcp.Context.error].

        Log messages are one-way notifications and do not expect a response from the client.
        They are useful for providing visibility into server operations, debugging issues,
        and tracking the flow of request processing.

        Args:
            level: The severity level of the log message as a `types.LoggingLevel`. Must be one of:

                - `debug`: Detailed information for debugging
                - `info`: General informational messages
                - `notice`: Normal but significant conditions
                - `warning`: Warning conditions that should be addressed
                - `error`: Error conditions that don't prevent operation
                - `critical`: Critical conditions requiring immediate attention
                - `alert`: Action must be taken immediately
                - `emergency`: System is unusable

            data: The data to log. Can be any JSON-serializable value including:

                - Simple strings for text messages
                - Objects/dictionaries for structured logging
                - Lists for multiple related items
                - Numbers, booleans, or null values

            logger: Optional name to identify the source of the log message.
                Useful for categorizing logs from different components or modules
                within your server (e.g., "database", "auth", "tool_handler").
            related_request_id: Optional `types.RequestId` linking this log to a specific client request.
                Use this to associate log messages with the request they relate to,
                making it easier to trace request processing and debug issues.

        Returns:
            None

        Raises:
            RuntimeError: If called before session initialization is complete.
            Various exceptions: Depending on serialization or transport errors.

        Examples:
            In a tool handler using the low-level SDK:

            ```python
            from typing import Any
            from mcp.server.lowlevel import Server
            import mcp.types as types

            app = Server("example-server")

            @app.call_tool()
            async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
                # Access the request context to get the session
                ctx = app.request_context

                # Log the start of processing
                await ctx.session.send_log_message(
                    level="info",
                    data=f"Processing tool call: {name}",
                    logger="tool_handler",
                    related_request_id=ctx.request_id
                )

                # Process and log any issues
                try:
                    result = perform_operation(arguments)
                except Exception as e:
                    await ctx.session.send_log_message(
                        level="error",
                        data={"error": str(e), "tool": name, "args": arguments},
                        logger="tool_handler",
                        related_request_id=ctx.request_id
                    )
                    raise

                return [types.TextContent(type="text", text=str(result))]
            ```

            Using FastMCP's [`Context`][mcp.server.fastmcp.Context] helper for cleaner logging:

            ```python
            from mcp.server.fastmcp import FastMCP, Context

            mcp = FastMCP(name="example-server")

            @mcp.tool()
            async def fetch_data(url: str, ctx: Context) -> str:
                # FastMCP's Context provides convenience methods that internally
                # call send_log_message with the appropriate parameters
                await ctx.info(f"Fetching data from {url}")
                await ctx.debug("Starting request")

                try:
                    data = await fetch(url)
                    await ctx.info("Data fetched successfully")
                    return data
                except Exception as e:
                    await ctx.error(f"Failed to fetch: {e}")
                    raise
            ```

            Streaming notifications with progress updates:

            ```python
            import anyio
            from typing import Any
            from mcp.server.lowlevel import Server
            import mcp.types as types

            app = Server("example-server")

            @app.call_tool()
            async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
                ctx = app.request_context
                count = arguments.get("count", 5)

                for i in range(count):
                    # Send progress updates to the client
                    await ctx.session.send_log_message(
                        level="info",
                        data=f"[{i + 1}/{count}] Processing item",
                        logger="progress_stream",
                        related_request_id=ctx.request_id
                    )
                    if i < count - 1:
                        await anyio.sleep(1)

                return [types.TextContent(type="text", text="Operation complete")]
            ```

        Note:
            Log messages are only delivered to the client if the client's configured
            logging level permits it. For example, if the client has set its level to
            "warning", it will not receive "debug" or "info" messages. Consider this
            when deciding what level to use for your log messages. This method internally
            uses [`send_notification`][mcp.shared.session.BaseSession.send_notification] to
            deliver the log message to the client.
        """
        await self.send_notification(
            types.ServerNotification(
                types.LoggingMessageNotification(
                    method="notifications/message",
                    params=types.LoggingMessageNotificationParams(
                        level=level,
                        data=data,
                        logger=logger,
                    ),
                )
            ),
            related_request_id,
        )

    async def send_resource_updated(self, uri: AnyUrl) -> None:
        """Send a resource updated notification."""
        await self.send_notification(
            types.ServerNotification(
                types.ResourceUpdatedNotification(
                    method="notifications/resources/updated",
                    params=types.ResourceUpdatedNotificationParams(uri=uri),
                )
            )
        )

    async def create_message(
        self,
        messages: list[types.SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: types.IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: types.ModelPreferences | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> types.CreateMessageResult:
        """Send a message to an LLM through the MCP client for processing.

        This method enables MCP servers to request LLM sampling from the connected client.
        The client forwards the request to its configured LLM provider (OpenAI, Anthropic, etc.)
        and returns the generated response. This is useful for tools that need LLM assistance
        to process user requests or generate content.

        The client must support the sampling capability for this method to work. Check
        client capabilities using [`check_client_capability`][mcp.server.session.ServerSession.check_client_capability] before calling this method.

        Args:
            messages: List of [`SamplingMessage`][mcp.types.SamplingMessage] objects representing the conversation history.
                Each message has a role ("user" or "assistant") and content (text, image, or audio).
            max_tokens: Maximum number of tokens the LLM should generate in the response.
            system_prompt: Optional system message to set the LLM's behavior and context.
            include_context: Optional context inclusion preferences for the LLM request.
            temperature: Optional sampling temperature (0.0-1.0) controlling response randomness.
                Lower values make responses more deterministic.
            stop_sequences: Optional list of strings that will cause the LLM to stop generating
                when encountered in the response.
            metadata: Optional arbitrary metadata to include with the request.
            model_preferences: Optional preferences for which model the client should use.
            related_request_id: Optional ID linking this request to a parent request for tracing.

        Returns:
            CreateMessageResult containing the LLM's response with role, content, model name,
                and stop reason information.

        Raises:
            RuntimeError: If called before session initialization is complete.
            Various exceptions: Depending on client implementation and LLM provider errors.

        Examples:
            Basic text generation:

            ```python
            from mcp.types import SamplingMessage, TextContent

            result = await session.create_message(
                messages=[
                    SamplingMessage(
                        role="user",
                        content=TextContent(type="text", text="Explain quantum computing")
                    )
                ],
                max_tokens=150
            )
            print(result.content.text)  # Generated explanation
            ```

            Multi-turn conversation with system prompt:

            ```python
            from mcp.types import SamplingMessage, TextContent

            result = await session.create_message(
                messages=[
                    SamplingMessage(
                        role="user",
                        content=TextContent(type="text", text="What's the weather like?")
                    ),
                    SamplingMessage(
                        role="assistant",
                        content=TextContent(type="text", text="I don't have access to weather data.")
                    ),
                    SamplingMessage(
                        role="user",
                        content=TextContent(type="text", text="Then help me write a poem about rain")
                    )
                ],
                max_tokens=100,
                system_prompt="You are a helpful poetry assistant.",
                temperature=0.8
            )
            ```

        Note:
            This method requires the client to have sampling capability enabled. Most modern
            MCP clients support this, but always check capabilities before use in production code.
        """
        return await self.send_request(
            request=types.ServerRequest(
                types.CreateMessageRequest(
                    method="sampling/createMessage",
                    params=types.CreateMessageRequestParams(
                        messages=messages,
                        systemPrompt=system_prompt,
                        includeContext=include_context,
                        temperature=temperature,
                        maxTokens=max_tokens,
                        stopSequences=stop_sequences,
                        metadata=metadata,
                        modelPreferences=model_preferences,
                    ),
                )
            ),
            result_type=types.CreateMessageResult,
            metadata=ServerMessageMetadata(
                related_request_id=related_request_id,
            ),
        )

    async def list_roots(self) -> types.ListRootsResult:
        """Send a roots/list request."""
        return await self.send_request(
            types.ServerRequest(
                types.ListRootsRequest(
                    method="roots/list",
                )
            ),
            types.ListRootsResult,
        )

    async def elicit(
        self,
        message: str,
        requestedSchema: types.ElicitRequestedSchema,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send an elicitation request to collect structured information from the client.

        This is the low-level method for client elicitation. For most use cases, prefer
        the higher-level [`Context.elicit`][mcp.server.fastmcp.Context.elicit] method
        which provides automatic Pydantic validation and a more convenient interface.

        You typically access this method through the session available in your request
        context via [`app.request_context.session`][mcp.shared.context.RequestContext] 
        within handler functions. Always check that the client supports elicitation using
        [`check_client_capability`][mcp.server.session.ServerSession.check_client_capability] 
        before calling this method.

        Args:
            message: The prompt or question to present to the user.
            requestedSchema: A [`types.ElicitRequestedSchema`][mcp.types.ElicitRequestedSchema] 
                defining the expected response structure according to JSON Schema.
            related_request_id: Optional `types.RequestId` linking 
                this elicitation to a specific client request for tracing.

        Returns:
            [`types.ElicitResult`][mcp.types.ElicitResult] containing the client's response
            and action taken (accept, decline, or cancel).

        Raises:
            RuntimeError: If called before session initialization is complete.
            Various exceptions: Depending on client implementation and user interaction.

        Note:
            Most developers should use [`Context.elicit`][mcp.server.fastmcp.Context.elicit] 
            instead, which provides Pydantic model validation and better error handling.
        """
        return await self.send_request(
            types.ServerRequest(
                types.ElicitRequest(
                    method="elicitation/create",
                    params=types.ElicitRequestParams(
                        message=message,
                        requestedSchema=requestedSchema,
                    ),
                )
            ),
            types.ElicitResult,
            metadata=ServerMessageMetadata(related_request_id=related_request_id),
        )

    async def send_ping(self) -> types.EmptyResult:
        """Send a ping request."""
        return await self.send_request(
            types.ServerRequest(
                types.PingRequest(
                    method="ping",
                )
            ),
            types.EmptyResult,
        )

    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
        related_request_id: str | None = None,
    ) -> None:
        """Send a progress notification."""
        await self.send_notification(
            types.ServerNotification(
                types.ProgressNotification(
                    method="notifications/progress",
                    params=types.ProgressNotificationParams(
                        progressToken=progress_token,
                        progress=progress,
                        total=total,
                        message=message,
                    ),
                )
            ),
            related_request_id,
        )

    async def send_resource_list_changed(self) -> None:
        """Send a resource list changed notification."""
        await self.send_notification(
            types.ServerNotification(
                types.ResourceListChangedNotification(
                    method="notifications/resources/list_changed",
                )
            )
        )

    async def send_tool_list_changed(self) -> None:
        """Send a tool list changed notification."""
        await self.send_notification(
            types.ServerNotification(
                types.ToolListChangedNotification(
                    method="notifications/tools/list_changed",
                )
            )
        )

    async def send_prompt_list_changed(self) -> None:
        """Send a prompt list changed notification."""
        await self.send_notification(
            types.ServerNotification(
                types.PromptListChangedNotification(
                    method="notifications/prompts/list_changed",
                )
            )
        )

    async def _handle_incoming(self, req: ServerRequestResponder) -> None:
        await self._incoming_message_stream_writer.send(req)

    @property
    def incoming_messages(
        self,
    ) -> MemoryObjectReceiveStream[ServerRequestResponder]:
        return self._incoming_message_stream_reader
