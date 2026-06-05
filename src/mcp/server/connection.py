"""`Connection` - per-client connection state and the standalone outbound channel.

Always present on `Context` (never `None`), even in stateless deployments.
Holds peer info populated at `initialize` time, per-connection scratch
`state` and an `exit_stack` for teardown, and an `Outbound` for the
standalone stream (the SSE GET stream in streamable HTTP, or the single duplex
stream in stdio).

`notify` is best-effort: it never raises. If there's no standalone channel
(stateless HTTP) or the stream has been dropped, the notification is
debug-logged and silently discarded - server-initiated notifications are
inherently advisory. `send_raw_request` *does* raise `NoBackChannelError` when
there's no channel; `ping` is the only spec-sanctioned standalone request.
"""

import logging
from collections.abc import Mapping
from contextlib import AsyncExitStack
from typing import Any, TypeVar, overload

import anyio
from pydantic import BaseModel

from mcp.shared.dispatcher import CallOptions, Outbound
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.peer import Meta, dump_params
from mcp.types import (
    ClientCapabilities,
    CreateMessageRequest,
    CreateMessageResult,
    ElicitRequest,
    ElicitResult,
    EmptyResult,
    InitializeRequestParams,
    ListRootsRequest,
    ListRootsResult,
    LoggingLevel,
    PingRequest,
    Request,
)

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


class Connection:
    """Per-client connection state and standalone-stream `Outbound`.

    Constructed by `ServerRunner` once per connection. The peer-info fields
    are `None` until `initialize` completes; `initialized` is set later, when
    the client's `notifications/initialized` follow-up arrives. In stateless
    deployments the runner sets `initialized` immediately and peer-info
    remains `None` (no handshake reaches a stateless connection).
    """

    has_standalone_channel: bool
    session_id: str | None

    client_params: InitializeRequestParams | None
    """The full `initialize` request params; `None` before initialization."""

    protocol_version: str | None
    """The protocol version negotiated during `initialize`; `None` before
    initialization, and always `None` on stateless connections (no handshake
    reaches them). Handlers read this as `ServerSession.protocol_version`."""

    initialized: anyio.Event
    """Set when `notifications/initialized` arrives (matches TS `oninitialized`);
    the point from which the spec permits server-initiated requests beyond
    ping/logging. Pre-set on stateless connections."""

    state: dict[str, Any]
    """Per-connection scratch state; persists across requests on this connection."""

    exit_stack: AsyncExitStack
    """Per-connection teardown, unwound LIFO (shielded) when the connection
    closes. Push cleanup from handlers or middleware; exceptions are logged
    and swallowed."""

    def __init__(self, outbound: Outbound, *, has_standalone_channel: bool, session_id: str | None = None) -> None:
        self._outbound = outbound
        self.has_standalone_channel = has_standalone_channel
        self.session_id = session_id

        self.client_params = None
        self.protocol_version = None
        self.initialized = anyio.Event()

        self.state = {}

        self.exit_stack = AsyncExitStack()

    @property
    def initialize_accepted(self) -> bool:
        """True once the inbound request gate is open: `initialize` recorded the
        peer info, or the handshake completed outright (stateless birth, or a
        bare `notifications/initialized`). Derived, never stored."""
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
        if not self.has_standalone_channel:
            raise NoBackChannelError(method)
        return await self._outbound.send_raw_request(method, params, opts)

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
        cls = result_type if result_type is not None else _RESULT_FOR[type(req)]
        return cls.model_validate(raw, by_name=False)

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        """Send a best-effort notification on the standalone stream.

        Never raises. If there's no standalone channel or the stream is broken,
        the notification is dropped and debug-logged.
        """
        if not self.has_standalone_channel:
            logger.debug("dropped %s: no standalone channel", method)
            return
        try:
            await self._outbound.notify(method, params)
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            logger.debug("dropped %s: standalone stream closed", method)

    async def ping(self, *, meta: Meta | None = None, opts: CallOptions | None = None) -> None:
        """Send a `ping` request on the standalone stream.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: `has_standalone_channel` is `False`.
        """
        await self.send_raw_request("ping", dump_params(None, meta), opts)

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

        Returns `False` if `initialize` hasn't completed yet.
        """
        # TODO: redesign - mirrors v1 ServerSession.check_client_capability
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
