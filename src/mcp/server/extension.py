"""Pluggable extension interface for MCP servers (SEP-2133).

An extension is a self-contained, opt-in bundle of MCP behaviour, identified by
a reverse-DNS string (e.g. `io.modelcontextprotocol/ui`). It is passed to
`MCPServer(extensions=[...])`, and the server applies a *closed* set of
contribution kinds: tools, resources, new request methods, and one `tools/call`
interceptor. The server never hands itself to an extension; the extension
declares what it adds, and the server consumes it.

The shape follows the httpx2 `Transport`/`Auth` pattern: a narrow base class whose
methods have sensible defaults, so an extension overrides only what it needs. A
purely additive extension (Apps) overrides `tools`/`resources`; an interceptive
one overrides `methods`/`intercept_tool_call`.

This module lives at the `mcp.server` tier (not `mcp.server.mcpserver`) so the
base class itself never drags in the composition tier that consumes it;
extensions remain importable without constructing an `MCPServer`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mcp_types import CallToolRequestParams
from mcp_types.methods import SPEC_CLIENT_METHODS
from pydantic import BaseModel

from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext

# Re-exported from `mcp.shared.extension` (shared with the client surface) for existing importers.
from mcp.shared.extension import validate_extension_identifier as validate_extension_identifier

if TYPE_CHECKING:
    from mcp.server.mcpserver.resources import Resource

RequestHandler = Callable[[ServerRequestContext[Any, Any], Any], Awaitable[HandlerResult]]


@dataclass(frozen=True)
class ToolBinding:
    """A tool an extension contributes, plus the `_meta` to stamp on it."""

    fn: Callable[..., Any]
    meta: dict[str, Any] | None = None
    kwargs: dict[str, Any] = field(default_factory=lambda: {})


@dataclass(frozen=True)
class ResourceBinding:
    """A pre-built resource an extension contributes."""

    resource: Resource


@dataclass(frozen=True)
class MethodBinding:
    """A new request method an extension serves, e.g. `tasks/get`.

    `params_type` validates incoming params before `handler` runs; it should
    subclass `RequestParams` so `_meta` parses uniformly. `protocol_versions`,
    when set, restricts the method to those wire versions - a request for the
    method at any other version is rejected as `METHOD_NOT_FOUND`, mirroring the
    spec's `(method, version)` boundary table. `None` (the default) admits the
    method at every version.

    Extension methods are additive: `method` must not name a spec-defined
    request method (`tools/list`, `completion/complete`, ...) — those handlers
    belong to the server, and an extension binding one would silently shadow or
    be shadowed by it. Both constraints are enforced at construction. To
    re-provide a spec method the 2026 revision removed (e.g. `logging/setLevel`
    for legacy clients), use the lowlevel `Server.add_request_handler` API
    instead — the runner's per-version surface gate would never route such a
    method to an extension handler anyway.
    """

    method: str
    params_type: type[BaseModel]
    handler: RequestHandler
    protocol_versions: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.method in SPEC_CLIENT_METHODS:
            raise ValueError(
                f"MethodBinding cannot bind spec method {self.method!r}; extension methods are "
                "additive — use Extension.intercept_tool_call or Server.middleware to wrap core behaviour"
            )
        if self.protocol_versions is not None and not self.protocol_versions:
            raise ValueError(
                f"MethodBinding for {self.method!r} has an empty protocol_versions set, so it could "
                "never be served; use None to admit every version"
            )


class Extension:
    """Base class for an opt-in MCP extension. Override only the methods you need.

    Subclass and set `identifier`, then override the contribution methods that
    apply. Every method has a default, so a minimal extension overrides nothing
    but `identifier` and one of `tools`/`resources`/`methods`. `identifier` is
    enforced at subclass-definition time.
    """

    #: Reverse-DNS extension identifier, advertised under `ServerCapabilities.extensions`.
    identifier: str

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Validate a class-level `identifier` at definition time. A subclass may
        # instead assign `identifier` in `__init__` (per-instance ids); that case
        # is validated when the extension is applied, since no class attribute
        # exists to inspect here.
        identifier = cls.__dict__.get("identifier")
        if identifier is not None:
            validate_extension_identifier(identifier, owner=cls.__name__)

    def settings(self) -> dict[str, Any]:
        """Per-extension settings advertised at `capabilities.extensions[identifier]`.

        An empty dict (the default) advertises the extension with no settings.
        """
        return {}

    def tools(self) -> Sequence[ToolBinding]:
        """Tools this extension contributes (additive)."""
        return ()

    def resources(self) -> Sequence[ResourceBinding]:
        """Resources this extension contributes (additive)."""
        return ()

    def methods(self) -> Sequence[MethodBinding]:
        """New request methods this extension serves (additive)."""
        return ()

    async def intercept_tool_call(
        self,
        params: CallToolRequestParams,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        """Wrap `tools/call`. Default: pass through unchanged.

        Override to short-circuit (return a result without calling `call_next`)
        or to observe the call. `params` is the validated `tools/call` params;
        `call_next(ctx)` runs the rest of the chain and the real handler.
        """
        return await call_next(ctx)


def compose_tool_call_interceptor(extensions: Sequence[Extension]) -> ServerMiddleware[Any]:
    """Fold every extension's `intercept_tool_call` into one `ServerMiddleware`.

    The returned middleware nests the interceptors (first extension outermost)
    and is a no-op for any method other than `tools/call`. It validates the
    `tools/call` params once and threads them to each interceptor.
    """

    async def middleware(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        params = CallToolRequestParams.model_validate({} if ctx.params is None else ctx.params, by_name=False)

        chain = call_next
        for extension in reversed(extensions):
            chain = _bind_interceptor(extension, params, chain)
        return await chain(ctx)

    return middleware


def _bind_interceptor(extension: Extension, params: CallToolRequestParams, call_next: CallNext) -> CallNext:
    async def call(ctx: ServerRequestContext[Any, Any]) -> HandlerResult:
        return await extension.intercept_tool_call(params, ctx, call_next)

    return call
