"""`ServerSession`: server-to-client requests and notifications.

A thin proxy over `JSONRPCDispatcher` and `Connection`. One instance per
client connection (built by `ServerRunner`). Handlers reach it as
`ctx.session` and use the typed helpers (`create_message`, `elicit_form`,
`send_log_message`, ...) to call back to the client.

The receive-loop, initialize handling, and per-request task isolation that
used to live here are now owned by `JSONRPCDispatcher` and `ServerRunner`.
"""

from typing import Any, TypeVar, cast, overload

from pydantic import AnyUrl, BaseModel
from typing_extensions import deprecated

from mcp import types
from mcp.server.connection import Connection
from mcp.server.validation import validate_sampling_tools, validate_tool_use_result_messages
from mcp.shared.dispatcher import CallOptions, Dispatcher, ProgressFnT
from mcp.shared.exceptions import MCPDeprecationWarning, NoBackChannelError, StatelessModeNotSupported
from mcp.shared.message import ServerMessageMetadata
from mcp.types import methods as _methods

__all__ = ["ServerSession"]

ResultT = TypeVar("ResultT", bound=BaseModel)


class ServerSession:
    """Connection-scoped proxy for server-to-client requests and notifications.

    `send_request` / `send_notification` model-dump their argument and forward
    to the dispatcher; the typed helpers below are unchanged from the previous
    implementation and only call those two methods.
    """

    def __init__(
        self,
        dispatcher: Dispatcher[Any],
        connection: Connection,
        *,
        stateless: bool = False,
    ) -> None:
        self._dispatcher = dispatcher
        self._connection = connection
        self._stateless = stateless

    @property
    def client_params(self) -> types.InitializeRequestParams | None:
        """The client's `initialize` request params; `None` before initialization."""
        return self._connection.client_params

    @property
    def protocol_version(self) -> str | None:
        """The protocol version negotiated during `initialize`.

        `None` before initialization, and normally `None` on stateless
        connections. For the per-request value, read `ctx.protocol_version`.
        """
        return self._connection.protocol_version

    async def send_request(
        self,
        request: types.ServerRequest,
        result_type: type[ResultT],
        request_read_timeout_seconds: float | None = None,
        metadata: ServerMessageMetadata | None = None,
        progress_callback: ProgressFnT | None = None,
    ) -> ResultT:
        """Send a typed server-to-client request and validate the result.

        `metadata.related_request_id` (when supplied) routes the outgoing
        message onto the originating request's response stream over
        streamable HTTP; it is the only metadata field honored here.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: If there is no related request to ride on and
                the connection has no standalone channel (stateless HTTP), so
                a response could never arrive.
            pydantic.ValidationError: The peer's result does not match `result_type`.
        """
        data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        opts: CallOptions = {}
        if request_read_timeout_seconds is not None:
            opts["timeout"] = request_read_timeout_seconds
        if progress_callback is not None:
            opts["on_progress"] = progress_callback
        related = metadata.related_request_id if metadata is not None else None
        if related is None and not self._connection.has_standalone_channel:
            # Fail fast instead of parking forever on a response that cannot
            # arrive; matches `Connection.send_raw_request`.
            raise NoBackChannelError(data["method"])
        # TODO: _related_request_id is not on the Dispatcher Protocol (and must not
        # be — it's transport-specific). The fix is to give `ctx.session` a per-request
        # Outbound (the DispatchContext, which threads its own request_id) alongside
        # the connection-level one, with `related_request_id` as the selector; that
        # belongs with the ServerSession/Context rework, not here.
        result = cast(
            "dict[str, Any]",
            await self._dispatcher.send_raw_request(
                data["method"],
                data.get("params"),
                opts or None,
                _related_request_id=related,  # type: ignore[call-arg]
            ),
        )
        # Literal fallback covers pre-handshake and stateless; matches runner.py.
        version = self.protocol_version or "2025-11-25"
        try:
            _methods.validate_client_result(request.method, version, result)
        except KeyError:
            pass
        return result_type.model_validate(result, by_name=False)

    async def send_notification(
        self,
        notification: types.ServerNotification,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        """Send a typed server-to-client notification."""
        data = notification.model_dump(by_alias=True, mode="json", exclude_none=True)
        await self._dispatcher.notify(data["method"], data.get("params"), _related_request_id=related_request_id)  # type: ignore[call-arg]

    def check_client_capability(self, capability: types.ClientCapabilities) -> bool:
        """Check if the client supports a specific capability."""
        return self._connection.check_capability(capability)

    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def send_log_message(
        self,
        level: types.LoggingLevel,
        data: Any,
        logger: str | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        """Send a log message notification."""
        await self.send_notification(
            types.LoggingMessageNotification(
                params=types.LoggingMessageNotificationParams(
                    level=level,
                    data=data,
                    logger=logger,
                ),
            ),
            related_request_id,
        )

    async def send_resource_updated(self, uri: str | AnyUrl) -> None:
        """Send a resource updated notification."""
        await self.send_notification(
            types.ResourceUpdatedNotification(
                params=types.ResourceUpdatedNotificationParams(uri=str(uri)),
            )
        )

    @overload
    @deprecated("The sampling capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
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
        tools: None = None,
        tool_choice: types.ToolChoice | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> types.CreateMessageResult:
        """Overload: Without tools, returns single content."""
        ...

    @overload
    @deprecated("The sampling capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
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
        tools: list[types.Tool],
        tool_choice: types.ToolChoice | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> types.CreateMessageResultWithTools:
        """Overload: With tools, returns array-capable content."""
        ...

    @deprecated("The sampling capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
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
        tools: list[types.Tool] | None = None,
        tool_choice: types.ToolChoice | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> types.CreateMessageResult | types.CreateMessageResultWithTools:
        """Send a sampling/create_message request.

        Args:
            messages: The conversation messages to send.
            max_tokens: Maximum number of tokens to generate.
            system_prompt: Optional system prompt.
            include_context: Optional context inclusion setting.
                Should only be set to "thisServer" or "allServers"
                if the client has sampling.context capability.
            temperature: Optional sampling temperature.
            stop_sequences: Optional stop sequences.
            metadata: Optional metadata to pass through to the LLM provider.
            model_preferences: Optional model selection preferences.
            tools: Optional list of tools the LLM can use during sampling.
                Requires client to have sampling.tools capability.
            tool_choice: Optional control over tool usage behavior.
                Requires client to have sampling.tools capability.
            related_request_id: Optional ID of a related request.

        Returns:
            The sampling result from the client.

        Raises:
            MCPError: If tools are provided but client doesn't support them.
            ValueError: If tool_use or tool_result message structure is invalid.
            StatelessModeNotSupported: If called in stateless HTTP mode.
        """
        if self._stateless:
            raise StatelessModeNotSupported(method="sampling")
        client_caps = self.client_params.capabilities if self.client_params else None
        validate_sampling_tools(client_caps, tools, tool_choice)
        validate_tool_use_result_messages(messages)

        request = types.CreateMessageRequest(
            params=types.CreateMessageRequestParams(
                messages=messages,
                system_prompt=system_prompt,
                include_context=include_context,
                temperature=temperature,
                max_tokens=max_tokens,
                stop_sequences=stop_sequences,
                metadata=metadata,
                model_preferences=model_preferences,
                tools=tools,
                tool_choice=tool_choice,
            ),
        )
        metadata_obj = ServerMessageMetadata(related_request_id=related_request_id)

        if tools is not None:
            return await self.send_request(
                request=request,
                result_type=types.CreateMessageResultWithTools,
                metadata=metadata_obj,
            )
        return await self.send_request(
            request=request,
            result_type=types.CreateMessageResult,
            metadata=metadata_obj,
        )

    @deprecated("The roots capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def list_roots(self) -> types.ListRootsResult:
        """Send a roots/list request."""
        if self._stateless:
            raise StatelessModeNotSupported(method="list_roots")
        return await self.send_request(
            types.ListRootsRequest(),
            types.ListRootsResult,
        )

    async def elicit(
        self,
        message: str,
        requested_schema: types.ElicitRequestedSchema,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send a form mode elicitation/create request.

        Args:
            message: The message to present to the user.
            requested_schema: Schema defining the expected response structure.
            related_request_id: Optional ID of the request that triggered this elicitation.

        Returns:
            The client's response.

        Note:
            This method is deprecated in favor of elicit_form(). It remains for
            backward compatibility but new code should use elicit_form().
        """
        return await self.elicit_form(message, requested_schema, related_request_id)

    async def elicit_form(
        self,
        message: str,
        requested_schema: types.ElicitRequestedSchema,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send a form mode elicitation/create request.

        Args:
            message: The message to present to the user.
            requested_schema: Schema defining the expected response structure.
            related_request_id: Optional ID of the request that triggered this elicitation.

        Returns:
            The client's response with form data.

        Raises:
            StatelessModeNotSupported: If called in stateless HTTP mode.
        """
        if self._stateless:
            raise StatelessModeNotSupported(method="elicitation")
        return await self.send_request(
            types.ElicitRequest(
                params=types.ElicitRequestFormParams(
                    message=message,
                    requested_schema=requested_schema,
                ),
            ),
            types.ElicitResult,
            metadata=ServerMessageMetadata(related_request_id=related_request_id),
        )

    async def elicit_url(
        self,
        message: str,
        url: str,
        elicitation_id: str,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send a URL mode elicitation/create request.

        This directs the user to an external URL for out-of-band interactions
        like OAuth flows, credential collection, or payment processing.

        Args:
            message: Human-readable explanation of why the interaction is needed.
            url: The URL the user should navigate to.
            elicitation_id: Unique identifier for tracking this elicitation.
            related_request_id: Optional ID of the request that triggered this elicitation.

        Returns:
            The client's response indicating acceptance, decline, or cancellation.

        Raises:
            StatelessModeNotSupported: If called in stateless HTTP mode.
        """
        if self._stateless:
            raise StatelessModeNotSupported(method="elicitation")
        return await self.send_request(
            types.ElicitRequest(
                params=types.ElicitRequestURLParams(
                    message=message,
                    url=url,
                    elicitation_id=elicitation_id,
                ),
            ),
            types.ElicitResult,
            metadata=ServerMessageMetadata(related_request_id=related_request_id),
        )

    async def send_ping(self) -> types.EmptyResult:
        """Send a ping request."""
        return await self.send_request(
            types.PingRequest(),
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
            types.ProgressNotification(
                params=types.ProgressNotificationParams(
                    progress_token=progress_token,
                    progress=progress,
                    total=total,
                    message=message,
                ),
            ),
            related_request_id,
        )

    async def send_resource_list_changed(self) -> None:
        """Send a resource list changed notification."""
        await self.send_notification(types.ResourceListChangedNotification())

    async def send_tool_list_changed(self) -> None:
        """Send a tool list changed notification."""
        await self.send_notification(types.ToolListChangedNotification())

    async def send_prompt_list_changed(self) -> None:
        """Send a prompt list changed notification."""
        await self.send_notification(types.PromptListChangedNotification())

    async def send_elicit_complete(
        self,
        elicitation_id: str,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        """Send an elicitation completion notification.

        This should be sent when a URL mode elicitation has been completed
        out-of-band to inform the client that it may retry any requests
        that were waiting for this elicitation.

        Args:
            elicitation_id: The unique identifier of the completed elicitation
            related_request_id: Optional ID of the request that triggered this notification
        """
        await self.send_notification(
            types.ElicitCompleteNotification(
                params=types.ElicitCompleteNotificationParams(elicitation_id=elicitation_id)
            ),
            related_request_id,
        )
