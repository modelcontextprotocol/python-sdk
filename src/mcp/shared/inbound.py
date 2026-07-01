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
from collections.abc import Iterable, Iterator, Mapping, Sequence
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
    "find_duplicated_routing_header",
    "find_invalid_x_mcp_header",
    "mcp_param_headers",
    "validate_mcp_param_headers",
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
"""Method → params key whose value is mirrored as the `Mcp-Name` HTTP header.

Shared by client emit (which header to send) and server validate (which body
field to compare against), so both ends agree on the field by construction.
"""

_B64_SENTINEL = re.compile(r"^=\?base64\?(?P<payload>.*)\?=$")
# RFC 7230 token chars minus DEL; visible ASCII 0x20-0x7E is the practical bound for a header value.
_HEADER_SAFE = re.compile(r"^[\x20-\x7E]*$")
# RFC 9110 §5.6.2 token: the only characters permitted in an HTTP field name.
_RFC9110_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
# JSON-Schema types the spec permits to carry `x-mcp-header` (transports.mdx
# §Custom Headers). `number` is explicitly forbidden — float→str is not
# portable across implementations.
_X_MCP_HEADER_PRIMITIVE_TYPES: Final = frozenset({"string", "integer", "boolean"})

# JSON Schema 2020-12 applicator keywords whose values are themselves schema
# positions, grouped by value shape. `properties` is handled separately as the
# only keyword that preserves the statically-reachable chain; every keyword
# here drops the chain to None. Instance-data keywords (`default`, `examples`,
# `const`, `enum`) and `$ref`/`$dynamicRef` are deliberately absent so the
# walk never mistakes data for an annotation and never dereferences.
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

    `properties_path` is the chain of `properties` keys from the root to the
    position, or `None` once any other applicator keyword has been crossed.
    The root itself yields `()`. Only the JSON Schema 2020-12 applicators
    listed above are entered; instance-data keywords are not, and `$ref` is
    not dereferenced, so the walk terminates on any finite JSON value. An
    explicit stack keeps the function total even on pathologically deep input.
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
    base64, non-canonical base64, or bad UTF-8) yields `None` so a corrupt
    header never matches a body value by accident. `None` in → `None` out so
    callers can pass `headers.get(...)` directly.
    """
    if value is None:
        return None
    m = _B64_SENTINEL.fullmatch(value)
    if m is None:
        return value
    payload = m.group("payload")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except binascii.Error:
        return None
    # Reject non-canonical base64 (e.g. non-zero trailing bits), which
    # `validate=True` tolerates; the encoder only ever emits canonical form.
    if base64.b64encode(decoded).decode("ascii") != payload:
        return None
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError:
        return None


def find_invalid_x_mcp_header(input_schema: Any) -> str | None:
    """Return a reason string if any `x-mcp-header` annotation in `input_schema` is invalid; else `None`.

    Walks every JSON Schema 2020-12 schema position. An annotation is valid
    only when it sits on a property statically reachable from the root via a
    chain of pure `properties` keys, names a non-empty RFC 9110 token, is on
    an integer/string/boolean property, and is case-insensitively unique
    across the whole schema. A `None` / non-mapping schema has no schema
    positions and returns `None`.
    """
    seen: dict[str, str] = {}
    for path, schema in _walk_schema_positions(input_schema):
        if X_MCP_HEADER_KEY not in schema:
            continue
        if not path:  # None (off the pure-properties chain) or () (the root itself)
            return f"{X_MCP_HEADER_KEY} found at a schema position not reachable via a pure `properties` chain"
        where = ".".join(path)
        header = schema[X_MCP_HEADER_KEY]
        # Wrong type and malformed value are distinct failures with distinct messages: the
        # non-str arm returns before any interpolation, because `repr` of an arbitrary
        # schema value is not total (a large `int` exceeds `sys.get_int_max_str_digits`).
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
    """Map each property carrying a valid `x-mcp-header` to its annotation token, keyed by property path.

    The key is the chain of `properties` keys from the schema root to the
    annotated property; a top-level property has a one-element path, a nested
    one a longer path. Call only on a schema that
    :func:`find_invalid_x_mcp_header` accepts; an invalid schema yields an
    undefined subset.
    """
    return {path: token for path, token, _ in _annotated_positions(input_schema)}


def _annotated_positions(input_schema: Any) -> Iterator[tuple[tuple[str, ...], str, dict[str, Any]]]:
    """Yield `(path, token, schema)` for every statically-reachable `x-mcp-header` annotation.

    Shared by client emit and server validate so both ends agree on what counts as a declared header.
    """
    for path, schema in _walk_schema_positions(input_schema):
        if path and isinstance(token := schema.get(X_MCP_HEADER_KEY), str):
            yield path, token, schema


def _render_header_scalar(value: Any) -> str | None:
    """Render `value` the way the client mirrors it into a header, or `None` when no rendering exists.

    Shared by emit and validate so both sides agree on what is mirrorable:
    non-primitives and ints beyond CPython's int-to-str digit limit are not.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if not isinstance(value, str | int | float):
        return None
    try:
        return str(value)
    except ValueError:
        return None


def mcp_param_headers(header_map: Mapping[tuple[str, ...], str], arguments: Mapping[str, Any]) -> dict[str, str]:
    """Build the `Mcp-Param-*` headers a `tools/call` mirrors from its arguments.

    For each `(path, token)` in `header_map`, read the value at that property
    path in `arguments` and, when it is present and not `None`, emit
    `Mcp-Param-<token>` carrying it: `bool` as `true`/`false`, other scalars via
    `str`, each passed through :func:`encode_header_value` so a non-token value
    is base64-wrapped. A path that hits a missing key or a non-mapping node is
    skipped, matching the spec's "omit the header when no value is present",
    as is a value with no header rendering.
    """
    headers: dict[str, str] = {}
    for path, token in header_map.items():
        value = _value_at_path(arguments, path)
        if value is None or (rendered := _render_header_scalar(value)) is None:
            continue
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


_ROUTING_HEADER_NAMES: Final = frozenset({MCP_PROTOCOL_VERSION_HEADER, MCP_METHOD_HEADER, MCP_NAME_HEADER})


def find_duplicated_routing_header(headers: Iterable[tuple[str, str]]) -> str | None:
    """Name of a routing header supplied more than once in raw header lines, or `None`.

    Takes raw `(name, value)` pairs — a folded mapping hides duplicates. A
    duplicate is rejected because first-copy and last-copy readers would
    disagree. `Mcp-Param-*` duplicates are :func:`validate_mcp_param_headers`'s job.
    """
    seen: set[str] = set()
    for name, _ in headers:
        key = name.lower()
        if key in _ROUTING_HEADER_NAMES:
            if key in seen:
                return key
            seen.add(key)
    return None


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
    3. The envelope's protocol version is a string in
       `supported_modern_versions` → non-string values are
       :data:`~mcp_types.jsonrpc.INVALID_PARAMS` (a shape defect, not a
       negotiation outcome), else
       :data:`~mcp_types.jsonrpc.UNSUPPORTED_PROTOCOL_VERSION` with
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

    if not isinstance(protocol_version, str):
        # Rung 3's precondition: a shape defect, not a version-negotiation
        # outcome - -32022 is the one code auto-negotiating clients do NOT
        # fall back from, and the typed rung-3 payload itself requires a
        # string `requested`. Sits after the header rung so the HTTP wire is
        # untouched when the version header is present (a string header can
        # never equal a non-string body value, so rung 2 fires first there).
        return InboundLadderRejection(
            code=INVALID_PARAMS,
            message="the protocol-version envelope value must be a string",
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


# Header values eligible for the spec's numeric-comparison SHOULD; scientific
# notation never compares numerically (matching the typescript-sdk's gate).
_CANONICAL_DECIMAL = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")


def _mcp_param_value_matches(prop_type: Any, value: Any, rendered: str, decoded: str) -> bool:
    """True when a decoded `Mcp-Param-*` header value agrees with the body argument.

    Integer-typed declarations with an integral body value compare numerically
    (`42` matches `42.0`, the spec's SHOULD) for canonical-decimal headers —
    exact, no float round-trip, so values beyond the IEEE754 safe range still
    compare. Anything else compares against `rendered`, the emit-side rendering.
    """
    if (
        prop_type == "integer"
        and not isinstance(value, bool)
        and (isinstance(value, int) or (isinstance(value, float) and value.is_integer()))
        and _CANONICAL_DECIMAL.fullmatch(decoded) is not None
    ):
        whole, _, fraction = decoded.partition(".")
        if fraction and set(fraction) != {"0"}:
            return False
        try:
            return int(whole) == int(value)
        except ValueError:
            return False
    return decoded == rendered


def validate_mcp_param_headers(
    input_schema: Any,
    arguments: Mapping[str, Any],
    headers: Mapping[str, str],
) -> InboundLadderRejection | None:
    """Compare a `tools/call` request's `Mcp-Param-*` headers against its body arguments.

    Each annotated property's header and argument must agree: present together
    and equal after sentinel decoding, or absent together (`null` counts as
    absent). Returns the first failure as a `HEADER_MISMATCH` rejection, else `None`.

    A header whose argument is absent or unrenderable is deliberately rejected:
    the spec's purpose clause is exactly an intermediary routing on a value the
    body never carried. A duplicated recognized header is rejected — first-copy
    and last-copy readers would disagree. A schema :func:`find_invalid_x_mcp_header`
    rejects validates nothing: conforming clients drop the tool and emit no headers.
    """
    if find_invalid_x_mcp_header(input_schema) is not None:
        return None
    folded: dict[str, str] = {}
    duplicated: set[str] = set()
    for name, value in headers.items():
        key = name.lower()
        if key in folded:
            duplicated.add(key)
        folded[key] = value
    for path, token, schema in _annotated_positions(input_schema):
        header_name = f"{MCP_PARAM_HEADER_PREFIX}{token}"
        key = header_name.lower()
        raw = folded.get(key)
        value = _value_at_path(arguments, path)
        argument = ".".join(path)
        if raw is not None and key in duplicated:
            return InboundLadderRejection(
                code=HEADER_MISMATCH,
                message=f"{header_name} header appears more than once",
            )
        if value is None:
            if raw is not None:
                return InboundLadderRejection(
                    code=HEADER_MISMATCH,
                    message=f"{header_name} header is present but the request body's {argument!r} argument is absent",
                )
            continue
        rendered = _render_header_scalar(value)
        if rendered is None:
            # Unrenderable value: a conforming client omitted the header, so one claiming it can never match.
            if raw is not None:
                return InboundLadderRejection(
                    code=HEADER_MISMATCH,
                    message=f"{header_name} header does not match the request body's {argument!r} argument",
                )
            continue
        if raw is None:
            return InboundLadderRejection(
                code=HEADER_MISMATCH,
                message=f"{header_name} header is missing but the request body's {argument!r} argument is present",
            )
        decoded = decode_header_value(raw)
        if decoded is None:
            return InboundLadderRejection(
                code=HEADER_MISMATCH,
                message=f"{header_name} header carries a malformed base64 sentinel value",
            )
        if not _mcp_param_value_matches(schema.get("type"), value, rendered, decoded):
            return InboundLadderRejection(
                code=HEADER_MISMATCH,
                message=f"{header_name} header does not match the request body's {argument!r} argument",
            )
    return None
