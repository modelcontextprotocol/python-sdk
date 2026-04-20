"""`Connection` — per-client connection state and the standalone outbound channel.

Always present on `Context` (never ``None``), even in stateless deployments.
Holds peer info populated at ``initialize`` time, the per-connection lifespan
output, and an `Outbound` for the standalone stream (the SSE GET stream in
streamable HTTP, or the single duplex stream in stdio).

`notify` is best-effort: it never raises. If there's no standalone channel
(stateless HTTP) or the stream has been dropped, the notification is
debug-logged and silently discarded — server-initiated notifications are
inherently advisory. `send_raw_request` *does* raise `NoBackChannelError` when
there's no channel; `ping` is the only spec-sanctioned standalone request.
"""

import logging
from collections.abc import Mapping
from typing import Any

import anyio

from mcp.server._typed_request import TypedServerRequestMixin
from mcp.shared.dispatcher import CallOptions, Outbound
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.peer import Meta, dump_params
from mcp.types import ClientCapabilities, Implementation, LoggingLevel

__all__ = ["Connection"]

logger = logging.getLogger(__name__)


def _notification_params(payload: dict[str, Any] | None, meta: Meta | None) -> dict[str, Any] | None:
    if not meta:
        return payload
    out = dict(payload or {})
    out["_meta"] = meta
    return out


class Connection(TypedServerRequestMixin):
    """Per-client connection state and standalone-stream `Outbound`.

    Constructed by `ServerRunner` once per connection. The peer-info fields are
    ``None`` until ``initialize`` completes; ``initialized`` is set then.
    """

    def __init__(self, outbound: Outbound, *, has_standalone_channel: bool) -> None:
        self._outbound = outbound
        self.has_standalone_channel = has_standalone_channel

        self.client_info: Implementation | None = None
        self.client_capabilities: ClientCapabilities | None = None
        self.protocol_version: str | None = None
        self.initialized: anyio.Event = anyio.Event()
        # TODO: make this generic (Connection[StateT]) once connection_lifespan
        # wiring lands in ServerRunner.
        self.state: Any = None

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        """Send a raw request on the standalone stream.

        Low-level `Outbound` channel. Prefer the typed ``send_request`` (from
        `TypedServerRequestMixin`) or the convenience methods below; use this
        directly only for off-spec messages.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: ``has_standalone_channel`` is ``False``.
        """
        if not self.has_standalone_channel:
            raise NoBackChannelError(method)
        return await self._outbound.send_raw_request(method, params, opts)

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
        """Send a ``ping`` request on the standalone stream.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: ``has_standalone_channel`` is ``False``.
        """
        await self.send_raw_request("ping", dump_params(None, meta), opts)

    async def log(self, level: LoggingLevel, data: Any, logger: str | None = None, *, meta: Meta | None = None) -> None:
        """Send a ``notifications/message`` log entry on the standalone stream. Best-effort."""
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

        Returns ``False`` if ``initialize`` hasn't completed yet.
        """
        # TODO: redesign — mirrors v1 ServerSession.check_client_capability
        # verbatim for parity.
        if self.client_capabilities is None:
            return False
        have = self.client_capabilities
        if capability.roots is not None:
            if have.roots is None:
                return False
            if capability.roots.list_changed and not have.roots.list_changed:
                return False
        if capability.sampling is not None and have.sampling is None:
            return False
        if capability.elicitation is not None and have.elicitation is None:
            return False
        if capability.experimental is not None:
            if have.experimental is None:
                return False
            for k in capability.experimental:
                if k not in have.experimental:
                    return False
        return True
