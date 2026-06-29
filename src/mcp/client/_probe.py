"""Connect-time era negotiation for ``mode='auto'``.

The ``server/discover`` probe is sent at the newest modern version. Anything
that is not positive evidence the peer is a modern MCP server falls back to
the legacy ``initialize`` handshake — a *denylist* (only the disjoint-modern
case raises) rather than an allowlist of fallback codes.

Every ``MCPError`` falls back except ``-32022`` with a disjoint modern-only
``supported`` list. The streamable-HTTP transport already maps HTTP-layer
4xx rejections (no JSON-RPC body) into ``MCPError`` codes, so those reach
the same path. Any non-``MCPError`` exception (network/connection errors,
anyio cancellation, the ``RuntimeError`` from ``adopt()`` on no-mutual)
propagates to the caller; an outage or in-process bug is never an era verdict.
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
    """Pull ``data.supported`` off a -32022 error, or ``None`` if not actionable."""
    try:
        return types.UnsupportedProtocolVersionErrorData.model_validate(data).supported
    except ValidationError:
        return None


async def negotiate_auto(session: ClientSession) -> None:
    """Drive the ``mode='auto'`` connect-time policy on ``session``.

    Probes ``server/discover`` once (twice if the server names a mutual
    modern version via -32022), then either ``adopt()``s the result or falls
    back to ``initialize()``. Idempotent only in the sense that one of
    ``session.discover_result`` / ``session.initialize_result`` is set on
    return.

    Raises:
        MCPError: The server is modern-only and shares no version with this
            client (-32022 with a disjoint ``supported`` list).
        Exception: Any transport/network error from the probe propagates as-is.
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
            await session.initialize()  # every other rpc-error → legacy (the denylist)
            return
        # any other exception (httpx2.TransportError, ConnectionError, anyio errors,
        # RuntimeError from adopt) → propagate
        try:
            result = types.DiscoverResult.model_validate(raw)
        except ValidationError:
            await session.initialize()  # unparseable result → not modern evidence
            return
        session.adopt(result)
        return
    raise AssertionError("unreachable")  # pragma: no cover — loop body always returns or raises
