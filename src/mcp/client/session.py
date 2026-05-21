from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, Protocol, cast, overload

import anyio
import anyio.abc
import anyio.lowlevel
import mcp_types as types
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    UNSUPPORTED_PROTOCOL_VERSION,
    RequestId,
    RequestParamsMeta,
)
from mcp_types import methods as _methods
from mcp_types.version import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    LATEST_HANDSHAKE_VERSION,
    LATEST_MODERN_VERSION,
    MODERN_PROTOCOL_VERSIONS,
)
from pydantic import BaseModel, TypeAdapter, ValidationError
from typing_extensions import Self, TypeVar, deprecated

from mcp.client._transport import ReadStream, WriteStream
from mcp.shared._compat import resync_tracer
from mcp.shared.dispatcher import CallOptions, DispatchContext, Dispatcher, ProgressFnT
from mcp.shared.exceptions import MCPDeprecationWarning, MCPError
from mcp.shared.inbound import (
    MCP_METHOD_HEADER,
    MCP_NAME_HEADER,
    MCP_PROTOCOL_VERSION_HEADER,
    NAME_BEARING_METHODS,
    encode_header_value,
    find_invalid_x_mcp_header,
)
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import ClientMessageMetadata, SessionMessage
from mcp.shared.session import RequestResponder
from mcp.shared.transport_context import TransportContext

DEFAULT_CLIENT_INFO = types.Implementation(name="mcp", version="0.1.0")
DISCOVER_TIMEOUT_SECONDS = 10.0

logger = logging.getLogger("client")


def _preconnect_stamp(data: dict[str, Any], opts: CallOptions) -> None:
    # initialize/discover forbid cancellation; other pre-handshake requests (lowlevel
    # ClientSession callers may skip the handshake entirely) keep the courtesy cancel.
    if data["method"] in ("initialize", "server/discover"):
        opts["cancel_on_abandon"] = False


def _make_handshake_stamp(protocol_version: str) -> Callable[[dict[str, Any], CallOptions], None]:
    def stamp(data: dict[str, Any], opts: CallOptions) -> None:
        opts.setdefault("headers", {})[MCP_PROTOCOL_VERSION_HEADER] = protocol_version

    return stamp


def _make_modern_stamp(
    protocol_version: str, client_info: dict[str, Any], capabilities: dict[str, Any]
) -> Callable[[dict[str, Any], CallOptions], None]:
    def stamp(data: dict[str, Any], opts: CallOptions) -> None:
        params = data.setdefault("params", {})
        meta = params.setdefault("_meta", {})
        meta[PROTOCOL_VERSION_META_KEY] = protocol_version
        meta[CLIENT_INFO_META_KEY] = client_info
        meta[CLIENT_CAPABILITIES_META_KEY] = capabilities
        opts["cancel_on_abandon"] = False
        headers = opts.setdefault("headers", {})
        headers[MCP_PROTOCOL_VERSION_HEADER] = protocol_version
        headers[MCP_METHOD_HEADER] = data["method"]
        name_key = NAME_BEARING_METHODS.get(data["method"])
        if name_key is not None and isinstance(name := params.get(name_key), str):
            headers[MCP_NAME_HEADER] = encode_header_value(name)

    return stamp


ReceiveResultT = TypeVar("ReceiveResultT", bound=BaseModel)


@dataclass(kw_only=True)
class ClientRequestContext:
    """Context for a server-initiated request, passed to the sampling/elicitation/list-roots callbacks."""

    session: ClientSession
    request_id: RequestId
    meta: RequestParamsMeta | None = None


class SamplingFnT(Protocol):
    async def __call__(
        self,
        context: ClientRequestContext,
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.CreateMessageResultWithTools | types.ErrorData: ...  # pragma: no branch


class ElicitationFnT(Protocol):
    async def __call__(
        self,
        context: ClientRequestContext,
        params: types.ElicitRequestParams,
    ) -> types.ElicitResult | types.ErrorData: ...  # pragma: no branch


class ListRootsFnT(Protocol):
    async def __call__(
        self, context: ClientRequestContext
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
    context: ClientRequestContext,
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult | types.CreateMessageResultWithTools | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message="Sampling not supported",
    )


async def _default_elicitation_callback(
    context: ClientRequestContext,
    params: types.ElicitRequestParams,
) -> types.ElicitResult | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message="Elicitation not supported",
    )


async def _default_list_roots_callback(
    context: ClientRequestContext,
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

_CallToolResultAdapter: TypeAdapter[types.CallToolResult | types.InputRequiredResult] = TypeAdapter(
    types.CallToolResult | types.InputRequiredResult
)


class ClientSession:
    """Client half of an MCP connection, running on a `Dispatcher`.

    Construct it over a transport's stream pair (or pass a pre-built
    `dispatcher=`), enter as an async context manager, then call
    `initialize()`. The dispatcher owns the receive loop and request
    correlation; this class owns the typed MCP layer and the constructor
    callbacks. Transport `Exception` items reach `message_handler` only when
    the session builds its own dispatcher from a stream pair.
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
        self._discover_result: types.DiscoverResult | None = None
        self._negotiated_version: str | None = None
        self._stamp: Callable[[dict[str, Any], CallOptions], None] = _preconnect_stamp
        self._task_group: anyio.abc.TaskGroup | None = None
        if dispatcher is not None:
            if read_stream is not None or write_stream is not None:
                raise ValueError("pass read_stream/write_stream or dispatcher, not both")
            self._dispatcher: Dispatcher[Any] = dispatcher
            if isinstance(dispatcher, JSONRPCDispatcher) and dispatcher.on_stream_exception is None:
                # Route transport-level Exception items into message_handler — only
                # stream-backed dispatchers carry these; DirectDispatcher has none.
                # Don't clobber a caller-supplied hook.
                # TODO(L78): this leaves a bound-method ref on the dispatcher after the
                # session exits (memory pin) and a second wrap of the same dispatcher would
                # skip install. The Transport-as-Dispatcher rework (L77) removes this seam.
                dispatcher.on_stream_exception = self._on_stream_exception
        else:
            if read_stream is None or write_stream is None:
                raise ValueError("read_stream and write_stream are required when no dispatcher is given")
            # Built eagerly so notifications can be sent before entering the context manager.
            self._dispatcher = JSONRPCDispatcher(
                read_stream, write_stream, on_stream_exception=self._on_stream_exception
            )

    async def __aenter__(self) -> Self:
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        try:
            await self._task_group.start(self._dispatcher.run, self._on_request, self._on_notify)
        except BaseException:
            # Unwind the entered task group before propagating: a cancellation
            # landing here (e.g. `move_on_after` around connect) would abandon
            # it and anyio would later raise "exited non-innermost cancel scope".
            task_group = self._task_group
            self._task_group = None
            task_group.cancel_scope.cancel()
            # Shield the group's own scope (a new one would break LIFO exit)
            # so a pending outer cancellation cannot re-fire inside __aexit__.
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
        # Exit must not block: cancel the dispatcher and in-flight callbacks.
        assert self._task_group is not None
        self._task_group.cancel_scope.cancel()
        result = await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
        await resync_tracer()
        return result

    async def send_request(
        self,
        request: types.ClientRequest,
        result_type: type[ReceiveResultT] | TypeAdapter[ReceiveResultT],
        request_read_timeout_seconds: float | None = None,
        metadata: ClientMessageMetadata | None = None,
        progress_callback: ProgressFnT | None = None,
    ) -> ReceiveResultT:
        """Send a request and wait for its typed result.

        Args:
            metadata: Streamable HTTP resumption hints.

        Raises:
            MCPError: Error response, read timeout, or connection closed.
            RuntimeError: Called before entering the context manager.
        """
        data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        method: str = data["method"]
        opts: CallOptions = {}
        self._stamp(data, opts)
        timeout = (
            request_read_timeout_seconds
            if request_read_timeout_seconds is not None
            else self._session_read_timeout_seconds
        )
        if timeout is not None:
            opts["timeout"] = timeout
        if progress_callback is not None:
            opts["on_progress"] = progress_callback
        if metadata is not None:
            if metadata.resumption_token is not None:
                opts["resumption_token"] = metadata.resumption_token
            if metadata.on_resumption_token_update is not None:
                opts["on_resumption_token"] = metadata.on_resumption_token_update
        raw = await self._dispatcher.send_raw_request(method, data.get("params"), opts)
        # Literal fallback covers pre-handshake and stateless; matches runner.py.
        version = self._negotiated_version or "2025-11-25"
        try:
            _methods.validate_server_result(method, version, raw)
        except KeyError:
            pass
        if isinstance(result_type, TypeAdapter):
            return result_type.validate_python(raw, by_name=False)
        return result_type.model_validate(raw, by_name=False)

    async def send_notification(self, notification: types.ClientNotification) -> None:
        """Send a one-way notification. Usable before entering the context manager.

        Fire-and-forget: after the connection has closed, the notification is
        dropped with a debug log instead of raising.
        """
        data = notification.model_dump(by_alias=True, mode="json", exclude_none=True)
        opts: CallOptions = {}
        self._stamp(data, opts)
        await self._dispatcher.notify(data["method"], data.get("params"), opts)

    def _build_capabilities(self) -> types.ClientCapabilities:
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
        return types.ClientCapabilities(sampling=sampling, elicitation=elicitation, experimental=None, roots=roots)

    async def initialize(self, protocol_version: str = LATEST_HANDSHAKE_VERSION) -> types.InitializeResult:
        if self._initialize_result is not None:
            return self._initialize_result
        result = await self.send_request(
            types.InitializeRequest(
                params=types.InitializeRequestParams(
                    protocol_version=protocol_version,
                    capabilities=self._build_capabilities(),
                    client_info=self._client_info,
                ),
            ),
            types.InitializeResult,
        )

        if result.protocol_version not in HANDSHAKE_PROTOCOL_VERSIONS:
            raise RuntimeError(f"Unsupported protocol version from the server: {result.protocol_version}")

        self.adopt(result)

        await self.send_notification(types.InitializedNotification())

        return result

    def adopt(self, result: types.InitializeResult | types.DiscoverResult) -> None:
        """Install negotiated state from a result the caller already holds (no wire traffic).

        Clears the opposite slot, so at most one of `initialize_result` /
        `discover_result` is ever non-None.

        Raises:
            RuntimeError: `result` is a `DiscoverResult` whose `supported_versions`
                shares nothing with this client's `MODERN_PROTOCOL_VERSIONS`.
        """
        if isinstance(result, types.DiscoverResult):
            # ordered oldest→newest via MODERN_PROTOCOL_VERSIONS
            mutual = [v for v in MODERN_PROTOCOL_VERSIONS if v in result.supported_versions]
            if not mutual:
                raise RuntimeError(
                    f"No mutually supported modern protocol version "
                    f"(server: {result.supported_versions}, client: {list(MODERN_PROTOCOL_VERSIONS)})"
                )
            client_info = self._client_info.model_dump(by_alias=True, mode="json", exclude_none=True)
            capabilities = self._build_capabilities().model_dump(by_alias=True, mode="json", exclude_none=True)
            self._stamp = _make_modern_stamp(mutual[-1], client_info, capabilities)
            self._discover_result = result
            self._initialize_result = None
            self._negotiated_version = mutual[-1]
        else:
            self._stamp = _make_handshake_stamp(result.protocol_version)
            self._initialize_result = result
            self._discover_result = None
            self._negotiated_version = result.protocol_version

    async def send_discover(self, version: str) -> dict[str, Any]:
        """Send a single ``server/discover`` at ``version`` and return the raw result dict.

        No retry, no ``adopt()``. The ``_meta`` envelope and the
        ``Mcp-Protocol-Version`` header are stamped at ``version`` so the
        server-side era router sees a coherent probe. Used by ``discover()`` and
        the connect-time auto-negotiation policy.

        Raises:
            MCPError: The server returned a JSON-RPC error, or the transport
                bounced the request at its own layer (a bare HTTP 4xx is
                synthesized into a JSON-RPC error by the transport).
        """
        client_info = self._client_info.model_dump(by_alias=True, mode="json", exclude_none=True)
        capabilities = self._build_capabilities().model_dump(by_alias=True, mode="json", exclude_none=True)
        request = types.DiscoverRequest(
            params=types.RequestParams(
                _meta={
                    PROTOCOL_VERSION_META_KEY: version,
                    CLIENT_INFO_META_KEY: client_info,
                    CLIENT_CAPABILITIES_META_KEY: capabilities,
                }
            )
        )
        data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        opts: CallOptions = {
            "timeout": DISCOVER_TIMEOUT_SECONDS,
            "cancel_on_abandon": False,
            "headers": {MCP_PROTOCOL_VERSION_HEADER: version, MCP_METHOD_HEADER: data["method"]},
        }
        return await self._dispatcher.send_raw_request(data["method"], data.get("params"), opts)

    async def discover(self) -> types.DiscoverResult:
        """Probe `server/discover` and adopt the result.

        Sends a single `server/discover` proposing the newest modern protocol
        version. On `UNSUPPORTED_PROTOCOL_VERSION` (-32022) the server's
        `supported` list is intersected with `MODERN_PROTOCOL_VERSIONS` and the
        probe is retried once at the highest mutual version. Any other error —
        including `METHOD_NOT_FOUND` (-32601) and `REQUEST_TIMEOUT` (-32001) —
        propagates; the legacy `initialize()` fallback is the caller's policy.

        Raises:
            MCPError: The server rejected `server/discover`, the probe timed
                out, or the -32022 retry found no mutual version / failed again.
            RuntimeError: `adopt()` found no mutual version in the returned
                `supported_versions`.
        """
        if self._discover_result is not None:
            return self._discover_result

        try:
            raw = await self.send_discover(LATEST_MODERN_VERSION)
        except MCPError as e:
            if e.code != UNSUPPORTED_PROTOCOL_VERSION:
                raise
            try:
                data = types.UnsupportedProtocolVersionErrorData.model_validate(e.error.data)
            except ValidationError:
                raise e from None
            # ordered oldest→newest via MODERN_PROTOCOL_VERSIONS
            mutual = [v for v in MODERN_PROTOCOL_VERSIONS if v in data.supported]
            if not mutual:
                raise
            raw = await self.send_discover(mutual[-1])

        result = types.DiscoverResult.model_validate(raw)
        self.adopt(result)
        return result

    @property
    def initialize_result(self) -> types.InitializeResult | None:
        """The server's InitializeResult. None unless `initialize()` ran (or was adopted)."""
        return self._initialize_result

    @property
    def discover_result(self) -> types.DiscoverResult | None:
        """The server's DiscoverResult. None unless `discover()` ran (or was adopted).

        Retained intact (supported_versions, ttl_ms, cache_scope) so callers
        can round-trip it as ``prior_discover=``.
        """
        return self._discover_result

    @property
    def protocol_version(self) -> str | None:
        """Negotiated protocol version. None until `initialize()`, `discover()`, or `adopt()`."""
        return self._negotiated_version

    @property
    def server_info(self) -> types.Implementation | None:
        """Server name/version. None until `initialize()`, `discover()`, or `adopt()`."""
        if self._discover_result is not None:
            return self._discover_result.server_info
        if self._initialize_result is not None:
            return self._initialize_result.server_info
        return None

    @property
    def server_capabilities(self) -> types.ServerCapabilities | None:
        """Server capabilities. None until `initialize()`, `discover()`, or `adopt()`."""
        if self._discover_result is not None:
            return self._discover_result.capabilities
        if self._initialize_result is not None:
            return self._initialize_result.capabilities
        return None

    @property
    def instructions(self) -> str | None:
        """Server-provided instructions text, if any."""
        if self._discover_result is not None:
            return self._discover_result.instructions
        if self._initialize_result is not None:
            return self._initialize_result.instructions
        return None

    async def send_ping(self, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        """Send a ping request."""
        return await self.send_request(types.PingRequest(params=types.RequestParams(_meta=meta)), types.EmptyResult)

    @deprecated(
        "Client-to-server progress is deprecated as of 2026-07-28; progress is server-to-client only.",
        category=MCPDeprecationWarning,
    )
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

    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
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

    @overload
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
        allow_input_required: Literal[False] = False,
    ) -> types.CallToolResult: ...

    @overload
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
        allow_input_required: bool,
    ) -> types.CallToolResult | types.InputRequiredResult: ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
        allow_input_required: bool = False,
    ) -> types.CallToolResult | types.InputRequiredResult:
        """Send a tools/call request with optional progress callback support.

        Args:
            input_responses: Responses to a prior `InputRequiredResult.input_requests`.
            request_state: Opaque state echoed from a prior `InputRequiredResult`.
            allow_input_required: When ``False`` (default), an `InputRequiredResult`
                from the server raises `RuntimeError`; when ``True``, it is returned
                so the caller can resolve the requests and retry.

        Raises:
            RuntimeError: If the server returns an `InputRequiredResult` and
                ``allow_input_required`` is ``False``.
        """

        result = await self.send_request(
            types.CallToolRequest(
                params=types.CallToolRequestParams(
                    name=name,
                    arguments=arguments,
                    input_responses=input_responses,
                    request_state=request_state,
                    _meta=meta,
                ),
            ),
            _CallToolResultAdapter,
            request_read_timeout_seconds=read_timeout_seconds,
            progress_callback=progress_callback,
        )

        if isinstance(result, types.CallToolResult) and not result.is_error:
            await self._validate_tool_result(name, result)

        if isinstance(result, types.InputRequiredResult) and not allow_input_required:
            raise RuntimeError(
                "Server returned InputRequiredResult; pass allow_input_required=True to receive it "
                "and retry call_tool(..., input_responses=..., request_state=result.request_state)."
            )
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

        if self._negotiated_version in MODERN_PROTOCOL_VERSIONS:
            # 2026-07-28: clients MUST drop tools whose x-mcp-header annotations are invalid.
            kept: list[types.Tool] = []
            for tool in result.tools:
                if (reason := find_invalid_x_mcp_header(tool.input_schema)) is not None:
                    logger.warning("dropping tool %r: invalid x-mcp-header (%s)", tool.name, reason)
                    continue
                kept.append(tool)
            result.tools = kept

        # Cache tool output schemas for future validation
        # Note: don't clear the cache, as we may be using a cursor
        for tool in result.tools:
            self._tool_output_schemas[tool.name] = tool.output_schema

        return result

    @deprecated("The roots capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def send_roots_list_changed(self) -> None:
        """Send a roots/list_changed notification."""
        await self.send_notification(types.RootsListChangedNotification())

    async def _on_request(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        """Answer a server-initiated request via the registered callbacks."""
        # Literal, not LATEST_PROTOCOL_VERSION: the fallback covers the initialize
        # handshake (which only exists at <=2025) and stateless until the header
        # is plumbed; its meaning is fixed regardless of LATEST bumps.
        version = self._negotiated_version or "2025-11-25"
        try:
            request = cast(types.ServerRequest, _methods.parse_server_request(method, version, params))
        except KeyError:
            raise MCPError(code=METHOD_NOT_FOUND, message="Method not found", data=method) from None

        response: types.ClientResult | types.ErrorData
        if isinstance(request, types.PingRequest):
            # Answered without a context: ping has no callback that would need one.
            response = types.EmptyResult()
        else:
            assert dctx.request_id is not None  # the callback-driving dispatchers always assign ids
            ctx = ClientRequestContext(
                session=self, request_id=dctx.request_id, meta=request.params.meta if request.params else None
            )
            match request:
                case types.CreateMessageRequest(params=sampling_params):
                    response = await self._sampling_callback(ctx, sampling_params)
                case types.ElicitRequest(params=elicit_params):
                    response = await self._elicitation_callback(ctx, elicit_params)
                case types.ListRootsRequest():  # pragma: no branch
                    response = await self._list_roots_callback(ctx)
        client_response = ClientResponse.validate_python(response)
        if isinstance(client_response, types.ErrorData):
            raise MCPError.from_error_data(client_response)
        dumped = client_response.model_dump(by_alias=True, mode="json", exclude_none=True)
        try:
            _methods.validate_client_result(method, version, dumped)
        except ValidationError:
            logger.exception("client callback for %r returned an invalid result", method)
            raise MCPError(code=INTERNAL_ERROR, message="Client callback returned an invalid result") from None
        return dumped

    async def _on_notify(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> None:
        """Route a server notification: validate, run the typed callback, tee to message_handler."""
        # Same fallback as `_on_request`: covers pre-handshake and stateless.
        version = self._negotiated_version or "2025-11-25"
        try:
            notification = cast(types.ServerNotification, _methods.parse_server_notification(method, version, params))
        except KeyError:
            logger.debug("dropped %r: not defined at %s", method, version)
            return
        except ValidationError:
            logger.warning("Failed to validate notification: %s", method, exc_info=True)
            return
        if isinstance(notification, types.CancelledNotification):
            # The dispatcher already applied the cancellation; not surfaced to message_handler.
            return
        try:
            if isinstance(notification, types.LoggingMessageNotification):
                await self._logging_callback(notification.params)
            await self._message_handler(notification)
        except Exception:
            # Contain here, not in the dispatcher: DirectDispatcher awaits this
            # handler inline in the peer's notify() call, so a raising callback
            # would otherwise fail the peer's send. A raising logging_callback
            # skips the message_handler tee for that notification (v1 parity).
            logger.exception("notification callback for %r raised", method)

    async def _on_stream_exception(self, exc: Exception) -> None:
        """Deliver a transport-level fault to message_handler via a spawned task.

        Running the handler inline would park the dispatcher's read loop and
        deadlock handlers that await session I/O.
        """
        assert self._task_group is not None
        self._task_group.start_soon(self._deliver_stream_exception, exc)

    async def _deliver_stream_exception(self, exc: Exception) -> None:
        try:
            await self._message_handler(exc)
        except Exception:
            logger.exception("message_handler raised on transport exception")
