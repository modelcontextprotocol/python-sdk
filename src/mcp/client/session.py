from __future__ import annotations

import logging
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Protocol, cast, get_args

import anyio
import anyio.abc
import anyio.lowlevel
from pydantic import BaseModel, TypeAdapter, ValidationError
from typing_extensions import Self, TypeVar

from mcp import types
from mcp.client._transport import ReadStream, WriteStream
from mcp.shared._compat import resync_tracer
from mcp.shared._context import RequestContext
from mcp.shared.dispatcher import CallOptions, DispatchContext, Dispatcher
from mcp.shared.exceptions import MCPError
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import ClientMessageMetadata, MessageMetadata, ServerMessageMetadata, SessionMessage
from mcp.shared.session import ProgressFnT, RequestResponder
from mcp.shared.transport_context import TransportContext
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types._types import RequestParamsMeta

DEFAULT_CLIENT_INFO = types.Implementation(name="mcp", version="0.1.0")

logger = logging.getLogger("client")

ReceiveResultT = TypeVar("ReceiveResultT", bound=BaseModel)


class SamplingFnT(Protocol):
    async def __call__(
        self,
        context: RequestContext[ClientSession],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.CreateMessageResultWithTools | types.ErrorData: ...  # pragma: no branch


class ElicitationFnT(Protocol):
    async def __call__(
        self,
        context: RequestContext[ClientSession],
        params: types.ElicitRequestParams,
    ) -> types.ElicitResult | types.ErrorData: ...  # pragma: no branch


class ListRootsFnT(Protocol):
    async def __call__(
        self, context: RequestContext[ClientSession]
    ) -> types.ListRootsResult | types.ErrorData: ...  # pragma: no branch


class LoggingFnT(Protocol):
    async def __call__(self, params: types.LoggingMessageNotificationParams) -> None: ...  # pragma: no branch


class MessageHandlerFnT(Protocol):
    async def __call__(
        self,
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None: ...  # pragma: no branch


async def _default_message_handler(
    message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
) -> None:
    await anyio.lowlevel.checkpoint()


async def _default_sampling_callback(
    context: RequestContext[ClientSession],
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult | types.CreateMessageResultWithTools | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message="Sampling not supported",
    )


async def _default_elicitation_callback(
    context: RequestContext[ClientSession],
    params: types.ElicitRequestParams,
) -> types.ElicitResult | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message="Elicitation not supported",
    )


async def _default_list_roots_callback(
    context: RequestContext[ClientSession],
) -> types.ListRootsResult | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message="List roots not supported",
    )


async def _default_logging_callback(
    params: types.LoggingMessageNotificationParams,
) -> None:
    pass


ClientResponse: TypeAdapter[types.ClientResult | types.ErrorData] = TypeAdapter(types.ClientResult | types.ErrorData)

_SERVER_REQUEST_METHODS: frozenset[str] = frozenset(
    cast(type[BaseModel], arm).model_fields["method"].default for arm in get_args(types.ServerRequest)
)
"""Method names in the SDK's `ServerRequest` union, derived from the
discriminator literal on each arm. Requests for any other method — including
spec methods this SDK deliberately doesn't model, like `tasks/*` — are
answered with METHOD_NOT_FOUND instead of failing union validation."""


class ClientSession:
    """Client half of an MCP connection, running on a `Dispatcher`.

    Construct it over a transport's stream pair (or pass a pre-built
    `dispatcher=` instead, e.g. a `DirectDispatcher` for in-process
    embedding), enter it as an async context manager, then call
    `initialize()`. The receive loop, request correlation, and per-request
    concurrency live in the dispatcher; this class owns the MCP type layer:
    typed requests, the initialize handshake, and routing server-initiated
    traffic to the constructor callbacks.

    Transport-level `Exception` items reach `message_handler` only when the
    session builds its own dispatcher from streams, where it wires the
    dispatcher's `on_stream_exception` itself. Faults are delivered
    concurrently in the session's task group, like notifications — never
    inline in the read loop — so the handler may await session I/O, and one
    that raises costs that delivery, not the connection.
    """

    def __init__(
        self,
        read_stream: ReadStream[SessionMessage | Exception] | None = None,
        write_stream: WriteStream[SessionMessage] | None = None,
        read_timeout_seconds: float | None = None,
        sampling_callback: SamplingFnT | None = None,
        elicitation_callback: ElicitationFnT | None = None,
        list_roots_callback: ListRootsFnT | None = None,
        logging_callback: LoggingFnT | None = None,
        message_handler: MessageHandlerFnT | None = None,
        client_info: types.Implementation | None = None,
        *,
        sampling_capabilities: types.SamplingCapability | None = None,
        dispatcher: Dispatcher[Any] | None = None,
    ) -> None:
        self._session_read_timeout_seconds = read_timeout_seconds
        self._client_info = client_info or DEFAULT_CLIENT_INFO
        self._sampling_callback = sampling_callback or _default_sampling_callback
        self._sampling_capabilities = sampling_capabilities
        self._elicitation_callback = elicitation_callback or _default_elicitation_callback
        self._list_roots_callback = list_roots_callback or _default_list_roots_callback
        self._logging_callback = logging_callback or _default_logging_callback
        self._message_handler = message_handler or _default_message_handler
        self._tool_output_schemas: dict[str, dict[str, Any] | None] = {}
        self._initialize_result: types.InitializeResult | None = None
        self._task_group: anyio.abc.TaskGroup | None = None
        if dispatcher is not None:
            if read_stream is not None or write_stream is not None:
                raise ValueError("pass read_stream/write_stream or dispatcher, not both")
            self._dispatcher: Dispatcher[Any] = dispatcher
        else:
            if read_stream is None or write_stream is None:
                raise ValueError("read_stream and write_stream are required when no dispatcher is given")
            # Built here (inert until run() starts in __aenter__) so notifications
            # can be sent before entering the context manager, as before.
            self._dispatcher = JSONRPCDispatcher(
                read_stream, write_stream, on_stream_exception=self._on_stream_exception
            )

    async def __aenter__(self) -> Self:
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        try:
            await self._task_group.start(self._dispatcher.run, self._on_request, self._on_notify)
        except BaseException:
            # A cancellation landing here (e.g. the caller wrapped connect in
            # `move_on_after`) would abandon the entered task group, and anyio
            # later raises "exited non-innermost cancel scope" instead of a
            # clean timeout. Unwind the group before propagating; cancelling
            # its scope first keeps __aexit__ from blocking under the
            # still-active cancellation.
            task_group = self._task_group
            self._task_group = None
            task_group.cancel_scope.cancel()
            # Shield the group's own scope (not a new one: scope exits must
            # stay LIFO) so a pending outer cancellation cannot re-fire
            # inside __aexit__; the join is prompt because the scope is
            # cancelled. The original exception then propagates from the
            # `raise`; a child error supersedes it, raised by __aexit__.
            task_group.cancel_scope.shield = True
            await task_group.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        # Exit must not block: cancel the dispatcher and any in-flight
        # callbacks rather than waiting for them.
        assert self._task_group is not None
        self._task_group.cancel_scope.cancel()
        result = await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
        await resync_tracer()
        return result

    async def send_request(
        self,
        request: types.ClientRequest,
        result_type: type[ReceiveResultT],
        request_read_timeout_seconds: float | None = None,
        metadata: MessageMetadata = None,
        progress_callback: ProgressFnT | None = None,
    ) -> ReceiveResultT:
        """Send a request and wait for its typed result.

        A per-request read timeout takes precedence over the session-level
        one. `metadata` carries transport hints: `ClientMessageMetadata`
        resumption fields (streamable HTTP), or a
        `ServerMessageMetadata.related_request_id` to route the message onto
        an originating request's stream.

        Raises:
            MCPError: The server responded with an error, or the read timeout
                elapsed, or the connection closed while sending or waiting.
            RuntimeError: Called before entering the context manager. Raised
                by the stream-built dispatcher; a user-supplied `dispatcher=`
                may not enforce this.
        """
        data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        method: str = data["method"]
        opts: CallOptions = {}
        timeout = request_read_timeout_seconds or self._session_read_timeout_seconds
        if timeout is not None:
            opts["timeout"] = timeout
        if progress_callback is not None:
            opts["on_progress"] = progress_callback
        related_request_id: types.RequestId | None = None
        if isinstance(metadata, ClientMessageMetadata):
            if metadata.resumption_token is not None:
                opts["resumption_token"] = metadata.resumption_token
            if metadata.on_resumption_token_update is not None:
                opts["on_resumption_token"] = metadata.on_resumption_token_update
        elif isinstance(metadata, ServerMessageMetadata):
            related_request_id = metadata.related_request_id
        if method == "initialize":
            # The spec forbids cancelling initialize; opt out of the
            # dispatcher's courtesy cancel-on-abandon.
            opts["cancel_on_abandon"] = False
        if related_request_id is not None and isinstance(self._dispatcher, JSONRPCDispatcher):
            # Related-request routing is JSON-RPC stream plumbing; other
            # dispatchers have no per-request streams to route onto.
            raw = await self._dispatcher.send_raw_request(
                method, data.get("params"), opts, _related_request_id=related_request_id
            )
        else:
            raw = await self._dispatcher.send_raw_request(method, data.get("params"), opts)
        return result_type.model_validate(raw, by_name=False)

    async def send_notification(
        self,
        notification: types.ClientNotification,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        """Send a one-way notification. Usable before entering the context manager."""
        data = notification.model_dump(by_alias=True, mode="json", exclude_none=True)
        # `is not None`, not truthiness: request ids are opaque and 0 is valid.
        if related_request_id is not None and isinstance(self._dispatcher, JSONRPCDispatcher):
            await self._dispatcher.notify(data["method"], data.get("params"), _related_request_id=related_request_id)
        else:
            await self._dispatcher.notify(data["method"], data.get("params"))

    async def initialize(self) -> types.InitializeResult:
        sampling = (
            (self._sampling_capabilities or types.SamplingCapability())
            if self._sampling_callback is not _default_sampling_callback
            else None
        )
        elicitation = (
            types.ElicitationCapability(form=types.FormElicitationCapability(), url=types.UrlElicitationCapability())
            if self._elicitation_callback is not _default_elicitation_callback
            else None
        )
        roots = (
            # TODO: Should this be based on whether we
            # _will_ send notifications, or only whether
            # they're supported?
            types.RootsCapability(list_changed=True)
            if self._list_roots_callback is not _default_list_roots_callback
            else None
        )

        result = await self.send_request(
            types.InitializeRequest(
                params=types.InitializeRequestParams(
                    protocol_version=types.LATEST_PROTOCOL_VERSION,
                    capabilities=types.ClientCapabilities(
                        sampling=sampling,
                        elicitation=elicitation,
                        experimental=None,
                        roots=roots,
                    ),
                    client_info=self._client_info,
                ),
            ),
            types.InitializeResult,
        )

        if result.protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise RuntimeError(f"Unsupported protocol version from the server: {result.protocol_version}")

        self._initialize_result = result

        await self.send_notification(types.InitializedNotification())

        return result

    @property
    def initialize_result(self) -> types.InitializeResult | None:
        """The server's InitializeResult. None until initialize() has been called.

        Contains server_info, capabilities, instructions, and the negotiated protocol_version.
        """
        return self._initialize_result

    async def send_ping(self, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        """Send a ping request."""
        return await self.send_request(types.PingRequest(params=types.RequestParams(_meta=meta)), types.EmptyResult)

    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> None:
        """Send a progress notification."""
        await self.send_notification(
            types.ProgressNotification(
                params=types.ProgressNotificationParams(
                    progress_token=progress_token,
                    progress=progress,
                    total=total,
                    message=message,
                    _meta=meta,
                ),
            )
        )

    async def set_logging_level(
        self,
        level: types.LoggingLevel,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.EmptyResult:
        """Send a logging/setLevel request."""
        return await self.send_request(
            types.SetLevelRequest(params=types.SetLevelRequestParams(level=level, _meta=meta)),
            types.EmptyResult,
        )

    async def list_resources(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListResourcesResult:
        """Send a resources/list request.

        Args:
            params: Full pagination parameters including cursor and any future fields
        """
        return await self.send_request(types.ListResourcesRequest(params=params), types.ListResourcesResult)

    async def list_resource_templates(
        self, *, params: types.PaginatedRequestParams | None = None
    ) -> types.ListResourceTemplatesResult:
        """Send a resources/templates/list request.

        Args:
            params: Full pagination parameters including cursor and any future fields
        """
        return await self.send_request(
            types.ListResourceTemplatesRequest(params=params),
            types.ListResourceTemplatesResult,
        )

    async def read_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.ReadResourceResult:
        """Send a resources/read request."""
        return await self.send_request(
            types.ReadResourceRequest(params=types.ReadResourceRequestParams(uri=uri, _meta=meta)),
            types.ReadResourceResult,
        )

    async def subscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        """Send a resources/subscribe request."""
        return await self.send_request(
            types.SubscribeRequest(params=types.SubscribeRequestParams(uri=uri, _meta=meta)),
            types.EmptyResult,
        )

    async def unsubscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        """Send a resources/unsubscribe request."""
        return await self.send_request(
            types.UnsubscribeRequest(params=types.UnsubscribeRequestParams(uri=uri, _meta=meta)),
            types.EmptyResult,
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.CallToolResult:
        """Send a tools/call request with optional progress callback support."""

        result = await self.send_request(
            types.CallToolRequest(
                params=types.CallToolRequestParams(name=name, arguments=arguments, _meta=meta),
            ),
            types.CallToolResult,
            request_read_timeout_seconds=read_timeout_seconds,
            progress_callback=progress_callback,
        )

        if not result.is_error:
            await self._validate_tool_result(name, result)

        return result

    async def _validate_tool_result(self, name: str, result: types.CallToolResult) -> None:
        """Validate the structured content of a tool result against its output schema."""
        if name not in self._tool_output_schemas:
            # refresh output schema cache
            await self.list_tools()

        output_schema = None
        if name in self._tool_output_schemas:
            output_schema = self._tool_output_schemas.get(name)
        else:
            logger.warning(f"Tool {name} not listed by server, cannot validate any structured content")

        if output_schema is not None:
            from jsonschema import SchemaError, ValidationError, validate

            if result.structured_content is None:
                raise RuntimeError(f"Tool {name} has an output schema but did not return structured content")
            try:
                validate(result.structured_content, output_schema)
            except ValidationError as e:
                raise RuntimeError(f"Invalid structured content returned by tool {name}: {e}")
            except SchemaError as e:  # pragma: no cover
                raise RuntimeError(f"Invalid schema for tool {name}: {e}")  # pragma: no cover

    async def list_prompts(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListPromptsResult:
        """Send a prompts/list request.

        Args:
            params: Full pagination parameters including cursor and any future fields
        """
        return await self.send_request(types.ListPromptsRequest(params=params), types.ListPromptsResult)

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
        *,
        meta: RequestParamsMeta | None = None,
    ) -> types.GetPromptResult:
        """Send a prompts/get request."""
        return await self.send_request(
            types.GetPromptRequest(params=types.GetPromptRequestParams(name=name, arguments=arguments, _meta=meta)),
            types.GetPromptResult,
        )

    async def complete(
        self,
        ref: types.ResourceTemplateReference | types.PromptReference,
        argument: dict[str, str],
        context_arguments: dict[str, str] | None = None,
    ) -> types.CompleteResult:
        """Send a completion/complete request."""
        context = None
        if context_arguments is not None:
            context = types.CompletionContext(arguments=context_arguments)

        return await self.send_request(
            types.CompleteRequest(
                params=types.CompleteRequestParams(
                    ref=ref,
                    argument=types.CompletionArgument(**argument),
                    context=context,
                ),
            ),
            types.CompleteResult,
        )

    async def list_tools(self, *, params: types.PaginatedRequestParams | None = None) -> types.ListToolsResult:
        """Send a tools/list request.

        Args:
            params: Full pagination parameters including cursor and any future fields
        """
        result = await self.send_request(
            types.ListToolsRequest(params=params),
            types.ListToolsResult,
        )

        # Cache tool output schemas for future validation
        # Note: don't clear the cache, as we may be using a cursor
        for tool in result.tools:
            self._tool_output_schemas[tool.name] = tool.output_schema

        return result

    async def send_roots_list_changed(self) -> None:
        """Send a roots/list_changed notification."""
        await self.send_notification(types.RootsListChangedNotification())

    async def _on_request(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        """Answer a server-initiated request via the registered callbacks.

        An unknown method raises `MCPError` (METHOD_NOT_FOUND), which the
        dispatcher puts on the wire as-is; malformed params for a known method
        raise `ValidationError`, which the dispatcher answers with
        INVALID_PARAMS; an `ErrorData` returned by a callback becomes the
        error response.
        """
        if method not in _SERVER_REQUEST_METHODS:
            # Unknown methods are METHOD_NOT_FOUND (-32601) per JSON-RPC 2.0,
            # not validation failures (-32602).
            raise MCPError(code=types.METHOD_NOT_FOUND, message="Method not found", data=method)
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = dict(params)
        request = types.server_request_adapter.validate_python(payload, by_name=False)

        ctx = RequestContext[ClientSession](
            request_id=dctx.request_id, meta=request.params.meta if request.params else None, session=self
        )
        response: types.ClientResult | types.ErrorData
        match request:
            case types.CreateMessageRequest(params=sampling_params):
                response = await self._sampling_callback(ctx, sampling_params)
            case types.ElicitRequest(params=elicit_params):
                response = await self._elicitation_callback(ctx, elicit_params)
            case types.ListRootsRequest():
                response = await self._list_roots_callback(ctx)
            case types.PingRequest():  # pragma: no branch
                response = types.EmptyResult()
        client_response = ClientResponse.validate_python(response)
        if isinstance(client_response, types.ErrorData):
            raise MCPError.from_error_data(client_response)
        return client_response.model_dump(by_alias=True, mode="json", exclude_none=True)

    async def _on_notify(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> None:
        """Route a server notification: validate, run the typed callback, tee to message_handler."""
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = dict(params)
        try:
            notification = types.server_notification_adapter.validate_python(payload, by_name=False)
        except ValidationError:
            logger.warning("Failed to validate notification: %s", payload, exc_info=True)
            return
        if isinstance(notification, types.CancelledNotification):
            # The dispatcher already applied the cancellation to the in-flight
            # request; message_handler never sees it, so handlers matching
            # exhaustively over ServerNotification need no arm for it.
            return
        if isinstance(notification, types.LoggingMessageNotification):
            await self._logging_callback(notification.params)
        await self._message_handler(notification)

    async def _on_stream_exception(self, exc: Exception) -> None:
        """Spawn delivery of a transport-level fault (connection error, parse error) to message_handler.

        The dispatcher awaits this observer inline in its read loop, so the
        handler must not run here: a slow handler would head-of-line block the
        session, and one that awaits session I/O (e.g. sends a ping) would
        deadlock against the parked loop. Spawn it instead, with the same
        containment notification deliveries get.
        """
        # The dispatcher only runs inside the task group entered in
        # __aenter__, so the group is always live when it calls back here.
        assert self._task_group is not None
        self._task_group.start_soon(self._deliver_stream_exception, exc)

    async def _deliver_stream_exception(self, exc: Exception) -> None:
        try:
            await self._message_handler(exc)
        except Exception:
            logger.exception("message_handler raised on transport exception")
