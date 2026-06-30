"""Opt-in extension interface for MCP clients.

Subclass `ClientExtension`, set `identifier`, override the hooks you need, and
pass instances to `Client(extensions=[...])`. For an identifier-only
capability ad, use `advertise()`.
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
"""The closed set of verbs a claim may attach to; widen together with the `method` Literal."""

ClaimedT = TypeVar("ClaimedT", bound=Result)
NotifyParamsT = TypeVar("NotifyParamsT", bound=BaseModel)


@dataclass(frozen=True, kw_only=True)
class ClaimContext:
    """Host-injected context for one `ResultClaim.resolve` call."""

    session: ClientSession
    tool_name: str
    read_timeout_seconds: float | None


@dataclass(frozen=True, kw_only=True)
class ResultClaim(Generic[ClaimedT]):
    """One extra result shape on one spec verb, keyed by the wire `resultType`.

    Active only while the declaring extension is constructed into the client and
    the negotiated protocol version admits it. `resolve` finishes a claimed
    result, may send follow-ups through `ctx.session`, and must return the
    verb's ordinary result. All field constraints are enforced at construction.
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
    """A claimed (extension) result arrived on a `call_tool` that did not opt in.

    The parsed value is carried as `result`; the server may already hold state it
    references. Opt in via `Client(extensions=[...])` or `allow_claimed=True`.
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
    """Deliver server notifications for `method` (the bare wire name) to `handler`.

    Observation-only: validated params arrive in order through a bounded queue,
    dropping the oldest with a warning on overflow. Methods the negotiated
    version's core tables handle are never delivered to bindings.
    """

    method: str
    params_type: type[NotifyParamsT]
    handler: Callable[[NotifyParamsT], Awaitable[None]]


class ClientExtension:
    """Base class for an opt-in client extension; override only what you need.

    The surface is declarative, fixed at construction, and never receives the client.
    """

    #: Reverse-DNS extension identifier, advertised under `ClientCapabilities.extensions`.
    identifier: str

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Per-instance identifiers (assigned in __init__) are validated at consumption instead.
        if (identifier := cls.__dict__.get("identifier")) is not None:
            validate_extension_identifier(identifier, owner=cls.__name__)

    def settings(self) -> dict[str, Any]:
        """Per-extension settings advertised at `ClientCapabilities.extensions[identifier]`.

        Read once at `Client` construction. A claim-bearing extension is
        advertised only at protocol versions where at least one of its claims
        is active.
        """
        return {}

    def claims(self) -> Sequence[ResultClaim[Any]]:
        """Extra result shapes this extension claims, with their resolvers."""
        return ()

    def notifications(self) -> Sequence[NotificationBinding[Any]]:
        """Server notifications this extension observes."""
        return ()


class _AdvertiseOnly(ClientExtension):
    """Ad-only extension returned by `advertise()`."""

    def __init__(self, identifier: str, settings: dict[str, Any]) -> None:
        self.identifier = identifier
        self._settings = settings

    def settings(self) -> dict[str, Any]:
        return self._settings


def advertise(identifier: str, settings: dict[str, Any] | None = None) -> ClientExtension:
    """Advertise an extension identifier (with optional settings) and nothing else.

    Advertising an extension you do not implement asserts wire support you do
    not have; for behavioral extensions construct the real extension instead.
    """
    validate_extension_identifier(identifier, owner="advertise")
    return _AdvertiseOnly(identifier, {} if settings is None else settings)
