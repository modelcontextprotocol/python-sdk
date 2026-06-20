"""Inbound request classification for the modern per-request-envelope path.

Pure module: no I/O, no transport, no ``mcp.server`` imports. Runs the
validation ladder against a decoded JSON-RPC body and returns either an
:class:`InboundModernRoute` (every rung passed) or an
:class:`InboundLadderRejection` (the first rung that failed). Callers map a
rejection's ``code`` through :data:`ERROR_CODE_HTTP_STATUS` to pick the HTTP
status.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from mcp.shared.version import MODERN_PROTOCOL_VERSIONS
from mcp.types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
)
from mcp.types.jsonrpc import (
    HEADER_MISMATCH,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    PARSE_ERROR,
    UNSUPPORTED_PROTOCOL_VERSION,
)

__all__ = [
    "ERROR_CODE_HTTP_STATUS",
    "InboundLadderRejection",
    "InboundModernRoute",
    "MCP_PROTOCOL_VERSION_HEADER",
    "classify_inbound_request",
]

MCP_PROTOCOL_VERSION_HEADER: Final = "mcp-protocol-version"
"""Canonical lowercase name of the HTTP header carrying the MCP protocol version."""

ERROR_CODE_HTTP_STATUS: Final[Mapping[int, int]] = MappingProxyType(
    {
        PARSE_ERROR: 400,
        INVALID_REQUEST: 400,
        INVALID_PARAMS: 400,
        HEADER_MISMATCH: 400,
        MISSING_REQUIRED_CLIENT_CAPABILITY: 400,
        UNSUPPORTED_PROTOCOL_VERSION: 400,
        METHOD_NOT_FOUND: 404,
    }
)
"""HTTP status to send for a JSON-RPC ``error.code``.

Consulted for classifier-origin *and* handler-origin errors, so one table
decides the wire status regardless of where the error was produced. Unmapped
codes fall back to the caller's default (typically 200).
"""


@dataclass(frozen=True)
class InboundModernRoute:
    """A modern-protocol request whose envelope passed every ladder rung.

    ``client_info`` and ``client_capabilities`` are the raw envelope values;
    the classifier checks presence only, not shape. Method existence is not a
    ladder rung — kernel dispatch is the single source of truth for that.
    """

    protocol_version: str
    client_info: Any
    client_capabilities: Any


@dataclass(frozen=True)
class InboundLadderRejection:
    """The first ladder rung that failed, as JSON-RPC error fields."""

    code: int
    message: str
    data: Any = None


def classify_inbound_request(
    body: Mapping[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
    supported_modern_versions: Sequence[str] = MODERN_PROTOCOL_VERSIONS,
) -> InboundModernRoute | InboundLadderRejection:
    """Run the modern-protocol validation ladder over a decoded JSON-RPC body.

    Rungs, in order — first failure wins:

    1. ``params._meta`` is a mapping carrying every reserved envelope key
       (protocol version, client info, client capabilities) → else
       :data:`~mcp.types.jsonrpc.INVALID_PARAMS`.
    2. When ``headers`` is given, its ``MCP-Protocol-Version`` entry equals
       the envelope's protocol version → else
       :data:`~mcp.types.jsonrpc.HEADER_MISMATCH`. Runs before the
       supported-version rung so a client that disagrees with itself is told
       so, rather than told the body's version is unsupported.
    3. The envelope's protocol version is in ``supported_modern_versions`` →
       else :data:`~mcp.types.jsonrpc.UNSUPPORTED_PROTOCOL_VERSION` with
       ``data = {"supported": [...], "requested": <value>}``.

    Method existence is *not* a rung: kernel dispatch owns that decision so
    custom-registered methods route and the answer lives in one place.

    Args:
        body: The decoded JSON-RPC request mapping. Envelope shape
            (``jsonrpc`` / ``id``) is not checked here.
        headers: Transport headers keyed by lowercase name, or ``None`` to
            skip the header rung (non-HTTP callers).
        supported_modern_versions: Modern protocol revisions this server
            accepts on the per-request-envelope path.
    """
    try:
        meta = body["params"]["_meta"]
        protocol_version = meta[PROTOCOL_VERSION_META_KEY]
        client_info = meta[CLIENT_INFO_META_KEY]
        client_capabilities = meta[CLIENT_CAPABILITIES_META_KEY]
    except (KeyError, TypeError):
        return InboundLadderRejection(
            code=INVALID_PARAMS,
            message="params._meta must carry the reserved protocol-version, client-info and "
            "client-capabilities envelope keys",
        )

    if headers is not None and headers.get(MCP_PROTOCOL_VERSION_HEADER) != protocol_version:
        return InboundLadderRejection(
            code=HEADER_MISMATCH,
            message=f"{MCP_PROTOCOL_VERSION_HEADER} header does not match the request envelope's protocol version",
        )

    if protocol_version not in supported_modern_versions:
        return InboundLadderRejection(
            code=UNSUPPORTED_PROTOCOL_VERSION,
            message="Unsupported protocol version",
            data={"supported": list(supported_modern_versions), "requested": protocol_version},
        )

    return InboundModernRoute(
        protocol_version=protocol_version,
        client_info=client_info,
        client_capabilities=client_capabilities,
    )
