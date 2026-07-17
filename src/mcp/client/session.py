from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from operator import or_
from types import TracebackType
from typing import Annotated, Any, Final, Literal, Protocol, cast, overload

import anyio
import anyio.abc
import anyio.lowlevel
import mcp_types as types
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    CONNECTION_CLOSED,
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
from pydantic import BaseModel, Discriminator, Tag, TypeAdapter, ValidationError
from typing_extensions import Self, TypeVar, deprecated

from mcp.client._transport import ReadStream, WriteStream
from mcp.client.extension import NotificationBinding, ResultClaim, UnexpectedClaimedResult
from mcp.client.subscriptions import ListenRoute
from mcp.shared._compat import resync_tracer
from mcp.shared.dispatcher import CallOptions, DispatchContext, Dispatcher, ProgressFnT, as_request_id
from mcp.shared.exceptions import MCPDeprecationWarning, MCPError
from mcp.shared.inbound import (
    MCP_METHOD_HEADER,
    MCP_NAME_HEADER,
    MCP_PROTOCOL_VERSION_HEADER,
    NAME_BEARING_METHODS,
    encode_header_value,
    find_invalid_x_mcp_header,
    mcp_param_headers,
    x_mcp_header_map,
)
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher, cancelled_request_id_from_params
from mcp.shared.message import ClientMessageMetadata, SessionMessage
from mcp.shared.session import RequestResponder
from mcp.shared.subscriptions import SUBSCRIPTION_ID_META_KEY, event_from_wire
from mcp.shared.transport_context import TransportContext

DEFAULT_CLIENT_INFO = types.Implementation(name="mcp", version="0.1.0")
DISCOVER_TIMEOUT_SECONDS = 10.0
_NOTIFICATION_QUEUE_SIZE: Final = 256

logger = logging.getLogger("client")


def _clamp_inbound_ttl(raw: dict[str, Any]) -> None:
    """Floor a negative inbound `ttlMs` to 0 before `ge=0` validation fails the call (2026-07-28 caching SHOULD)."""
    ttl = raw.get("ttlMs")
    if isinstance(ttl, int | float) and not isinstance(ttl, bool) and ttl < 0:
        raw["ttlMs"] = 0


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
    protocol_version: str,
    client_info: dict[str, Any],
    capabilities: dict[str, Any],
    resolve_param_headers: Callable[[str, Mapping[str, Any]], dict[str, str]],
) -> Callable[[dict[str, Any], CallOptions], None]:
    def stamp(data: dict[str, Any], opts: CallOptions) -> None:
        params = data.setdefault("params", {})
        meta = params.setdefault("_meta", {})
        meta[PROTOCOL_VERSION_META_KEY] = protocol_version
        meta[CLIENT_INFO_META_KEY] = client_info
        meta[CLIENT_CAPABILITIES_META_KEY] = capabilities
        # `cancel_on_abandon` stays at the dispatcher default (True): the
        # courtesy `notifications/cancelled` is the abandon signal. On the
        # stream transports it is the 2026 wire's cancellation spelling; the
        # streamable-HTTP transport translates it into aborting the request's
        # own POST instead of writing it (the 2026 HTTP wire has no
        # client-to-server notifications - closing the stream is the signal).
        # The negotiation methods still opt out, mirroring `_preconnect_stamp`:
        # the spec forbids cancelling them.
        if data["method"] in ("initialize", "server/discover"):
            opts["cancel_on_abandon"] = False
        headers = opts.setdefault("headers", {})
        headers[MCP_PROTOCOL_VERSION_HEADER] = protocol_version
        headers[MCP_METHOD_HEADER] = data["method"]
        name_key = NAME_BEARING_METHODS.get(data["method"])
        if name_key is not None and isinstance(name := params.get(name_key), str):
            headers[MCP_NAME_HEADER] = encode_header_value(name)
        if data["method"] == "tools/call" and isinstance(name := params.get("name"), str):
            headers.update(resolve_param_headers(name, params.get("arguments") or {}))

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

# Typed against the wide parse union so adopt-built claim adapters share this attribute type.
_CallToolResultAdapter: TypeAdapter[types.CallToolResult | types.InputRequiredResult | types.Result] = TypeAdapter(
    types.CallToolResult | types.InputRequiredResult
)
_GetPromptResultAdapter: TypeAdapter[types.GetPromptResult | types.InputRequiredResult] = TypeAdapter(
    types.GetPromptResult | types.InputRequiredResult
)
_ReadResourceResultAdapter: TypeAdapter[types.ReadResourceResult | types.InputRequiredResult] = TypeAdapter(
    types.ReadResourceResult | types.InputRequiredResult
)


def _claim_active(claim: ResultClaim[Any], version: str) -> bool:
    """A claim is active at modern versions only, narrowed by its optional version subset."""
    return version in MODERN_PROTOCOL_VERSIONS and (
        claim.protocol_versions is None or version in claim.protocol_versions
    )


def _active_claims_at(
    claims_by_extension: Mapping[str, tuple[ResultClaim[Any], ...]], version: str
) -> dict[str, ResultClaim[Any]]:
    """Claims active at `version`, keyed by wire tag; empty at any legacy version."""
    return {
        claim.result_type: claim
        for claims in claims_by_extension.values()
        for claim in claims
        if _claim_active(claim, version)
    }


def _build_call_tool_adapter(
    active: Mapping[str, ResultClaim[Any]],
) -> TypeAdapter[types.CallToolResult | types.InputRequiredResult | types.Result]:
    """Build a discriminated tools/call adapter: a core arm plus one arm per active claim."""
    if not active:
        return _CallToolResultAdapter
    tags = frozenset(active)
    core_arm = "core"
    while core_arm in tags:  # the routing sentinel must never collide with a claimed tag
        core_arm += "-"

    def _route(value: Any) -> str:
        # pydantic hands the discriminator either the raw dict or an already-built model.
        # Unknown or non-string tags route to the core arm and fail core validation there.
        if isinstance(value, dict):
            tag = cast("dict[str, Any]", value).get("resultType")
        else:
            tag = getattr(value, "result_type", None)
        return tag if isinstance(tag, str) and tag in tags else core_arm

    arms: list[Any] = [Annotated[types.CallToolResult | types.InputRequiredResult, Tag(core_arm)]]
    arms += [Annotated[claim.model, Tag(tag)] for tag, claim in active.items()]
    # reduce(or_) rather than Union star-unpack, which needs py3.11+.
    return TypeAdapter(Annotated[reduce(or_, arms), Discriminator(_route)])


def _index_claims(
    result_claims: Mapping[str, Sequence[ResultClaim[Any]]] | None,
    extensions: dict[str, dict[str, Any]] | None,
) -> dict[str, tuple[ResultClaim[Any], ...]]:
    """Validate and copy the claims-by-extension mapping."""
    indexed: dict[str, tuple[ResultClaim[Any], ...]] = {}
    seen: set[str] = set()
    for identifier, claims in (result_claims or {}).items():
        if extensions is None or identifier not in extensions:
            raise ValueError(
                f"result_claims key {identifier!r} has no extensions entry; a claim is only "
                "advertised through its extension's capability ad"
            )
        if not claims:
            raise ValueError(
                f"result_claims[{identifier!r}] is empty and would drop the extension from "
                "the capability ad at every version. Omit the key instead"
            )
        for claim in claims:
            if claim.result_type in seen:
                raise ValueError(f"duplicate result claim for resultType {claim.result_type!r}")
            seen.add(claim.result_type)
        indexed[identifier] = tuple(claims)
    return indexed


def _index_bindings(
    notification_bindings: Sequence[NotificationBinding[Any]] | None,
) -> dict[str, NotificationBinding[Any]]:
    """Index bindings by wire method, rejecting duplicates."""
    indexed: dict[str, NotificationBinding[Any]] = {}
    for binding in notification_bindings or ():
        if binding.method in indexed:
            raise ValueError(f"duplicate notification binding for method {binding.method!r}")
        indexed[binding.method] = binding
    return indexed


def _input_required_unexpected(method: str) -> RuntimeError:
    return RuntimeError(
        "Server returned InputRequiredResult; pass allow_input_required=True to receive it "
        f"and retry {method}(..., input_responses=..., request_state=result.request_state)."
    )


class ClientSession:
    """Client half of an MCP connection, running on a `Dispatcher`.

    Construct it over a transport's stream pair (or pass a pre-built
    `dispatcher=`), enter as an async context manager, then call
    `initialize()`. The dispatcher owns the receive loop and request
    correlation; this class owns the typed MCP layer and the constructor
    callbacks. Transport `Exception` items reach `message_handler` only when
    the session builds its own dispatcher from a stream pair.

    Extension `result_claims` fold into tools/call parsing at `adopt()`;
    `notification_bindings` observe vendor notifications via bounded FIFOs.
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
        extensions: dict[str, dict[str, Any]] | None = None,
        result_claims: Mapping[str, Sequence[ResultClaim[Any]]] | None = None,
        notification_bindings: Sequence[NotificationBinding[Any]] | None = None,
        dispatcher: Dispatcher[Any] | None = None,
    ) -> None:
        self._session_read_timeout_seconds = read_timeout_seconds
        self._client_info = client_info or DEFAULT_CLIENT_INFO
        self._sampling_callback = sampling_callback or _default_sampling_callback
        self._sampling_capabilities = sampling_capabilities
        self._extensions = dict(extensions) if extensions is not None else None
        self._result_claims = _index_claims(result_claims, extensions)
        self._notification_bindings = _index_bindings(notification_bindings)
        self._active_claims: dict[str, ResultClaim[Any]] = {}
        self._call_tool_adapter = _CallToolResultAdapter
        self._binding_queues: dict[
            str, tuple[MemoryObjectSendStream[BaseModel], MemoryObjectReceiveStream[BaseModel]]
        ] = {}
        self._elicitation_callback = elicitation_callback or _default_elicitation_callback
        self._list_roots_callback = list_roots_callback or _default_list_roots_callback
        self._logging_callback = logging_callback or _default_logging_callback
        self._message_handler = message_handler or _default_message_handler
        self._tool_output_schemas: dict[str, dict[str, Any] | None] = {}
        self._x_mcp_header_maps: dict[str, dict[tuple[str, ...], str]] = {}
        self._initialize_result: types.InitializeResult | None = None
        self._discover_result: types.DiscoverResult | None = None
        self._negotiated_version: str | None = None
        self._stamp: Callable[[dict[str, Any], CallOptions], None] = _preconnect_stamp
        self._task_group: anyio.abc.TaskGroup | None = None
        # subscriptions/listen demux routes; membership decides ack consumption (raw listens are never registered)
        self._listen_routes: dict[RequestId, ListenRoute] = {}
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
            # Queues must exist before the dispatcher starts: _on_notify enqueues into this dict.
            for binding in self._notification_bindings.values():
                send, receive = anyio.create_memory_object_stream[BaseModel](_NOTIFICATION_QUEUE_SIZE)
                self._binding_queues[binding.method] = (send, receive)
            await self._task_group.start(
                self._dispatcher.run, self._on_request, self._on_notify, self._intercept_notification
            )
            for binding in self._notification_bindings.values():
                _, receive = self._binding_queues[binding.method]
                self._task_group.start_soon(self._deliver_bound_notifications, binding, receive)
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
            try:
                await task_group.__aexit__(None, None, None)
            finally:
                self._close_binding_queues()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        # Exit must not block: cancel the dispatcher, binding consumers, and in-flight callbacks.
        assert self._task_group is not None
        self._task_group.cancel_scope.cancel()
        try:
            result = await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
        finally:
            self._close_binding_queues()
            self._settle_listen_routes_closed()
        await resync_tracer()
        return result

    def _close_binding_queues(self) -> None:
        # Unclosed memory object streams warn at garbage collection; close is idempotent.
        for send, receive in self._binding_queues.values():
            send.close()
            receive.close()
        self._binding_queues.clear()

    async def _deliver_bound_notifications(
        self, binding: NotificationBinding[Any], receive: MemoryObjectReceiveStream[BaseModel]
    ) -> None:
        """Consume one binding's FIFO, decoupled from the dispatcher so handlers can do session I/O."""
        while True:
            params = await receive.receive()
            try:
                await binding.handler(params)
            except Exception:
                # A raising handler costs only that delivery, as in _on_notify.
                logger.exception("notification binding handler for %r raised", binding.method)

    async def send_request(
        self,
        request: types.ClientRequest | types.Request[Any, Any],
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
            ValueError: The request declares `name_param` but its params carry no string name.
            pydantic.ValidationError: The server returned a result that does not
                conform to the negotiated protocol version.
        """
        data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        method: str = data["method"]
        opts: CallOptions = {}
        self._stamp(data, opts)
        # The stamp runs first, so its NAME_BEARING_METHODS rows win; a missing name fails loud.
        headers = opts.setdefault("headers", {})
        if (key := type(request).name_param) is not None and MCP_NAME_HEADER not in headers:
            params_data: dict[str, Any] = data.get("params") or {}
            name = params_data.get(key)
            if not isinstance(name, str):
                raise ValueError(f"{method} requires params[{key!r}] for Mcp-Name")
            headers[MCP_NAME_HEADER] = encode_header_value(name)
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
        _clamp_inbound_ttl(raw)
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

    def _build_capabilities(self, version: str) -> types.ClientCapabilities:
        """Build the capability ad for a wire speaking `version`.

        Claim-bearing identifiers whose claims are all inactive at `version` drop, so
        the client never advertises result shapes it would reject; claim-less
        identifiers always advertise.
        """
        extensions = self._extensions
        if extensions is not None and self._result_claims:
            extensions = {
                identifier: settings
                for identifier, settings in extensions.items()
                if identifier not in self._result_claims
                or any(_claim_active(claim, version) for claim in self._result_claims[identifier])
            } or None
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
        return types.ClientCapabilities(
            sampling=sampling, elicitation=elicitation, experimental=None, extensions=extensions, roots=roots
        )

    async def initialize(self) -> types.InitializeResult:
        if self._initialize_result is not None:
            return self._initialize_result
        result = await self.send_request(
            types.InitializeRequest(
                params=types.InitializeRequestParams(
                    protocol_version=LATEST_HANDSHAKE_VERSION,
                    # The handshake negotiates only legacy versions, where no claim is active.
                    capabilities=self._build_capabilities(LATEST_HANDSHAKE_VERSION),
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
            version = mutual[-1]
            client_info = self._client_info.model_dump(by_alias=True, mode="json", exclude_none=True)
            capabilities = self._build_capabilities(version).model_dump(by_alias=True, mode="json", exclude_none=True)
            self._stamp = _make_modern_stamp(version, client_info, capabilities, self._resolve_param_headers)
            self._discover_result = result
            self._initialize_result = None
        else:
            version = result.protocol_version
            self._stamp = _make_handshake_stamp(version)
            self._initialize_result = result
            self._discover_result = None
        self._negotiated_version = version
        # Both arms reach here, so re-adoption resets cleanly; legacy versions activate no claims.
        # Core-vocabulary tags are unconstructible (ResultClaim.__post_init__), so no exclusion needed.
        self._active_claims = _active_claims_at(self._result_claims, version)
        self._call_tool_adapter = _build_call_tool_adapter(self._active_claims)
        for method in self._notification_bindings:
            # Bindings are consulted only for methods core does not know, so this one can never fire.
            if (method, version) in _methods.SERVER_NOTIFICATIONS:
                logger.warning(
                    "notification binding for %r will never fire at %s: the core protocol defines this method",
                    method,
                    version,
                )

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
        capabilities = self._build_capabilities(version).model_dump(by_alias=True, mode="json", exclude_none=True)
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
        raw = await self._dispatcher.send_raw_request(data["method"], data.get("params"), opts)
        # Un-floored, a negative ttl fails the mode='auto' probe's validation and silently downgrades the handshake.
        _clamp_inbound_ttl(raw)
        return raw

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

    @overload
    async def read_resource(
        self,
        uri: str,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
        allow_input_required: Literal[False] = False,
    ) -> types.ReadResourceResult: ...

    @overload
    async def read_resource(
        self,
        uri: str,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
        allow_input_required: bool,
    ) -> types.ReadResourceResult | types.InputRequiredResult: ...

    async def read_resource(
        self,
        uri: str,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
        allow_input_required: bool = False,
    ) -> types.ReadResourceResult | types.InputRequiredResult:
        """Send a resources/read request.

        Args:
            input_responses: Responses to a prior `InputRequiredResult.input_requests`.
            request_state: Opaque state echoed from a prior `InputRequiredResult`.
            allow_input_required: When `False` (default), an `InputRequiredResult`
                from the server raises `RuntimeError`; when `True`, it is returned
                so the caller can resolve the requests and retry.

        Raises:
            RuntimeError: If the server returns an `InputRequiredResult` and
                `allow_input_required` is `False`.
        """
        result = await self.send_request(
            types.ReadResourceRequest(
                params=types.ReadResourceRequestParams(
                    uri=uri,
                    input_responses=input_responses,
                    request_state=request_state,
                    _meta=meta,
                ),
            ),
            _ReadResourceResultAdapter,
        )
        if isinstance(result, types.InputRequiredResult) and not allow_input_required:
            raise _input_required_unexpected("read_resource")
        return result

    @deprecated(
        "resources/subscribe is removed as of 2026-07-28; use Client.listen() instead.",
        category=MCPDeprecationWarning,
    )
    async def subscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        """Send a resources/subscribe request (2025-era servers only)."""
        return await self.send_request(
            types.SubscribeRequest(params=types.SubscribeRequestParams(uri=uri, _meta=meta)),
            types.EmptyResult,
        )

    @deprecated(
        "resources/unsubscribe is removed as of 2026-07-28; use Client.listen() instead.",
        category=MCPDeprecationWarning,
    )
    async def unsubscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> types.EmptyResult:
        """Send a resources/unsubscribe request (2025-era servers only)."""
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
        allow_claimed: Literal[False] = False,
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
        allow_claimed: Literal[False] = False,
    ) -> types.CallToolResult | types.InputRequiredResult: ...

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
        allow_claimed: bool,
    ) -> types.CallToolResult | types.Result: ...

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
        allow_claimed: bool,
    ) -> types.CallToolResult | types.InputRequiredResult | types.Result: ...

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
        allow_claimed: bool = False,
    ) -> types.CallToolResult | types.InputRequiredResult | types.Result:
        """Send a tools/call request with optional progress callback support.

        On a modern (2026-07-28) connection, arguments annotated with `x-mcp-header`
        in the tool's input schema are mirrored into `Mcp-Param-*` request headers.
        The annotations are read from the tool's last `list_tools` entry, so list
        the tool before calling it to enable header emission.

        Args:
            input_responses: Responses to a prior `InputRequiredResult.input_requests`.
            request_state: Opaque state echoed from a prior `InputRequiredResult`.
            allow_input_required: When ``False`` (default), an `InputRequiredResult`
                from the server raises `RuntimeError`; when ``True``, it is returned
                so the caller can resolve the requests and retry.
            allow_claimed: When `False` (default), a claimed extension result raises
                `UnexpectedClaimedResult`; when `True`, the parsed claim model is returned.

        Raises:
            RuntimeError: If the server returns an `InputRequiredResult` and
                ``allow_input_required`` is ``False``.
            UnexpectedClaimedResult: Claimed result with `allow_claimed` False; carries the parsed value.
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
            self._call_tool_adapter,
            request_read_timeout_seconds=read_timeout_seconds,
            progress_callback=progress_callback,
        )

        if isinstance(result, types.CallToolResult) and not result.is_error:
            await self.validate_tool_result(name, result)

        # The input_required arm stays first; a claimed shape is terminal for the multi-round-trip driver.
        if isinstance(result, types.InputRequiredResult) and not allow_input_required:
            raise _input_required_unexpected("call_tool")
        if not isinstance(result, types.CallToolResult | types.InputRequiredResult) and not allow_claimed:
            raise UnexpectedClaimedResult(result)
        return result

    def _resolve_param_headers(self, name: str, arguments: Mapping[str, Any]) -> dict[str, str]:
        """`Mcp-Param-*` headers for a `tools/call`, or empty when the tool was never listed."""
        header_map = self._x_mcp_header_maps.get(name)
        if header_map is None:
            return {}
        return mcp_param_headers(header_map, arguments)

    async def validate_tool_result(self, name: str, result: types.CallToolResult) -> None:
        """Revalidate a `CallToolResult` against the tool's declared output schema.

        Raises:
            RuntimeError: Structured content is missing or does not conform to the schema.
        """
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

    @overload
    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
        allow_input_required: Literal[False] = False,
    ) -> types.GetPromptResult: ...

    @overload
    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
        allow_input_required: bool,
    ) -> types.GetPromptResult | types.InputRequiredResult: ...

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
        allow_input_required: bool = False,
    ) -> types.GetPromptResult | types.InputRequiredResult:
        """Send a prompts/get request.

        Args:
            input_responses: Responses to a prior `InputRequiredResult.input_requests`.
            request_state: Opaque state echoed from a prior `InputRequiredResult`.
            allow_input_required: When `False` (default), an `InputRequiredResult`
                from the server raises `RuntimeError`; when `True`, it is returned
                so the caller can resolve the requests and retry.

        Raises:
            RuntimeError: If the server returns an `InputRequiredResult` and
                `allow_input_required` is `False`.
        """
        result = await self.send_request(
            types.GetPromptRequest(
                params=types.GetPromptRequestParams(
                    name=name,
                    arguments=arguments,
                    input_responses=input_responses,
                    request_state=request_state,
                    _meta=meta,
                ),
            ),
            _GetPromptResultAdapter,
        )
        if isinstance(result, types.InputRequiredResult) and not allow_input_required:
            raise _input_required_unexpected("get_prompt")
        return result

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
        complete = (params is None or params.cursor is None) and result.next_cursor is None
        return self._absorb_tool_listing(result, complete=complete)

    def _absorb_tool_listing(self, result: types.ListToolsResult, *, complete: bool) -> types.ListToolsResult:
        """Filter the listing per the 2026 x-mcp-header MUST and rebuild derived per-tool state, in place.

        Idempotent: cached values are already post-filter, so the response cache can re-absorb a served listing.
        `complete` (an uncursored single-page listing) prunes per-tool state down to the listing's tools.
        """
        if self._negotiated_version in MODERN_PROTOCOL_VERSIONS:
            # 2026-07-28: clients MUST drop tools whose x-mcp-header annotations are invalid.
            kept: list[types.Tool] = []
            for tool in result.tools:
                if (reason := find_invalid_x_mcp_header(tool.input_schema)) is not None:
                    logger.warning("dropping tool %r: invalid x-mcp-header (%s)", tool.name, reason)
                    # Evict any map cached from a prior valid listing so a stale entry can't
                    # mirror headers for a tool this listing dropped.
                    self._x_mcp_header_maps.pop(tool.name, None)
                    continue
                # Cache the arg→header map so a later tools/call mirrors it into Mcp-Param-* headers.
                self._x_mcp_header_maps[tool.name] = x_mcp_header_map(tool.input_schema)
                kept.append(tool)
            result.tools = kept

        # Cache tool output schemas for future validation; cursor pages only ever add.
        for tool in result.tools:
            self._tool_output_schemas[tool.name] = tool.output_schema

        if complete:
            # The listing is the full tool universe, so state for unlisted tools is stale
            # (the server dropped them, or a shared-cache writer's filter did).
            names = {tool.name for tool in result.tools}
            self._x_mcp_header_maps = {k: v for k, v in self._x_mcp_header_maps.items() if k in names}
            self._tool_output_schemas = {k: v for k, v in self._tool_output_schemas.items() if k in names}

        return result

    # ---------- Pagination-draining helpers ----------
    #
    # The single-page `list_*` methods return the server's first page plus a
    # `next_cursor`; callers who don't loop on the cursor silently get only
    # page zero. The four `list_all_*` helpers drain all pages and return a
    # flat list, so the common "give me everything" use case stops hiding
    # pagination behind what looks like a single call. The single-page
    # methods are unchanged.

    async def list_all_tools(self) -> list[types.Tool]:
        """Drain pagination across `tools/list` and return the full tool list.

        Each intermediate page flows through `list_tools` -> `_absorb_tool_listing`
        with `complete=False`, which populates per-tool cache state (`_x_mcp_header_maps`,
        `_tool_output_schemas`) as a pure addition. After the loop ends, the helper
        runs `_absorb_tool_listing` once more with `complete=True` on the merged
        result so state for tools that disappeared across pages (or were filtered
        by the per-page x-mcp-header MUST) is pruned to match the drained universe.
        The returned list reflects the post-filter view that the cache exposes.
        """
        tools: list[types.Tool] = []
        cursor: str | None = None
        while True:
            result = await self.list_tools(params=types.PaginatedRequestParams(cursor=cursor))
            tools.extend(result.tools)
            cursor = result.next_cursor
            if cursor is None:
                break
        # Final absorption pass with `complete=True` so the per-tool cache matches
        # the drained listing (prunes entries for tools no longer present).
        merged = types.ListToolsResult(tools=tools, next_cursor=None)
        absorbed = self._absorb_tool_listing(merged, complete=True)
        return absorbed.tools

    async def list_all_resources(self) -> list[types.Resource]:
        """Drain pagination across `resources/list` and return the full resource list."""
        items: list[types.Resource] = []
        cursor: str | None = None
        while True:
            result = await self.list_resources(params=types.PaginatedRequestParams(cursor=cursor))
            items.extend(result.resources)
            cursor = result.next_cursor
            if cursor is None:
                return items

    async def list_all_resource_templates(self) -> list[types.ResourceTemplate]:
        """Drain pagination across `resources/templates/list` and return the full template list."""
        templates: list[types.ResourceTemplate] = []
        cursor: str | None = None
        while True:
            result = await self.list_resource_templates(params=types.PaginatedRequestParams(cursor=cursor))
            templates.extend(result.resource_templates)
            cursor = result.next_cursor
            if cursor is None:
                return templates

    async def list_all_prompts(self) -> list[types.Prompt]:
        """Drain pagination across `prompts/list` and return the full prompt list."""
        items: list[types.Prompt] = []
        cursor: str | None = None
        while True:
            result = await self.list_prompts(params=types.PaginatedRequestParams(cursor=cursor))
            items.extend(result.prompts)
            cursor = result.next_cursor
            if cursor is None:
                return items

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
            response = await self.dispatch_input_request(ctx, request)
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

    async def dispatch_input_request(
        self, ctx: ClientRequestContext, request: types.InputRequest
    ) -> types.InputResponse | types.ErrorData:
        """Route an input request through the client's callback table.

        Shared by the legacy server→client RPC path (`_on_request`) and the
        2026-07-28 multi-round-trip driver, which dispatches the embedded
        `InputRequiredResult.input_requests` through the same callbacks.

        Returns the callback's `InputResponse`, or `ErrorData` when the callback declines.
        """
        match request:
            case types.CreateMessageRequest(params=p):
                return await self._sampling_callback(ctx, p)
            case types.ElicitRequest(params=p):
                return await self._elicitation_callback(ctx, p)
            case types.ListRootsRequest():  # pragma: no branch
                return await self._list_roots_callback(ctx)

    def _register_listen_route(self, request_id: RequestId) -> ListenRoute:
        """Create the demux route for a listen request id; the caller registers BEFORE sending."""
        route = ListenRoute()
        self._listen_routes[request_id] = route
        return route

    def _unregister_listen_route(self, request_id: RequestId) -> None:
        """Drop a listen route; the handle owns membership, so a missing key is a no-op."""
        self._listen_routes.pop(request_id, None)

    def _settle_listen_routes_closed(self) -> None:
        """Settle all open listen routes as lost on session exit; cancelled driver tasks cannot."""
        closed = MCPError(code=CONNECTION_CLOSED, message="Connection closed")
        for route in self._listen_routes.values():
            route.settle("lost", error=closed)
        self._listen_routes.clear()

    def _intercept_notification(self, method: str, params: Mapping[str, Any] | None) -> bool:
        """Wire-order listen demux, run synchronously on the dispatcher's receive path.

        Bookkeeping must advance in receive order with the listen result (resolved on
        this same path); the spawned `_on_notify` path would race it and drop events.
        Returns True to consume the frame: a live route's ack is driver state, never surfaced.
        """
        if not self._listen_routes:
            return False
        if method == "notifications/cancelled":
            request_id = cancelled_request_id_from_params(params)
            if request_id is not None and (listen_route := self._listen_routes.get(request_id)) is not None:
                # a server-sent cancel naming a listen request is that stream's teardown signal
                listen_route.settle("lost")
            return False  # _on_notify swallows every cancelled either way (v1 parity)
        if params is None:
            return False
        meta = params.get("_meta")
        if not isinstance(meta, Mapping):
            return False
        # as_request_id is not a tripwire: raw wire _meta can carry a non-id (even unhashable) value
        subscription_id = as_request_id(cast("Mapping[str, Any]", meta).get(SUBSCRIPTION_ID_META_KEY))
        if subscription_id is None or (listen_route := self._listen_routes.get(subscription_id)) is None:
            return False
        if method == "notifications/subscriptions/acknowledged":
            raw_filter = params.get("notifications")
            if raw_filter is None:
                # malformed, not an empty filter: leave it to the spawned path's validation warning
                return False
            try:
                honored = types.SubscriptionFilter.model_validate(raw_filter)
            except ValidationError:
                return False
            listen_route.set_acked(honored)
            return True
        if (event := event_from_wire(method, params)) is not None:
            listen_route.deliver(event)
        return False  # events (and any other stamped frame) still tee as usual

    async def _on_notify(
        self, dctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> None:
        """Route a server notification: validate, run the typed callback, tee to message_handler."""
        # Same fallback as `_on_request`: covers pre-handshake and stateless.
        version = self._negotiated_version or "2025-11-25"
        try:
            notification = cast(types.ServerNotification, _methods.parse_server_notification(method, version, params))
        except KeyError:
            # Only methods unknown to the negotiated version's core tables reach the bindings.
            binding = self._notification_bindings.get(method)
            if binding is None:
                logger.debug("dropped %r: not defined at %s", method, version)
                return
            try:
                bound_params = binding.params_type.model_validate(params or {})
            except ValidationError:
                logger.warning("Failed to validate notification: %s", method, exc_info=True)
                return
            send, receive = self._binding_queues[method]
            try:
                # Must not await: DirectDispatcher calls _on_notify inline; blocking deadlocks in-process servers.
                send.send_nowait(bound_params)
            except anyio.WouldBlock:
                # Evict the oldest event; no checkpoint since the failed send,
                # so the buffer is still full and the retry cannot block.
                receive.receive_nowait()
                logger.warning("notification queue for %r is full; dropped the oldest event", method)
                send.send_nowait(bound_params)
            return
        except ValidationError:
            logger.warning("Failed to validate notification: %s", method, exc_info=True)
            return
        if isinstance(notification, types.CancelledNotification):
            # Never surfaced (v1 parity): the dispatcher already applied it; listen cancels settled by the intercept.
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
