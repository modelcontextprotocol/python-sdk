"""`Connection` - per-client connection state and the standalone outbound channel.

Always present on `Context`, even in stateless deployments: peer info,
per-connection `state`, an `exit_stack` for teardown, and an `Outbound` for
the standalone stream. Construct via `Connection.from_envelope` (modern
single-exchange path) or `Connection.for_loop` (handshake-driven loop path).
`notify` is best-effort and never raises; `send_raw_request` raises
`NoBackChannelError` when there is no channel.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import AsyncExitStack
from typing import Any, TypeVar, overload

import anyio
from mcp_types import (
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
from mcp_types import methods as _methods
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from pydantic import BaseModel, ValidationError
from typing_extensions import deprecated

from mcp.shared.dispatcher import CallOptions, Outbound
from mcp.shared.exceptions import MCPDeprecationWarning, NoBackChannelError
from mcp.shared.peer import Meta, dump_params

__all__ = ["Connection"]

logger = logging.getLogger(__name__)

ResultT = TypeVar("ResultT", bound=BaseModel)

# Result types for the spec's server-to-client request set; `send_request` infers from this.
_RESULT_FOR: dict[type[Request[Any, Any]], type[BaseModel]] = {
    CreateMessageRequest: CreateMessageResult,
    ElicitRequest: ElicitResult,
    ListRootsRequest: ListRootsResult,
    PingRequest: EmptyResult,
}


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _typed(model: type[_ModelT], raw: Any) -> _ModelT | None:
    """Validate a raw envelope value into `model`; `None` when missing or mis-shaped, so the request still routes."""
    try:
        return model.model_validate(raw, by_name=False)
    except ValidationError:
        return None


def _notification_params(payload: dict[str, Any] | None, meta: Meta | None) -> dict[str, Any] | None:
    if not meta:
        return payload
    out = dict(payload or {})
    out["_meta"] = meta
    return out


class _NoChannelOutbound:
    """Connection-scoped `Outbound` for the no-back-channel case: `send_raw_request`
    raises `NoBackChannelError`; `notify` drops with a debug log."""

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        raise NoBackChannelError(method)

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        logger.debug("dropped %s: no standalone channel", method)


_NO_CHANNEL = _NoChannelOutbound()


class NotifyOnlyOutbound(_NoChannelOutbound):
    """Connection-scoped `Outbound` for modern (2026-07-28+) duplex-stream connections:
    forwards notifications, refuses server-initiated requests (the protocol forbids them)."""

    def __init__(self, outbound: Outbound) -> None:
        self._outbound = outbound

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        await self._outbound.notify(method, params, opts)


class Connection:
    """Per-client connection state and standalone-stream `Outbound`.

    Construct via `from_envelope` (born ready) or `for_loop` (handshake-driven);
    `protocol_version` is populated at construction.
    """

    outbound: Outbound
    """The connection-scoped channel for server-initiated messages."""

    session_id: str | None

    client_capabilities: ClientCapabilities | None
    """The capabilities the peer declared: the handshake's on the loop path,
    the request envelope's on the modern path. `None` when none were declared.
    Kept in lockstep with `client_params` by its setter, and settable on its
    own for the modern envelope, where capabilities are required but client
    info is optional (spec PR #3002) - capability checks must not depend on the
    peer having identified itself."""

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
        self.client_capabilities = None
        self.client_params = client_params
        self.initialized = anyio.Event()
        self.state = {}
        self.exit_stack = AsyncExitStack()

    @property
    def client_params(self) -> InitializeRequestParams | None:
        """The full `initialize` request params, or the equivalent built from the
        2026-era envelope. `None` when no client info was supplied."""
        return self._client_params

    @client_params.setter
    def client_params(self, value: InitializeRequestParams | None) -> None:
        # Assignment is the sync point: recording full client params (the
        # handshake commit, or a modern envelope carrying client info) also
        # records the capabilities fact, so the two can never drift. Clearing
        # to `None` leaves `client_capabilities` alone - the modern envelope
        # declares capabilities without client info.
        self._client_params = value
        if value is not None:
            self.client_capabilities = value.capabilities

    @classmethod
    def from_envelope(
        cls,
        protocol_version: str,
        client_info: Any,
        client_capabilities: Any,
        *,
        outbound: Outbound = _NO_CHANNEL,
    ) -> Connection:
        """A born-ready connection populated from a request's `_meta` envelope.

        `protocol_version` must already be validated. Well-formed
        `client_capabilities` are recorded as `client_capabilities` (client info
        is optional per spec PR #3002, so capability checks never depend on it),
        and the full `client_params` is additionally synthesized when
        well-formed `client_info` was supplied too; mis-shaped values are
        treated as not supplied. `outbound` defaults to the no-channel
        sentinel; duplex modern transports pass a notify-only wrapper.
        """
        info = _typed(Implementation, client_info)
        capabilities = _typed(ClientCapabilities, client_capabilities)
        client_params = None
        if info is not None and capabilities is not None:
            client_params = InitializeRequestParams(
                protocol_version=protocol_version,
                capabilities=capabilities,
                client_info=info,
            )
        connection = cls(outbound, protocol_version=protocol_version, client_params=client_params)
        connection.client_capabilities = capabilities
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
        """A connection for the handshake-driven loop path: not born-ready;
        `protocol_version` is seeded from the hint (or `LATEST_HANDSHAKE_VERSION`)
        until the handshake overwrites it."""
        return cls(
            outbound,
            protocol_version=protocol_version_hint if protocol_version_hint is not None else LATEST_HANDSHAKE_VERSION,
            session_id=session_id,
        )

    @property
    def has_standalone_channel(self) -> bool:
        """Whether this connection has a real channel for server-initiated messages
        (`False` only for the no-channel sentinel). Presence, not request permission:
        a modern duplex connection has a channel yet refuses server-initiated requests."""
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
        """Send a raw request on the standalone stream (low-level `Outbound`; prefer `send_request`).

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests
                (`has_standalone_channel` is `False`, or a modern connection).
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

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        """Send a best-effort notification on the standalone stream.

        Never raises. If there's no standalone channel or the stream is broken,
        the notification is dropped and debug-logged.
        """
        try:
            await self.outbound.notify(method, params, opts)
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            logger.debug("dropped %s: standalone stream closed", method)

    async def ping(self, *, meta: Meta | None = None, opts: CallOptions | None = None) -> None:
        """Send a `ping` request on the standalone stream.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: No back-channel for server-initiated requests
                (`has_standalone_channel` is `False`, or a modern connection).
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

        Returns `False` when no capabilities have been recorded.
        """
        # TODO(L53): redesign - mirrors v1 ServerSession.check_client_capability
        # verbatim for parity.
        if self.client_capabilities is None:
            return False
        have = self.client_capabilities
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
        if capability.extensions is not None:
            # SEP-2133: presence of the identifier, not value equality, is the check.
            if have.extensions is None:
                return False
            for identifier in capability.extensions:
                if identifier not in have.extensions:
                    return False
        return True
