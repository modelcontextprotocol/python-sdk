"""Connect-time era negotiation for ``mode='auto'``.

The ``server/discover`` probe is sent at the newest modern version. Anything
that is not positive evidence the peer is a modern MCP server falls back to
the legacy ``initialize`` handshake — a *denylist* (only the disjoint-modern
case raises) rather than an allowlist of fallback codes.

Every ``MCPError`` falls back except ``-32022`` with a disjoint modern-only
``supported`` list. The streamable-HTTP transport already maps HTTP-layer
4xx rejections (no JSON-RPC body) into ``MCPError`` codes, so those reach
the same path. Any non-``MCPError`` exception (network/connection errors,
anyio cancellation) propagates to the caller; an outage or in-process bug
is never an era verdict.

A successful ``DiscoverResult`` whose ``supportedVersions`` shares no modern
version with this client is treated the same way: the server speaks discover
but advertises only handshake-era versions, which is a legacy advertisement,
not an incompatibility.

The fallback handshake itself can be answered with ``-32022`` — e.g. a probe
that timed out client-side but succeeded on a slow-starting server locked the
connection modern before the pipelined ``initialize`` arrived. That code is
itself positive modern evidence (it names the server's versions), so it
triggers one re-probe at a mutual version instead of failing the connect.
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


async def negotiate_auto(session: ClientSession, protocol_version: str | None = None) -> None:
    """Drive the ``mode='auto'`` connect-time policy on ``session``.

    Probes ``server/discover`` once (twice if the server names a mutual
    modern version via -32022), then either ``adopt()``s the result or falls
    back to ``initialize()``. Idempotent only in the sense that one of
    ``session.discover_result`` / ``session.initialize_result`` is set on
    return.

    Raises:
        MCPError: The server is modern-only and shares no version with this
            client (-32022 with a disjoint ``supported`` list), or the
            fallback handshake failed and one corrective re-probe did too.
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
            try:
                if protocol_version is not None:
                    await session.initialize(protocol_version=protocol_version)
                else:
                    await session.initialize()  # every other rpc-error → legacy (the denylist)
            except MCPError as handshake_exc:
                if handshake_exc.code != UNSUPPORTED_PROTOCOL_VERSION or attempt != 0:
                    raise
                # -32022 from the handshake is itself modern evidence: a probe
                # that timed out client-side but succeeded on the server locked
                # the connection modern before this initialize arrived. Re-probe
                # once at a version the server names; the era is already
                # settled, so the second probe answers without the slow start.
                supported = _parse_supported(handshake_exc.error.data)
                mutual = [v for v in MODERN_PROTOCOL_VERSIONS if v in (supported or ())]
                if not mutual:
                    raise
                version = mutual[-1]
                continue
            return
        # any other exception (httpx2.TransportError, ConnectionError,
        # anyio errors) → propagate
        try:
            result = types.DiscoverResult.model_validate(raw)
        except ValidationError:
            if protocol_version is not None:
                await session.initialize(protocol_version=protocol_version)
            else:
                await session.initialize()  # unparseable result → not modern evidence
            return
        if not any(v in result.supported_versions for v in MODERN_PROTOCOL_VERSIONS):
            # A discover-answering server that advertises no modern version
            # (go-sdk's stateful streamable default does this) is an explicit
            # legacy advertisement: fall back like the -32022 branch above
            # instead of letting `adopt()` raise. The ts and go clients fall
            # back here too.
            await session.initialize()
            return
        session.adopt(result)
        return
    raise AssertionError("unreachable")  # pragma: no cover — loop body always returns or raises
