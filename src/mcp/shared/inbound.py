"""Inbound request classification for the modern per-request-envelope path.

Pure module (no I/O, no transport, no `mcp.server` imports): the validation ladder
returns `InboundModernRoute` (every rung passed) or `InboundLadderRejection` (the
first failed rung), whose `code` maps through `ERROR_CODE_HTTP_STATUS` to an HTTP
status. Also hosts the header-value codec and `x-mcp-header` schema validator
shared by client emit and server validate.
"""

import base64
import binascii
import re
from collections.abc import Iterator, Mapping, Sequence
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
    "MCP_PARAM_HEADER_PREFIX",
    "MCP_PROTOCOL_VERSION_HEADER",
    "NAME_BEARING_METHODS",
    "X_MCP_HEADER_KEY",
    "classify_inbound_request",
    "decode_header_value",
    "encode_header_value",
    "find_invalid_x_mcp_header",
    "mcp_param_headers",
    "x_mcp_header_map",
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
"""Method → params key mirrored as the `Mcp-Name` HTTP header; shared by client emit and server validate."""

_B64_SENTINEL = re.compile(r"^=\?base64\?(?P<payload>.*)\?=$")
# RFC 7230 token chars minus DEL; visible ASCII 0x20-0x7E is the practical bound for a header value.
_HEADER_SAFE = re.compile(r"^[\x20-\x7E]*$")
# RFC 9110 §5.6.2 token: the only characters permitted in an HTTP field name.
_RFC9110_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
# Types the spec permits to carry `x-mcp-header` (transports.mdx §Custom Headers).
# `number` is explicitly forbidden — float→str is not portable across implementations.
_X_MCP_HEADER_PRIMITIVE_TYPES: Final = frozenset({"string", "integer", "boolean"})

# JSON Schema 2020-12 applicator keywords grouped by value shape; `properties` alone preserves
# the statically-reachable chain. Instance-data keywords (`default`, `examples`, `const`, `enum`)
# and `$ref`/`$dynamicRef` are deliberately absent so the walk never mistakes data for an
# annotation and never dereferences.
_SUBSCHEMA_SINGLE: Final = frozenset(
    {
        "items",
        "contains",
        "unevaluatedItems",
        "additionalProperties",
        "propertyNames",
        "unevaluatedProperties",
        "not",
        "if",
        "then",
        "else",
        "contentSchema",
    }
)
_SUBSCHEMA_LIST: Final = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SUBSCHEMA_MAP: Final = frozenset({"patternProperties", "dependentSchemas", "$defs", "definitions"})


def _walk_schema_positions(root: Any) -> Iterator[tuple[tuple[str, ...] | None, dict[str, Any]]]:
    """Yield `(properties_path, schema)` for every schema position in `root`.

    `properties_path` is the chain of `properties` keys from the root (itself `()`),
    or `None` once any other applicator keyword is crossed. `$ref` is never
    dereferenced and the stack is explicit, so the walk terminates on any finite
    JSON value, however deep.
    """
    stack: list[tuple[tuple[str, ...] | None, Any]] = [((), root)]
    while stack:
        path, node = stack.pop()
        if not isinstance(node, dict):
            continue
        schema = cast(dict[str, Any], node)
        yield path, schema
        for kw, val in schema.items():
            if kw == "properties" and isinstance(val, dict):
                for name, sub in cast(dict[str, Any], val).items():
                    stack.append(((*path, name) if path is not None else None, sub))
            elif kw in _SUBSCHEMA_SINGLE:
                stack.append((None, val))
            elif kw in _SUBSCHEMA_LIST and isinstance(val, list):
                stack.extend((None, sub) for sub in cast(list[Any], val))
            elif kw in _SUBSCHEMA_MAP and isinstance(val, dict):
                stack.extend((None, sub) for sub in cast(dict[str, Any], val).values())


def encode_header_value(value: str) -> str:
    """Wrap `value` in the `=?base64?...?=` sentinel when it would not survive an HTTP field round-trip.

    Printable ASCII without edge whitespace passes verbatim; control chars, non-ASCII,
    edge whitespace, or a value already shaped like the sentinel is base64-wrapped.
    """
    if _HEADER_SAFE.fullmatch(value) and value == value.strip() and not _B64_SENTINEL.fullmatch(value):
        return value
    return f"=?base64?{base64.b64encode(value.encode('utf-8')).decode('ascii')}?="


def decode_header_value(value: str | None) -> str | None:
    """Inverse of `encode_header_value`; `None` in → `None` out.

    A malformed sentinel (bad base64 or bad UTF-8) yields `None` so a corrupt
    header never matches a body value by accident.
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

    Valid annotations sit on a property reachable from the root via pure `properties`
    keys, name an RFC 9110 token, annotate an integer/string/boolean property, and
    are case-insensitively unique across the whole schema.
    """
    seen: dict[str, str] = {}
    for path, schema in _walk_schema_positions(input_schema):
        if X_MCP_HEADER_KEY not in schema:
            continue
        if not path:  # None (off the pure-properties chain) or () (the root itself)
            return f"{X_MCP_HEADER_KEY} found at a schema position not reachable via a pure `properties` chain"
        where = ".".join(path)
        header = schema[X_MCP_HEADER_KEY]
        # The non-str arm returns before any interpolation: `repr` of an arbitrary schema
        # value is not total (a large `int` exceeds `sys.get_int_max_str_digits`).
        if not isinstance(header, str):
            return f"property {where!r}: {X_MCP_HEADER_KEY} must be a string, not {type(header).__name__}"
        if not _RFC9110_TOKEN.fullmatch(header):
            return f"property {where!r}: {X_MCP_HEADER_KEY} {header!r} is not an RFC 9110 token"
        prop_type = schema.get("type")
        if not isinstance(prop_type, str):
            return (
                f"property {where!r}: {X_MCP_HEADER_KEY} is only permitted on "
                f"integer/string/boolean properties (the type keyword is {type(prop_type).__name__}, not a string)"
            )
        if prop_type not in _X_MCP_HEADER_PRIMITIVE_TYPES:
            return (
                f"property {where!r}: {X_MCP_HEADER_KEY} is only permitted on "
                f"integer/string/boolean properties (got {prop_type!r})"
            )
        lower = header.lower()
        if lower in seen:
            return f"{X_MCP_HEADER_KEY} {header!r} on property {where!r} duplicates property {seen[lower]!r}"
        seen[lower] = where
    return None


MCP_PARAM_HEADER_PREFIX: Final = "Mcp-Param-"
"""Prefix the `x-mcp-header` token is joined to, forming the per-parameter HTTP header name."""


def x_mcp_header_map(input_schema: Any) -> dict[tuple[str, ...], str]:
    """Map each property carrying a valid `x-mcp-header` to its token, keyed by `properties`-key path.

    Call only on a schema `find_invalid_x_mcp_header` accepts; an invalid schema
    yields an undefined subset.
    """
    mapping: dict[tuple[str, ...], str] = {}
    for path, schema in _walk_schema_positions(input_schema):
        if path and isinstance(header := schema.get(X_MCP_HEADER_KEY), str):
            mapping[path] = header
    return mapping


def mcp_param_headers(header_map: Mapping[tuple[str, ...], str], arguments: Mapping[str, Any]) -> dict[str, str]:
    """Build the `Mcp-Param-*` headers a `tools/call` mirrors from its arguments.

    `bool` renders as `true`/`false`, other scalars via `str`, each passed through
    `encode_header_value`. A missing or `None` value skips its header, matching the
    spec's "omit the header when no value is present".
    """
    headers: dict[str, str] = {}
    for path, token in header_map.items():
        value = _value_at_path(arguments, path)
        if value is None:
            continue
        rendered = ("true" if value else "false") if isinstance(value, bool) else str(value)
        headers[f"{MCP_PARAM_HEADER_PREFIX}{token}"] = encode_header_value(rendered)
    return headers


def _value_at_path(arguments: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    """Read the value at a `properties`-key path in `arguments`, or `None` if any step is missing or non-mapping."""
    node: Any = arguments
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = cast("Mapping[str, Any]", node).get(key)
    return node


# INTERNAL_ERROR is deliberately unmapped (→ HTTP 200): the spec assigns no status to
# -32603, and whether handler-origin errors should get 5xx is still an open question.
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
"""HTTP status to send for a JSON-RPC `error.code`, classifier- and handler-origin alike.

Unmapped codes fall back to the caller's default (typically 200).
"""


@dataclass(frozen=True)
class InboundModernRoute:
    """A modern-protocol request whose envelope passed every ladder rung.

    `client_info` / `client_capabilities` are the raw envelope values — the
    classifier checks presence only, not shape.
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

    1. `params._meta` carries every reserved envelope key → else `INVALID_PARAMS`.
    2. When `headers` is given, `MCP-Protocol-Version`, `Mcp-Method`, and (for
       `NAME_BEARING_METHODS`) `Mcp-Name` match the body → else `HEADER_MISMATCH`.
       Runs before rung 3 so a client that disagrees with itself is told so,
       rather than told the body's version is unsupported.
    3. The envelope's protocol version is in `supported_modern_versions` → else
       `UNSUPPORTED_PROTOCOL_VERSION` with supported/requested in `data`.

    Method existence is *not* a rung: kernel dispatch owns that decision so
    custom-registered methods route and the answer lives in one place.

    Args:
        body: Decoded JSON-RPC request mapping; `jsonrpc`/`id` shape is not checked.
        headers: Transport headers keyed by lowercase name, or `None` to skip
            rung 2 (non-HTTP callers).
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
