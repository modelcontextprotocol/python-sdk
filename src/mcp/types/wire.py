"""Version-aware wire boundary for MCP types.

`mcp.types` defines a single superset model set — "the monolith" throughout
this package — covering every known protocol version at once, instead of
maintaining parallel per-version model trees. This module is where the
per-version differences are applied: serialize a monolith model for, or
parse wire data under, a specific negotiated protocol version. The unique
key for every behavior in this module is (monolith type, negotiated protocol
version). Versions are opaque strings ordered by KNOWN_PROTOCOL_VERSIONS;
nothing here negotiates, dispatches, or holds session state. This module
exposes the version registry, the per-version method tables, `serialize_for`
/ `parse_as`, and the two error types version-aware serialization raises;
the shaping facts live in `mcp.types._version_facts` and the engine that
applies them in `mcp.types._shaping`.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final, TypeVar, overload

from pydantic import BaseModel

from mcp.shared.version import KNOWN_PROTOCOL_VERSIONS
from mcp.types import _shaping
from mcp.types._types import Notification, Request, Result
from mcp.types._version_facts import VERSION_FACTS, UnsupportedAtVersionError
from mcp.types.jsonrpc import JSONRPCError, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse

__all__ = [
    "CLIENT_NOTIFICATION_METHODS",
    "CLIENT_REQUEST_METHODS",
    "KNOWN_PROTOCOL_VERSIONS",
    "SERVER_NOTIFICATION_METHODS",
    "SERVER_REQUEST_METHODS",
    "UnknownProtocolVersionError",
    "UnsupportedAtVersionError",
    "parse_as",
    "serialize_for",
]

T = TypeVar("T")

# Per-version method tables: version -> frozenset of wire method strings.
# Plain data, read directly off the per-version fact blocks; session-layer
# dispatch gating (out of scope for the type layer) consumes them.
CLIENT_REQUEST_METHODS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {facts.version: facts.client_request_methods for facts in VERSION_FACTS.values()}
)
"""Client-to-server request methods defined at each protocol version."""

CLIENT_NOTIFICATION_METHODS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {facts.version: facts.client_notification_methods for facts in VERSION_FACTS.values()}
)
"""Client-to-server notification methods defined at each protocol version."""

SERVER_REQUEST_METHODS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {facts.version: facts.server_request_methods for facts in VERSION_FACTS.values()}
)
"""Server-to-client request methods defined at each protocol version.

Empty at 2026-07-28: that revision removed the standalone server-to-client
request channel (sampling, roots, and elicitation requests become payloads
embedded in input-required results).
"""

SERVER_NOTIFICATION_METHODS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {facts.version: facts.server_notification_methods for facts in VERSION_FACTS.values()}
)
"""Server-to-client notification methods defined at each protocol version."""


class UnknownProtocolVersionError(ValueError):
    """The requested version is not in KNOWN_PROTOCOL_VERSIONS.

    Raised on serialization only: the type layer must never guess a wire shape
    for a version it does not know. Parsing accepts unknown version strings
    leniently (an unknown version is most plausibly newer than this SDK).
    """

    def __init__(self, version: str) -> None:
        super().__init__(f"unknown protocol version {version!r}; known versions: {', '.join(KNOWN_PROTOCOL_VERSIONS)}")
        self.version: str = version
        self.known: tuple[str, ...] = KNOWN_PROTOCOL_VERSIONS


def _is_serializable(model: BaseModel) -> bool:
    """`serialize_for` accepts message bodies and JSON-RPC envelope models only;
    bare fragments (content blocks, params classes, capabilities objects, ...)
    are shaped in situ, inside the body that carries them."""
    return isinstance(
        model,
        Request | Notification | Result | JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError,
    )


# OD-11 alternative: strip audio/resource_link content and narrow opened tool
# schemas when emitting to versions that predate them; pass-through chosen.


def serialize_for(model: BaseModel, version: str) -> dict[str, Any]:
    """Dump `model` as its wire JSON for a session negotiated at `version`.

    `model` is a top-level message body (a concrete request, notification, or
    result model) or a `mcp.types.jsonrpc` envelope model; any other monolith
    model (a bare fragment: content blocks, `SamplingMessage`, capabilities
    objects, params classes, ...) raises `TypeError` — fragments are shaped
    only in situ, inside the body that carries them.

    Returns the message body (requests/notifications/results) or the full
    frame when given an envelope model. Applies the per-version shaping facts
    of `mcp.types._version_facts`: injections fire only on the versions that
    require a construct, and strips fire on every version whose wire shape
    lacks the field — versions that predate it and versions that removed it.
    Nothing is injected on 2025-11-25 and earlier, so for a model that sets
    none of the fields those versions strip, the dump is byte-identical to
    the plain model dump.

    Raises:
        UnknownProtocolVersionError: `version` is not a known protocol version.
        UnsupportedAtVersionError: `model` has no legal wire form at `version`.
    """
    if not _is_serializable(model):
        raise TypeError("serialize_for expects a message body or an envelope model")
    facts = VERSION_FACTS.get(version)
    if facts is None:
        raise UnknownProtocolVersionError(version)
    return _shaping.serialize(model, version, facts)


@overload
def parse_as(type_: type[T], data: Mapping[str, Any], version: str) -> T: ...
@overload
def parse_as(type_: Any, data: Mapping[str, Any], version: str) -> Any: ...
def parse_as(type_: Any, data: Mapping[str, Any], version: str) -> Any:
    """Validate inbound wire `data` as `type_` under `version` semantics.

    `type_` is a monolith model class or a public union alias (ClientRequest,
    ServerResult, ContentBlock, JSONRPCMessage, ...). Parsing is one lenient
    superset parse at every version — unknown fields are never rejected — plus
    three version-keyed mandates applied on 2026-07-28 inbound only: a present
    but unrecognized `resultType` is rejected, a request's `params._meta`
    must carry all three reserved `io.modelcontextprotocol/*` keys, and
    embedded input-request entries must each carry `method`.
    Result-bearing unions resolve their member structurally — the arms
    matching the payload's keys are tried best match first and the first that
    validates wins — so the open-shaped EmptyResult arm cannot mask a
    better-matching member's validation failures, and a body is rejected only
    when every matching arm rejects it (with the best-matching arm's errors);
    unknown-shaped result bodies still parse (as the EmptyResult arm).
    Unknown `version` strings parse leniently with NO version-keyed mandates
    applied.

    Raises:
        pydantic.ValidationError: `data` is not valid for `type_` at `version`.
    """
    return _shaping.parse(type_, data, version, VERSION_FACTS.get(version))
