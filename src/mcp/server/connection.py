"""`Connection` - per-client connection state and the standalone outbound channel.

Always present on `Context` (never `None`), even in stateless deployments.
Holds peer info, per-connection scratch `state` and an `exit_stack` for
teardown, and an `Outbound` for the standalone stream (the SSE GET stream in
streamable HTTP, or the single duplex stream in stdio).

Construct via the factories: `Connection.from_envelope` for the 2026-era
single-exchange path (born ready, no back-channel) and `Connection.for_loop`
for the handshake-driven loop path. Both populate `protocol_version` so the
kernel reads it as a fact.

`notify` is best-effort: it never raises. If there's no standalone channel
or the stream has been dropped, the notification is debug-logged and silently
discarded - server-initiated notifications are inherently advisory.
`send_raw_request` raises `NoBackChannelError` when there's no channel; `ping`
is the only spec-sanctioned standalone request.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import AsyncExitStack
from typing import Any, TypeVar, overload

import anyio
from pydantic import BaseModel
from typing_extensions import deprecated

from mcp.shared.dispatcher import CallOptions, Outbound
from mcp.shared.exceptions import MCPDeprecationWarning, NoBackChannelError
from mcp.shared.peer import Meta, dump_params
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    CreateMessageRequest,
    CreateMessageResult,
    ElicitRequest,
    ElicitResult,
    EmptyResult,
    Implementation,
    InitializeRequestParams,
    ListRootsRequest,
    ListRootsResult,
    LoggingLevel,
    PingRequest,
    Request,
)
from mcp.types import methods as _methods

__all__ = ["Connection"]

logger = logging.getLogger(__name__)

ResultT = TypeVar("ResultT", bound=BaseModel)

# Result types for the spec's server-to-client request set, used by
# `Connection.send_request` to infer the result type. If the spec's request
# set grows substantially, consider declaring the result mapping on the
# request types themselves (a `__mcp_result__` ClassVar read via a structural
# protocol) so this table and the overload ladder don't need maintaining.
_RESULT_FOR: dict[type[Request[Any, Any]], type[BaseModel]] = {
    CreateMessageRequest: CreateMessageResult,
    ElicitRequest: ElicitResult,
    ListRootsRequest: ListRootsResult,
    PingRequest: EmptyResult,
}


def _notification_params(payload: dict[str, Any] | None, meta: Meta | None) -> dict[str, Any] | None:
    if not meta:
        return payload
    out = dict(payload or {})
    out["_meta"] = meta
    return out


class _NoChannelOutbound:
    """Connection-scoped `Outbound` for the no-back-channel case.

    The structural answer to "this connection cannot push to its peer":
    `send_raw_request` raises `NoBackChannelError`; `notify` drops with a
    debug log. `Connection.from_envelope` installs this so the modern
    single-exchange path never needs a mode flag - the channel itself says no.
    """

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        raise NoBackChannelError(method)

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        logger.debug("dropped %s: no standalone channel", method)


_NO_CHANNEL = _NoChannelOutbound()


class Connection:
    """Per-client connection state and standalone-stream `Outbound`.

    Construct via `from_envelope` (modern single-exchange: born ready, no
    back-channel) or `for_loop` (handshake-driven: ready once the client's
    `notifications/initialized` arrives). Either way `protocol_version` is
    populated at construction.
    """

    outbound: Outbound
    """The connection-scoped channel for server-initiated messages."""

    session_id: str | None

    client_params: InitializeRequestParams | None
    """The full `initialize` request params, or the equivalent built from the
    2026-era envelope. `None` when no client info was supplied."""

    protocol_version: str
    """The protocol version this connection speaks. Populated at construction
    by the factory and overwritten by `_handle_initialize` once the handshake
    commits on the loop path."""

    initialized: anyio.Event
    """Set when `notifications/initialized` arrives (matches TS `oninitialized`);
    the point from which the spec permits server-initiated requests beyond
    ping/logging. Pre-set on connections built via `from_envelope`."""

    state: dict[str, Any]
    """Per-connection scratch state; persists across requests on this connection."""

    exit_stack: AsyncExitStack
    """Per-connection teardown, unwound LIFO (shielded) when the connection
    closes. Push cleanup from handlers or middleware; exceptions are logged
    and swallowed."""

    def __init__(
        self,
        outbound: Outbound,
        *,
        protocol_version: str,
        session_id: str | None = None,
        client_params: InitializeRequestParams | None = None,
    ) -> None:
        self.outbound = outbound
        self.protocol_version = protocol_version
        self.session_id = session_id
        self.client_params = client_params
        self.initialized = anyio.Event()
        self.state = {}
        self.exit_stack = AsyncExitStack()

    @classmethod
    def from_envelope(
        cls,
        protocol_version: str,
        client_info: Implementation | None,
        client_capabilities: ClientCapabilities | None,
        *,
        outbound: Outbound = _NO_CHANNEL,
    ) -> Connection:
        """A born-ready connection populated from a request's `_meta` envelope.

        `initialized` is set and the envelope's client info/capabilities (when
        both supplied) are recorded as `client_params` so capability checks
        work. `outbound` defaults to the no-channel sentinel for the
        single-exchange HTTP path; duplex modern transports (e.g. stdio) pass
        the dispatcher so server-initiated messages have a back-channel.
        """
        client_params = None
        if client_info is not None and client_capabilities is not None:
            client_params = InitializeRequestParams(
                protocol_version=protocol_version,
                capabilities=client_capabilities,
                client_info=client_info,
            )
        connection = cls(outbound, protocol_version=protocol_version, client_params=client_params)
        connection.initialized.set()
        return connection

    @classmethod
    def for_loop(
        cls,
        outbound: Outbound,
        *,
        session_id: str | None = None,
        protocol_version_hint: str | None = None,
    ) -> Connection:
        """A connection for the handshake-driven loop path.

        Not born-ready: `initialized` is set later by the kernel when
        `notifications/initialized` arrives. `protocol_version` is seeded from
        the transport hint (or `LATEST_PROTOCOL_VERSION`) so it's never `None`;
        the handshake overwrites it once negotiated.
        """
        return cls(
            outbound,
            protocol_version=protocol_version_hint if protocol_version_hint is not None else LATEST_PROTOCOL_VERSION,
            session_id=session_id,
        )

    @property
    def has_standalone_channel(self) -> bool:
        """Whether this connection has a real back-channel for server-initiated
        messages. Derived from `outbound` - the no-channel sentinel is the only
        case that doesn't."""
        return self.outbound is not _NO_CHANNEL

    @property
    def initialize_accepted(self) -> bool:
        """True once the inbound request gate is open: `initialize` recorded the
        peer info, or the handshake completed outright (born-ready, or a bare
        `notifications/initialized`). Derived, never stored."""
        return self.client_params is not None or self.initialized.is_set()

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        """Send a raw request on the standalone stream.

        Low-level `Outbound` channel. Prefer the typed `send_request` or the
        convenience methods below; use this directly only for off-spec
        messages. `opts` carries per-call `timeout` / `on_progress` /
        resumption hints; see `CallOptions`.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: `has_standalone_channel` is `False`.
        """
        return await self.outbound.send_raw_request(method, params, opts)

    @overload
    async def send_request(
        self, req: CreateMessageRequest, *, opts: CallOptions | None = None
    ) -> CreateMessageResult: ...
    @overload
    async def send_request(self, req: ElicitRequest, *, opts: CallOptions | None = None) -> ElicitResult: ...
    @overload
    async def send_request(self, req: ListRootsRequest, *, opts: CallOptions | None = None) -> ListRootsResult: ...
    @overload
    async def send_request(self, req: PingRequest, *, opts: CallOptions | None = None) -> EmptyResult: ...
    @overload
    async def send_request(
        self, req: Request[Any, Any], *, result_type: type[ResultT], opts: CallOptions | None = None
    ) -> ResultT: ...
    async def send_request(
        self,
        req: Request[Any, Any],
        *,
        result_type: type[BaseModel] | None = None,
        opts: CallOptions | None = None,
    ) -> BaseModel:
        """Send a typed server-to-client request and return its typed result.

        For spec request types the result type is inferred. For custom requests
        pass `result_type=` explicitly.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests.
            pydantic.ValidationError: The peer's result does not match the expected result type.
            KeyError: `result_type` omitted for a non-spec request type.
        """
        raw = await self.send_raw_request(req.method, dump_params(req.params), opts)
        if req.method in _methods.MONOLITH_REQUESTS:
            try:
                _methods.validate_client_result(req.method, self.protocol_version, raw)
            except KeyError:
                pass
        cls = result_type if result_type is not None else _RESULT_FOR[type(req)]
        return cls.model_validate(raw, by_name=False)

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        """Send a best-effort notification on the standalone stream.

        Never raises. If there's no standalone channel or the stream is broken,
        the notification is dropped and debug-logged.
        """
        try:
            await self.outbound.notify(method, params)
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            logger.debug("dropped %s: standalone stream closed", method)

    async def ping(self, *, meta: Meta | None = None, opts: CallOptions | None = None) -> None:
        """Send a `ping` request on the standalone stream.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: `has_standalone_channel` is `False`.
        """
        await self.send_raw_request("ping", dump_params(None, meta), opts)

    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def log(self, level: LoggingLevel, data: Any, logger: str | None = None, *, meta: Meta | None = None) -> None:
        """Send a `notifications/message` log entry on the standalone stream. Best-effort."""
        params: dict[str, Any] = {"level": level, "data": data}
        if logger is not None:
            params["logger"] = logger
        await self.notify("notifications/message", _notification_params(params, meta))

    async def send_tool_list_changed(self, *, meta: Meta | None = None) -> None:
        await self.notify("notifications/tools/list_changed", _notification_params(None, meta))

    async def send_prompt_list_changed(self, *, meta: Meta | None = None) -> None:
        await self.notify("notifications/prompts/list_changed", _notification_params(None, meta))

    async def send_resource_list_changed(self, *, meta: Meta | None = None) -> None:
        await self.notify("notifications/resources/list_changed", _notification_params(None, meta))

    async def send_resource_updated(self, uri: str, *, meta: Meta | None = None) -> None:
        await self.notify("notifications/resources/updated", _notification_params({"uri": uri}, meta))

    def check_capability(self, capability: ClientCapabilities) -> bool:
        """Return whether the connected client declared the given capability.

        Returns `False` when no client info has been recorded.
        """
        # TODO(L53): redesign - mirrors v1 ServerSession.check_client_capability
        # verbatim for parity.
        if self.client_params is None:
            return False
        have = self.client_params.capabilities
        if capability.roots is not None:
            if have.roots is None:
                return False
            if capability.roots.list_changed and not have.roots.list_changed:
                return False
        if capability.sampling is not None:
            if have.sampling is None:
                return False
            if capability.sampling.context is not None and have.sampling.context is None:
                return False
            if capability.sampling.tools is not None and have.sampling.tools is None:
                return False
        if capability.elicitation is not None and have.elicitation is None:
            return False
        if capability.experimental is not None:
            if have.experimental is None:
                return False
            for k, v in capability.experimental.items():
                if k not in have.experimental or have.experimental[k] != v:
                    return False
        return True
