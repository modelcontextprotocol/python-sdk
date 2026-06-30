"""Opt-in extension interface for MCP clients.

To make an extension: subclass `ClientExtension`, set `identifier`, and
override whichever of `settings()` / `claims()` / `notifications()` apply. To
use one: pass instances to `Client(extensions=[...])` — the client folds the
declarations into its own machinery; the extension never receives the client.
To advertise an extension identifier with no client-side behaviour, use
`advertise()`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Generic, Literal, TypeVar, get_args

from mcp_types import CORE_RESULT_TYPES, CallToolResult, InputRequiredResult, Result
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel

from mcp.shared.extension import validate_extension_identifier

if TYPE_CHECKING:
    from mcp.client.session import ClientSession

__all__ = [
    "ClaimContext",
    "ClientExtension",
    "NotificationBinding",
    "ResultClaim",
    "UnexpectedClaimedResult",
    "advertise",
]

_CLAIM_METHODS: Final[frozenset[str]] = frozenset({"tools/call"})
"""The closed set of verbs a claim may attach to (widened with the `method` Literal)."""

ClaimedT = TypeVar("ClaimedT", bound=Result)
NotifyParamsT = TypeVar("NotifyParamsT", bound=BaseModel)


@dataclass(frozen=True, kw_only=True)
class ClaimContext:
    """Host-injected context for one `ResultClaim.resolve` call.

    `session` is the sanctioned public low-level handle — the same one users
    already reach via `client.session`; the resolver gets no `Client` and no
    new authority.
    """

    session: ClientSession
    tool_name: str
    read_timeout_seconds: float | None


@dataclass(frozen=True, kw_only=True)
class ResultClaim(Generic[ClaimedT]):
    """One extra result shape on one spec verb, keyed by the wire `resultType`.

    A claim is active only while the declaring extension is constructed in AND
    the negotiated version admits it; otherwise parsing stays byte-identical to
    a claim-less client, so an undeclared shape still fails validation — the
    supported `resultType` set is always core plus declared claims.

    `resolve` finishes a claimed result on the transparent path: it may send
    follow-ups through `ctx.session` and must return the verb's ordinary
    result. It is required — a claim nothing can finish would be useless. A
    package that wants explicit-only handling ships a resolver that raises a
    typed error naming `session.call_tool(allow_claimed=True)`, which is also
    how callers reach the undriven shape per-call.

    `model` must declare `result_type` as a Literal of exactly the claimed tag,
    and must not subclass a core result type — a core subclass would satisfy
    the session's isinstance branches and bypass claim routing. `protocol_versions`,
    when set, restricts the claim to a subset of the modern protocol revisions;
    `None` (the default) means every modern version. The modern floor is
    structural, not a restriction: claimed shapes cannot be delivered on a
    legacy wire. All of this is enforced at construction.
    """

    result_type: str
    model: type[ClaimedT]
    resolve: Callable[[ClaimedT, ClaimContext], Awaitable[CallToolResult]]
    method: Literal["tools/call"] = "tools/call"
    protocol_versions: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.method not in _CLAIM_METHODS:
            raise ValueError(f"claims attach to {sorted(_CLAIM_METHODS)} only; got method {self.method!r}")
        if self.result_type in CORE_RESULT_TYPES:
            raise ValueError(f"resultType {self.result_type!r} is core protocol vocabulary")
        if issubclass(self.model, CallToolResult | InputRequiredResult):
            raise ValueError("claim models must not subclass core result types")
        field = self.model.model_fields.get("result_type")
        if field is None or get_args(field.annotation) != (self.result_type,):
            raise ValueError(f"{self.model.__name__}.result_type must be Literal[{self.result_type!r}]")
        if self.protocol_versions is not None and not self.protocol_versions:
            raise ValueError("empty protocol_versions could never activate; use None for all")
        if self.protocol_versions is not None and not self.protocol_versions.issubset(MODERN_PROTOCOL_VERSIONS):
            unrecognized = sorted(self.protocol_versions.difference(MODERN_PROTOCOL_VERSIONS))
            raise ValueError(
                f"protocol_versions {unrecognized} are not modern protocol revisions; claimed shapes "
                "cannot be delivered on a legacy wire (None means every modern version)"
            )


class UnexpectedClaimedResult(RuntimeError):
    """A claimed (extension) result shape arrived on a `call_tool` that did not opt in.

    Raised by `ClientSession.call_tool` when a claimed shape parses and
    `allow_claimed` is False. By the time this raises the server may have
    durably created state (e.g. a task) — the parsed value is carried as
    `result` so the caller can reach its id to clean up, not just read a
    message. To handle claimed shapes, pass the owning extension to
    `Client(extensions=[...])` (the transparent path) or call with
    `allow_claimed=True` and handle the shape yourself.
    """

    def __init__(self, result: Result) -> None:
        super().__init__(
            f"Server returned a claimed result ({type(result).__name__}); pass the owning extension to "
            "Client(extensions=[...]) for transparent resolution, or call with allow_claimed=True "
            "and handle the shape. The carried result may reference server-side state needing cleanup."
        )
        self.result = result


@dataclass(frozen=True, kw_only=True)
class NotificationBinding(Generic[NotifyParamsT]):
    """Deliver server notifications for `method` to `handler` (unbound methods stay silently dropped).

    Observation-only: the handler receives validated params, returns None, and
    cannot short-circuit anything. Delivery is per-binding serialized through a
    bounded FIFO — one consumer task per binding, so a handler sees events in
    arrival order and may do session I/O without deadlocking the in-process
    dispatch path; on overflow the oldest event is dropped with a warning
    (observation semantics make the drop acceptable).

    There is deliberately no spec-table check at construction: bindings are
    consulted only for methods the negotiated version's core tables do NOT
    know, so they are additive by construction. If a future core version
    adopts the method, the binding goes quiet — detected and warned once at
    activation, not per delivery — instead of import-erroring every package.

    `method` is the bare wire name (e.g. `notifications/tasks`); `params_type`
    validates the notification params before `handler` runs.
    """

    method: str
    params_type: type[NotifyParamsT]
    handler: Callable[[NotifyParamsT], Awaitable[None]]


class ClientExtension:
    """Base class for an opt-in client extension. Override only what you need.

    Mirror of `mcp.server.extension.Extension` in feel: a closed declarative
    surface, fixed at construction, that never receives the client. The
    contribution kinds are the ones a 2026 client actually has — there is
    deliberately no served-request kind (servers do not initiate requests) and
    no open interceptor (the only sanctioned augmentation is extension
    `resultType` values, and a claim already names its owner, so composition
    and ordering questions dissolve by construction).
    """

    #: Reverse-DNS extension identifier, advertised under `ClientCapabilities.extensions`.
    identifier: str

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Validate a class-level `identifier` at definition time. A subclass may
        # instead assign `identifier` in `__init__` (per-instance ids); that case
        # is validated when the extension is consumed, since no class attribute
        # exists to inspect here.
        if (identifier := cls.__dict__.get("identifier")) is not None:
            validate_extension_identifier(identifier, owner=cls.__name__)

    def settings(self) -> dict[str, Any]:
        """Per-extension settings advertised at `ClientCapabilities.extensions[identifier]`.

        Read ONCE at `Client` construction — dynamic per-request settings are
        out of scope. An empty dict (the default) advertises the extension with
        no settings.

        A claim-bearing extension's identifier is advertised only at protocol
        versions where at least one of its claims is active: the ad and the
        claims dissolve together, so the client never advertises an extension
        on a request whose claimed result shapes it would reject. Claim-less
        extensions advertise at every version.
        """
        return {}

    def claims(self) -> Sequence[ResultClaim[Any]]:
        """Extra result shapes this extension claims, with their resolvers."""
        return ()

    def notifications(self) -> Sequence[NotificationBinding[Any]]:
        """Server notifications this extension observes."""
        return ()


class _AdvertiseOnly(ClientExtension):
    """Ad-only extension returned by `advertise()`: an identifier plus captured settings."""

    def __init__(self, identifier: str, settings: dict[str, Any]) -> None:
        self.identifier = identifier
        self._settings = settings

    def settings(self) -> dict[str, Any]:
        return self._settings


def advertise(identifier: str, settings: dict[str, Any] | None = None) -> ClientExtension:
    """Advertise an extension identifier (with optional settings) and nothing else.

    Returns an extension that contributes only the capability ad: no claims, no
    notification bindings. The identifier is validated eagerly, at this call.

    WARNING: advertising an extension you do not implement asserts wire support
    you don't have — for behavioral extensions (e.g. tasks) construct the real
    extension object instead.
    """
    validate_extension_identifier(identifier, owner="advertise")
    return _AdvertiseOnly(identifier, {} if settings is None else settings)
