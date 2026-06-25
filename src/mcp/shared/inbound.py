"""Inbound request classification for the modern per-request-envelope path.

Pure module: no I/O, no transport, no `mcp.server` imports. Runs the
validation ladder against a decoded JSON-RPC body and returns either an
:class:`InboundModernRoute` (every rung passed) or an
:class:`InboundLadderRejection` (the first rung that failed). Callers map a
rejection's `code` through :data:`ERROR_CODE_HTTP_STATUS` to pick the HTTP
status.

Also hosts the shared header-value codec and the `x-mcp-header` schema
validator so client emit and server validate read the same source of truth.
"""

import base64
import binascii
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, cast

from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
    UnsupportedProtocolVersionErrorData,
)
from mcp_types.jsonrpc import (
    HEADER_MISMATCH,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    PARSE_ERROR,
    UNSUPPORTED_PROTOCOL_VERSION,
)
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

__all__ = [
    "ERROR_CODE_HTTP_STATUS",
    "InboundLadderRejection",
    "InboundModernRoute",
    "MCP_METHOD_HEADER",
    "MCP_NAME_HEADER",
    "MCP_PROTOCOL_VERSION_HEADER",
    "NAME_BEARING_METHODS",
    "X_MCP_HEADER_KEY",
    "classify_inbound_request",
    "decode_header_value",
    "encode_header_value",
    "find_invalid_x_mcp_header",
]

MCP_PROTOCOL_VERSION_HEADER: Final = "mcp-protocol-version"
"""Canonical lowercase name of the HTTP header carrying the MCP protocol version."""

MCP_METHOD_HEADER: Final = "mcp-method"
"""Canonical lowercase name of the HTTP header carrying the JSON-RPC method."""

MCP_NAME_HEADER: Final = "mcp-name"
"""Canonical lowercase name of the HTTP header carrying the resource name (tool/prompt/resource URI)."""

X_MCP_HEADER_KEY: Final = "x-mcp-header"
"""JSON-Schema property annotation that designates an `Mcp-Param-*` HTTP header."""

NAME_BEARING_METHODS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "tools/call": "name",
        "prompts/get": "name",
        "resources/read": "uri",
    }
)
"""Method → params key whose value is mirrored as the `Mcp-Name` HTTP header.

Shared by client emit (which header to send) and server validate (which body
field to compare against), so both ends agree on the field by construction.
"""

_B64_SENTINEL = re.compile(r"^=\?base64\?(?P<payload>.*)\?=$")
# RFC 7230 token chars minus DEL; visible ASCII 0x20-0x7E is the practical bound for a header value.
_HEADER_SAFE = re.compile(r"^[\x20-\x7E]*$")
# RFC 9110 §5.6.2 token: the only characters permitted in an HTTP field name.
_RFC9110_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
# JSON-Schema types that stringify cleanly into a single header value. The spec
# names string/integer/boolean; number is admitted because the conformance
# harness emits it and float→str round-trips to within tolerance.
_X_MCP_HEADER_PRIMITIVE_TYPES: Final = frozenset({"string", "integer", "boolean", "number"})


def encode_header_value(value: str) -> str:
    """Wrap `value` in the `=?base64?...?=` sentinel when it would not survive an HTTP field round-trip.

    Plain printable ASCII without leading/trailing whitespace passes verbatim;
    anything else (control chars, non-ASCII, edge whitespace, or a value that
    already looks like the sentinel) is base64-wrapped so the receiver can
    recover the exact bytes.
    """
    if _HEADER_SAFE.fullmatch(value) and value == value.strip() and not _B64_SENTINEL.fullmatch(value):
        return value
    return f"=?base64?{base64.b64encode(value.encode('utf-8')).decode('ascii')}?="


def decode_header_value(value: str | None) -> str | None:
    """Inverse of :func:`encode_header_value`.

    Returns the value verbatim unless it carries the `=?base64?...?=` sentinel,
    in which case the payload is decoded as UTF-8. A malformed sentinel (bad
    base64 or bad UTF-8) yields `None` so a corrupt header never matches a body
    value by accident. `None` in → `None` out so callers can pass
    `headers.get(...)` directly.
    """
    if value is None:
        return None
    m = _B64_SENTINEL.fullmatch(value)
    if m is None:
        return value
    try:
        return base64.b64decode(m.group("payload"), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None


def find_invalid_x_mcp_header(input_schema: Any) -> str | None:
    """Return a reason string if any `x-mcp-header` annotation in `input_schema` is invalid; else `None`.

    The spec restricts the annotation to top-level primitive properties whose
    header name is a non-empty RFC 9110 token unique (case-insensitively) within
    the schema. A `None` / non-object / property-less schema has nothing to
    validate and returns `None`.
    """
    match input_schema:
        case {"properties": {**properties}}:
            pass
        case _:
            return None
    seen: dict[str, str] = {}
    for prop_name, raw in properties.items():
        if not isinstance(raw, dict) or X_MCP_HEADER_KEY not in raw:
            continue
        prop_schema = cast(dict[str, Any], raw)
        header = prop_schema[X_MCP_HEADER_KEY]
        if not isinstance(header, str) or not _RFC9110_TOKEN.fullmatch(header):
            return f"property {prop_name!r}: {X_MCP_HEADER_KEY} {header!r} is not an RFC 9110 token"
        if prop_schema.get("type") not in _X_MCP_HEADER_PRIMITIVE_TYPES:
            return f"property {prop_name!r}: {X_MCP_HEADER_KEY} is only permitted on primitive-typed properties"
        lower = header.lower()
        if lower in seen:
            return f"{X_MCP_HEADER_KEY} {header!r} on property {prop_name!r} duplicates property {seen[lower]!r}"
        seen[lower] = prop_name
    return None


# INTERNAL_ERROR is deliberately unmapped (→ HTTP 200): the spec assigns no status to
# -32603, and whether handler-origin errors get 5xx is an open S4 question — see TODO(L66).
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
"""HTTP status to send for a JSON-RPC `error.code`.

Consulted for classifier-origin *and* handler-origin errors, so one table
decides the wire status regardless of where the error was produced. Unmapped
codes fall back to the caller's default (typically 200).
"""


@dataclass(frozen=True)
class InboundModernRoute:
    """A modern-protocol request whose envelope passed every ladder rung.

    `client_info` and `client_capabilities` are the raw envelope values;
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

    1. `params._meta` is a mapping carrying every reserved envelope key
       (protocol version, client info, client capabilities) → else
       :data:`~mcp_types.jsonrpc.INVALID_PARAMS`.
    2. When `headers` is given, `MCP-Protocol-Version` equals the envelope's
       protocol version, `Mcp-Method` equals `body.method`, and — for the
       methods in :data:`NAME_BEARING_METHODS` — `Mcp-Name` equals the named
       body param → else :data:`~mcp_types.jsonrpc.HEADER_MISMATCH`. Runs
       before the supported-version rung so a client that disagrees with itself
       is told so, rather than told the body's version is unsupported.
    3. The envelope's protocol version is in `supported_modern_versions` →
       else :data:`~mcp_types.jsonrpc.UNSUPPORTED_PROTOCOL_VERSION` with
       `data = {"supported": [...], "requested": <value>}`.

    Method existence is *not* a rung: kernel dispatch owns that decision so
    custom-registered methods route and the answer lives in one place.

    Args:
        body: The decoded JSON-RPC request mapping. Envelope shape
            (`jsonrpc` / `id`) is not checked here.
        headers: Transport headers keyed by lowercase name, or `None` to
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

    if headers is not None:
        if headers.get(MCP_PROTOCOL_VERSION_HEADER) != protocol_version:
            return InboundLadderRejection(
                code=HEADER_MISMATCH,
                message=f"{MCP_PROTOCOL_VERSION_HEADER} header does not match the request envelope's protocol version",
            )
        method: Any = body.get("method")
        if headers.get(MCP_METHOD_HEADER) != method:
            return InboundLadderRejection(
                code=HEADER_MISMATCH,
                message=f"{MCP_METHOD_HEADER} header does not match the request body's method",
            )
        name_key = NAME_BEARING_METHODS.get(method)
        if name_key is not None:
            # Rung 1 already proved body["params"] is a mapping.
            body_value = body["params"].get(name_key)
            if body_value is not None and decode_header_value(headers.get(MCP_NAME_HEADER)) != body_value:
                return InboundLadderRejection(
                    code=HEADER_MISMATCH,
                    message=f"{MCP_NAME_HEADER} header does not match the request body's {name_key!r} parameter",
                )

    if protocol_version not in supported_modern_versions:
        return InboundLadderRejection(
            code=UNSUPPORTED_PROTOCOL_VERSION,
            message="Unsupported protocol version",
            data=UnsupportedProtocolVersionErrorData(
                supported=list(supported_modern_versions), requested=protocol_version
            ).model_dump(mode="json"),
        )

    return InboundModernRoute(
        protocol_version=protocol_version,
        client_info=client_info,
        client_capabilities=client_capabilities,
    )
