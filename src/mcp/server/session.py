"""`ServerSession`: server-to-client requests and notifications.

A per-request proxy built by the kernel for each inbound request. Exposes the
request-scoped outbound channel and the connection's standalone channel.
Handlers reach it as `ctx.session` and use the typed helpers (`elicit_form`,
`send_log_message`, ...) to call back to the client.
"""

from typing import Any, TypeVar, overload

import mcp_types as types
from mcp_types import methods as _methods
from pydantic import AnyUrl, BaseModel
from typing_extensions import deprecated

from mcp.server.connection import Connection
from mcp.server.validation import validate_sampling_tools, validate_tool_use_result_messages
from mcp.shared.dispatcher import CallOptions, DispatchContext, ProgressFnT
from mcp.shared.exceptions import MCPDeprecationWarning
from mcp.shared.message import ServerMessageMetadata

__all__ = ["ServerSession"]

ResultT = TypeVar("ResultT", bound=BaseModel)


class ServerSession:
    """Per-request proxy for server-to-client requests and notifications.

    Built once per inbound request by the kernel's `_make_context`. Holds two
    `Outbound` channels: the request-scoped one (the per-request
    `DispatchContext`, which on streamable HTTP routes onto the originating
    POST's response stream) and the connection's standalone channel
    (`connection.outbound`). `related_request_id` on the public methods is the
    selector — present means request-scoped, absent means standalone — and
    never crosses the `Outbound` Protocol.
    """

    def __init__(self, request_outbound: DispatchContext[Any], connection: Connection) -> None:
        self._request_outbound = request_outbound
        self._connection = connection

    @property
    def client_params(self) -> types.InitializeRequestParams | None:
        """The client's `initialize` request params; `None` when no client info was supplied."""
        return self._connection.client_params

    @property
    def can_send_request(self) -> bool:
        """Whether this request's channel can currently deliver a server-initiated request."""
        return self._request_outbound.can_send_request

    @property
    def protocol_version(self) -> str:
        """The protocol version this connection speaks.

        Populated at `Connection` construction and overwritten once the
        handshake commits on the loop path; never `None`.
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

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: The connection has no back-channel for
                server-initiated requests (raised by the held `Outbound`).
            pydantic.ValidationError: The peer's result does not match `result_type`.
        """
        related = metadata.related_request_id if metadata is not None else None
        channel = self._request_outbound if related is not None else self._connection.outbound
        data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        opts: CallOptions = {}
        if request_read_timeout_seconds is not None:
            opts["timeout"] = request_read_timeout_seconds
        if progress_callback is not None:
            opts["on_progress"] = progress_callback
        result = await channel.send_raw_request(data["method"], data.get("params"), opts or None)
        try:
            _methods.validate_client_result(request.method, self.protocol_version, result)
        except KeyError:
            pass
        return result_type.model_validate(result, by_name=False)

    async def send_notification(
        self,
        notification: types.ServerNotification,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        """Send a typed server-to-client notification."""
        channel = self._request_outbound if related_request_id is not None else self._connection.outbound
        data = notification.model_dump(by_alias=True, mode="json", exclude_none=True)
        await channel.notify(data["method"], data.get("params"))

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
            NoBackChannelError: The connection has no back-channel for
                server-initiated requests.
        """
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
        """Send a roots/list request.

        Raises:
            NoBackChannelError: The connection has no back-channel for
                server-initiated requests.
        """
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
            NoBackChannelError: The connection has no back-channel for
                server-initiated requests.
        """
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
            NoBackChannelError: The connection has no back-channel for
                server-initiated requests.
        """
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

    async def report_progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        """Report progress for the inbound request this session is scoped to.

        A no-op when the caller did not request progress. Dispatcher-agnostic:
        on JSON-RPC the held `DispatchContext` emits ``notifications/progress``
        against the caller's token; on the in-process direct dispatcher it
        invokes the caller's callback directly.
        """
        await self._request_outbound.progress(progress, total, message)

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
