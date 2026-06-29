"""Connect-time era negotiation for `mode='auto'`.

Fallback to legacy `initialize` is a denylist: every `MCPError` falls back
except `-32022` with a disjoint modern-only `supported` list. Streamable HTTP
maps HTTP-layer 4xx rejections into `MCPError` codes, so they take the same
path. Non-`MCPError` exceptions propagate — an outage is never an era verdict.
"""

from __future__ import annotations

from typing import Any

import mcp_types as types
from mcp_types import UNSUPPORTED_PROTOCOL_VERSION
from mcp_types.version import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    LATEST_MODERN_VERSION,
    MODERN_PROTOCOL_VERSIONS,
)
from pydantic import ValidationError

from mcp.client.session import ClientSession
from mcp.shared.exceptions import MCPError


def _parse_supported(data: Any) -> list[str] | None:
    """Pull `data.supported` off a -32022 error, or `None` if not actionable."""
    try:
        return types.UnsupportedProtocolVersionErrorData.model_validate(data).supported
    except ValidationError:
        return None


async def negotiate_auto(session: ClientSession) -> None:
    """Drive the `mode='auto'` connect-time policy on `session`.

    Probes `server/discover` (retrying once at a mutual modern version on
    -32022), then `adopt()`s the result or falls back to `initialize()`; one of
    `session.discover_result`/`session.initialize_result` is set on return.

    Raises:
        MCPError: Server is modern-only with a disjoint `supported` list (-32022).
        Exception: Transport/network errors from the probe propagate as-is.
    """
    version = LATEST_MODERN_VERSION
    for attempt in range(2):
        try:
            raw = await session.send_discover(version)
        except MCPError as e:
            if e.code == UNSUPPORTED_PROTOCOL_VERSION:
                supported = _parse_supported(e.error.data)
                mutual = [v for v in MODERN_PROTOCOL_VERSIONS if v in (supported or ())]
                if mutual and attempt == 0:
                    version = mutual[-1]
                    continue
                if supported is not None and not any(v in HANDSHAKE_PROTOCOL_VERSIONS for v in supported):
                    raise  # server is modern-only and disjoint — real incompatibility
            await session.initialize()  # any other MCPError → legacy (the denylist)
            return
        try:
            result = types.DiscoverResult.model_validate(raw)
        except ValidationError:
            await session.initialize()  # unparseable result → not modern evidence
            return
        session.adopt(result)
        return
    raise AssertionError("unreachable")  # pragma: no cover — loop body always returns or raises
