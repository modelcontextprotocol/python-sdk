"""Version-aware wire boundary for MCP types.

`mcp.types` defines a single superset model set — "the monolith" throughout
this package — covering every known protocol version at once, instead of
maintaining parallel per-version model trees. This module is where the
per-version differences are applied: serialize a monolith model for, or
parse wire data under, a specific negotiated protocol version. The unique
key for every behavior in this module is (monolith type, negotiated protocol
version). Versions are opaque strings ordered by KNOWN_PROTOCOL_VERSIONS;
nothing here negotiates, dispatches, or holds session state.

Wire shaping is keyed on two surfaces, not five versions: every version at
or below 2025-11-25 maps to the `v2025_11_25` surface block, whose emission
is the plain monolith dump and whose parsing carries no version-keyed
mandates, while 2026-07-28 maps to the `v2026_07_28` surface block, which
injects the new protocol's required fields and enforces its mandates. The
surface blocks and the per-version method tables live in
`mcp.types._version_facts`; the engine that applies them lives in
`mcp.types._shaping`. This module exposes the version registry, the method
tables, `serialize_for` / `parse_as`, and the two error types version-aware
serialization raises.
"""

from collections.abc import Mapping
from typing import Any, TypeVar, overload

from pydantic import BaseModel

from mcp.shared.version import KNOWN_PROTOCOL_VERSIONS
from mcp.types import _shaping
from mcp.types._types import Notification, Request, Result
from mcp.types._version_facts import (
    CLIENT_NOTIFICATION_METHODS,
    CLIENT_REQUEST_METHODS,
    SERVER_NOTIFICATION_METHODS,
    SERVER_REQUEST_METHODS,
    SURFACE_FACTS,
    UnsupportedAtVersionError,
)
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
    frame when given an envelope model. The boundary is additive-only:
    nothing is ever removed from the model's own dump, at any version. At
    2025-11-25 and earlier the emitted body IS the plain dump
    (`model_dump(by_alias=True, mode="json", exclude_none=True)`),
    byte-identical. At 2026-07-28 the boundary additionally injects the
    protocol-required fields when unset — `resultType` on the results the
    2026-07-28 schema defines it on, the `ttlMs`/`cacheScope` don't-cache
    pair on cacheable results, and the reserved protocol-version `_meta` key
    on requests (merged, never overwriting a caller-set value) — and refuses
    values with no legal 2026-07-28 wire form. Emitted leaf values always
    come from the model's dump, never from a re-validated copy.

    Raises:
        UnknownProtocolVersionError: `version` is not a known protocol version.
        UnsupportedAtVersionError: 2026-07-28 only — the request lacks a
            caller-supplied client identity `_meta` key, an input-required
            result sets neither `inputRequests` nor `requestState`, or the
            model's type is one the 2026-07-28 schema does not define.
    """
    if not _is_serializable(model):
        raise TypeError("serialize_for expects a message body or an envelope model")
    facts = SURFACE_FACTS.get(version)
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
    return _shaping.parse(type_, data, version, SURFACE_FACTS.get(version))
