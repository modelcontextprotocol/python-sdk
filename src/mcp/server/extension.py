"""Pluggable extension interface for MCP servers (SEP-2133).

An extension is an opt-in bundle of MCP behaviour, identified by a reverse-DNS
string (e.g. `io.modelcontextprotocol/ui`) and passed to `MCPServer(extensions=[...])`.
The server applies a closed set of contribution kinds — tools, resources, new
request methods, one `tools/call` interceptor — and never hands itself to the
extension. Lives at the `mcp.server` tier so extensions stay importable without
the composition tier that consumes them.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mcp_types import CallToolRequestParams
from mcp_types.methods import SPEC_CLIENT_METHODS
from pydantic import BaseModel

from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext

if TYPE_CHECKING:
    from mcp.server.mcpserver.resources import Resource

RequestHandler = Callable[[ServerRequestContext[Any, Any], Any], Awaitable[HandlerResult]]

# Extension identifiers follow the `_meta` key grammar with a mandatory vendor prefix (SEP-2133 / basic/index.mdx).
_LABEL = r"[A-Za-z](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_IDENTIFIER_RE = re.compile(rf"{_LABEL}(?:\.{_LABEL})*/{_NAME}")


def validate_extension_identifier(identifier: Any, *, owner: str) -> None:
    """Raise `TypeError` unless `identifier` is a SEP-2133 `vendor-prefix/name` string."""
    if not isinstance(identifier, str) or not _IDENTIFIER_RE.fullmatch(identifier):
        raise TypeError(
            f"{owner}.identifier must be a `vendor-prefix/name` string "
            f"(reverse-DNS prefix required), got {identifier!r}"
        )


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

    `params_type` validates params before `handler` runs; subclass `RequestParams`
    so `_meta` parses uniformly. `protocol_versions` restricts the method to those
    wire versions (others get `METHOD_NOT_FOUND`); `None` admits every version.

    Binding a spec-defined method raises at construction — it would shadow or be
    shadowed by the server's handler. To re-provide a spec method the 2026 revision
    removed (e.g. `logging/setLevel`), use the lowlevel `Server.add_request_handler`
    instead — the runner's per-version surface gate would never route it here anyway.
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

    Subclass and set `identifier` (validated at class-definition time), then
    override whichever contribution methods apply — every method has a default.
    """

    #: Reverse-DNS extension identifier, advertised under `ServerCapabilities.extensions`.
    identifier: str

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # A subclass may instead assign `identifier` in `__init__` (per-instance
        # ids); that case is validated when the extension is applied.
        identifier = cls.__dict__.get("identifier")
        if identifier is not None:
            validate_extension_identifier(identifier, owner=cls.__name__)

    def settings(self) -> dict[str, Any]:
        """Settings advertised at `capabilities.extensions[identifier]`; empty dict (default) means none."""
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

        Override to observe the call or short-circuit (return without calling
        `call_next(ctx)`, which runs the rest of the chain and the real handler).
        """
        return await call_next(ctx)


def compose_tool_call_interceptor(extensions: Sequence[Extension]) -> ServerMiddleware[Any]:
    """Fold every extension's `intercept_tool_call` into one `ServerMiddleware`.

    Nests the interceptors (first extension outermost), no-ops for methods other
    than `tools/call`, and validates the params once for all interceptors.
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
