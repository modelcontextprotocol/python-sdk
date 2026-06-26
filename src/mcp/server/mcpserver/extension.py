"""Pluggable extension interface for `MCPServer` (SEP-2133).

An extension is a self-contained, opt-in bundle of MCP behaviour, identified by
a reverse-DNS string (e.g. `io.modelcontextprotocol/ui`). It is passed at
construction - `MCPServer(..., extensions=[Apps(), Tasks(store)])` - and the
server applies a *closed* set of contribution kinds: tools, resources, new
request methods, and one `tools/call` interceptor. The server never hands itself
to an extension; the extension declares what it adds, and the server consumes it.

The shape follows the HTTPX `Transport`/`Auth` pattern: a narrow base class
whose methods have sensible defaults, so an extension overrides only what it
needs. A purely additive extension (Apps) overrides `tools`/`resources`; an
interceptive one (Tasks) overrides `methods`/`intercept_tool_call`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from mcp_types import CallToolRequestParams
from pydantic import BaseModel

from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
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
    subclass `RequestParams` so `_meta` parses uniformly.
    """

    method: str
    params_type: type[BaseModel]
    handler: RequestHandler


class Extension:
    """Base class for an opt-in MCP extension. Override only the methods you need.

    Subclass and set `identifier`, then override the contribution methods that
    apply. Every method has a default, so a minimal extension overrides nothing
    but `identifier` and one of `tools`/`resources`/`methods`.
    """

    #: Reverse-DNS extension identifier, advertised under `ServerCapabilities.extensions`.
    identifier: str

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
